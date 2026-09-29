import datetime

from day_plan.plugins.light import LightPlugin


class Ctx:
    lang = "en"
    centroid = (51.5074, -0.1278)
    date = datetime.date(2026, 6, 21)
    duration_hours = 5.0
    start_time = None


def _run(shared=None, **overrides):
    ctx = Ctx()
    for k, v in overrides.items():
        setattr(ctx, k, v)
    return LightPlugin().run(ctx, shared if shared is not None else {"weather": {"utc_offset_seconds": 3600}})


def test_reports_sunrise_sunset_and_length_in_local_time():
    section = _run()
    assert "**04:43**" in section.markdown or "**04:44**" in section.markdown
    assert "**21:21**" in section.markdown or "**21:22**" in section.markdown
    assert "16 h 3" in section.markdown
    assert section.confidence == "derived"
    assert section.shared["kind"] == "normal"


def test_without_start_time_reports_latest_start():
    section = _run()
    assert "start no later than" in section.markdown


def test_start_time_reports_finish_and_margin_without_warning():
    section = _run(start_time=datetime.time(9, 0))
    assert "estimated finish 14:00" in section.markdown
    assert section.warnings == []


def test_finish_after_sunset_is_a_danger_warning():
    section = _run(start_time=datetime.time(18, 0))
    assert [w.severity for w in section.warnings] == ["danger"]
    assert "after sunset" in section.warnings[0].text


def test_tight_margin_is_a_caution():
    section = _run(start_time=datetime.time(15, 30))  # ends 20:30, sunset ~21:21
    assert [w.severity for w in section.warnings] == ["caution"]


def test_route_longer_than_daylight_is_danger():
    section = _run(duration_hours=17.0)
    assert any(w.severity == "danger" and "does not fit" in w.text for w in section.warnings)


def test_latest_start_before_sunrise_is_a_caution():
    section = _run(duration_hours=16.0)  # 16 h + 60 min buffer > 16 h 38 min of light
    assert any(w.severity == "caution" for w in section.warnings)
    assert not any(w.severity == "danger" for w in section.warnings)


def test_missing_duration_skips_margin_and_says_so():
    section = _run(duration_hours=None)
    assert "not in the archive" in section.markdown
    assert section.warnings == []


def test_missing_weather_falls_back_to_longitude_offset_and_says_so():
    section = _run(shared={})
    assert "estimated from longitude" in section.markdown


def test_polar_night_is_a_danger_and_polar_day_is_info():
    night = _run(centroid=(69.65, 18.96), date=datetime.date(2026, 12, 21))
    assert night.warnings[0].severity == "danger"
    day = _run(centroid=(69.65, 18.96), date=datetime.date(2026, 6, 21))
    assert day.warnings[0].severity == "info"


def test_russian_output():
    section = _run(lang="ru")
    assert "Рассвет" in section.markdown and "ч" in section.markdown
