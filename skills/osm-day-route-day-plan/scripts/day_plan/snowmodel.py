"""Snow depth and ice for a given elevation from Open-Meteo hourly data: the
"hybrid" estimate. The model's own snow depth is corrected for the elevation of
a leg by two identical simulations of the last days, one with the model's
temperatures and one with the temperatures at the leg's elevation; the
difference is added to the model depth. Ice comes from explicit rules
(freezing rain, refreezing after wet weather, black ice on clear nights).

Everything here is a heuristic estimate, not a measurement; the constants are
in one place. Units: depths in centimetres (Open-Meteo gives `snow_depth` in
metres, the row parser converts it once), temperatures in degrees Celsius,
precipitation and rain in millimetres, snowfall in centimetres.

A row is a dict with `temp`, `dew`, `precip`, `rain`, `snowfall`, `snow_cm`,
`cloud`, `code` (any may be None) and `hour` (0-23 local); rows are hourly and
consecutive, and the planned date starts at `day_start` (a row index)."""

LAPSE_C_PER_M = 0.0065         # temperature falls this much per metre of height
SNOW_LINE_C = 1.0              # snow accumulates at or below this temperature
MELT_CM_PER_C_DAY = 1.5        # degree-day melt of snow depth
MELT_CM_PER_MM_RAIN = 0.3      # extra melt from rain falling on snow
SIM_HOURS = 10 * 24            # length of the simulation before the date
GLAZE_CODES = frozenset({56, 57, 66, 67})      # freezing drizzle / freezing rain
GLAZE_HOURS = 6                # glaze is remembered this long
REFREEZE_HOURS = 12            # look back this far for the thaw
WET_MM = 0.2                   # precipitation in those hours that wets the ground
BLACK_ICE_SPREAD_C = 1.5       # temperature minus dew point at most
BLACK_ICE_CLOUD_PCT = 30
APPLY_SNOW_CM = 0.5            # lying snow that makes the assessment relevant
APPLY_RECENT_HOURS = 72        # snow that fell this recently makes it relevant
APPLY_TEMP_C = 2.0             # frost risk: at or below this in the window or the previous 24 hours
APPLY_TEMP_HOURS = 24
SLUSH_DEPTH_CM = 0.5
ICE_RANK = {"none": 0, "moderate": 1, "high": 2}


def temp_at(temp, model_elev, elev):
    """Temperature at `elev` given the model temperature at `model_elev` (no correction when an elevation is unknown)."""
    if temp is None or model_elev is None or elev is None:
        return temp
    return temp + (model_elev - elev) * LAPSE_C_PER_M


def _accumulation(row, t_level):
    """Centimetres of snow added in this hour at a level with temperature `t_level`: the model's snowfall where it is
    cold enough, plus model rain that is snow at this level (1 mm of water is about 1 cm of snow)."""
    if t_level is None or t_level > SNOW_LINE_C:
        return 0.0
    snow = row.get("snowfall") or 0.0
    rain = row.get("rain") or 0.0
    t_model = row.get("temp")
    return snow + (rain if t_model is not None and t_model > SNOW_LINE_C else 0.0)


def simulate(rows, model_elev, elev, first, last):
    """Snow depth in cm for rows first..last (inclusive) at `elev`, starting from zero at row `first`."""
    depth, out = 0.0, []
    for i in range(first, last + 1):
        row = rows[i]
        t = temp_at(row.get("temp"), model_elev, elev)
        if t is not None:
            rain = row.get("rain") or 0.0
            melt = MELT_CM_PER_C_DAY * max(0.0, t) / 24.0 + (MELT_CM_PER_MM_RAIN * rain if t > SNOW_LINE_C else 0.0)
            depth = max(0.0, depth + _accumulation(row, t) - melt)
        out.append(depth)
    return out


def depth_series(rows, model_elev, elev, day_start, day_end):
    """Snow depth in cm at `elev` for rows day_start..day_end: the model depth plus the difference of two identical
    simulations over the last SIM_HOURS (at `elev` and at the model's own elevation), never below zero."""
    first = max(0, day_start - SIM_HOURS)
    at_level = simulate(rows, model_elev, elev, first, day_end)
    at_model = simulate(rows, model_elev, model_elev, first, day_end)
    shift = day_start - first
    return [max(0.0, (rows[day_start + k].get("snow_cm") or 0.0) + at_level[shift + k] - at_model[shift + k])
            for k in range(day_end - day_start + 1)]


def ice_levels(rows, model_elev, elev, depth, day_start, day_end, is_night):
    """(cleared, uncleared): the ice level ("none" | "moderate" | "high") per hour of day_start..day_end on cleared
    surfaces (wet asphalt, black ice) and on uncleared ones (icy crust of snow). `depth` is depth_series for the level;
    `is_night(hour)` says whether a local hour is dark."""
    cleared, uncleared = [], []
    for k, i in enumerate(range(day_start, day_end + 1)):
        row = rows[i]
        t = temp_at(row.get("temp"), model_elev, elev)
        glaze = any(rows[j].get("code") in GLAZE_CODES for j in range(max(0, i - GLAZE_HOURS), i + 1))
        previous = [temp_at(rows[j].get("temp"), model_elev, elev) for j in range(max(0, i - REFREEZE_HOURS), i)]
        previous = [p for p in previous if p is not None]
        wet = sum(rows[j].get("precip") or 0.0 for j in range(max(0, i - REFREEZE_HOURS), i)) > WET_MM
        refreeze = t is not None and t <= 0.0 and bool(previous) and max(previous) > SNOW_LINE_C and (
            wet or depth[k] >= SLUSH_DEPTH_CM)
        spread = None if row.get("temp") is None or row.get("dew") is None else row["temp"] - row["dew"]
        black = (t is not None and t <= 0.0 and spread is not None and spread <= BLACK_ICE_SPREAD_C
                 and row.get("cloud") is not None and row["cloud"] <= BLACK_ICE_CLOUD_PCT and is_night(row.get("hour")))
        c = u = "none"
        if glaze:
            c = u = "high"
        elif refreeze:
            c, u = "high", "moderate"
        elif black:
            c = "moderate"
        cleared.append(c)
        uncleared.append(u)
    return cleared, uncleared


def _worst(levels):
    return max(levels, key=ICE_RANK.__getitem__, default="none")


def window_conditions(rows, model_elev, elev, day_start, day_end, window_hours, is_night):
    """(snow_cm, ice_uncleared, ice_cleared, slush) at `elev`: the worst values in the planned window."""
    depth = depth_series(rows, model_elev, elev, day_start, day_end)
    cleared, uncleared = ice_levels(rows, model_elev, elev, depth, day_start, day_end, is_night)
    picks = [h for h in window_hours if 0 <= h <= day_end - day_start]
    snow = max((depth[h] for h in picks), default=0.0)
    slush = any((temp_at(rows[day_start + h].get("temp"), model_elev, elev) or 0.0) > 0.0 and depth[h] >= SLUSH_DEPTH_CM
                for h in picks)
    return snow, _worst(uncleared[h] for h in picks), _worst(cleared[h] for h in picks), slush


def applies(rows, model_elev, elevations, day_start, day_end, window_hours):
    """True when snow or ice is plausible for the plan: at any of the given elevations snow lies in the window, snow
    fell in the last APPLY_RECENT_HOURS, or the temperature was at or below APPLY_TEMP_C in the window or in the
    APPLY_TEMP_HOURS before the date."""
    picks = [day_start + h for h in window_hours if 0 <= h <= day_end - day_start]
    if not picks:
        return False
    for elev in elevations:
        depth = depth_series(rows, model_elev, elev, day_start, day_end)
        if max((depth[i - day_start] for i in picks), default=0.0) > APPLY_SNOW_CM:
            return True
        recent_from = max(0, day_start - APPLY_RECENT_HOURS)
        if any(_accumulation(rows[i], temp_at(rows[i].get("temp"), model_elev, elev)) > 0.0
               for i in range(recent_from, min(picks) + 1)):
            return True
        watched = list(range(max(0, day_start - APPLY_TEMP_HOURS), day_start)) + picks
        if any((t := temp_at(rows[i].get("temp"), model_elev, elev)) is not None and t <= APPLY_TEMP_C for i in watched):
            return True
    return False


def in_cold_season(month: int, lat: float, max_elevation: float | None) -> bool:
    """Whether snow or frost is plausible at all in this month: October to April north of the equator, April to
    October south of it, the whole year when the route reaches 2 000 m."""
    if max_elevation is not None and max_elevation >= 2000.0:
        return True
    return (month >= 10 or month <= 4) if lat >= 0 else (4 <= month <= 10)
