import datetime
from pathlib import Path

import pytest

from day_plan.context import build_context
from day_plan.gwis import (
    FWI_HORIZON_DAYS, Hotspot, fwi_at, fwi_url, hotspots_near, hotspots_url, parse_fwi, parse_hotspots,
)
from day_plan.http import HttpError

FIXTURES = Path(__file__).parent / "fixtures"
FWI_HTML = (FIXTURES / "gwis_fwi_ekb_2026-09-28.html").read_text(encoding="utf-8")
HOTSPOT_HTML = (FIXTURES / "gwis_hotspots_biscay.html").read_text(encoding="utf-8")


def test_parse_the_real_fwi_table():
    values = parse_fwi(FWI_HTML)
    assert values == {"FWI": pytest.approx(9.5045595), "ISI": pytest.approx(4.747189), "BUI": pytest.approx(29.865156),
                      "FFMC": pytest.approx(87.779564), "DMC": pytest.approx(20.014561), "DC": pytest.approx(147.02386)}


@pytest.mark.parametrize("html", ["", None, "<html>nothing</html>", "<table id='main'><tr><td>Anomaly Index</td><td>1.1</td></tr></table>",
                                  "<tr><td>Fire Weather Index (FWI)</td><td>n/a</td></tr>"])
def test_no_fwi_row_means_none(html):
    assert parse_fwi(html) is None


def test_fwi_url_is_latitude_first_https_dated_and_has_empty_styles():
    url = fwi_url(56.84, 60.6, datetime.date(2026, 9, 28))
    assert url.startswith("https://maps.effis.emergency.copernicus.eu/gwis?")
    assert "bbox=56.3400,60.1000,57.3400,61.1000" in url          # lat, lon, lat, lon — not lon-first
    assert "crs=EPSG:4326" in url and "version=1.3.0" in url and "styles=&" in url
    assert "info_format=text/html" in url and "time=2026-09-28" in url and "layers=ecmwf.query" in url


def test_parse_the_real_hotspot_blocks():
    hotspots = parse_hotspots(HOTSPOT_HTML)
    assert len(hotspots) >= 2
    first = hotspots[0]
    assert (first.lat, first.lon, first.date, first.time) == (43.20694, -2.77349, "2026-09-29", "02:17:00")
    assert first.satellite == "NOAA-21/VIIRS" and first.confidence == "High" and first.frp_mw == pytest.approx(0.5)


def test_hotspots_url_has_a_time_range_a_feature_count_and_a_small_box():
    url = hotspots_url(43.2, -2.8, datetime.date(2026, 9, 27), datetime.date(2026, 9, 29))
    assert "layers=viirs.hs.query" in url and "time=2026-09-27/2026-09-29" in url and "feature_count=50" in url
    assert "bbox=42.7000,-3.3000,43.7000,-2.3000" in url


class Text:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def __call__(self, url):
        self.calls.append(url)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer(url) if callable(self.answer) else self.answer


def _ctx(make_route, fixed_now, text, date=datetime.date(2026, 9, 29), folder="route"):
    return build_context(make_route(folder=folder), date, http_text=text, now=fixed_now)


def test_fwi_at_caches_a_future_value_for_three_hours_and_a_past_one_for_good(make_route, fixed_now):
    text = Text(FWI_HTML)
    ctx = _ctx(make_route, fixed_now, text, date=datetime.date(2026, 6, 22))          # future relative to fixed_now
    assert fwi_at(ctx, 56.84, 60.6, ctx.date)["FWI"] == pytest.approx(9.5045595)
    fwi_at(ctx, 56.84, 60.6, ctx.date)
    assert len(text.calls) == 1
    past = _ctx(make_route, fixed_now, text, date=datetime.date(2026, 6, 10), folder="past")
    past.cache = ctx.cache
    fwi_at(past, 56.84, 60.6, past.date)
    fwi_at(past, 56.84, 60.6, past.date)
    assert len(text.calls) == 2


def test_fwi_at_returns_none_beyond_the_horizon_body_and_remembers_it(make_route, fixed_now):
    text = Text("")
    ctx = _ctx(make_route, fixed_now, text, date=datetime.date(2026, 7, 5))
    assert fwi_at(ctx, 56.84, 60.6, ctx.date) is None and fwi_at(ctx, 56.84, 60.6, ctx.date) is None
    assert len(text.calls) == 1 and FWI_HORIZON_DAYS == 8


def test_fwi_at_raises_http_error_and_does_not_cache_it(make_route, fixed_now):
    text = Text(HttpError("503"))
    ctx = _ctx(make_route, fixed_now, text)
    for _ in range(2):
        with pytest.raises(HttpError):
            fwi_at(ctx, 56.84, 60.6, ctx.date)
    assert len(text.calls) == 2


def test_hotspots_near_filters_by_the_real_distance_to_the_route(make_route, fixed_now):
    text = Text(HOTSPOT_HTML)
    ctx = _ctx(make_route, fixed_now, text)
    near = hotspots_near(ctx, [(43.21, -2.78), (43.25, -2.75)], datetime.date(2026, 9, 27), datetime.date(2026, 9, 29))
    assert near and all(distance <= 15.0 for _, distance in near)
    assert near[0][0].lat == 43.20694 and near[0][1] < 2.0
    far = hotspots_near(ctx, [(42.0, -1.0)], datetime.date(2026, 9, 27), datetime.date(2026, 9, 29))
    assert far == []


def test_hotspots_are_deduplicated_across_query_points_and_limited_in_number(make_route, fixed_now):
    text = Text(HOTSPOT_HTML)
    ctx = _ctx(make_route, fixed_now, text)
    samples = [(43.20 + i * 0.005, -2.77) for i in range(40)]
    found = hotspots_near(ctx, samples, datetime.date(2026, 9, 27), datetime.date(2026, 9, 29))
    assert len(text.calls) <= 6
    assert len({(h.lat, h.lon, h.date, h.time) for h, _ in found}) == len(found)


def test_hotspot_batches_are_cached_for_an_hour(make_route, fixed_now):
    text = Text(HOTSPOT_HTML)
    ctx = _ctx(make_route, fixed_now, text)
    args = ([(43.21, -2.78)], datetime.date(2026, 9, 27), datetime.date(2026, 9, 29))
    hotspots_near(ctx, *args)
    hotspots_near(ctx, *args)
    assert len(text.calls) == 1
    assert isinstance(parse_hotspots(HOTSPOT_HTML)[0], Hotspot)


def test_a_hotspot_query_failure_raises(make_route, fixed_now):
    ctx = _ctx(make_route, fixed_now, Text(HttpError("504")))
    with pytest.raises(HttpError):
        hotspots_near(ctx, [(43.2, -2.8)], datetime.date(2026, 9, 27), datetime.date(2026, 9, 29))
