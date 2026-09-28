"""Duration estimate (pace + Naismith-style ascent penalty, spec §3.9) and
the soft daylight-fit warning. The warning is heuristic and never blocks
route construction — a precise seasonal check is osm-day-route-prepare's
job, not this skill's."""


def estimate_duration_hours(distance_km: float, elevation_gain_m: float,
                             pace_kmh: float, ascent_minutes_per_100m: float) -> float:
    base_hours = distance_km / pace_kmh
    ascent_hours = (elevation_gain_m / 100.0) * ascent_minutes_per_100m / 60.0
    return base_hours + ascent_hours


def duration_warning(estimated_hours: float, duration_warning_hours: float) -> str | None:
    if estimated_hours <= duration_warning_hours:
        return None
    return (
        f"Оценка времени в пути (~{estimated_hours:.1f} ч) превышает {duration_warning_hours:.0f} ч — "
        "маршрут может не влезть в световой день в зависимости от сезона и широты. "
        "Для точной проверки по конкретной дате используйте osm-day-route-prepare."
    )
