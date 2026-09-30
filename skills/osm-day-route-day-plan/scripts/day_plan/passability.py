"""Pure logic of the trail and road passability assessment: the configuration
table, the classification of the road a part of the route runs on, the legs
between the route's points, and the verdicts. No network, no plan text.

All numbers below are heuristics kept in one place. Only two of them rest on a
published figure: walking needs snowshoes or skis from 20 cm (8 inches) of
snow (a regulation of the High Peaks Wilderness in New York, reported by the
Adirondack Explorer), and micro-spikes do not suit steep or demanding ice
(Mammut's guide). Studded bicycle tires suit compact snow and ice and are not
useful in deep snow or powder, but no depth is published, so the bicycle
depths are guesses, labelled `derived` by the caller."""
from dataclasses import dataclass, field

from .osm_features import haversine_m

VERDICT_RANK = {"passable": 0, "caution": 1, "danger": 2}

# ---- configuration ---------------------------------------------------------------------------------------------------
CLEARED_HIGHWAYS = frozenset({"motorway", "trunk", "primary", "secondary", "tertiary", "residential", "living_street",
                              "unclassified"})
HARD_SURFACES = frozenset({"asphalt", "concrete", "paving_stones", "sett", "concrete:plates", "concrete:lanes",
                           "metal", "paved", "cobblestone"})
COMPACTED_SURFACES = frozenset({"compacted", "fine_gravel", "gravel", "pebblestone"})
SOFT_SURFACES = frozenset({"ground", "dirt", "earth", "grass", "sand", "mud", "unpaved", "woodchips", "grass_paver",
                           "snow", "ice"})
# the base a road has when its surface tag is missing, by highway class (the "assumed" flag is set then)
DEFAULT_BASE = {"motorway": "hard", "trunk": "hard", "primary": "hard", "secondary": "hard", "tertiary": "hard",
                "residential": "hard", "living_street": "hard", "unclassified": "compacted", "service": "compacted",
                "track": "compacted", "cycleway": "hard"}
TRACKTYPE_BASE = {"grade1": "hard", "grade2": "compacted", "grade3": "compacted", "grade4": "soft", "grade5": "soft"}
SAC_RANK = {"hiking": 1, "mountain_hiking": 2, "demanding_mountain_hiking": 3, "alpine_hiking": 4,
            "demanding_alpine_hiking": 5, "difficult_alpine_hiking": 6}

# snow depth in cm from which a run is difficult / not recommended, by profile and base; bicycles are assessed with
# studded tires (the caller says so in the text)
SNOW_THRESHOLDS = {
    "walk": {"hard": (8.0, 20.0), "compacted": (8.0, 20.0), "soft": (8.0, 20.0), "unknown": (8.0, 20.0)},
    "bike_leisure": {"hard": (3.0, 8.0), "compacted": (3.0, 8.0), "soft": (2.0, 6.0), "unknown": (2.0, 6.0)},
    "bike_sport": {"hard": (3.0, 10.0), "compacted": (3.0, 10.0), "soft": (2.0, 8.0), "unknown": (2.0, 8.0)},
}
STEEP_GRADIENT_PCT = 10.0          # walking on high ice: not recommended on a leg at least this steep
ICY_SAC_RANK = 3                   # T3 and harder with any snow on foot: not recommended
SNOW_ON_TECHNICAL_CM = 1.0
MTB_SCALE_CAUTION = 2              # mtb:scale from this with snow: difficult by bicycle
LEG_DANGER_SHARE = 0.20            # a leg is not recommended when its not-recommended runs make up this share
LEG_CAUTION_SHARE = 0.30           # difficult when difficult plus not-recommended runs make up this share
LEG_CAUTION_DANGER_SHARE = 0.10    # ... or when not-recommended runs alone make up this share (no cliff below 20 %)
POINT_SNAP_M = 300.0               # points farther from the track do not split it


def profile_for(mode: str, style: str | None) -> str | None:
    """The assessment profile of a route: walk, bike_leisure or bike_sport; None for a mode that is not assessed."""
    if mode == "walk":
        return "walk"
    if mode == "bike":
        return "bike_sport" if style == "sport" else "bike_leisure"
    return None


# ---- the road a part of the route runs on ------------------------------------------------------------------------------
@dataclass(frozen=True)
class Surface:
    cleared: bool            # snow is cleared from it (by class or by tag)
    base: str                # "hard" | "compacted" | "soft" | "unknown"
    assumed: bool            # the base came from the road class, not from a surface tag
    no_data: bool            # the archive says nothing about the road (no highway tag)
    sac: int                 # 0 when absent, else 1..6 (T1..T6)
    mtb: int                 # mtb:scale, 0 when absent
    label: str               # the surface tag or the highway class, for the table


def _int(value) -> int:
    try:
        return int(str(value).strip().rstrip("+-"))
    except ValueError:
        return 0


def classify_segment(segment: dict) -> Surface:
    """The Surface of one run of the archive's `segments`. The road is cleared of snow when `winter_service` or
    `snowplowing` says so, not cleared when `winter_service=no`, otherwise by its class."""
    highway = str(segment.get("highway", "")).removesuffix("_link")
    if str(segment.get("winter_service", "")).lower() == "yes" or str(segment.get("snowplowing", "")).lower() == "yes":
        cleared = True
    elif str(segment.get("winter_service", "")).lower() == "no":
        cleared = False
    else:
        cleared = highway in CLEARED_HIGHWAYS
    surface = str(segment.get("surface", "")).lower()
    assumed = False
    if surface in HARD_SURFACES:
        base = "hard"
    elif surface in COMPACTED_SURFACES:
        base = "compacted"
    elif surface in SOFT_SURFACES:
        base = "soft"
    else:
        assumed = True
        base = TRACKTYPE_BASE.get(str(segment.get("tracktype", "")).lower()) or DEFAULT_BASE.get(highway, "soft")
    no_data = not highway
    if no_data:
        base, cleared, assumed = "soft", False, True     # no road data: an uncleared soft path, the worst case
    return Surface(cleared=cleared, base=base, assumed=assumed, no_data=no_data,
                   sac=SAC_RANK.get(str(segment.get("sac_scale", "")).lower(), 0),
                   mtb=_int(segment.get("mtb:scale", 0)), label=surface or highway or "?")


# ---- legs ----------------------------------------------------------------------------------------------------------------
@dataclass
class Leg:
    name: str
    start: int                       # vertex indices into the route coordinates, inclusive
    end: int
    length_km: float
    min_ele: float | None
    max_ele: float | None
    mean_ele: float | None
    gradient_pct: float              # mean absolute gradient from the vertex elevations
    runs: list = field(default_factory=list)      # [(Surface, length_m)]


def _cumulative_m(coords: list) -> list:
    dist = [0.0]
    for a, b in zip(coords, coords[1:]):
        dist.append(dist[-1] + haversine_m(a[1], a[0], b[1], b[0]))
    return dist


def _known_elevations(coords: list) -> list:
    """Elevation per vertex with None for the unknown ones. The planner stores 0.0 where it could not look an elevation
    up, so a route whose elevations are all 0.0 has none, and an exact 0.0 next to elevations of 100 m or more is a
    gap, not sea level (the same reading as the mountain plugin)."""
    values = [c[2] for c in coords if c[2] is not None]
    top = max(values, default=0.0)
    return [None if c[2] is None or (c[2] == 0.0 and top >= 100.0) or (c[2] == 0.0 and top == 0.0) else c[2]
            for c in coords]


def _snap(coords: list, lat: float, lon: float):
    """(vertex index, distance in m) of the vertex nearest to the point."""
    best = min(range(len(coords)), key=lambda i: haversine_m(lat, lon, coords[i][1], coords[i][0]))
    return best, haversine_m(lat, lon, coords[best][1], coords[best][0])


def build_legs(coords: list, points: list, segments: list, start_name: str, finish_name: str, whole_name: str) -> list:
    """The parts of the track between neighbouring points. `points` are objects with name, role, lat and lon; one
    within POINT_SNAP_M of the track splits it at its nearest vertex (points at the same vertex are merged, the first
    name is kept). Without such a point the whole route is one leg. The two ends of the track are always
    boundaries. Runs come from `segments` ([{"from": i, "to": j, ...}], contiguous, covering every vertex)."""
    if len(coords) < 2:
        return []
    names = {}
    for point in points:
        index, distance = _snap(coords, point.lat, point.lon)
        if distance <= POINT_SNAP_M:
            names.setdefault(index, point.name)
    last = len(coords) - 1
    inner = sorted(i for i in names if 0 < i < last)
    boundaries = [0] + inner + [last]
    dist = _cumulative_m(coords)
    known = _known_elevations(coords)
    legs = []
    for a, b in zip(boundaries, boundaries[1:]):
        if len(boundaries) == 2:
            name = whole_name
        else:
            name = f"{names.get(a, start_name if a == 0 else '?')} → {names.get(b, finish_name if b == last else '?')}"
        elevations = [e for e in known[a:b + 1] if e is not None]
        gain = sum(abs(y - x) for x, y in zip(known[a:b + 1], known[a + 1:b + 1]) if x is not None and y is not None)
        length_m = dist[b] - dist[a]
        leg = Leg(name=name, start=a, end=b, length_km=length_m / 1000.0,
                  min_ele=min(elevations) if elevations else None, max_ele=max(elevations) if elevations else None,
                  mean_ele=sum(elevations) / len(elevations) if elevations else None,
                  gradient_pct=(gain / length_m * 100.0) if length_m > 0 else 0.0)
        for segment in segments:
            lo, hi = max(segment["from"], a), min(segment["to"], b)
            if hi > lo:
                leg.runs.append((classify_segment(segment), dist[hi] - dist[lo]))
        legs.append(leg)
    return legs


def surface_summary(runs: list, top: int = 3) -> list:
    """[(label, percent)] of the leg's length by surface label (the surface tag, else the highway class), largest
    first, at most `top`; the rest is merged into ("other", percent)."""
    total = sum(length for _, length in runs)
    if total <= 0:
        return []
    by_label = {}
    for surface, length in runs:
        by_label[surface.label] = by_label.get(surface.label, 0.0) + length
    ordered = sorted(by_label.items(), key=lambda kv: -kv[1])
    shown = [(label, round(100.0 * length / total)) for label, length in ordered[:top]]
    rest = sum(length for _, length in ordered[top:])
    if rest > 0:
        shown.append(("other", round(100.0 * rest / total)))
    return shown


# ---- verdicts ---------------------------------------------------------------------------------------------------------------
@dataclass
class Conditions:
    snow_cm: float            # snow depth at the leg's elevation, the worst in the planned window
    ice: str                  # "none" | "moderate" | "high": ice on uncleared surfaces (the worst in the window)
    slush: bool = False       # snow on the ground while the temperature is above freezing
    ice_cleared: str | None = None    # ice on cleared surfaces (wet asphalt, black ice); None: the same as `ice`

    def ice_on(self, surface) -> str:
        return self.ice_cleared if surface.cleared and self.ice_cleared is not None else self.ice


def _worse(a: str, b: str) -> str:
    return a if VERDICT_RANK[a] >= VERDICT_RANK[b] else b


def judge_run(profile: str, surface: Surface, conditions: Conditions, gradient_pct: float) -> str:
    """"passable" | "caution" | "danger" for one run of a leg."""
    snow = 0.0 if surface.cleared else conditions.snow_cm
    caution_from, danger_from = SNOW_THRESHOLDS[profile][surface.base]
    verdict = "passable"
    if snow >= danger_from:
        verdict = "danger"
    elif snow >= caution_from:
        verdict = "caution"
    ice = conditions.ice_on(surface)
    if profile == "walk":
        if ice == "high":
            verdict = _worse(verdict, "danger" if gradient_pct >= STEEP_GRADIENT_PCT else "caution")
        if surface.sac >= ICY_SAC_RANK and conditions.snow_cm >= SNOW_ON_TECHNICAL_CM:
            verdict = "danger"
    else:                                   # studded tires: ice alone costs nothing
        if not surface.cleared and ice != "none" and conditions.snow_cm > 0:
            verdict = _worse(verdict, "caution")            # an icy crust or rutted ice on an uncleared run
        if snow > 0 and conditions.slush:
            verdict = _worse(verdict, "caution")
        if surface.mtb >= MTB_SCALE_CAUTION and snow >= SNOW_ON_TECHNICAL_CM:
            verdict = _worse(verdict, "caution")
    return verdict


@dataclass
class LegVerdict:
    verdict: str
    danger_share: float
    caution_share: float
    no_data_share: float


def judge_leg(profile: str, leg: Leg, conditions: Conditions) -> LegVerdict:
    """The verdict of a leg: not recommended when its not-recommended runs make up LEG_DANGER_SHARE of its length,
    else difficult when they make up LEG_CAUTION_DANGER_SHARE, or when difficult and not-recommended runs together
    make up LEG_CAUTION_SHARE, else passable. A leg with no runs (no road data) is judged as an uncleared soft path."""
    runs = leg.runs or [(classify_segment({}), max(leg.length_km * 1000.0, 1.0))]
    total = sum(length for _, length in runs)
    danger = caution = no_data = 0.0
    for surface, length in runs:
        result = judge_run(profile, surface, conditions, leg.gradient_pct)
        if result == "danger":
            danger += length
        elif result == "caution":
            caution += length
        if surface.no_data:
            no_data += length
    danger_share, caution_share = danger / total, caution / total
    if danger_share >= LEG_DANGER_SHARE:
        verdict = "danger"
    elif danger_share >= LEG_CAUTION_DANGER_SHARE or danger_share + caution_share >= LEG_CAUTION_SHARE:
        verdict = "caution"
    else:
        verdict = "passable"
    return LegVerdict(verdict, danger_share, caution_share, no_data / total)
