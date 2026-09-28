"""IGN España's MTN (Mapa Topografico Nacional) layer via WMTS KVP
addressing — official Spanish government topographic map. Region-limited
by nature (Spain only), so always live-probed, never always_available.
Exact query-string parameters sourced from tile-providers-research.md's
working example (2026-09-28) — reconfirm with a real rendered map before
trusting in production, per this skill's own established verification
bar (SKILL.md Common Mistakes: curl alone has missed a cache-masked
block before)."""
from .base import TileProviderPlugin


class IgnEsMtnProvider(TileProviderPlugin):
    provider_id = "ign_es_mtn"
    display_name = "IGN España (MTN)"
    tile_url_template = (
        "https://www.ign.es/wmts/mapa-raster?service=WMTS&request=GetTile"
        "&version=1.0.0&layer=MTN&style=default&format=image/jpeg"
        "&TileMatrixSet=GoogleMapsCompatible&TileMatrix={z}&TileRow={y}&TileCol={x}"
    )
    attribution = "CC-BY 4.0 ign.es"
    max_zoom = 19
    max_native_zoom = 19
    always_available = False
    # IGN's own placeholder ("no data") response for a point outside Spain
    # can be nearly 2KB (observed: Lisbon 1920B, Toulouse 1672B) — well
    # above the generic 256B floor other providers use. A real MTN tile is
    # ~19KB+. This provider-specific threshold is the actual precision
    # check; the bbox below is only a cheap pre-filter to skip a network
    # call for points nowhere near Western Europe.
    min_body_bytes = 5000

    # Generous "roughly Western Europe / North Africa" pre-filter — wide
    # enough to include Portugal and southern France on purpose (a
    # rectangle cannot cleanly separate Spain from Portugal, whose border
    # is irregular; the min_body_bytes threshold above is what actually
    # distinguishes real Spain coverage from a placeholder within this
    # region), narrow enough to skip a pointless network call for a point
    # nowhere close (Moscow, most of the world).
    _WESTERN_EUROPE_BBOX = (27.0, -19.0, 44.5, 5.0)  # (lat_min, lon_min, lat_max, lon_max)
    # Canary Islands (roughly lat 27.6-29.5, lon -18.2 to -13.4) fall
    # within the box above, so a single box suffices here — unlike the
    # previous, tighter Spain-only version which needed two.

    def covers(self, points, timeout=5.0):
        if not points:
            return False
        lat_min, lon_min, lat_max, lon_max = self._WESTERN_EUROPE_BBOX
        if not all(lat_min <= lat <= lat_max and lon_min <= lon <= lon_max for lat, lon in points):
            return False
        return super().covers(points, timeout)
