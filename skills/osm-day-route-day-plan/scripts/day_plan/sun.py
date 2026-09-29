"""Sunrise/sunset from the NOAA solar-position equations. Pure math, no
network. Times are minutes after 00:00 UTC of the given date (they may be
negative or above 1440 at extreme longitudes), where `date` is the local
solar date — the caller adds the UTC offset."""
import datetime
import math
from dataclasses import dataclass

_ZENITH_DEG = 90.833  # sunrise/sunset: refraction + solar disc radius


@dataclass(frozen=True)
class SunTimes:
    kind: str  # "normal" | "polar_day" | "polar_night"
    sunrise_utc_min: float | None = None
    sunset_utc_min: float | None = None


def _julian_century(date: datetime.date, minutes_utc: float) -> float:
    jd = date.toordinal() + 1721424.5 + minutes_utc / 1440.0
    return (jd - 2451545.0) / 36525.0


def _solar(t: float) -> tuple[float, float]:
    """(declination in radians, equation of time in minutes)."""
    l0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360.0
    m = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    mr = math.radians(m)
    c = (math.sin(mr) * (1.914602 - t * (0.004817 + 0.000014 * t))
         + math.sin(2 * mr) * (0.019993 - 0.000101 * t)
         + math.sin(3 * mr) * 0.000289)
    omega = math.radians(125.04 - 1934.136 * t)
    lam = math.radians(l0 + c - 0.00569 - 0.00478 * math.sin(omega))
    seconds = 21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))
    eps = math.radians(23.0 + (26.0 + seconds / 60.0) / 60.0 + 0.00256 * math.cos(omega))
    decl = math.asin(math.sin(eps) * math.sin(lam))
    y = math.tan(eps / 2.0) ** 2
    l0r = math.radians(l0)
    eqtime = 4.0 * math.degrees(
        y * math.sin(2 * l0r) - 2 * e * math.sin(mr)
        + 4 * e * y * math.sin(mr) * math.cos(2 * l0r)
        - 0.5 * y * y * math.sin(4 * l0r) - 1.25 * e * e * math.sin(2 * mr)
    )
    return decl, eqtime


def _cos_hour_angle(lat: float, decl: float) -> float:
    latr = math.radians(lat)
    return (math.cos(math.radians(_ZENITH_DEG)) / (math.cos(latr) * math.cos(decl))
            - math.tan(latr) * math.tan(decl))


def sun_times(date: datetime.date, lat: float, lon: float) -> SunTimes:
    decl, eq = _solar(_julian_century(date, 720.0 - 4.0 * lon))
    cos_ha = _cos_hour_angle(lat, decl)
    if cos_ha > 1.0:
        return SunTimes("polar_night")
    if cos_ha < -1.0:
        return SunTimes("polar_day")

    def event(sign: int) -> float:
        # sign=+1 sunrise, -1 sunset; refine at the event's own time.
        minutes = 720.0 - 4.0 * lon - eq
        for _ in range(3):
            decl_i, eq_i = _solar(_julian_century(date, minutes))
            ha = math.degrees(math.acos(max(-1.0, min(1.0, _cos_hour_angle(lat, decl_i)))))
            minutes = 720.0 - 4.0 * (lon + sign * ha) - eq_i
        return minutes

    return SunTimes("normal", sunrise_utc_min=event(+1), sunset_utc_min=event(-1))
