"""Client for the Copernicus GWIS WMS (maps.effis.emergency.copernicus.eu):
official fire-weather indices and satellite-detected active fires, keyless.
Checked live while writing this (2026-09-30):

* the layer `ecmwf.query` answers GetFeatureInfo for any point on Earth
  (Yekaterinburg included) with the Fire Weather Index and its components,
  for dates from 2018 up to 8 days ahead (an empty body beyond that);
* only `info_format=text/html` returns values (text/plain and GML come back
  empty), so the HTML table is parsed;
* WMS 1.3.0 with EPSG:4326 takes the bbox latitude-first; a lon/lat swap
  silently queries another place. `styles=` must be sent, and https is needed
  (http answers 301). Without `time` the layer answers for 2019-01-01;
* `viirs.hs.query` returns the detections near the queried pixel (about 13
  pixels of tolerance): use a small bbox around each query point and filter
  by distance yourself.

Model output is labelled `derived`; a detection list is `web-sourced`."""
import datetime
import math
import re
from dataclasses import asdict, dataclass

from .http import HttpError
from .osm_features import haversine_m

GWIS_URL = "https://maps.effis.emergency.copernicus.eu/gwis"
FWI_LAYER = "ecmwf.query"
HOTSPOT_LAYER = "viirs.hs.query"
FWI_HORIZON_DAYS = 8
FWI_FORECAST_TTL_S = 3 * 3600
HOTSPOT_TTL_S = 3600
HOTSPOT_RADIUS_KM = 15.0
HOTSPOT_WINDOW_DAYS = 2          # detections of today and the two days before
MAX_HOTSPOT_QUERIES = 6
_HALF_DEG = 0.6                  # 1.2 degree box, 101 px: about 1.3 km per pixel, so 13 px of tolerance exceed 15 km
_MIN_COS = 0.2                   # the longitude span is widened by 1/cos(latitude), capped near the poles

_ROW = re.compile(r"<tr>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>", re.S | re.I)
_FWI_LABELS = (("(FWI)", "FWI"), ("(ISI)", "ISI"), ("(BUI)", "BUI"), ("(FFMC)", "FFMC"), ("(DMC)", "DMC"),
               ("(DC)", "DC"))


def _url(layer: str, lat: float, lon: float, time: str, extra: str = "") -> str:
    half_lon = _HALF_DEG / max(_MIN_COS, math.cos(math.radians(lat)))      # a pixel is as many km wide as high
    return (f"{GWIS_URL}?service=WMS&version=1.3.0&request=GetFeatureInfo&layers={layer}&query_layers={layer}"
            f"&styles=&crs=EPSG:4326&bbox={lat - _HALF_DEG:.4f},{lon - half_lon:.4f},{lat + _HALF_DEG:.4f},"
            f"{lon + half_lon:.4f}&width=101&height=101&i=50&j=50&info_format=text/html&time={time}{extra}")


EMPTY_FWI_TTL_S = 24 * 3600


def fwi_url(lat: float, lon: float, date: datetime.date) -> str:
    return _url(FWI_LAYER, lat, lon, date.isoformat())


def _number(text: str) -> float | None:
    m = re.match(r"\s*(-?\d+(?:\.\d+)?)", text)
    return float(m.group(1)) if m else None


def parse_fwi(html: str) -> dict | None:
    """{'FWI': .., 'ISI': .., 'BUI': .., 'FFMC': .., 'DMC': .., 'DC': ..} or None when there is no FWI row."""
    values = {}
    for label, value in _ROW.findall(html or ""):
        for marker, key in _FWI_LABELS:
            if marker in label and _number(value) is not None:
                values[key] = _number(value)
    return values if "FWI" in values else None


def fwi_at(ctx, lat: float, lon: float, date: datetime.date) -> dict | None:
    """The FWI components for a date, or None (beyond the horizon, or no value). Raises HttpError."""
    key = f"gwis_fwi|{lat:.2f}|{lon:.2f}|{date.isoformat()}"
    forecast = date >= ctx.today
    cached = ctx.cache.get_entry(key, FWI_FORECAST_TTL_S if forecast else None)
    if cached is not None and (cached[0] or ctx.now.timestamp() - cached[1] <= EMPTY_FWI_TTL_S):
        return cached[0] or None      # an empty answer is remembered for a day only, even for a past date
    values = parse_fwi(ctx.http_text(fwi_url(lat, lon, date)))
    ctx.cache.put(key, values or {})
    return values


@dataclass
class Hotspot:
    lat: float
    lon: float
    date: str
    time: str
    satellite: str
    confidence: str
    frp_mw: float | None


def hotspots_url(lat: float, lon: float, date_from: datetime.date, date_to: datetime.date) -> str:
    return _url(HOTSPOT_LAYER, lat, lon, f"{date_from.isoformat()}/{date_to.isoformat()}", "&feature_count=50")


def parse_hotspots(html: str) -> list:
    hotspots = []
    for block in (html or "").split("<table")[1:]:
        fields = {re.sub(r"\s+", " ", k).strip(): re.sub(r"\s+", " ", v).strip() for k, v in _ROW.findall(block)}
        lat, lon = _number(fields.get("Latitude", "")), _number(fields.get("Longitude", ""))
        if lat is None or lon is None:
            continue
        hotspots.append(Hotspot(lat, lon, fields.get("Detection Date", ""), fields.get("Detection time", ""),
                                fields.get("Satellite", ""), fields.get("Confidence", ""),
                                _number(fields.get("Fire Radiative Power", ""))))
    return hotspots


def hotspots_near(ctx, samples: list, date_from: datetime.date, date_to: datetime.date,
                  radius_km: float = HOTSPOT_RADIUS_KM) -> list:
    """[(Hotspot, distance_km)] within radius_km of the route, nearest first. One small query per query point
    (at most MAX_HOTSPOT_QUERIES points spread along the route); raises HttpError if a query fails."""
    step = max(1, len(samples) // MAX_HOTSPOT_QUERIES)
    query_points = samples[::step][:MAX_HOTSPOT_QUERIES]
    if samples[-1] not in query_points:            # the end of the route is always searched
        if len(query_points) < MAX_HOTSPOT_QUERIES:
            query_points.append(samples[-1])
        else:
            query_points[-1] = samples[-1]
    seen, found = set(), []
    for lat, lon in query_points:
        key = f"gwis_hotspots|{lat:.2f}|{lon:.2f}|{date_from.isoformat()}|{date_to.isoformat()}"
        cached = ctx.cache.get_entry(key, HOTSPOT_TTL_S)
        if cached is not None:
            batch = [Hotspot(**h) for h in cached[0]]
        else:
            batch = parse_hotspots(ctx.http_text(hotspots_url(lat, lon, date_from, date_to)))
            ctx.cache.put(key, [asdict(h) for h in batch])
        for h in batch:
            ident = (round(h.lat, 5), round(h.lon, 5), h.date, h.time)
            if ident in seen:
                continue
            seen.add(ident)
            distance = min(haversine_m(h.lat, h.lon, s_lat, s_lon) for s_lat, s_lon in samples) / 1000.0
            if distance <= radius_km:
                found.append((h, distance))
    return sorted(found, key=lambda pair: pair[1])
