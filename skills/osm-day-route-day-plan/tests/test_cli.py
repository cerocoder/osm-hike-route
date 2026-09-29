import datetime

import build_day_plan


def test_cli_writes_plan_file_and_reports_path(make_route, weather_response, fixed_now, capsys):
    route_dir = make_route()
    code = build_day_plan.main([str(route_dir), "2026-06-21", "--lang", "en", "--departure", "Waterloo",
                                "--start", "09:00"], http=lambda url: weather_response(), now=fixed_now)
    assert code == 0
    text = (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
    assert "From: Waterloo" in text
    assert "estimated finish 14:00" in text
    assert "wrote" in capsys.readouterr().out


def test_cli_overwrites_the_same_date_and_keeps_other_dates(make_route, weather_response, fixed_now):
    route_dir = make_route()
    http = lambda url: weather_response()  # noqa: E731
    build_day_plan.main([str(route_dir), "2026-06-21"], http=http, now=fixed_now)
    build_day_plan.main([str(route_dir), "2026-06-22"], http=lambda url: weather_response(date="2026-06-22"),
                        now=fixed_now)
    build_day_plan.main([str(route_dir), "2026-06-21", "--lang", "ru"], http=http, now=fixed_now)
    assert (route_dir / "day-plan-2026-06-22.md").exists()
    assert "Главное на день" in (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")


def test_cli_drops_departure_that_looks_like_a_street_address(make_route, weather_response, fixed_now, capsys):
    route_dir = make_route()
    build_day_plan.main([str(route_dir), "2026-06-21", "--departure", "Baker Street 221B"],
                        http=lambda url: weather_response(), now=fixed_now)
    text = (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
    assert "Baker" not in text and "From:" not in text
    assert "street address" in capsys.readouterr().err


def test_coarse_departure_keeps_plain_city_or_station():
    assert build_day_plan.coarse_departure("  Madrid, Atocha ") == ("Madrid, Atocha", False)
    assert build_day_plan.coarse_departure(None) == (None, False)


def test_cli_rejects_bad_date_and_missing_route(make_route, tmp_path, capsys):
    assert build_day_plan.main([str(make_route()), "21-06-2026"]) == 1
    assert build_day_plan.main([str(tmp_path / "nope"), "2026-06-21"]) == 1
    assert "not found" in capsys.readouterr().err


def test_plan_written_by_cli_is_found_by_glob_used_in_show(make_route, weather_response, fixed_now):
    route_dir = make_route()
    build_day_plan.main([str(route_dir), "2026-06-21"], http=lambda url: weather_response(), now=fixed_now)
    assert [p.name for p in route_dir.glob("day-plan-????-??-??.md")] == ["day-plan-2026-06-21.md"]
