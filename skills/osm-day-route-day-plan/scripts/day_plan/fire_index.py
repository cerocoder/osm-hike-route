"""Fire-danger classes and the Russian Nesterov index.

FWI classes as used by EFFIS (Copernicus): very low < 5.2, low 5.2-11.2,
moderate 11.2-21.3, high 21.3-38, very high 38-50, extreme >= 50 — tuned for
Europe; boreal or mountain forests may deserve other thresholds.

Russia: Rosleskhoz order No. 287 of 2011-07-05 classifies forest fire danger
by weather with the Nesterov index (I <= 300 absent, II 301-1000 low,
III 1001-4000 moderate, IV 4001-10000 high, V > 10000 extreme). The index is
the sum of t*(t - dew point) at 12:00 over the days since the last day with
more than 3 mm of precipitation. This implementation is the simplified form
(days at or below 0 C add nothing; the order's smaller-rain reductions are not
applied), so it can slightly overstate the danger — labelled `derived`."""
import datetime

FWI_STEPS = ((5.2, "very_low"), (11.2, "low"), (21.3, "moderate"), (38.0, "high"), (50.0, "very_high"))
KPO_STEPS = ((300, 1), (1000, 2), (4000, 3), (10000, 4))
RAIN_RESET_MM = 3.0
NESTEROV_DAYS = 30


def fwi_class(fwi: float) -> str:
    for limit, name in FWI_STEPS:
        if fwi < limit:
            return name
    return "extreme"


def kpo_class(value: float) -> int:
    """1..5 (Roman I..V in the order)."""
    for limit, cls in KPO_STEPS:
        if value <= limit:
            return cls
    return 5


def daily_from_hourly(response: dict) -> list:
    """Open-Meteo hourly answer -> [{'date', 't', 'dew', 'precip'}] oldest first: temperature and dew point at
    12:00 local, precipitation summed over the day. Days without a noon value are skipped."""
    hourly = response["hourly"]
    days = {}
    for i, stamp in enumerate(hourly["time"]):
        day = days.setdefault(stamp[:10], {"date": stamp[:10], "t": None, "dew": None, "precip": 0.0})
        if stamp[11:13] == "12":
            day["t"] = (hourly.get("temperature_2m") or [None] * (i + 1))[i]
            day["dew"] = (hourly.get("dew_point_2m") or [None] * (i + 1))[i]
        rain = (hourly.get("precipitation") or [None] * (i + 1))[i]
        if rain is not None:
            day["precip"] += rain
    return [days[k] for k in sorted(days) if days[k]["t"] is not None and days[k]["dew"] is not None]


def nesterov_index(days: list) -> float:
    """The index at the last of the given days (oldest first)."""
    value = 0.0
    for day in days:
        if day["precip"] > RAIN_RESET_MM:
            value = 0.0
        elif day["t"] > 0:
            value += day["t"] * max(0.0, day["t"] - day["dew"])
    return value


def history_range(date: datetime.date) -> tuple:
    return date - datetime.timedelta(days=NESTEROV_DAYS), date
