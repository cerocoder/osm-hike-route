# Day Plan Radiation, People and Coverage (part 3b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the hazards of `day-plan-<date>.md`: a Radiation part backed by a researched, sourced registry of contaminated zones (Urals, Chernobyl, Bryansk, Semipalatinsk), a People and access part from recorded facts, and a Mobile coverage section, all embedded in `map.html` like the rest of the plan.

**Architecture:** A static registry (`data/radiation_zones.json`) and a small planar-geometry module; three new `SectionPlugin`s in the existing service. The radiation plugin depends on nothing and its warnings are pinned in the Summary. Coverage reuses the shared `osm_features` masts.

**Tech Stack:** Python 3 stdlib only, pytest. No API keys, no network at run time for radiation.

**Note:** this plan was regenerated after its execution and contains the final code, including the fixes of the final whole-branch review (a truthful no-entry line next to advisory areas, distances in tenths of a kilometre, no repeated event in the pinned caution, the corrected Russian mushroom name, a failure-safe hint, the credit line as its own paragraph). The task order and tests are those that were executed.

**Spec:** `docs/superpowers/specs/2026-09-29-osm-day-route-day-plan-design.md`. Parts 1, 2 and 3a are merged. This is part **3b**, the last of the third plan.

**Deviations from the spec (decided while researching):**
- **A third tier, `info`, for advisory areas** (the Bavarian mushroom areas named by the German federal radiation protection office and the Norwegian mountain municipalities singled out by the Norwegian authority): an info line only when the route is inside, with the mushroom and game advice only, because the source itself calls moderate consumption harmless.
- **Radiation severity per zone.** The spec gives a `danger` on any hit. Here a closed or heavily contaminated zone (the East Ural reserve, Mayak, Karachay, the Chernobyl zone, the Polesie reserve) gives `danger`, and a wide affected area (the East Urals trace, the Techa floodplain, south-western Bryansk, the Semipalatinsk site) gives `caution`, because most of a district or of a 18 000 km² test site is far cleaner than its worst spot. The mushroom, berry and spring advice is the same for both.
- **Radiation comes first in the Hazards group** (the spec lists it after air) and its warnings are pinned in the Summary.
- **People hazards: no fact means no section**, not `no-data` (which would put "People and access" in every plan's missing-data list). Animals need no new plugin: `bio_hazards` facts already carry them.
- **Mobile coverage is info-only**: mast count from OpenStreetMap, advice and links, no terrain model. OpenStreetMap masts are sparse and a model without measured data would be a guess dressed as an estimate. Only nPerf and OpenCellID were confirmed to answer; the operators' own maps (MTS, MegaFon, Beeline, T2) could not be confirmed and are not linked.
- **Registry area.** The registry covers rectangles for Europe with the Urals (north of 36 N), Siberia, northern Kazakhstan and the Far East north of 49 N, and Primorye. The spec excluded China, Mongolia and the Far East outside Russia; rectangles cannot follow borders, so a route just inside a box edge in China or Mongolia is a known limitation.
- **The registry starts with thirteen researched zones**, not the spec's whole list. Every zone has a source read during research and geometry from OpenStreetMap or from published figures. Totskoye, Novaya Zemlya, the Seversk 1993 trace, the peaceful underground explosions, Sweden and Finland were researched and left out because the sources show only local plots, decayed or contradictory contamination, no outline, or no need for a warning; Wismut, Jáchymov, La Hague, Sellafield, Andreeva Bay and the Balkans are not researched yet. `data/README.md` and SKILL.md say why for each; a plan says so and never says "safe".

## Global Constraints

- Every script is stdlib-only; no API keys, no new dependencies. Tests never touch the network.
- Confidence tiers: `tag-backed` (OSM, or a registry zone with a primary source), `web-sourced`, `derived`, `no-data`. "Not applicable" is `omit=True`, never "missing data".
- The plan is embedded in a `map.html` that is forwarded: no street addresses, phone numbers or personal data; facts need an `http(s)` source; plugin failures are isolated and never break the plan.
- Every registry zone: a cited `http(s)` source (one `primary` for a zone that raises a warning), English and Russian text, coordinates as `[longitude, latitude]`, closed rings, an `approximate` flag with a bilingual note where the outline is not published, the OpenStreetMap credit (ODbL) where its geometry is used.
- Localized body text for English and Russian (English fallback), headings in seven languages; no English text may leak into a Russian plan.
- Section order: summary, light, weather, transit, pois, hazards (radiation, mountain, fire, bio, air, people), cell_coverage.
- Commit trailer on every commit: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

- A route whose only contact with a zone is one long straight segment (no vertex inside, as with a zone crossed between two far-apart track points): still a hit.
- No hit, or a route outside the registry: the plan says "no entry in the registry", never "safe"; a route outside the registry's boxes (China, Mongolia, Japan, Korea, the Americas) gets no radiation part at all.
- Five weather dangers must not push a radiation danger out of the Summary's top five; radiation must still appear when the network and every other plugin fail.
- Mobile coverage: a missing OpenStreetMap mast is never "no signal"; Overpass down gives a no-data line that keeps the links and the advice; nothing above `info`.
- A `people_hazards` fact without a source is ignored; no fact means no section; no text about a group of people.

---

### Task 1: Foundation: pinned warnings, geometry, strings

`PlanWarning.pinned` lets the Summary list a warning before other warnings of the same severity (used by radiation, so five weather dangers cannot push a contaminated zone out of the top five). `geo.py` is the planar geometry the radiation registry needs: kilometre projection, point-in-polygon, segment intersection and distances, bounding-box clipping. All new localized strings of part 3b (en and ru) are added here so later tasks only use them.

**Files:**
- Create: `skills/osm-day-route-day-plan/tests/test_geo.py`
- Create: `skills/osm-day-route-day-plan/tests/test_pinned_warnings.py`
- Modify: `skills/osm-day-route-day-plan/scripts/day_plan/base.py`
- Modify: `skills/osm-day-route-day-plan/scripts/day_plan/summary.py`
- Create: `skills/osm-day-route-day-plan/scripts/day_plan/geo.py`
- Modify: `skills/osm-day-route-day-plan/scripts/day_plan/i18n.py`

- [ ] **Step 1: Add the tests** (14 tests in the file(s) below)

Create `skills/osm-day-route-day-plan/tests/test_geo.py`:

```python
import math

import pytest

from day_plan.geo import (
    bboxes_close, clip_segments, point_in_ring, point_segment_distance, polygon_distance, polyline_distance, project,
    segment_segment_distance, segments_distance, segments_intersect, to_segments,
)

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)]


def test_project_gives_kilometres_and_shrinks_longitude_with_latitude():
    x, y = project(11.0, 60.0, 60.0, 10.0)
    assert x == pytest.approx(111.195 * 0.5, rel=1e-3) and y == 0.0
    assert project(10.0, 61.0, 60.0, 10.0) == pytest.approx((0.0, 111.195))


def test_project_wraps_at_the_antimeridian():
    x, _ = project(-179.5, 0.0, 0.0, 179.5)
    assert x == pytest.approx(111.195, rel=1e-3)


def test_point_in_ring_inside_outside_and_concave():
    assert point_in_ring(5, 5, SQUARE) and not point_in_ring(11, 5, SQUARE) and not point_in_ring(5, -1, SQUARE)
    u_shape = [(0, 0), (9, 0), (9, 9), (6, 9), (6, 3), (3, 3), (3, 9), (0, 9), (0, 0)]
    assert point_in_ring(1, 5, u_shape) and point_in_ring(8, 5, u_shape) and not point_in_ring(4.5, 6, u_shape)


def test_segments_intersect_crossing_disjoint_and_parallel():
    assert segments_intersect((0, 0), (10, 10), (0, 10), (10, 0))
    assert not segments_intersect((0, 0), (1, 0), (2, 0), (3, 0))
    assert not segments_intersect((0, 0), (10, 0), (0, 1), (10, 1))


def test_segment_distances():
    assert point_segment_distance(5, 3, 0, 0, 10, 0) == 3.0
    assert point_segment_distance(-4, 3, 0, 0, 10, 0) == 5.0                  # beyond the end: distance to the endpoint
    assert segment_segment_distance((0, 0), (10, 0), (0, 4), (10, 4)) == 4.0
    assert segment_segment_distance((0, 0), (10, 10), (0, 10), (10, 0)) == 0.0


def test_a_single_segment_crossing_a_polygon_with_both_ends_outside_touches_it():
    assert polygon_distance([(-5.0, 5.0), (15.0, 5.0)], SQUARE) == 0.0


def test_a_route_beside_a_polygon_gets_the_distance_to_its_edge_and_a_cap_gives_infinity():
    assert polygon_distance([(13.0, 2.0), (13.0, 8.0)], SQUARE) == pytest.approx(3.0)
    assert polygon_distance([(13.0, 2.0), (13.0, 8.0)], SQUARE, cap=2.0) == math.inf


def test_a_route_entirely_inside_a_polygon_is_zero():
    assert polygon_distance([(2.0, 2.0), (3.0, 3.0)], SQUARE) == 0.0


def test_polyline_distance_with_a_single_point_and_a_cap():
    assert polyline_distance([(0.0, 5.0)], [(3.0, 0.0), (3.0, 10.0)]) == pytest.approx(3.0)
    assert polyline_distance([(0.0, 5.0)], [(30.0, 0.0), (30.0, 10.0)], cap=5.0) == math.inf


def test_clip_segments_keeps_only_segments_near_the_box():
    segments = to_segments([(0, 0), (1, 0), (50, 0), (51, 0)])
    kept = clip_segments(segments, (0.0, -1.0, 2.0, 1.0), margin=1.0)
    assert kept == [((0, 0), (1, 0)), ((1, 0), (50, 0))]                       # the last one is 48 km away


def test_bboxes_close_uses_a_margin_in_km():
    a, b = (0.0, 0.0, 1.0, 1.0), (1.02, 0.0, 2.0, 1.0)
    assert bboxes_close(a, b, 3.0) and not bboxes_close(a, b, 0.5)
    assert not bboxes_close(a, (5.0, 5.0, 6.0, 6.0), 10.0)


def test_segments_distance_of_two_crossing_sets_is_zero():
    assert segments_distance(to_segments([(0, 0), (10, 10)]), to_segments([(0, 10), (10, 0)])) == 0.0
```

Create `skills/osm-day-route-day-plan/tests/test_pinned_warnings.py`:

```python
from day_plan.base import PlanWarning, Section
from day_plan.summary import MAX_ITEMS, build_summary_section


def test_the_summary_keeps_a_pinned_danger_in_the_top_items_even_after_many_other_dangers():
    storm = Section("weather", "", "derived", warnings=[PlanWarning("danger", f"Storm {i}") for i in range(MAX_ITEMS + 2)])
    radiation = Section("hazards", "", "tag-backed", warnings=[
        PlanWarning("caution", "Bryansk caution", pinned=True), PlanWarning("danger", "Zone danger", pinned=True)])
    summary = build_summary_section([storm, radiation], "en")
    lines = summary.markdown.splitlines()
    assert lines[0] == "- **Danger:** Zone danger"
    assert "Bryansk caution" not in summary.markdown                        # the cap is still five items
    assert len([l for l in lines if l.startswith("- **")]) == MAX_ITEMS


def test_pinned_only_breaks_ties_within_a_severity():
    a = Section("weather", "", "derived", warnings=[PlanWarning("danger", "Storm")])
    b = Section("hazards", "", "tag-backed", warnings=[PlanWarning("caution", "Zone", pinned=True)])
    assert build_summary_section([b, a], "en").markdown.splitlines()[:2] == ["- **Danger:** Storm", "- **Caution:** Zone"]
```

- [ ] **Step 2: Run them and see them fail** — `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_geo.py tests/test_pinned_warnings.py -q` (import errors or assertion failures: the code does not exist yet).

- [ ] **Step 3: Write the implementation**

Modify `skills/osm-day-route-day-plan/scripts/day_plan/base.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-day-plan/scripts/day_plan/base.py
+++ b/skills/osm-day-route-day-plan/scripts/day_plan/base.py
@@ -16,6 +16,7 @@
 class PlanWarning:
     severity: str  # one of SEVERITIES
     text: str
+    pinned: bool = False  # sorts before other warnings of the same severity in the Summary (radiation)
 
 
 @dataclass
```

Modify `skills/osm-day-route-day-plan/scripts/day_plan/summary.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-day-plan/scripts/day_plan/summary.py
+++ b/skills/osm-day-route-day-plan/scripts/day_plan/summary.py
@@ -24,7 +24,7 @@
 
 def build_summary_section(sections: list, lang: str) -> Section:
     warnings = [w for s in sections for w in s.warnings]
-    warnings.sort(key=lambda w: _SEVERITY_RANK.get(w.severity, 3))  # stable: keeps plugin order
+    warnings.sort(key=lambda w: (_SEVERITY_RANK.get(w.severity, 3), not w.pinned))  # stable: keeps plugin order
     lines = [f"- **{_severity_label(w.severity, lang)}:** {_flat(w.text)}" for w in warnings[:MAX_ITEMS]]
     if not lines:
         lines.append("- " + tr("summary_none", lang))
```

Create `skills/osm-day-route-day-plan/scripts/day_plan/geo.py`:

```python
"""Small planar geometry for the radiation registry: everything is projected to
kilometres around one reference latitude (equirectangular), which is exact
enough for zones a few hundred kilometres across. Routes are tested by
their segments, not only by their vertices: a straight segment can cross a
small zone with both ends far outside it."""
import math

KM_PER_DEG = 111.195


def project(lon: float, lat: float, lat0: float, lon0: float) -> tuple:
    """(x_km, y_km) east and north of (lat0, lon0); longitude differences wrap at the antimeridian."""
    dlon = (lon - lon0 + 180.0) % 360.0 - 180.0
    return dlon * KM_PER_DEG * math.cos(math.radians(lat0)), (lat - lat0) * KM_PER_DEG


def bbox_of(points: list) -> tuple:
    """(min_lon, min_lat, max_lon, max_lat) of [(lon, lat), ...]."""
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    return min(lons), min(lats), max(lons), max(lats)


def bboxes_close(a: tuple, b: tuple, margin_km: float) -> bool:
    """True when two (min_lon, min_lat, max_lon, max_lat) boxes are within margin_km (generous: uses the widest longitude scale)."""
    lat = max(abs(a[1]), abs(a[3]), abs(b[1]), abs(b[3]))
    dlat = margin_km / KM_PER_DEG
    dlon = margin_km / (KM_PER_DEG * max(0.05, math.cos(math.radians(min(lat, 85.0)))))
    return not (a[2] + dlon < b[0] or b[2] + dlon < a[0] or a[3] + dlat < b[1] or b[3] + dlat < a[1])


def point_in_ring(x: float, y: float, ring: list) -> bool:
    """Ray casting; ring is [(x, y), ...], closed or not."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def point_segment_distance(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _orient(ax, ay, bx, by, cx, cy) -> float:
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def segments_intersect(a1, a2, b1, b2) -> bool:
    d1 = _orient(*b1, *b2, *a1)
    d2 = _orient(*b1, *b2, *a2)
    d3 = _orient(*a1, *a2, *b1)
    d4 = _orient(*a1, *a2, *b2)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 != 0 and d2 != 0 and d3 != 0 and d4 != 0:
        return True
    return False


def segment_segment_distance(a1, a2, b1, b2) -> float:
    if segments_intersect(a1, a2, b1, b2):
        return 0.0
    return min(point_segment_distance(*a1, *b1, *b2), point_segment_distance(*a2, *b1, *b2),
               point_segment_distance(*b1, *a1, *a2), point_segment_distance(*b2, *a1, *a2))


def to_segments(line: list) -> list:
    """[(x, y), ...] -> [((x1, y1), (x2, y2)), ...]; a single point becomes one zero-length segment."""
    if len(line) == 1:
        return [(line[0], line[0])]
    return [(line[i], line[i + 1]) for i in range(len(line) - 1)]


def _box(segment) -> tuple:
    (x1, y1), (x2, y2) = segment
    return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)


def clip_segments(segments: list, box: tuple, margin: float) -> list:
    """The segments whose bounding box comes within `margin` of box = (min_x, min_y, max_x, max_y)."""
    kept = []
    for seg in segments:
        sx0, sy0, sx1, sy1 = _box(seg)
        if sx1 >= box[0] - margin and sx0 <= box[2] + margin and sy1 >= box[1] - margin and sy0 <= box[3] + margin:
            kept.append(seg)
    return kept


def segments_distance(segs_a: list, segs_b: list, cap: float = math.inf) -> float:
    """Minimum distance between two sets of segments; pairs whose bounding boxes are more than `cap` apart are skipped
    (the result is then math.inf when nothing lies within cap)."""
    best = math.inf
    boxes_b = [_box(s) for s in segs_b]
    for a in segs_a:
        ax0, ay0, ax1, ay1 = _box(a)
        for b, (bx0, by0, bx1, by1) in zip(segs_b, boxes_b):
            if max(ax0 - bx1, bx0 - ax1, ay0 - by1, by0 - ay1) > min(cap, best):
                continue
            best = min(best, segment_segment_distance(a[0], a[1], b[0], b[1]))
            if best == 0.0:
                return 0.0
    return best


def polyline_distance(line_a: list, line_b: list, cap: float = math.inf) -> float:
    """Minimum distance between two polylines [(x, y), ...]."""
    return segments_distance(to_segments(line_a), to_segments(line_b), cap)


def polygon_distance_segments(segments: list, ring: list, cap: float = math.inf) -> float:
    """0 when any route segment touches or lies inside the polygon ring, else the shortest distance to its edge."""
    if any(point_in_ring(*seg[0], ring) or point_in_ring(*seg[1], ring) for seg in segments):
        return 0.0
    closed = ring if ring[0] == ring[-1] else ring + [ring[0]]
    return segments_distance(segments, to_segments(closed), cap)


def polygon_distance(route: list, ring: list, cap: float = math.inf) -> float:
    """polygon_distance_segments for a route given as points [(x, y), ...]."""
    return polygon_distance_segments(to_segments(route), ring, cap)
```

Modify `skills/osm-day-route-day-plan/scripts/day_plan/i18n.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-day-plan/scripts/day_plan/i18n.py
+++ b/skills/osm-day-route-day-plan/scripts/day_plan/i18n.py
@@ -154,6 +154,36 @@
         "air_warn_emissions": "Industrial emissions may be carried toward the route ({hours}).",
         "hz_bio": "Ticks and biting insects", "hz_mountain": "Mountain hazards", "hz_fire": "Fire danger",
         "hz_air": "Air: pollen and pollution",
+        "hz_radiation": "Radiation", "hz_people": "People and access",
+        "rad_none": "No zone of the radiation registry lies within {km} km of the route or its points. The registry is curated by hand and incomplete (it covers: {areas}), so no entry does not mean the land is clean.",
+        "rad_none_advisory": "No danger zone or affected area of the radiation registry lies within {km} km of the route or its points. The registry is curated by hand and incomplete (it covers: {areas}), so no entry does not mean the land is clean.",
+        "rad_areas": "the East Urals trace, the Techa river, Mayak and Lake Karachay, the Chernobyl zones (Ukraine, Belarus, the Bryansk, Tula, Kaluga and Orel regions), the Semipalatinsk test site, the Yenisei below Zheleznogorsk, wild-mushroom areas in Bavaria and Norway",
+        "rad_inside": "- **{name}** ({severity}): the route or one of its points is inside the zone. {contamination}. {status}",
+        "rad_near": "- **{name}** ({severity}): the route passes about {km} km from the zone. {contamination}. {status}",
+        "rad_approx": " *Approximate outline: {note}*",
+        "rad_advice_title": "In or near such land:",
+        "rad_advice_food": "- Do not pick mushrooms or berries.",
+        "rad_advice_water": "- Springs, streams and other natural water may be contaminated: do not drink from them or collect water.",
+        "rad_advice_dust": "- Avoid dust and open fires on the soil; take no soil, wood or plants out.",
+        "rad_advice_wind": "- Wind and wildfire lift contaminated dust and smoke: check the wind in the weather table and the fire danger below.",
+        "rad_replan": "Consider changing the route (osm-day-route-planning) so that it avoids the zone.",
+        "rad_osm_credit": "Zone outlines from OpenStreetMap (© OpenStreetMap contributors, ODbL) where noted.",
+        "rad_warn_inside_danger": "The route enters {name}: contaminated land. Do not pick mushrooms or berries, do not drink from springs or streams, stay out of the zone if it is closed.",
+        "rad_warn_inside_caution": "The route crosses {name}. Do not pick mushrooms or berries and do not drink from springs or streams.",
+        "rad_warn_near": "The route passes about {km} km from {name}: do not pick mushrooms or berries and do not drink from springs or streams near it.",
+        "rad_sev_danger": "danger zone", "rad_sev_caution": "affected area", "rad_sev_info": "advisory area",
+        "rad_advice_mushrooms": "- Wild mushrooms and game from these areas can still carry caesium-137: eat them in moderation and check the local advice.",
+        "rad_warn_inside_info": "The route crosses {name}: some wild mushrooms and game here can still exceed the caesium-137 limit; eat them in moderation.",
+        "ppl_web_title": "**Access and safety notes (from web sources, not verified in person)**",
+        "cell_masts": "- Mobile masts recorded in OpenStreetMap within {km} km of the route: **{count}**{nearest}.",
+        "cell_nearest": " (nearest about {dist} km)",
+        "cell_none": "- No mobile masts are recorded in OpenStreetMap within {km} km of the route.",
+        "cell_osm_unavailable": "- Mast data from OpenStreetMap could not be loaded ({reason}).",
+        "cell_caveat": "  *OpenStreetMap records only a share of the masts: a missing mast does not mean there is no signal, and a mast does not guarantee it (valleys, forest and distance weaken it). Coverage is not measured here.*",
+        "cell_advice": "- Download offline maps and the GPX track before you leave, tell someone the route and your return time, carry a power bank, and know that 112 is the emergency number in Europe and Russia.",
+        "cell_maps": "- Coverage maps: [nPerf]({nperf}), [OpenCellID](https://opencellid.org/) (masts and measurements); your operator's own coverage map shows more.",
+        "cell_warn_none": "No mobile masts are recorded near the route: the signal may be weak or absent, take offline maps and tell someone your plan.",
+        "fire_kpo_beyond": "The Nesterov index needs weather data and is not available this far ahead.",
         "weekday_names": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
         "cal_line": "Date: {weekday} {date} — {kind}; {holiday} {source}",
         "cal_weekend": "weekend", "cal_workday": "working day", "cal_dayoff": "day off",
@@ -332,6 +362,36 @@
         "air_warn_emissions": "Выбросы промышленных объектов могут нести на маршрут ({hours}).",
         "hz_bio": "Клещи и кровососущие насекомые", "hz_mountain": "Горные опасности",
         "hz_fire": "Пожарная опасность", "hz_air": "Воздух: пыльца и загрязнение",
+        "hz_radiation": "Радиация", "hz_people": "Люди и доступ",
+        "rad_none": "В радиус {km} км от маршрута и его точек не попадает ни одна зона реестра радиации. Реестр составлен вручную и неполон (в нём: {areas}), поэтому отсутствие записи не означает, что земля чистая.",
+        "rad_none_advisory": "Ни опасная зона, ни затронутая территория реестра радиации не лежат в радиусе {km} км от маршрута и его точек. Реестр составлен вручную и неполон (в нём: {areas}), поэтому отсутствие записи не означает, что земля чистая.",
+        "rad_areas": "Восточно-Уральский след, река Теча, «Маяк» и озеро Карачай, чернобыльские зоны (Украина, Беларусь, Брянская, Тульская, Калужская и Орловская области), Семипалатинский полигон, Енисей ниже Железногорска, районы Баварии и Норвегии с грибами",
+        "rad_inside": "- **{name}** ({severity}): маршрут или одна из его точек внутри зоны. {contamination}. {status}",
+        "rad_near": "- **{name}** ({severity}): маршрут проходит примерно в {km} км от зоны. {contamination}. {status}",
+        "rad_approx": " *Приблизительный контур: {note}*",
+        "rad_advice_title": "На такой земле и рядом с ней:",
+        "rad_advice_food": "- Не собирайте грибы и ягоды.",
+        "rad_advice_water": "- Родники, ручьи и другая природная вода могут быть заражены: не пейте из них и не набирайте воду.",
+        "rad_advice_dust": "- Избегайте пыли и костров на этой почве; ничего не выносите — ни почву, ни дрова, ни растения.",
+        "rad_advice_wind": "- Ветер и лесные пожары поднимают заражённую пыль и дым: посмотрите ветер в таблице погоды и раздел о пожарной опасности ниже.",
+        "rad_replan": "Подумайте об изменении маршрута (osm-day-route-planning), чтобы обойти зону.",
+        "rad_osm_credit": "Контуры зон — из OpenStreetMap (© участники OpenStreetMap, ODbL), где это указано.",
+        "rad_warn_inside_danger": "Маршрут входит в зону: {name} — заражённая земля. Не собирайте грибы и ягоды, не пейте из родников и ручьёв; если зона закрыта, не входите в неё.",
+        "rad_warn_inside_caution": "Маршрут пересекает зону: {name}. Не собирайте грибы и ягоды и не пейте из родников и ручьёв.",
+        "rad_warn_near": "Маршрут проходит примерно в {km} км от зоны: {name}. Рядом не собирайте грибы и ягоды и не пейте из родников и ручьёв.",
+        "rad_sev_danger": "опасная зона", "rad_sev_caution": "затронутая территория", "rad_sev_info": "зона с рекомендациями",
+        "rad_advice_mushrooms": "- Дикие грибы и дичь из этих районов всё ещё могут содержать цезий-137: ешьте их умеренно и уточняйте местные рекомендации.",
+        "rad_warn_inside_info": "Маршрут пересекает зону: {name}. Некоторые дикие грибы и дичь здесь всё ещё могут превышать предел по цезию-137; ешьте их умеренно.",
+        "ppl_web_title": "**Доступ и безопасность (по веб-источникам, лично не проверено)**",
+        "cell_masts": "- Вышек сотовой связи в OpenStreetMap в радиусе {km} км от маршрута: **{count}**{nearest}.",
+        "cell_nearest": " (ближайшая примерно в {dist} км)",
+        "cell_none": "- В OpenStreetMap нет вышек сотовой связи в радиусе {km} км от маршрута.",
+        "cell_osm_unavailable": "- Данные о вышках из OpenStreetMap загрузить не удалось ({reason}).",
+        "cell_caveat": "  *В OpenStreetMap записана лишь часть вышек: отсутствие вышки не значит, что связи нет, а её наличие не гарантирует сигнал (долины, лес и расстояние его ослабляют). Покрытие здесь не измеряется.*",
+        "cell_advice": "- Скачайте офлайн-карты и GPX-трек до выхода, сообщите кому-нибудь маршрут и время возвращения, возьмите внешний аккумулятор и помните: 112 — номер экстренных служб в Европе и России.",
+        "cell_maps": "- Карты покрытия: [nPerf]({nperf}), [OpenCellID](https://opencellid.org/) (вышки и замеры); карта вашего оператора покажет больше.",
+        "cell_warn_none": "Рядом с маршрутом нет вышек в OpenStreetMap: сигнал может быть слабым или отсутствовать, возьмите офлайн-карты и сообщите кому-нибудь свой план.",
+        "fire_kpo_beyond": "Показатель Нестерова считается по данным погоды и на такой срок недоступен.",
         "weekday_names": ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"],
         "cal_line": "Дата: {weekday} {date} — {kind}; {holiday} {source}",
         "cal_weekend": "выходной", "cal_workday": "рабочий день", "cal_dayoff": "выходной день",
```

- [ ] **Step 4: Run the whole suite** — `cd skills/osm-day-route-day-plan && python3 -m pytest tests -q` (all green), and for the show skill `cd skills/osm-day-route-show && python3 -m pytest tests -q`.

- [ ] **Step 5: Commit**

```bash
git add skills README.md
git commit -m "Pinned warnings, planar geometry and strings for radiation, people and coverage

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

### Task 2: Carried over from part 3a

Five small honesty fixes the final review of part 3a deferred: on a climatology day the weather codes are not a thunderstorm forecast; no tick line on a freezing day; an empty GWIS answer is remembered for a day, not for good, even for a past date; the Nesterov index says it is unavailable beyond the weather horizon instead of vanishing. (The sixth, the hint that must never fail a written plan, is in Task 6 with the CLI.) Drop this task if you do not want them: nothing else depends on it.

**Files:**
- Modify: `skills/osm-day-route-day-plan/tests/test_fire.py`
- Modify: `skills/osm-day-route-day-plan/tests/test_mountain.py`
- Modify: `skills/osm-day-route-day-plan/tests/test_bio_hazards.py`
- Modify: `skills/osm-day-route-day-plan/tests/test_gwis.py`
- Modify: `skills/osm-day-route-day-plan/scripts/day_plan/plugins/fire.py`
- Modify: `skills/osm-day-route-day-plan/scripts/day_plan/plugins/mountain.py`
- Modify: `skills/osm-day-route-day-plan/scripts/day_plan/plugins/bio_hazards.py`
- Modify: `skills/osm-day-route-day-plan/scripts/day_plan/gwis.py`

- [ ] **Step 1: Add the tests** (96 tests in the file(s) below)

Modify `skills/osm-day-route-day-plan/tests/test_fire.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-day-plan/tests/test_fire.py
+++ b/skills/osm-day-route-day-plan/tests/test_fire.py
@@ -174,7 +174,8 @@
 def test_no_nesterov_beyond_the_open_meteo_horizon(make_route, fixed_now):
     world = World(country="ru", history=history(31))
     section = run(make_route, fixed_now, world, coords=EKB, date=TODAY + datetime.timedelta(days=16))
-    assert "Nesterov" not in section.markdown and not any("open-meteo" in u for u in world.json_calls)
+    assert "The Nesterov index needs weather data and is not available this far ahead." in section.markdown
+    assert not any("open-meteo" in u for u in world.json_calls)
 
 
 def test_restrictions_from_facts_are_shown_with_sources_and_warnings(make_route, fixed_now):
```

Modify `skills/osm-day-route-day-plan/tests/test_mountain.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-day-plan/tests/test_mountain.py
+++ b/skills/osm-day-route-day-plan/tests/test_mountain.py
@@ -21,14 +21,15 @@
 
 
 def run(make_route, fixed_now, elevations, weather_rows=None, features=None, osm_error=None, date=SUMMER, lang="en",
-        facts=None, elevation_m=None, folder="route", with_osm=True):
+        facts=None, elevation_m=None, folder="route", with_osm=True, weather_source=None):
     route_dir = make_route(coords=coords(*elevations), folder=folder)
     if facts is not None:
         (route_dir / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
     ctx = build_context(route_dir, date, lang=lang, http=lambda u: {}, now=fixed_now)
     shared = {}
     if weather_rows is not None:
-        shared["weather"] = {"daytime_rows": weather_rows, "rows": weather_rows, "elevation_m": elevation_m}
+        shared["weather"] = {"daytime_rows": weather_rows, "rows": weather_rows, "elevation_m": elevation_m,
+                             **({"source": weather_source} if weather_source else {})}
     if with_osm:
         shared["osm_features"] = {"features": features or [], "samples": [(c[1], c[0]) for c in ctx.coords],
                                   "error": osm_error}
@@ -211,3 +212,12 @@
     section = run(make_route, fixed_now, (None, None), facts={"all": {"mountain": fact}})
     assert "no elevation data" in section.markdown and "avalanche bulletin for the Caucasus" in section.markdown
     assert section.confidence == "web-sourced" and "Sources: [example.org](https://example.org/aval)" in section.markdown
+
+
+def test_thunder_weather_codes_of_a_climatology_day_are_not_a_forecast(make_route, fixed_now):
+    climate = run(make_route, fixed_now, (900.0, 1700.0), weather_rows=rows(code=95), folder="climate",
+                  weather_source="climate")
+    assert "Thunderstorms are forecast" not in climate.markdown and not any("Thunderstorm" in w.text for w in climate.warnings)
+    forecast = run(make_route, fixed_now, (900.0, 1700.0), weather_rows=rows(code=95), folder="forecast",
+                   weather_source="forecast")
+    assert "Thunderstorms are forecast" in forecast.markdown
```

Modify `skills/osm-day-route-day-plan/tests/test_bio_hazards.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-day-plan/tests/test_bio_hazards.py
+++ b/skills/osm-day-route-day-plan/tests/test_bio_hazards.py
@@ -169,3 +169,15 @@
 def test_group_title_and_dependencies():
     assert BioHazardsPlugin.title_key == "hz_bio"
     assert BioHazardsPlugin.depends_on == ("weather", "light", "osm_features")
+
+
+MARCH = datetime.date(2026, 3, 20)
+
+
+def test_no_tick_line_on_a_freezing_day_even_in_a_tick_month(make_route, fixed_now):
+    freezing = run(make_route, fixed_now, rows(temp=-3.0), mean=-3.0, date=MARCH)
+    assert freezing.omit is True and freezing.markdown == ""
+    mild = run(make_route, fixed_now, rows(temp=8.0), mean=8.0, date=MARCH, folder="mild")
+    assert "Ticks: **high**" in mild.markdown
+    chilly = run(make_route, fixed_now, rows(temp=2.0), mean=2.0, date=MARCH, folder="chilly")
+    assert "Ticks: **low**" in chilly.markdown
```

Modify `skills/osm-day-route-day-plan/tests/test_gwis.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-day-plan/tests/test_gwis.py
+++ b/skills/osm-day-route-day-plan/tests/test_gwis.py
@@ -145,3 +145,13 @@
     ctx = _ctx(make_route, fixed_now, Text(HttpError("504")))
     with pytest.raises(HttpError):
         hotspots_near(ctx, [(43.2, -2.8)], datetime.date(2026, 9, 27), datetime.date(2026, 9, 29))
+
+
+def test_an_empty_fwi_answer_is_remembered_for_a_day_only_even_for_a_past_date(make_route, fixed_now):
+    text = Text("")
+    ctx = _ctx(make_route, fixed_now, text, date=datetime.date(2026, 6, 10))          # a past date: normally cached for good
+    assert fwi_at(ctx, 56.84, 60.6, ctx.date) is None and fwi_at(ctx, 56.84, 60.6, ctx.date) is None
+    assert len(text.calls) == 1
+    ctx.cache._data["gwis_fwi|56.84|60.60|2026-06-10"]["t"] = fixed_now.timestamp() - 2 * 24 * 3600
+    assert fwi_at(ctx, 56.84, 60.6, ctx.date) is None
+    assert len(text.calls) == 2
```

- [ ] **Step 2: Run them and see them fail** — `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_fire.py tests/test_mountain.py tests/test_bio_hazards.py tests/test_gwis.py -q` (import errors or assertion failures: the code does not exist yet).

- [ ] **Step 3: Write the implementation**

Modify `skills/osm-day-route-day-plan/scripts/day_plan/plugins/fire.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-day-plan/scripts/day_plan/plugins/fire.py
+++ b/skills/osm-day-route-day-plan/scripts/day_plan/plugins/fire.py
@@ -118,6 +118,8 @@
                         elevated = True
                         warnings.append(PlanWarning("caution" if cls == 4 else "danger", tr(
                             "fire_warn_kpo", lang, roman=ROMAN[cls - 1], name=name)))
+                else:
+                    lines.append("- " + tr("fire_kpo_beyond", lang))
 
         # 3. active fires near the route (only meaningful around today)
         hotspots = []
```

Modify `skills/osm-day-route-day-plan/scripts/day_plan/plugins/mountain.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-day-plan/scripts/day_plan/plugins/mountain.py
+++ b/skills/osm-day-route-day-plan/scripts/day_plan/plugins/mountain.py
@@ -128,7 +128,7 @@
             if estimate <= 0:
                 warnings.append(PlanWarning("caution", tr("mt_warn_top_cold", lang, temp=f"{estimate:.0f}")))
         cape = max(_values(rows, "cape"), default=0.0)
-        forecast_thunder = any(r.get("code") in _THUNDER_CODES for r in rows)
+        forecast_thunder = weather.get("source") != "climate" and any(r.get("code") in _THUNDER_CODES for r in rows)
         if forecast_thunder:
             lines.append("- " + tr("mt_thunder_forecast", lang))
         if cape >= CAPE_THUNDER or forecast_thunder:
```

Modify `skills/osm-day-route-day-plan/scripts/day_plan/plugins/bio_hazards.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-day-plan/scripts/day_plan/plugins/bio_hazards.py
+++ b/skills/osm-day-route-day-plan/scripts/day_plan/plugins/bio_hazards.py
@@ -86,7 +86,7 @@
 
         # ticks
         mean = weather.get("daily_mean_temp")
-        if mean is not None and in_season(month, TICK_MONTHS, lat):
+        if mean is not None and mean >= 0.0 and in_season(month, TICK_MONTHS, lat):      # no tick line on a freezing day
             band = tick_band(mean)
             lines.append("- " + tr("bio_tick", lang, band=tr("bio_band", lang)[_BANDS[band]], temp=f"{mean:.0f}"))
             if band >= 1:
```

Modify `skills/osm-day-route-day-plan/scripts/day_plan/gwis.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-day-plan/scripts/day_plan/gwis.py
+++ b/skills/osm-day-route-day-plan/scripts/day_plan/gwis.py
@@ -47,6 +47,9 @@
             f"{lon + half_lon:.4f}&width=101&height=101&i=50&j=50&info_format=text/html&time={time}{extra}")
 
 
+EMPTY_FWI_TTL_S = 24 * 3600
+
+
 def fwi_url(lat: float, lon: float, date: datetime.date) -> str:
     return _url(FWI_LAYER, lat, lon, date.isoformat())
 
@@ -71,8 +74,8 @@
     key = f"gwis_fwi|{lat:.2f}|{lon:.2f}|{date.isoformat()}"
     forecast = date >= ctx.today
     cached = ctx.cache.get_entry(key, FWI_FORECAST_TTL_S if forecast else None)
-    if cached is not None:
-        return cached[0] or None
+    if cached is not None and (cached[0] or ctx.now.timestamp() - cached[1] <= EMPTY_FWI_TTL_S):
+        return cached[0] or None      # an empty answer is remembered for a day only, even for a past date
     values = parse_fwi(ctx.http_text(fwi_url(lat, lon, date)))
     ctx.cache.put(key, values or {})
     return values
```

- [ ] **Step 4: Run the whole suite** — `cd skills/osm-day-route-day-plan && python3 -m pytest tests -q` (all green), and for the show skill `cd skills/osm-day-route-show && python3 -m pytest tests -q`.

- [ ] **Step 5: Commit**

```bash
git add skills README.md
git commit -m "Part 3a follow-ups: climatology thunder, freezing-day ticks, empty GWIS cache, Nesterov horizon line

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

### Task 3: The radiation registry

`data/radiation_zones.json` holds thirteen zones, each with geometry, a bilingual name, contamination, status and event, an `approximate` flag with a bilingual note where the shape is not a published outline, and cited sources (each checked by reading the source while researching; see `data/README.md`, which also lists what was researched and left out and why). Geometry is taken from OpenStreetMap through Nominatim and simplified, or built from published figures; nothing comes from memory. `radiation.py` loads and validates the registry and finds the zones a route (by its segments, together with its access and interest points) is inside or within the margin of. Registry validation and known inside/outside places are pinned by tests.

**Files:**
- Create: `skills/osm-day-route-day-plan/tests/test_radiation_registry.py`
- Create: `skills/osm-day-route-day-plan/scripts/day_plan/radiation.py`
- Create: `skills/osm-day-route-day-plan/data/radiation_zones.json`
- Create: `skills/osm-day-route-day-plan/data/README.md`

- [ ] **Step 1: Add the tests** (65 tests in the file(s) below)

Create `skills/osm-day-route-day-plan/tests/test_radiation_registry.py`:

```python
import copy

import pytest

from day_plan.radiation import (
    find_hits, in_scope, load_registry, validate_registry, validate_zone, zone_bbox,
)

REGISTRY = load_registry()
ZONES = {z["id"]: z for z in REGISTRY["zones"]}

# where each zone must lie (min_lon, min_lat, max_lon, max_lat): catches swapped lon/lat and stray vertices
EXPECTED_BBOX = {
    "ural-eurt-core": (60.6, 55.6, 61.2, 56.1),
    "ural-eurt-trace": (60.0, 55.3, 64.5, 58.4),
    "ural-techa-river": (60.6, 55.3, 63.4, 56.5),
    "ural-mayak-site": (60.7, 55.6, 61.1, 55.9),
    "ural-karachay": (60.6, 55.5, 61.0, 55.8),
    "ua-chernobyl-exclusion-zone": (29.0, 50.9, 30.8, 51.7),
    "by-polesie-reserve": (29.0, 51.0, 30.8, 52.1),
    "ru-bryansk-contaminated-districts": (31.0, 51.9, 32.8, 53.4),
    "kz-semipalatinsk-test-site": (76.8, 49.0, 79.4, 51.2),
    "ru-central-chernobyl-districts": (33.5, 52.9, 38.0, 54.4),
    "de-bavaria-wild-food-areas": (10.9, 47.3, 14.0, 49.4),
    "ru-yenisei-mcc-floodplain": (93.0, 56.0, 94.0, 57.2),
    "no-wild-mushroom-municipalities": (8.6, 61.0, 14.7, 65.95),
}


def test_the_shipped_registry_is_valid():
    assert validate_registry(REGISTRY) == []


def test_every_zone_has_at_least_one_source_and_a_primary_one_for_the_strong_claims():
    for zone in REGISTRY["zones"]:
        assert zone["sources"], zone["id"]
        assert all(s["url"].startswith(("https://", "http://government.ru/")) for s in zone["sources"]), zone["id"]
    assert all(any(s["kind"] == "primary" for s in z["sources"]) for z in REGISTRY["zones"])


def test_the_registry_covers_the_researched_areas_and_nothing_is_invented():
    assert set(ZONES) == set(EXPECTED_BBOX)


@pytest.mark.parametrize("zone_id", sorted(EXPECTED_BBOX))
def test_each_zone_lies_where_it_should(zone_id):
    min_lon, min_lat, max_lon, max_lat = zone_bbox(ZONES[zone_id])
    e_min_lon, e_min_lat, e_max_lon, e_max_lat = EXPECTED_BBOX[zone_id]
    assert e_min_lon <= min_lon and max_lon <= e_max_lon and e_min_lat <= min_lat and max_lat <= e_max_lat


def test_approximate_zones_say_how_their_shape_was_made():
    approximate = [z for z in REGISTRY["zones"] if z["approximate"]]
    assert {z["id"] for z in approximate} == {
        "ural-eurt-trace", "ural-techa-river", "ural-mayak-site", "ural-karachay", "ru-bryansk-contaminated-districts",
        "ru-central-chernobyl-districts", "de-bavaria-wild-food-areas", "ru-yenisei-mcc-floodplain",
        "no-wild-mushroom-municipalities"}
    assert all(len(z["geometry_note"]["en"]) > 40 and len(z["geometry_note"]["ru"]) > 40 for z in approximate)


def test_severity_and_advice_are_consistent():
    for zone in REGISTRY["zones"]:
        assert zone["severity"] in ("danger", "caution", "info") and zone["advice"] in ("full", "mushrooms")
        if zone["severity"] == "info":
            assert zone["advice"] == "mushrooms"
        if zone["severity"] == "danger":
            assert zone["advice"] == "full"


def test_every_zone_has_a_short_event_and_bilingual_texts():
    for zone in REGISTRY["zones"]:
        for key in ("name", "contamination", "status", "event"):
            assert zone[key]["en"] and zone[key]["ru"], (zone["id"], key)
        assert "Outline from OpenStreetMap" not in zone["event"]["en"]


KNOWN_INSIDE = {
    "Techa upper reach": ((60.7448, 55.7639), "ural-techa-river"),
    "Chernobyl NPP": ((30.099, 51.389), "ua-chernobyl-exclusion-zone"),
    "Polesie reserve": ((30.03, 51.55), "by-polesie-reserve"),
    "Novozybkov": ((31.93, 52.54), "ru-bryansk-contaminated-districts"),
    "Kamensk-Uralsky": ((61.93, 56.41), "ural-eurt-trace"),
    "Bogdanovich": ((62.05, 56.78), "ural-eurt-trace"),
    "Degelen": ((78.106, 49.805), "kz-semipalatinsk-test-site"),
    "Shchekino": ((37.52, 54.0), "ru-central-chernobyl-districts"),
    "Zhizdra": ((34.73, 53.75), "ru-central-chernobyl-districts"),
    "Belev": ((36.14, 53.81), "ru-central-chernobyl-districts"),
    "Bolkhov": ((36.0, 53.44), "ru-central-chernobyl-districts"),
    "Grafenau (Bavarian Forest)": ((13.40, 48.86), "de-bavaria-wild-food-areas"),
    "Berchtesgaden": ((13.0, 47.63), "de-bavaria-wild-food-areas"),
    "Mittenwald": ((11.26, 47.44), "de-bavaria-wild-food-areas"),
    "Yenisei at the combine": ((93.5264, 56.3085), "ru-yenisei-mcc-floodplain"),
    "Beitostølen (Øystre Slidre)": ((8.91, 61.25), "no-wild-mushroom-municipalities"),
    "Lierne": ((13.6, 64.46), "no-wild-mushroom-municipalities"),
    "Hattfjelldal": ((13.99, 65.6), "no-wild-mushroom-municipalities"),
    "Karachay": ((60.7997, 55.6783), "ural-karachay"),
    "Mayak": ((60.9, 55.7333), "ural-mayak-site"),
}
KNOWN_CLEAN = {"Kyiv": (30.52, 50.45), "Moscow": (37.62, 55.75), "Madrid": (-3.70, 40.42),
               "Ekaterinburg": (60.60, 56.84), "Chelyabinsk": (61.40, 55.16), "Minsk": (27.56, 53.90),
               "Argayash (south of Mayak)": (60.87, 55.49), "Shadrinsk (east of the trace)": (63.63, 56.09),
               "Kyshtym (upwind, west of Mayak)": (60.56, 55.71), "Kaluga city": (36.26, 54.51),
               "Oslo": (10.75, 59.91), "Trondheim": (10.40, 63.43), "Stockholm": (18.07, 59.33), "Munich": (11.58, 48.14), "Hamburg": (9.99, 53.55), "Krasnoyarsk city": (92.87, 56.01)}


@pytest.mark.parametrize("name", sorted(KNOWN_INSIDE))
def test_known_places_inside_the_zones_are_hits(name):
    (lon, lat), zone_id = KNOWN_INSIDE[name]
    hits = {h.zone["id"]: h for h in find_hits(REGISTRY, [(lon, lat), (lon + 0.0001, lat)], [])}
    assert zone_id in hits and hits[zone_id].inside


@pytest.mark.parametrize("name", sorted(KNOWN_CLEAN))
def test_known_clean_places_miss_every_zone(name):
    lon, lat = KNOWN_CLEAN[name]
    assert find_hits(REGISTRY, [(lon, lat), (lon + 0.0001, lat)], []) == []


def test_a_segment_crossing_a_zone_with_both_ends_outside_is_a_hit():
    hits = find_hits(REGISTRY, [(29.0, 51.3), (31.0, 51.3)], [])
    assert hits[0].zone["id"] == "ua-chernobyl-exclusion-zone" and hits[0].inside


def test_a_point_off_the_track_counts_and_a_near_miss_reports_the_distance():
    hits = find_hits(REGISTRY, [(40.0, 55.0), (40.1, 55.0)], [(30.099, 51.389)])
    assert [h.zone["id"] for h in hits] == ["ua-chernobyl-exclusion-zone"] and hits[0].inside
    south_lon, south_lat = 30.3851, 51.0834                                       # the zone's southernmost vertex
    assert find_hits(REGISTRY, [(south_lon, south_lat - 0.05), (south_lon + 0.001, south_lat - 0.05)], []) == []
    near = find_hits(REGISTRY, [(south_lon, south_lat - 0.02), (south_lon + 0.001, south_lat - 0.02)], [])
    assert near and not near[0].inside and near[0].distance_km == pytest.approx(2.22, abs=0.05)


def test_the_techa_buffer_follows_the_river_not_its_bounding_box():
    techa = ZONES["ural-techa-river"]["geometry"]["lines"][0][20]
    assert [h.zone["id"] for h in find_hits(REGISTRY, [tuple(techa), (techa[0] + 0.0001, techa[1])], [])
            if h.zone["id"] == "ural-techa-river"]
    lon, lat = techa
    far = find_hits(REGISTRY, [(lon, lat + 0.5), (lon + 0.0001, lat + 0.5)], [], margin_km=3.0)
    assert "ural-techa-river" not in [h.zone["id"] for h in far]


def _hit(pts, zone_id):
    return [h for h in find_hits(REGISTRY, pts, []) if h.zone["id"] == zone_id]


def test_a_long_segment_crossing_the_mayak_circle_with_both_ends_far_outside_is_a_hit():
    west, east = (60.6, 55.7333), (61.2, 55.7333)                # about 19 km either side of the 6 km circle
    assert _hit([west, west], "ural-mayak-site") == [] and _hit([east, east], "ural-mayak-site") == []
    hits = _hit([west, east], "ural-mayak-site")
    assert len(hits) == 1 and hits[0].inside and hits[0].distance_km == 0


def test_a_long_segment_crossing_the_techa_line_between_two_far_ends_is_a_hit():
    lon, lat = ZONES["ural-techa-river"]["geometry"]["lines"][0][20]      # a river vertex
    south, north = (lon, lat - 0.1), (lon, lat + 0.1)                     # about 11 km either side, beyond buffer and margin
    assert _hit([south, south], "ural-techa-river") == [] and _hit([north, north], "ural-techa-river") == []
    hits = _hit([south, north], "ural-techa-river")
    assert len(hits) == 1 and hits[0].inside and hits[0].distance_km == 0


def test_the_corridor_of_the_trace_does_not_reach_upwind_of_the_release_point():
    trace = [h for h in find_hits(REGISTRY, [(60.62, 55.70), (60.6201, 55.70)], []) if h.zone["id"] == "ural-eurt-trace"]
    assert trace == []                                    # Kyshtym-side land west of Mayak: the plume went north-east
    downwind = find_hits(REGISTRY, [(61.2, 56.0), (61.2001, 56.0)], [])
    assert "ural-eurt-trace" in [h.zone["id"] for h in downwind]


def test_the_trace_spans_about_three_hundred_kilometres_from_mayak():
    min_lon, min_lat, max_lon, max_lat = zone_bbox(ZONES["ural-eurt-trace"])
    far = (max_lon, max_lat)
    assert 250.0 <= km_from_mayak(far) <= 330.0


def km_from_mayak(point):
    import math
    lon, lat = point
    return math.hypot((lon - 60.9) * 111.195 * math.cos(math.radians(56.5)), (lat - 55.7333) * 111.195)


def test_in_scope():
    for lat, lon in ((56.84, 60.6), (40.4, -3.7), (64.0, 100.0), (43.1, 131.9), (62.0, 129.7), (41.0, 29.0)):
        assert in_scope(REGISTRY, lat, lon), (lat, lon)
    for lat, lon in ((-33.9, 151.2), (40.7, -74.0), (39.9, 116.4), (47.9, 106.9), (35.7, 139.7), (37.6, 127.0),
                     (30.0, 31.2)):
        assert not in_scope(REGISTRY, lat, lon), (lat, lon)


def test_validation_catches_broken_entries():
    zone = copy.deepcopy(ZONES["ua-chernobyl-exclusion-zone"])
    zone["geometry"]["rings"][0][-1] = [0.0, 0.0]
    assert any("closed" in p for p in validate_zone(zone))
    bad_scope = copy.deepcopy(REGISTRY)
    bad_scope["scope"] = {"lon": [0, 1], "lat": [0, 1]}
    assert any("scope needs boxes" in p for p in validate_registry(bad_scope))
    zone = copy.deepcopy(ZONES["ua-chernobyl-exclusion-zone"])
    zone["sources"] = []
    assert any("source" in p for p in validate_zone(zone))
    zone = copy.deepcopy(ZONES["ua-chernobyl-exclusion-zone"])
    zone["sources"][0]["url"] = "ftp://example.org/x"
    zone["severity"] = "fatal"
    zone["name"]["ru"] = ""
    problems = validate_zone(zone)
    assert any("bad source" in p for p in problems) and any("severity" in p for p in problems) \
        and any("name needs" in p for p in problems)
    no_advice = copy.deepcopy(ZONES["ural-karachay"])
    del no_advice["advice"]
    assert any("advice must be" in p for p in validate_zone(no_advice))
    circle = copy.deepcopy(ZONES["ural-karachay"])
    circle["geometry"]["center"] = [55.6783, 900.0]
    circle["approximate"] = True
    circle.pop("geometry_note")
    problems = validate_zone(circle)
    assert any("circle" in p for p in problems) and any("geometry_note" in p for p in problems)
    note = copy.deepcopy(ZONES["ural-karachay"])
    note["geometry_note"] = "English only"
    del note["event"]
    problems = validate_zone(note)
    assert any("geometry_note needs" in p for p in problems) and any("event needs" in p for p in problems)
    line = copy.deepcopy(ZONES["ural-techa-river"])
    line["geometry"]["half_width_km"] = 0
    assert any("half_width" in p for p in validate_zone(line))
    broken = copy.deepcopy(REGISTRY)
    broken["zones"].append(copy.deepcopy(broken["zones"][0]))
    assert any("duplicate" in p for p in validate_registry(broken))


def test_the_norwegian_zone_names_the_right_russian_mushroom():
    ru = ZONES["no-wild-mushroom-municipalities"]["status"]["ru"]
    assert "колпаке кольчатом" in ru and "кольцевик" not in ru
```

- [ ] **Step 2: Run them and see them fail** — `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_radiation_registry.py -q` (import errors or assertion failures: the code does not exist yet).

- [ ] **Step 3: Write the implementation**

Create `skills/osm-day-route-day-plan/scripts/day_plan/radiation.py`:

```python
"""The radiation registry: a hand-curated list of contaminated or closed zones
in `data/radiation_zones.json`, each with geometry, what happened, the
current status and at least one cited source, and the search of a route
against it.

Geometry kinds: `polygons` (a list of outer rings, [lon, lat]), `circle`
(centre and radius) and `buffered_polyline` (one or more lines and a
half-width). Every zone with a published outline says so; where only a
centre and an extent, or a set of named settlements, exist the entry is
`approximate` and says how the shape was made (`geometry_note`).

A route is tested by its segments (a straight segment can cross a small zone
with both ends outside it), together with its access and interest points,
which may lie off the track (a spring, a viewpoint). Nothing here touches the
network; an empty result is "no entry", never "safe"."""
import json
import math
from dataclasses import dataclass
from pathlib import Path

from .geo import (
    KM_PER_DEG, bbox_of, bboxes_close, clip_segments, point_segment_distance, polygon_distance_segments, project,
    segments_distance, to_segments,
)

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "data" / "radiation_zones.json"
SEVERITIES = ("danger", "caution", "info")
ADVICE_KINDS = ("full", "mushrooms")
SOURCE_KINDS = ("primary", "secondary")
GEOMETRY_KINDS = ("polygons", "circle", "buffered_polyline")


def load_registry(path=REGISTRY_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _valid_url(url) -> bool:
    return isinstance(url, str) and url.startswith(("http://", "https://")) and not any(c.isspace() for c in url) \
        and "." in url.split("//", 1)[1].split("/", 1)[0]


def _lonlat(point) -> bool:
    return (isinstance(point, list) and len(point) == 2 and all(isinstance(v, (int, float)) for v in point)
            and -180.0 <= point[0] <= 180.0 and -90.0 <= point[1] <= 90.0)


def _bilingual(value) -> bool:
    return isinstance(value, dict) and all(isinstance(value.get(lang), str) and value[lang].strip()
                                           for lang in ("en", "ru"))


def validate_zone(zone: dict) -> list:
    """Human-readable problems of one registry entry ([] when it is sound)."""
    problems = []
    zid = zone.get("id", "?")
    for key in ("name", "contamination", "status", "event"):
        value = zone.get(key)
        if not _bilingual(value):
            problems.append(f"{zid}: {key} needs non-empty en and ru text")
    if "geometry_note" in zone and not _bilingual(zone["geometry_note"]):
        problems.append(f"{zid}: geometry_note needs non-empty en and ru text")
    if zone.get("severity") not in SEVERITIES:
        problems.append(f"{zid}: severity must be one of {SEVERITIES}")
    if zone.get("advice") not in ADVICE_KINDS:
        problems.append(f"{zid}: advice must be one of {ADVICE_KINDS}")
    if not isinstance(zone.get("approximate"), bool):
        problems.append(f"{zid}: approximate must be true or false")
    elif zone["approximate"] and not zone.get("geometry_note"):
        problems.append(f"{zid}: an approximate zone needs a geometry_note")
    sources = zone.get("sources")
    if not (isinstance(sources, list) and sources):
        problems.append(f"{zid}: at least one source is required")
    else:
        for source in sources:
            if not (isinstance(source, dict) and _valid_url(source.get("url")) and source.get("title")
                    and source.get("kind") in SOURCE_KINDS):
                problems.append(f"{zid}: bad source {source!r}")
    geometry = zone.get("geometry") or {}
    kind = geometry.get("type")
    if kind == "polygons":
        rings = geometry.get("rings")
        if not (isinstance(rings, list) and rings):
            problems.append(f"{zid}: polygons need rings")
        else:
            for ring in rings:
                if not (isinstance(ring, list) and len(ring) >= 4 and all(_lonlat(p) for p in ring)):
                    problems.append(f"{zid}: a ring needs at least 4 [lon, lat] points")
                elif ring[0] != ring[-1]:
                    problems.append(f"{zid}: a ring must be closed")
    elif kind == "circle":
        if not (_lonlat(geometry.get("center")) and isinstance(geometry.get("radius_km"), (int, float))
                and 0 < geometry["radius_km"] <= 200):
            problems.append(f"{zid}: a circle needs center [lon, lat] and 0 < radius_km <= 200")
    elif kind == "buffered_polyline":
        lines = geometry.get("lines")
        if not (isinstance(lines, list) and lines and all(isinstance(line, list) and len(line) >= 2
                                                          and all(_lonlat(p) for p in line) for line in lines)):
            problems.append(f"{zid}: a buffered polyline needs lines of at least 2 [lon, lat] points")
        if not (isinstance(geometry.get("half_width_km"), (int, float)) and 0 < geometry["half_width_km"] <= 100):
            problems.append(f"{zid}: half_width_km must be in (0, 100]")
    else:
        problems.append(f"{zid}: geometry type must be one of {GEOMETRY_KINDS}")
    return problems


def validate_registry(data: dict) -> list:
    problems = []
    scope = data.get("scope") or {}
    if not (isinstance(data.get("margin_km"), (int, float)) and data["margin_km"] > 0):
        problems.append("margin_km must be positive")
    boxes = scope.get("boxes")
    if not (isinstance(boxes, list) and boxes and all(
            isinstance(b, list) and len(b) == 4 and all(isinstance(v, (int, float)) for v in b)
            and b[0] < b[2] and b[1] < b[3] for b in boxes)):
        problems.append("scope needs boxes [min_lon, min_lat, max_lon, max_lat]")
    zones = data.get("zones")
    if not (isinstance(zones, list) and zones):
        return problems + ["no zones"]
    seen = set()
    for zone in zones:
        if zone.get("id") in seen:
            problems.append(f"duplicate id {zone.get('id')}")
        seen.add(zone.get("id"))
        problems += validate_zone(zone)
    return problems


def zone_bbox(zone: dict) -> tuple:
    """(min_lon, min_lat, max_lon, max_lat), including a circle's radius or a buffer's half-width."""
    g = zone["geometry"]
    if g["type"] == "polygons":
        return bbox_of([tuple(p) for ring in g["rings"] for p in ring])
    if g["type"] == "circle":
        (lon, lat), r = g["center"], g["radius_km"]
        dlat = r / KM_PER_DEG
        dlon = r / (KM_PER_DEG * max(0.05, math.cos(math.radians(lat))))
        return lon - dlon, lat - dlat, lon + dlon, lat + dlat
    min_lon, min_lat, max_lon, max_lat = bbox_of([tuple(p) for line in g["lines"] for p in line])
    w = g["half_width_km"]
    dlat = w / KM_PER_DEG
    dlon = w / (KM_PER_DEG * max(0.05, math.cos(math.radians(max(abs(min_lat), abs(max_lat))))))
    return min_lon - dlon, min_lat - dlat, max_lon + dlon, max_lat + dlat


@dataclass
class ZoneHit:
    zone: dict
    distance_km: float   # 0.0 = the route or one of its points is inside or on the zone

    @property
    def inside(self) -> bool:
        return self.distance_km <= 0.0


def _route_segments(route: list, points: list, lat0: float, lon0: float) -> list:
    """Projected segments of the route plus one zero-length segment per point of interest / access point."""
    xy = [project(lon, lat, lat0, lon0) for lon, lat in route]
    segments = to_segments(xy) if xy else []
    segments += [(p, p) for p in (project(lon, lat, lat0, lon0) for lon, lat in points)]
    return segments


def zone_distance_km(zone: dict, route: list, points: list, cap_km: float) -> float | None:
    """Shortest distance in km from the route (or one of its points) to the zone, 0.0 when inside, or None when
    it is more than cap_km away. `route` and `points` are [(lon, lat), ...]."""
    min_lon, min_lat, max_lon, max_lat = zone_bbox(zone)
    lat0, lon0 = (min_lat + max_lat) / 2.0, (min_lon + max_lon) / 2.0
    segments = _route_segments(route, points, lat0, lon0)
    x0, y0 = project(min_lon, min_lat, lat0, lon0)
    x1, y1 = project(max_lon, max_lat, lat0, lon0)
    segments = clip_segments(segments, (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)), cap_km)
    if not segments:
        return None
    g = zone["geometry"]
    if g["type"] == "polygons":
        best = math.inf
        for ring in g["rings"]:
            xy = [project(lon, lat, lat0, lon0) for lon, lat in ring]
            best = min(best, polygon_distance_segments(segments, xy, cap_km))
            if best == 0.0:
                break
    elif g["type"] == "circle":
        cx, cy = project(g["center"][0], g["center"][1], lat0, lon0)
        best = max(0.0, min(point_segment_distance(cx, cy, *a, *b) for a, b in segments) - g["radius_km"])
    else:
        lines = [[project(lon, lat, lat0, lon0) for lon, lat in line] for line in g["lines"]]
        half = g["half_width_km"]
        best = math.inf
        for line in lines:
            best = min(best, segments_distance(segments, to_segments(line), cap_km + half))
        best = max(0.0, best - half)
    return best if best <= cap_km else None


def find_hits(registry: dict, route: list, points: list, margin_km: float | None = None) -> list:
    """[ZoneHit] for every zone the route or its points are inside or within margin_km of, nearest first."""
    margin = margin_km if margin_km is not None else registry["margin_km"]
    if not route:
        return []
    route_box = bbox_of(route + points)
    hits = []
    for zone in registry["zones"]:
        if not bboxes_close(route_box, zone_bbox(zone), margin):
            continue
        distance = zone_distance_km(zone, route, points, margin)
        if distance is not None:
            hits.append(ZoneHit(zone, distance))
    return sorted(hits, key=lambda h: (h.distance_km, h.zone["id"]))


def in_scope(registry: dict, lat: float, lon: float) -> bool:
    """True when the place lies in one of the boxes the registry is meant to cover (Europe with the Urals, Siberia and the
    Far East north of 49 N, Primorye); elsewhere a radiation part would say nothing."""
    return any(b[0] <= lon <= b[2] and b[1] <= lat <= b[3] for b in registry["scope"]["boxes"])
```

Create `skills/osm-day-route-day-plan/data/radiation_zones.json`:

```json
{
 "version": 1,
 "scope": {
  "boxes": [
   [
    -25.0,
    36.0,
    70.0,
    82.0
   ],
   [
    70.0,
    49.0,
    180.0,
    82.0
   ],
   [
    130.0,
    42.0,
    135.0,
    49.0
   ]
  ]
 },
 "margin_km": 3.0,
 "zones": [
  {
   "id": "ural-eurt-core",
   "severity": "danger",
   "approximate": false,
   "name": {
    "en": "East Ural State Nature Reserve (core of the East Urals Radioactive Trace)",
    "ru": "Восточно-Уральский государственный заповедник (ядро Восточно-Уральского радиоактивного следа)"
   },
   "contamination": {
    "en": "strontium-90 after the 1957 Kyshtym accident at Mayak",
    "ru": "стронций-90 после аварии на «Маяке» в 1957 году"
   },
   "status": {
    "en": "State radiation and strict nature reserve, not open to the public; about 180 km² near the explosion site are still officially off-limits (NRPA, 2007).",
    "ru": "Государственный радиационный и строгий заповедник, закрыт для посещения; около 180 км² у места взрыва официально остаются закрытыми (NRPA, 2007 год)."
   },
   "geometry": {
    "type": "polygons",
    "rings": [
     [[60.808, 55.7665], [60.8096, 55.7591], [60.8151, 55.7545], [60.8481, 55.754], [60.9006, 55.7355], [60.9078, 55.7355], [60.9164, 55.7379], [60.9468, 55.756], [60.9407, 55.7662], [60.941, 55.7741], [60.9472, 55.783], [60.9513, 55.7855], [60.9533, 55.7912], [60.9657, 55.8021], [60.9623, 55.809], [60.9653, 55.8192], [60.9608, 55.822], [60.9624, 55.8244], [60.9685, 55.8275], [61.0057, 55.8348], [61.0017, 55.8391], [61.0012, 55.8522], [61.0124, 55.8561], [61.0092, 55.8601], [61.0486, 55.8996], [61.0661, 55.8973], [61.0674, 55.8995], [61.0735, 55.9161], [61.0711, 55.9276], [61.066, 55.935], [61.065, 55.9448], [61.0596, 55.9589], [61.0402, 55.9739], [61.0369, 55.9646], [61.0268, 55.9593], [61.0154, 55.9493], [60.9943, 55.9463], [60.9921, 55.9361], [60.994, 55.9337], [60.9756, 55.9023], [60.9665, 55.9019], [60.946, 55.9063], [60.9428, 55.8917], [60.9361, 55.889], [60.9352, 55.8854], [60.9273, 55.8854], [60.9246, 55.8833], [60.9088, 55.8863], [60.9021, 55.8779], [60.9052, 55.8669], [60.9013, 55.8623], [60.8948, 55.8602], [60.8834, 55.8479], [60.8733, 55.8479], [60.8483, 55.821], [60.8351, 55.824], [60.8221, 55.8123], [60.8358, 55.807], [60.8269, 55.7978], [60.826, 55.7914], [60.8119, 55.7813], [60.808, 55.7665]]
    ]
   },
   "geometry_note": {
    "en": "Outline from OpenStreetMap (© OpenStreetMap contributors, ODbL), way 256825533",
    "ru": "Контур из OpenStreetMap (© участники OpenStreetMap, ODbL), way 256825533"
   },
   "event": {
    "en": "Kyshtym accident, 1957",
    "ru": "авария 1957 года на «Маяке»"
   },
   "sources": [
    {
     "url": "https://dsa.no/publikasjoner/straleverninfo-8-2007-the-kyshtym-accident-29th-september-1957/StralevernInfo_8_2007.pdf",
     "title": "NRPA Bulletin 8-07: The Kyshtym accident, 29th September 1957",
     "kind": "primary"
    },
    {
     "url": "https://en.wikipedia.org/wiki/East_Ural_Nature_Reserve",
     "title": "East Ural Nature Reserve (Wikipedia)",
     "kind": "secondary"
    }
   ],
   "advice": "full"
  },
  {
   "id": "ural-eurt-trace",
   "severity": "caution",
   "approximate": true,
   "name": {
    "en": "East Urals Radioactive Trace (fallout of 1957, approximate outline)",
    "ru": "Восточно-Уральский радиоактивный след (выпадения 1957 года, приблизительный контур)"
   },
   "contamination": {
    "en": "strontium-90; about 300 km long and 30–50 km wide, up to 15 000–20 000 km² above 3.7 kBq/m²",
    "ru": "стронций-90; около 300 км в длину и 30–50 км в ширину, до 15 000–20 000 км² с плотностью более 3,7 кБк/м²"
   },
   "status": {
    "en": "23 rural communities were evacuated after the accident; after 1961 most of the land was reclaimed for farming.",
    "ru": "После аварии эвакуированы 23 сельских населённых пункта; после 1961 года большая часть земли возвращена в сельскохозяйственное использование."
   },
   "geometry": {
    "type": "buffered_polyline",
    "lines": [
     [[61.1341, 55.9157], [61.5061, 56.2038], [61.9171, 56.4035], [62.3812, 56.81], [63.4735, 57.7498]]
    ],
    "half_width_km": 25.0
   },
   "geometry_note": {
    "en": "Centre line through Bagaryak, Kamensk-Uralsky and the area between Bogdanovich and Kamyshlov (the settlements named on the source's map), starting 25 km downwind of Mayak and ending so that the outline spans 300 km from Mayak; half-width 25 km is the upper bound of the 30–50 km width given by the source. An outline, not an isoline.",
    "ru": "Осевая линия через Багаряк, Каменск-Уральский и место между Богдановичем и Камышловом (населённые пункты с карты источника), начинается в 25 км от «Маяка» по ветру и заканчивается так, чтобы контур занимал 300 км от «Маяка»; полуширина 25 км — верхняя граница ширины 30–50 км из источника. Контур, а не изолиния."
   },
   "event": {
    "en": "Kyshtym accident, 1957",
    "ru": "авария 1957 года на «Маяке»"
   },
   "sources": [
    {
     "url": "https://dsa.no/publikasjoner/straleverninfo-8-2007-the-kyshtym-accident-29th-september-1957/StralevernInfo_8_2007.pdf",
     "title": "NRPA Bulletin 8-07: The Kyshtym accident, 29th September 1957",
     "kind": "primary"
    }
   ],
   "advice": "full"
  },
  {
   "id": "ural-techa-river",
   "severity": "caution",
   "approximate": true,
   "name": {
    "en": "Techa river and its floodplain (Mayak discharges 1949–1956)",
    "ru": "Река Теча и её пойма (сбросы «Маяка» 1949–1956 годов)"
   },
   "contamination": {
    "en": "caesium-137, strontium-90, ruthenium isotopes and others; more than 100 PBq discharged in total",
    "ru": "цезий-137, стронций-90, изотопы рутения и другие; всего сброшено более 100 ПБк"
   },
   "status": {
    "en": "About 240 km² of the floodplain were contaminated in 1949–1957, 80 km² of them above 3.7×10¹⁰ Bq/km²; dams created reservoirs holding high levels of radionuclides.",
    "ru": "В 1949–1957 годах загрязнено около 240 км² поймы, из них 80 км² выше 3,7×10¹⁰ Бк/км²; плотины создали водохранилища с высоким содержанием радионуклидов."
   },
   "geometry": {
    "type": "buffered_polyline",
    "lines": [
     [[61.163, 55.6441], [61.1579, 55.6383], [61.1789, 55.6299], [61.1865, 55.6313], [61.2553, 55.61], [61.2916, 55.6109], [61.3431, 55.6042], [61.3803, 55.615], [61.4102, 55.6034], [61.417, 55.5893], [61.4429, 55.5818], [61.4367, 55.5708], [61.4443, 55.5675], [61.4437, 55.5591], [61.4649, 55.5471], [61.4761, 55.546], [61.4903, 55.5542], [61.5058, 55.5525], [61.5165, 55.5599], [61.5258, 55.5555], [61.5333, 55.5651], [61.5284, 55.5689], [61.5386, 55.572], [61.5439, 55.5813], [61.5711, 55.585], [61.6136, 55.6007], [61.6152, 55.6123], [61.6303, 55.6145]],
     [[61.1922, 55.6287], [61.1995, 55.6268]],
     [[61.1845, 55.6301], [61.192, 55.6285]],
     [[61.2606, 55.6099], [61.263, 55.6104]],
     [[61.3927, 55.6098], [61.3992, 55.6076]],
     [[61.4401, 55.5754], [61.4432, 55.5723], [61.4368, 55.5714]],
     [[61.4781, 55.5465], [61.4809, 55.547]],
     [[61.7967, 55.581], [61.7977, 55.5797]],
     [[61.6257, 55.6142], [61.642, 55.6148], [61.6547, 55.6079], [61.6706, 55.6079], [61.6815, 55.6031], [61.7027, 55.6054], [61.7127, 55.6015], [61.717, 55.6053], [61.74, 55.6063], [61.7494, 55.5953], [61.7745, 55.5938], [61.8059, 55.5755], [61.8498, 55.5664], [61.8863, 55.5684], [61.9008, 55.5597], [61.9181, 55.5642], [61.9405, 55.5564], [62.0003, 55.5717], [62.0239, 55.5704], [62.0286, 55.5756], [62.0407, 55.5727], [62.059, 55.5802], [62.0841, 55.5785], [62.0907, 55.5802], [62.0881, 55.5841], [62.11, 55.5872], [62.1225, 55.6092], [62.117, 55.6192], [62.1275, 55.6285], [62.1218, 55.6342], [62.1356, 55.6409], [62.1416, 55.653], [62.141, 55.6676], [62.128, 55.6787], [62.1338, 55.681], [62.1295, 55.6939], [62.1532, 55.7047], [62.1493, 55.7131], [62.1662, 55.7303], [62.1614, 55.7372], [62.1788, 55.7584], [62.1924, 55.7625], [62.173, 55.7763], [62.1917, 55.7928], [62.201, 55.8121], [62.227, 55.8147], [62.2399, 55.8256], [62.2633, 55.8285], [62.2929, 55.8397], [62.3123, 55.8402], [62.3157, 55.8454], [62.345, 55.8465], [62.3581, 55.855], [62.3624, 55.852], [62.3966, 55.8625], [62.4384, 55.8644], [62.5171, 55.8778], [62.527, 55.8735], [62.5288, 55.877], [62.5331, 55.8735], [62.5448, 55.875], [62.5545, 55.8898], [62.5847, 55.9012], [62.5826, 55.9242], [62.5908, 55.9231], [62.6101, 55.9336], [62.6285, 55.9335], [62.6461, 55.9425], [62.6927, 55.9522], [62.711, 55.967], [62.7058, 55.9713], [62.6963, 55.9701], [62.7005, 55.9795], [62.6949, 55.9817], [62.6992, 56.0011], [62.7121, 56.0045], [62.7036, 56.014], [62.6894, 56.0146], [62.6694, 56.0378], [62.6579, 56.0407], [62.6565, 56.0617], [62.6904, 56.0617], [62.7014, 56.0741], [62.6865, 56.0821], [62.6924, 56.0894], [62.7365, 56.0973], [62.7514, 56.1189], [62.7659, 56.1248], [62.7661, 56.1323], [62.7714, 56.13], [62.7836, 56.138], [62.7815, 56.1438], [62.7647, 56.1469], [62.7664, 56.1582], [62.7867, 56.1739], [62.7875, 56.182], [62.8011, 56.1833], [62.8051, 56.1947], [62.8136, 56.1956], [62.8036, 56.1985], [62.8044, 56.2083], [62.8189, 56.2089], [62.8225, 56.2128], [62.8429, 56.2105], [62.8926, 56.2358], [62.9165, 56.2361], [62.92, 56.2329], [62.9405, 56.2384], [62.9517, 56.237]],
     [[60.7341, 55.7697], [60.7344, 55.766], [60.7383, 55.7648], [60.7485, 55.7641], [60.7471, 55.7624], [60.7483, 55.76], [60.7508, 55.7581], [60.7556, 55.7587]],
     [[61.1284, 55.647], [61.1341, 55.6465], [61.1362, 55.6442], [61.138, 55.6448], [61.1389, 55.6433], [61.1412, 55.6427], [61.1462, 55.6427], [61.1465, 55.6419], [61.1454, 55.6412], [61.1508, 55.6402], [61.1513, 55.6391], [61.154, 55.6386], [61.1537, 55.6378], [61.1557, 55.6378], [61.1554, 55.637], [61.157, 55.6378], [61.1683, 55.6344]],
     [[61.2156, 55.6227], [61.2173, 55.6222], [61.2192, 55.6201], [61.222, 55.619], [61.2251, 55.6191], [61.2255, 55.618], [61.2291, 55.6179], [61.2322, 55.616]]
    ],
    "half_width_km": 1.5
   },
   "geometry_note": {
    "en": "Outline from OpenStreetMap (© OpenStreetMap contributors, ODbL), relation 2124164 (waterway Теча) and ways 1104519187, 125750492, 786464969 upstream of its west end, simplified; a half-width of 1.5 km stands for the floodplain; the Mayak reservoir cascade (Reservoirs 3, 4, 10, 11) is not outlined",
    "ru": "Контур из OpenStreetMap (© участники OpenStreetMap, ODbL), relation 2124164 (водоток Теча) и ways 1104519187, 125750492, 786464969 выше её западного конца, упрощены; полуширина 1,5 км соответствует пойме; каскад водохранилищ «Маяка» (В-3, В-4, В-10, В-11) не оконтурен"
   },
   "event": {
    "en": "Mayak discharges, 1949–1956",
    "ru": "сбросы «Маяка» 1949–1956 годов"
   },
   "sources": [
    {
     "url": "https://dsa.no/publikasjoner/stralevernrapport-3-2008-mayak-health-report/StralevernRapport_3_2008.pdf",
     "title": "NRPA StrålevernRapport 2008:3: Mayak Health Report",
     "kind": "primary"
    }
   ],
   "advice": "full"
  },
  {
   "id": "ural-mayak-site",
   "severity": "danger",
   "approximate": true,
   "name": {
    "en": "Mayak Production Association site",
    "ru": "Площадка ПО «Маяк»"
   },
   "contamination": {
    "en": "the source of the Techa discharges and of the 1957 accident",
    "ru": "источник сбросов в Течу и аварии 1957 года"
   },
   "status": {
    "en": "Industrial nuclear site of about 90 km², not a public area.",
    "ru": "Промышленная ядерная площадка около 90 км², не общедоступная территория."
   },
   "geometry": {
    "type": "circle",
    "center": [60.9, 55.7333],
    "radius_km": 6.0
   },
   "geometry_note": {
    "en": "Centre 55°44′N 60°54′E and area about 90 km² from the source; the radius of 6 km is a rounded-up equivalent circle, the real outline is not published in the source.",
    "ru": "Центр 55°44′ с. ш. 60°54′ в. д. и площадь около 90 км² — из источника; радиус 6 км — округлённый в большую сторону эквивалентный круг, реальный контур в источнике не опубликован."
   },
   "event": {
    "en": "Mayak discharges and the 1957 accident",
    "ru": "сбросы «Маяка» и авария 1957 года"
   },
   "sources": [
    {
     "url": "https://dsa.no/publikasjoner/stralevernrapport-3-2008-mayak-health-report/StralevernRapport_3_2008.pdf",
     "title": "NRPA StrålevernRapport 2008:3: Mayak Health Report",
     "kind": "primary"
    }
   ],
   "advice": "full"
  },
  {
   "id": "ural-karachay",
   "severity": "danger",
   "approximate": true,
   "name": {
    "en": "Lake Karachay",
    "ru": "Озеро Карачай"
   },
   "contamination": {
    "en": "liquid radioactive waste stored in the lake; wind dispersal of dust from the dried bed in 1967",
    "ru": "жидкие радиоактивные отходы, хранившиеся в озере; ветровой вынос пыли с высохшего дна в 1967 году"
   },
   "status": {
    "en": "Part of the Mayak site; the dispersal event of 1967 is one of the three major contamination events at Mayak.",
    "ru": "Часть площадки «Маяка»; вынос 1967 года — одно из трёх крупных событий загрязнения на «Маяке»."
   },
   "geometry": {
    "type": "circle",
    "center": [60.7997, 55.6783],
    "radius_km": 3.0
   },
   "geometry_note": {
    "en": "Centre from Wikipedia (55°40′42″N 60°47′59″E); the 3 km radius is an assumed safety margin, no extent is published in the source.",
    "ru": "Центр по Википедии (55°40′42″ с. ш. 60°47′59″ в. д.); радиус 3 км — принятый запас, протяжённость в источнике не указана."
   },
   "event": {
    "en": "waste storage and the 1967 dust dispersal",
    "ru": "хранение отходов и вынос пыли в 1967 году"
   },
   "sources": [
    {
     "url": "https://dsa.no/publikasjoner/stralevernrapport-3-2008-mayak-health-report/StralevernRapport_3_2008.pdf",
     "title": "NRPA StrålevernRapport 2008:3: Mayak Health Report",
     "kind": "primary"
    },
    {
     "url": "https://en.wikipedia.org/wiki/Lake_Karachay",
     "title": "Lake Karachay (Wikipedia)",
     "kind": "secondary"
    }
   ],
   "advice": "full"
  },
  {
   "id": "ua-chernobyl-exclusion-zone",
   "severity": "danger",
   "approximate": false,
   "name": {
    "en": "Chernobyl exclusion zone (Ukraine)",
    "ru": "Чернобыльская зона отчуждения (Украина)"
   },
   "contamination": {
    "en": "caesium-137, strontium-90 and plutonium after the 1986 accident",
    "ru": "цезий-137, стронций-90 и плутоний после аварии 1986 года"
   },
   "status": {
    "en": "The area the population was evacuated from in 1986, including the 30 km zone around the plant: 76 settlements and 2 122 km² (2007 zoning data).",
    "ru": "Территория, с которой в 1986 году эвакуировано население, включая 30-километровую зону вокруг станции: 76 населённых пунктов и 2 122 км² (данные зонирования 2007 года)."
   },
   "geometry": {
    "type": "polygons",
    "rings": [
     [[29.2675, 51.2648], [29.3053, 51.158], [29.3162, 51.1315], [29.3213, 51.1278], [29.3292, 51.1267], [29.3306, 51.1576], [29.3489, 51.16], [29.4275, 51.1239], [29.4618, 51.1321], [29.4739, 51.1276], [29.488, 51.1352], [29.4919, 51.1295], [29.5058, 51.1346], [29.5088, 51.1315], [29.5126, 51.1335], [29.5236, 51.1226], [29.5395, 51.1277], [29.5434, 51.1224], [29.5441, 51.1299], [29.5475, 51.1279], [29.5559, 51.1326], [29.5783, 51.1349], [29.5809, 51.1468], [29.5964, 51.1457], [29.5932, 51.1529], [29.6214, 51.1525], [29.6112, 51.1683], [29.6035, 51.1669], [29.5567, 51.1735], [29.5363, 51.1802], [29.4876, 51.1876], [29.4148, 51.1819], [29.3871, 51.1966], [29.3812, 51.2291], [29.4164, 51.2267], [29.4003, 51.2342], [29.4004, 51.2461], [29.4172, 51.2335], [29.4698, 51.2265], [29.4638, 51.2374], [29.476, 51.2387], [29.4788, 51.2463], [29.4748, 51.2492], [29.493, 51.2557], [29.4966, 51.2622], [29.5613, 51.2575], [29.5801, 51.2454], [29.6209, 51.237], [29.6689, 51.2394], [29.7085, 51.2531], [29.7525, 51.2533], [29.7583, 51.2591], [29.8516, 51.2345], [29.8714, 51.2047], [29.8776, 51.2019], [29.8793, 51.1715], [29.8861, 51.1624], [29.8823, 51.1522], [29.8734, 51.1497], [29.8732, 51.147], [29.8877, 51.1423], [29.8881, 51.1384], [29.883, 51.1368], [29.8866, 51.1334], [29.9091, 51.1376], [29.9115, 51.1419], [29.9168, 51.1387], [29.9168, 51.1323], [29.9214, 51.131], [29.9573, 51.1345], [29.9734, 51.1276], [30.0207, 51.1286], [30.0211, 51.1347], [30.0363, 51.1298], [30.0824, 51.1287], [30.0867, 51.1251], [30.0974, 51.1299], [30.1214, 51.1177], [30.1435, 51.1183], [30.1454, 51.1152], [30.1695, 51.1121], [30.1959, 51.1117], [30.2011, 51.1205], [30.206, 51.1172], [30.2554, 51.1103], [30.2963, 51.1208], [30.3104, 51.1205], [30.3189, 51.1029], [30.3308, 51.0948], [30.3483, 51.0914], [30.3563, 51.0856], [30.3635, 51.0893], [30.3851, 51.0834], [30.3895, 51.0886], [30.404, 51.086], [30.4821, 51.0916], [30.4932, 51.0984], [30.5137, 51.1028], [30.5166, 51.1134], [30.4981, 51.129], [30.4917, 51.1395], [30.4905, 51.1651], [30.4999, 51.1752], [30.5288, 51.1736], [30.541, 51.1797], [30.5364, 51.1841], [30.5172, 51.1871], [30.5307, 51.2021], [30.5052, 51.2268], [30.5134, 51.2328], [30.5259, 51.2361], [30.5489, 51.2296], [30.5613, 51.236], [30.5552, 51.2504], [30.5427, 51.2557], [30.5386, 51.2627], [30.5045, 51.2798], [30.4636, 51.2728], [30.4535, 51.2734], [30.4509, 51.2827], [30.4641, 51.291], [30.4581, 51.2986], [30.4638, 51.3066], [30.4436, 51.3085], [30.424, 51.3056], [30.3976, 51.3127], [30.3915, 51.3215], [30.3242, 51.3605], [30.3431, 51.3699], [30.3464, 51.3759], [30.3575, 51.3787], [30.3424, 51.4204], [30.3517, 51.423], [30.3346, 51.4262], [30.2885, 51.4635], [30.2698, 51.4701], [30.2467, 51.4855], [30.2124, 51.4931], [30.1802, 51.5125], [30.1686, 51.5093], [30.1639, 51.489], [30.1479, 51.4932], [30.128, 51.5061], [30.121, 51.5046], [30.1265, 51.4905], [30.1174, 51.4874], [30.0705, 51.499], [30.0517, 51.4986], [30.0358, 51.5039], [30.0142, 51.5051], [30.0211, 51.4966], [30.0149, 51.4902], [29.9909, 51.4825], [29.9851, 51.4864], [29.9771, 51.4863], [29.9708, 51.474], [29.9624, 51.4709], [29.9493, 51.4748], [29.949, 51.484], [29.9448, 51.4865], [29.9266, 51.4921], [29.923, 51.4881], [29.8936, 51.4853], [29.8939, 51.4802], [29.8856, 51.4784], [29.8916, 51.4739], [29.8891, 51.4627], [29.8788, 51.4578], [29.8813, 51.4463], [29.8522, 51.4499], [29.8465, 51.4584], [29.8171, 51.4498], [29.8135, 51.46], [29.7944, 51.4581], [29.7973, 51.4417], [29.7443, 51.4574], [29.7463, 51.4649], [29.7317, 51.4924], [29.7422, 51.4932], [29.7463, 51.502], [29.7395, 51.5093], [29.7463, 51.5154], [29.7377, 51.5316], [29.7111, 51.5275], [29.702, 51.519], [29.6767, 51.5122], [29.6728, 51.503], [29.6546, 51.5063], [29.6433, 51.499], [29.6336, 51.5063], [29.6245, 51.4944], [29.6088, 51.4937], [29.6059, 51.4716], [29.5793, 51.4624], [29.5388, 51.4825], [29.5355, 51.4627], [29.5217, 51.4524], [29.5191, 51.4437], [29.5235, 51.4389], [29.5233, 51.4238], [29.5151, 51.4241], [29.4957, 51.3968], [29.4216, 51.4151], [29.3828, 51.4022], [29.3692, 51.3894], [29.3605, 51.3876], [29.3594, 51.3759], [29.3934, 51.3794], [29.3964, 51.3275], [29.3651, 51.2856], [29.3545, 51.2744], [29.3349, 51.2697], [29.3285, 51.2724], [29.3314, 51.2786], [29.3245, 51.2756], [29.3101, 51.2757], [29.3075, 51.2713], [29.3009, 51.2739], [29.2675, 51.2648]]
    ]
   },
   "geometry_note": {
    "en": "Outline from OpenStreetMap (© OpenStreetMap contributors, ODbL), relation 3311547, simplified",
    "ru": "Контур из OpenStreetMap (© участники OpenStreetMap, ODbL), relation 3311547, упрощён"
   },
   "event": {
    "en": "Chernobyl accident, 1986",
    "ru": "Чернобыльская авария 1986 года"
   },
   "sources": [
    {
     "url": "https://www.iaea.org/sites/default/files/21/07/_t1_02_kashparov_ukraine.pdf",
     "title": "V. Kashparov (UIAR), National experience in remediation of contaminated farmlands after the Chernobyl accident (IAEA)",
     "kind": "primary"
    }
   ],
   "advice": "full"
  },
  {
   "id": "by-polesie-reserve",
   "severity": "danger",
   "approximate": false,
   "name": {
    "en": "Polesie State Radioecological Reserve (Belarus)",
    "ru": "Полесский государственный радиационно-экологический заповедник (Беларусь)"
   },
   "contamination": {
    "en": "Chernobyl fallout in the Belarusian exclusion and resettlement zones",
    "ru": "чернобыльские выпадения в белорусских зонах отчуждения и отселения"
   },
   "status": {
    "en": "Unauthorised presence of people is prohibited; taking out plants, mushrooms and berries without a special permit is prohibited (regulation of the Ministry for Emergency Situations of Belarus, 1995).",
    "ru": "Несанкционированное нахождение людей запрещено; вывоз растительных продуктов, грибов и ягод без специального разрешения запрещён (положение МЧС Беларуси, 1995 год)."
   },
   "geometry": {
    "type": "polygons",
    "rings": [
     [[29.4242, 51.532], [29.4297, 51.533], [29.4317, 51.5276], [29.4351, 51.5279], [29.4422, 51.4987], [29.4509, 51.4991], [29.4429, 51.495], [29.4448, 51.4842], [29.5096, 51.4809], [29.5093, 51.4596], [29.5355, 51.4627], [29.5388, 51.4825], [29.5793, 51.4624], [29.5952, 51.4668], [29.6091, 51.4747], [29.6088, 51.4937], [29.6245, 51.4944], [29.6336, 51.5063], [29.6433, 51.499], [29.6546, 51.5063], [29.6728, 51.503], [29.6767, 51.5122], [29.702, 51.519], [29.7167, 51.5299], [29.7404, 51.5311], [29.7463, 51.5154], [29.7395, 51.5093], [29.7463, 51.502], [29.7422, 51.4932], [29.7317, 51.4924], [29.7463, 51.4649], [29.7443, 51.4574], [29.7973, 51.4417], [29.7944, 51.4581], [29.8135, 51.46], [29.8171, 51.4498], [29.8465, 51.4584], [29.8522, 51.4499], [29.8813, 51.4463], [29.8788, 51.4578], [29.8891, 51.4627], [29.8916, 51.4739], [29.8856, 51.4784], [29.8939, 51.4802], [29.8936, 51.4853], [29.923, 51.4881], [29.9266, 51.4921], [29.9448, 51.4865], [29.949, 51.484], [29.9493, 51.4748], [29.9624, 51.4709], [29.9708, 51.474], [29.9771, 51.4863], [29.9851, 51.4864], [29.9909, 51.4825], [30.0149, 51.4902], [30.0211, 51.4966], [30.0142, 51.5051], [30.0358, 51.5039], [30.0517, 51.4986], [30.0705, 51.499], [30.1174, 51.4874], [30.1265, 51.4905], [30.121, 51.5046], [30.128, 51.5061], [30.1479, 51.4932], [30.1639, 51.489], [30.1686, 51.5093], [30.1802, 51.5125], [30.2124, 51.4931], [30.2467, 51.4855], [30.2698, 51.4701], [30.2885, 51.4635], [30.3346, 51.4262], [30.3517, 51.423], [30.3424, 51.4204], [30.3575, 51.3787], [30.3464, 51.3759], [30.3431, 51.3699], [30.3242, 51.3605], [30.3915, 51.3215], [30.3976, 51.3127], [30.4124, 51.3084], [30.4092, 51.3106], [30.4103, 51.327], [30.3958, 51.3271], [30.3911, 51.3313], [30.4003, 51.3389], [30.4007, 51.3535], [30.3914, 51.3596], [30.3877, 51.3747], [30.4162, 51.3762], [30.4173, 51.3819], [30.4358, 51.3769], [30.4403, 51.392], [30.4473, 51.3929], [30.4408, 51.3977], [30.4462, 51.3981], [30.4468, 51.4484], [30.4438, 51.4483], [30.443, 51.4638], [30.4371, 51.4637], [30.4365, 51.473], [30.4309, 51.4729], [30.4306, 51.4799], [30.4248, 51.4798], [30.4247, 51.4873], [30.4624, 51.4936], [30.4562, 51.4996], [30.4622, 51.5009], [30.4598, 51.5072], [30.4528, 51.5082], [30.4607, 51.5122], [30.4503, 51.5194], [30.4563, 51.5274], [30.4268, 51.5379], [30.4079, 51.5504], [30.3821, 51.5602], [30.3721, 51.5751], [30.3376, 51.601], [30.3212, 51.5966], [30.2994, 51.5991], [30.2643, 51.616], [30.2646, 51.6289], [30.297, 51.6335], [30.3004, 51.6379], [30.2641, 51.6649], [30.2289, 51.7048], [30.2485, 51.7758], [30.2428, 51.7727], [30.2276, 51.7743], [30.2193, 51.7801], [30.2105, 51.7792], [30.2104, 51.7812], [30.1853, 51.7863], [30.1795, 51.7764], [30.1554, 51.7819], [30.1451, 51.7865], [30.1491, 51.7895], [30.1415, 51.7911], [30.1395, 51.7872], [30.1161, 51.7932], [30.1065, 51.792], [30.0923, 51.7974], [30.0853, 51.7857], [30.0806, 51.7868], [30.0724, 51.7766], [30.0659, 51.7833], [30.0572, 51.7818], [30.0578, 51.7887], [30.0388, 51.7878], [30.0312, 51.7978], [29.9993, 51.7985], [29.9857, 51.7946], [29.9735, 51.7965], [29.9646, 51.7931], [29.9607, 51.7939], [29.9595, 51.8005], [29.9456, 51.7966], [29.9451, 51.8003], [29.916, 51.7987], [29.9142, 51.8011], [29.9217, 51.8022], [29.9201, 51.8047], [29.9049, 51.8015], [29.8788, 51.8029], [29.8712, 51.7975], [29.8384, 51.7938], [29.829, 51.7856], [29.814, 51.7945], [29.8096, 51.7925], [29.8007, 51.7941], [29.7949, 51.7985], [29.7899, 51.7956], [29.7719, 51.8062], [29.7721, 51.8153], [29.7658, 51.8192], [29.7729, 51.8234], [29.7501, 51.8383], [29.7682, 51.8485], [29.7592, 51.8584], [29.7317, 51.8547], [29.7051, 51.8406], [29.6948, 51.8281], [29.6884, 51.8309], [29.6879, 51.8459], [29.6991, 51.8465], [29.6913, 51.8687], [29.6936, 51.8721], [29.6369, 51.8877], [29.6151, 51.8866], [29.6086, 51.8903], [29.6085, 51.8945], [29.5935, 51.8969], [29.5917, 51.8943], [29.5842, 51.8947], [29.5824, 51.8917], [29.5798, 51.893], [29.5701, 51.8663], [29.5702, 51.8499], [29.5348, 51.8461], [29.5192, 51.8375], [29.5073, 51.8281], [29.501, 51.8097], [29.5294, 51.7908], [29.557, 51.7886], [29.566, 51.784], [29.5745, 51.787], [29.5772, 51.7997], [29.5866, 51.7996], [29.5909, 51.7873], [29.5728, 51.7767], [29.5718, 51.7697], [29.593, 51.7585], [29.5876, 51.748], [29.5696, 51.7484], [29.558, 51.7454], [29.5579, 51.7279], [29.5452, 51.7122], [29.5327, 51.7122], [29.528, 51.7077], [29.5143, 51.7121], [29.5065, 51.7028], [29.506, 51.6455], [29.5, 51.646], [29.4718, 51.6139], [29.4594, 51.5881], [29.4269, 51.5465], [29.4242, 51.532]]
    ]
   },
   "geometry_note": {
    "en": "Outline from OpenStreetMap (© OpenStreetMap contributors, ODbL), relation 3397849, simplified",
    "ru": "Контур из OpenStreetMap (© участники OpenStreetMap, ODbL), relation 3397849, упрощён"
   },
   "event": {
    "en": "Chernobyl accident, 1986",
    "ru": "Чернобыльская авария 1986 года"
   },
   "sources": [
    {
     "url": "https://faolex.fao.org/docs/pdf/blr62425.pdf",
     "title": "Order of the Ministry for Emergency Situations of Belarus No. 39 of 5 Aug 1995: regulation on the Polesie State Radioecological Reserve",
     "kind": "primary"
    }
   ],
   "advice": "full"
  },
  {
   "id": "ru-bryansk-contaminated-districts",
   "severity": "caution",
   "approximate": true,
   "name": {
    "en": "South-western Bryansk region (districts with Chernobyl-contaminated settlements)",
    "ru": "Юго-запад Брянской области (районы с загрязнёнными после Чернобыля населёнными пунктами)"
   },
   "contamination": {
    "en": "caesium-137 from the 1986 Chernobyl accident",
    "ru": "цезий-137 после Чернобыльской аварии 1986 года"
   },
   "status": {
    "en": "The government list of Chernobyl-contaminated settlements (decree No. 1074 of 2015) puts settlements of the Gordeevsky, Zlynkovsky, Klintsovsky, Krasnogorsky and Novozybkovsky districts into the resettlement zone, those of Krasnogorsky district also into the exclusion zone, and adds Klimovsky district to the zone of residence with the right to resettle; forest mushrooms can account for up to 75–82 % of the internal dose there (Radiation Hygiene, 2023). Only some settlements of each district are listed.",
    "ru": "В перечне населённых пунктов в зонах радиоактивного загрязнения (постановление Правительства РФ № 1074 от 2015 года) населённые пункты Гордеевского, Злынковского, Клинцовского, Красногорского и Новозыбковского районов отнесены к зоне отселения, часть Красногорского района — к зоне отчуждения, а Климовский район добавлен к зоне проживания с правом на отселение; вклад лесных грибов во внутреннюю дозу там может достигать 75–82 % (журнал «Радиационная гигиена», 2023). В перечне указаны лишь некоторые населённые пункты каждого района."
   },
   "geometry": {
    "type": "polygons",
    "rings": [
     [[31.6773, 52.8542], [31.7286, 52.8324], [31.7172, 52.8062], [31.6845, 52.7945], [31.6848, 52.7567], [31.7274, 52.7246], [31.7213, 52.7075], [31.7544, 52.7054], [31.773, 52.7684], [31.8973, 52.7912], [31.9112, 52.8185], [31.8982, 52.8368], [31.9671, 52.8403], [31.9743, 52.8698], [32.0336, 52.8833], [32.0928, 52.923], [32.1768, 52.9306], [32.1492, 52.9793], [32.1618, 53.0019], [32.1476, 53.044], [32.1114, 53.0781], [32.018, 53.0909], [32.0191, 53.1001], [31.9926, 53.0853], [31.9347, 53.0831], [31.9135, 53.0889], [31.9225, 53.105], [31.8871, 53.1145], [31.831, 53.1104], [31.8147, 53.1244], [31.7612, 53.1059], [31.7507, 53.0907], [31.7819, 53.0804], [31.766, 53.075], [31.7635, 53.0356], [31.735, 53.0305], [31.7462, 52.997], [31.7283, 52.9887], [31.6957, 53.002], [31.7119, 52.9868], [31.7008, 52.9302], [31.7191, 52.9057], [31.6845, 52.8777], [31.7048, 52.8727], [31.7018, 52.862], [31.6773, 52.8542]],
     [[31.5326, 52.486], [31.5375, 52.4738], [31.5602, 52.4766], [31.5764, 52.4635], [31.5746, 52.4836], [31.5326, 52.486]],
     [[31.5588, 52.5181], [31.5735, 52.4978], [31.6001, 52.5054], [31.625, 52.4919], [31.5808, 52.4571], [31.6078, 52.4537], [31.5941, 52.4149], [31.6216, 52.4183], [31.6325, 52.3987], [31.6254, 52.3315], [31.5807, 52.3284], [31.6273, 52.2892], [31.714, 52.2652], [31.6965, 52.2579], [31.7109, 52.2148], [31.6883, 52.1945], [31.7735, 52.1857], [31.8311, 52.2007], [31.868, 52.1832], [31.8926, 52.1862], [31.8952, 52.2544], [31.9345, 52.2501], [31.9289, 52.2744], [31.9406, 52.266], [31.9914, 52.2884], [32.0424, 52.2906], [32.0176, 52.3012], [32.0209, 52.3237], [31.9907, 52.3415], [32.0074, 52.3695], [31.9879, 52.3784], [32.0037, 52.3915], [32.0356, 52.3888], [32.0323, 52.4102], [31.9455, 52.4329], [31.9186, 52.4199], [31.9173, 52.434], [31.8799, 52.4492], [31.8307, 52.4452], [31.8317, 52.4852], [31.7265, 52.4795], [31.7244, 52.5019], [31.6676, 52.4982], [31.6845, 52.5285], [31.6236, 52.5533], [31.5943, 52.5163], [31.5588, 52.5181]],
     [[31.7763, 52.1878], [31.7993, 52.1196], [31.7806, 52.1144], [31.7977, 52.1021], [31.8676, 52.1105], [31.9538, 52.0819], [31.9582, 52.0683], [31.9212, 52.0569], [31.9163, 52.0423], [31.9622, 52.0532], [32.0659, 52.0349], [32.1338, 52.0439], [32.1472, 52.0691], [32.1994, 52.0661], [32.2244, 52.0872], [32.2905, 52.1031], [32.3204, 52.1366], [32.3647, 52.1433], [32.3654, 52.156], [32.3238, 52.1516], [32.3472, 52.1834], [32.3244, 52.2237], [32.3467, 52.2447], [32.4017, 52.248], [32.3831, 52.27], [32.3934, 52.2784], [32.3695, 52.277], [32.3562, 52.3283], [32.4007, 52.3381], [32.4894, 52.3145], [32.5181, 52.3617], [32.5766, 52.3751], [32.5649, 52.3896], [32.5382, 52.3911], [32.5518, 52.4485], [32.4598, 52.5046], [32.3474, 52.5086], [32.3461, 52.4933], [32.3816, 52.4732], [32.3686, 52.4706], [32.2821, 52.5178], [32.1841, 52.5051], [32.181, 52.4949], [32.16, 52.5188], [32.1247, 52.5224], [32.1257, 52.497], [32.0867, 52.4697], [32.0772, 52.4348], [32.0188, 52.4258], [32.0449, 52.4187], [32.0356, 52.3888], [32.0037, 52.3915], [31.9879, 52.3784], [32.0074, 52.3695], [31.9917, 52.3375], [32.0209, 52.3237], [32.0176, 52.3012], [32.0424, 52.2906], [31.9914, 52.2884], [31.9406, 52.266], [31.9289, 52.2744], [31.9345, 52.2501], [31.8952, 52.2544], [31.8926, 52.1862], [31.868, 52.1832], [31.8311, 52.2007], [31.7763, 52.1878]],
     [[31.7567, 52.7194], [31.7947, 52.7344], [31.8157, 52.6752], [31.9125, 52.6879], [31.926, 52.6495], [31.9668, 52.6704], [32.059, 52.6527], [32.0765, 52.6429], [32.0692, 52.6317], [32.1166, 52.6305], [32.1221, 52.6524], [32.1646, 52.6505], [32.1435, 52.6289], [32.19, 52.6244], [32.2153, 52.5856], [32.2675, 52.5807], [32.2302, 52.564], [32.2703, 52.5325], [32.2321, 52.5203], [32.2891, 52.5154], [32.3686, 52.4706], [32.3816, 52.4732], [32.3461, 52.4933], [32.3474, 52.5086], [32.4359, 52.5053], [32.4214, 52.5264], [32.4428, 52.5546], [32.5098, 52.5573], [32.5114, 52.5877], [32.4607, 52.6139], [32.4618, 52.6405], [32.4066, 52.7031], [32.4447, 52.7354], [32.4814, 52.7008], [32.5514, 52.6987], [32.5498, 52.7321], [32.5197, 52.7296], [32.4726, 52.769], [32.4462, 52.7675], [32.4268, 52.8021], [32.4247, 52.8182], [32.4588, 52.8173], [32.4545, 52.8344], [32.4737, 52.8229], [32.4852, 52.837], [32.4862, 52.8462], [32.4216, 52.8659], [32.453, 52.8949], [32.4104, 52.864], [32.3871, 52.8711], [32.3788, 52.8636], [32.3508, 52.8841], [32.2876, 52.8834], [32.2931, 52.8956], [32.257, 52.9277], [32.177, 52.9419], [32.1768, 52.9306], [32.1035, 52.9257], [32.0336, 52.8833], [31.9743, 52.8698], [31.9671, 52.8403], [31.8982, 52.8368], [31.9112, 52.8185], [31.8973, 52.7912], [31.773, 52.7684], [31.7567, 52.7194]],
     [[32.252, 52.7282], [32.2658, 52.7244], [32.2636, 52.733], [32.252, 52.7282]],
     [[31.2419, 53.0288], [31.3562, 52.9846], [31.3751, 52.9271], [31.4394, 52.8813], [31.4808, 52.8605], [31.5382, 52.8564], [31.5194, 52.8315], [31.5626, 52.7968], [31.5896, 52.7914], [31.5889, 52.758], [31.6848, 52.7567], [31.6845, 52.7945], [31.7172, 52.8062], [31.7286, 52.8324], [31.6773, 52.8542], [31.7018, 52.862], [31.7048, 52.8727], [31.6845, 52.8777], [31.7191, 52.9057], [31.7008, 52.9302], [31.7119, 52.9868], [31.6957, 53.002], [31.7283, 52.9887], [31.7462, 52.997], [31.735, 53.0305], [31.7635, 53.0356], [31.766, 53.075], [31.7819, 53.0804], [31.7507, 53.0907], [31.7612, 53.1059], [31.8147, 53.1244], [31.7906, 53.1772], [31.6285, 53.2312], [31.564, 53.1923], [31.4018, 53.2118], [31.4149, 53.1783], [31.3636, 53.144], [31.3655, 53.1267], [31.3988, 53.1097], [31.3912, 53.0965], [31.3348, 53.0912], [31.3306, 53.0418], [31.2623, 53.043], [31.2419, 53.0288]],
     [[32.1526, 52.7569], [32.1717, 52.7427], [32.211, 52.7502], [32.1982, 52.7423], [32.2223, 52.7363], [32.2131, 52.7277], [32.2458, 52.7363], [32.2658, 52.7244], [32.2869, 52.7274], [32.2825, 52.7456], [32.3068, 52.7518], [32.2714, 52.7752], [32.2538, 52.7691], [32.2422, 52.7856], [32.2152, 52.7852], [32.2001, 52.7551], [32.1777, 52.7607], [32.1711, 52.7481], [32.1526, 52.7569]],
     [[31.4978, 52.6952], [31.5695, 52.6352], [31.564, 52.5943], [31.6304, 52.5628], [31.6736, 52.5611], [31.647, 52.5429], [31.6845, 52.5285], [31.6676, 52.4982], [31.7244, 52.5019], [31.7265, 52.4795], [31.8317, 52.4852], [31.8307, 52.4452], [31.8912, 52.4462], [31.9186, 52.4199], [31.9455, 52.4329], [32.0435, 52.4139], [32.0188, 52.4258], [32.0772, 52.4348], [32.0867, 52.4697], [32.1257, 52.497], [32.1247, 52.5224], [32.16, 52.5188], [32.181, 52.4949], [32.1841, 52.5051], [32.2168, 52.5062], [32.2703, 52.5325], [32.2302, 52.564], [32.2675, 52.5807], [32.2153, 52.5856], [32.19, 52.6244], [32.1435, 52.6289], [32.1646, 52.6505], [32.1221, 52.6524], [32.1166, 52.6305], [32.0692, 52.6317], [32.0765, 52.6429], [32.059, 52.6527], [31.9668, 52.6704], [31.926, 52.6495], [31.9125, 52.6879], [31.8259, 52.6748], [31.802, 52.6807], [31.8098, 52.7168], [31.7947, 52.7344], [31.7567, 52.7194], [31.7544, 52.7054], [31.7213, 52.7075], [31.7274, 52.7246], [31.6848, 52.7567], [31.6094, 52.7648], [31.567, 52.7081], [31.4978, 52.6952]]
    ]
   },
   "geometry_note": {
    "en": "Outline from OpenStreetMap (© OpenStreetMap contributors, ODbL), district boundaries (relations 1242315, 1242352, 1242354, 1242351, 1242316, 4464145, 1242353), simplified to about 0.8 km; whole districts, so the outline overstates the contaminated land",
    "ru": "Контур из OpenStreetMap (© участники OpenStreetMap, ODbL), границы районов (relations 1242315, 1242352, 1242354, 1242351, 1242316, 4464145, 1242353), упрощены; районы целиком, поэтому контур преувеличивает загрязнённую землю"
   },
   "event": {
    "en": "Chernobyl accident, 1986",
    "ru": "Чернобыльская авария 1986 года"
   },
   "sources": [
    {
     "url": "https://www.radhyg.ru/jour/article/download/993/861",
     "title": "Structure of forest mushroom consumption by residents of contaminated territories of the Bryansk region, Radiation Hygiene 2023;16(4):55-63",
     "kind": "primary"
    },
    {
     "url": "http://government.ru/docs/all/103736/",
     "title": "Government of the Russian Federation, decree No. 1074 of 8 Oct 2015: list of settlements within the Chernobyl radioactive-contamination zones",
     "kind": "primary"
    }
   ],
   "advice": "full"
  },
  {
   "id": "kz-semipalatinsk-test-site",
   "severity": "caution",
   "approximate": false,
   "name": {
    "en": "Semipalatinsk former nuclear test site (Kazakhstan)",
    "ru": "Бывший Семипалатинский ядерный полигон (Казахстан)"
   },
   "contamination": {
    "en": "radionuclides at the test locations (Experimental Field, Degelen, Balapan, Sary-Uzen, Aktan-Berli, Telkem and others) and in fallout areas",
    "ru": "радионуклиды на испытательных площадках (Опытное поле, Дегелен, Балапан, Сары-Узен, Актан-Берли, Телькем и другие) и на территориях выпадений"
   },
   "status": {
    "en": "The site covers more than 18 300 km²; use of the former test site is governed by the 2023 law on the Semipalatinsk Nuclear Safety Zone. The contamination is local, so most of the polygon is much cleaner than the test locations.",
    "ru": "Полигон занимает более 18 300 км²; использование территории регулирует закон 2023 года о Семипалатинской зоне ядерной безопасности. Загрязнение локальное, поэтому большая часть полигона чище испытательных площадок."
   },
   "geometry": {
    "type": "polygons",
    "rings": [
     [[77.076, 50.665], [77.263, 50.5661], [77.199, 50.5081], [77.2296, 50.4327], [77.1823, 50.4385], [77.161, 50.4313], [77.1934, 50.4111], [77.2155, 50.3601], [77.2701, 50.2913], [77.2816, 50.2372], [77.324, 50.2157], [77.4015, 50.1298], [77.4811, 50.0656], [77.4365, 50.029], [77.2703, 49.981], [77.2238, 49.9513], [77.1901, 49.9541], [77.1542, 49.9372], [77.1342, 49.887], [77.1455, 49.8717], [77.1293, 49.78], [77.1638, 49.7655], [77.1596, 49.7129], [77.151, 49.6912], [77.0799, 49.6242], [77.1299, 49.5383], [77.1337, 49.5059], [77.1941, 49.4709], [77.4373, 49.4142], [77.488, 49.3604], [77.5249, 49.3446], [78.0732, 49.3566], [78.1399, 49.3509], [78.1293, 49.3294], [78.2305, 49.3174], [78.2521, 49.3248], [78.2587, 49.353], [78.3952, 49.3931], [78.4371, 49.4213], [78.5744, 49.4708], [78.6738, 49.5193], [78.6478, 49.5696], [78.6578, 49.5883], [78.6148, 49.6381], [78.6446, 49.675], [78.6898, 49.7016], [78.7873, 49.7046], [78.8186, 49.6935], [78.871, 49.7415], [78.9055, 49.7588], [78.9567, 49.7767], [79.0621, 49.7841], [79.0976, 49.8194], [79.0721, 49.8539], [79.1148, 49.8604], [79.1567, 49.8876], [79.1335, 49.8923], [79.1743, 49.924], [79.081, 50.0037], [79.0966, 50.0235], [79.1252, 50.0348], [78.8926, 50.1302], [78.8046, 50.1389], [78.7836, 50.323], [78.7529, 50.4385], [78.6711, 50.4593], [78.6801, 50.6963], [78.4795, 50.7878], [78.4714, 50.7726], [78.4509, 50.7668], [78.4555, 50.7315], [78.3971, 50.7282], [78.3156, 50.7489], [78.3024, 50.7795], [78.2539, 50.8017], [78.1895, 50.8234], [78.0952, 50.8308], [78.0015, 50.8494], [77.9327, 50.8729], [77.8732, 50.9086], [77.7741, 50.9114], [77.6993, 50.9243], [77.6323, 50.9218], [77.5815, 50.9087], [77.4601, 50.9137], [77.3851, 50.8929], [77.076, 50.665]]
    ]
   },
   "geometry_note": {
    "en": "Outline from OpenStreetMap (© OpenStreetMap contributors, ODbL), way 932505322 (boundary=hazard), simplified",
    "ru": "Контур из OpenStreetMap (© участники OpenStreetMap, ODbL), way 932505322 (boundary=hazard), упрощён"
   },
   "event": {
    "en": "nuclear tests, 1949–1989",
    "ru": "ядерные испытания 1949–1989 годов"
   },
   "sources": [
    {
     "url": "https://nnc.kz/en/activity/radioecology.html",
     "title": "National Nuclear Center of the Republic of Kazakhstan: radioecological surveys",
     "kind": "primary"
    }
   ],
   "advice": "full"
  },
  {
   "id": "ru-central-chernobyl-districts",
   "severity": "caution",
   "approximate": true,
   "name": {
    "en": "Tula, Kaluga and Orel districts with Chernobyl-contaminated settlements",
    "ru": "Районы Тульской, Калужской и Орловской областей с загрязнёнными после Чернобыля населёнными пунктами"
   },
   "contamination": {
    "en": "caesium-137 from the 1986 Chernobyl accident",
    "ru": "цезий-137 после Чернобыльской аварии 1986 года"
   },
   "status": {
    "en": "The government list (decree No. 1074 of 2015) puts settlements of the Arsenyevsky, Belevsky, Plavsky, Chernsky and Shchekinsky districts of the Tula region, the Zhizdra, Ulyanovo and Khvastovichi districts of the Kaluga region and the Bolkhov district of the Orel region into the zone of residence with the right to resettle. Only some settlements of each district are listed.",
    "ru": "В перечне Правительства РФ (постановление № 1074 от 2015 года) населённые пункты Арсеньевского, Белёвского, Плавского, Чернского и Щёкинского районов Тульской области, Жиздринского, Ульяновского и Хвастовичского районов Калужской области и Болховского района Орловской области отнесены к зоне проживания с правом на отселение. В перечне указаны лишь некоторые населённые пункты каждого района."
   },
   "event": {
    "en": "Chernobyl accident, 1986",
    "ru": "Чернобыльская авария 1986 года"
   },
   "geometry": {
    "type": "polygons",
    "rings": [
     [[36.2705, 53.6757], [36.3142, 53.6557], [36.3, 53.6424], [36.334, 53.6164], [36.3288, 53.5942], [36.3535, 53.6039], [36.3641, 53.5886], [36.2972, 53.5492], [36.2879, 53.5176], [36.3233, 53.5003], [36.3179, 53.4745], [36.3616, 53.4717], [36.3849, 53.4495], [36.4109, 53.4739], [36.4594, 53.4616], [36.48, 53.4901], [36.5327, 53.5114], [36.4856, 53.5168], [36.4588, 53.5587], [36.5047, 53.5635], [36.4981, 53.5552], [36.5496, 53.5446], [36.5656, 53.5283], [36.6124, 53.5432], [36.64, 53.5381], [36.7132, 53.5513], [36.7338, 53.5643], [36.7238, 53.5824], [36.7911, 53.5845], [36.8274, 53.6222], [36.8521, 53.6279], [36.89, 53.6133], [36.9169, 53.6266], [36.994, 53.6729], [36.9507, 53.6892], [36.9553, 53.7014], [37.0428, 53.7338], [37.0304, 53.7502], [36.9833, 53.7522], [36.9929, 53.768], [36.9269, 53.7737], [36.8868, 53.7673], [36.8719, 53.753], [36.8426, 53.7691], [36.8519, 53.7768], [36.786, 53.7751], [36.7741, 53.8013], [36.7218, 53.8041], [36.6429, 53.7803], [36.642, 53.7625], [36.6186, 53.7794], [36.5834, 53.7769], [36.5668, 53.7871], [36.5127, 53.7808], [36.5199, 53.7555], [36.3899, 53.7734], [36.406, 53.7363], [36.3802, 53.7061], [36.3167, 53.6991], [36.3046, 53.7093], [36.3069, 53.691], [36.2868, 53.6948], [36.2705, 53.6757]],
     [[35.8986, 53.8502], [35.9728, 53.8164], [35.9698, 53.797], [35.9173, 53.777], [35.9335, 53.7528], [35.9584, 53.7519], [35.9585, 53.7185], [36.0288, 53.7262], [36.0304, 53.712], [36.0877, 53.7029], [36.074, 53.6819], [36.028, 53.6731], [35.9925, 53.6414], [35.9912, 53.6263], [36.037, 53.6102], [36.0189, 53.5676], [36.0386, 53.5588], [36.0607, 53.5734], [36.1739, 53.5394], [36.2268, 53.5613], [36.2317, 53.5445], [36.3175, 53.5584], [36.3641, 53.5886], [36.3535, 53.6039], [36.3288, 53.5942], [36.334, 53.6164], [36.3, 53.6424], [36.3142, 53.6557], [36.2705, 53.6757], [36.2828, 53.693], [36.3069, 53.691], [36.3046, 53.7093], [36.3167, 53.6991], [36.3802, 53.7061], [36.406, 53.7363], [36.3899, 53.7734], [36.5199, 53.7555], [36.4883, 53.7742], [36.4826, 53.8014], [36.4458, 53.8079], [36.4815, 53.8542], [36.4654, 53.8507], [36.3976, 53.879], [36.4238, 53.8838], [36.4328, 53.9022], [36.4988, 53.9199], [36.4956, 53.9341], [36.4065, 53.9664], [36.3887, 53.9465], [36.3452, 53.9365], [36.3023, 53.952], [36.2616, 53.95], [36.2615, 53.967], [36.2057, 53.9557], [36.1992, 53.9826], [36.1737, 53.9695], [36.1666, 53.9797], [36.1274, 53.9809], [36.1284, 53.9648], [36.1568, 53.9562], [36.1413, 53.9404], [36.1201, 53.9385], [36.0944, 53.9593], [36.0472, 53.9559], [36.0559, 53.9464], [36.0241, 53.9346], [36.0356, 53.924], [35.9836, 53.9081], [36.0008, 53.8727], [35.9698, 53.8526], [35.8986, 53.8502]],
     [[36.9507, 53.6892], [36.994, 53.6729], [36.9538, 53.6473], [37.1155, 53.5904], [37.1353, 53.5969], [37.1591, 53.5795], [37.1215, 53.5535], [37.1423, 53.5315], [37.1248, 53.5033], [37.1619, 53.488], [37.1583, 53.4791], [37.1911, 53.4776], [37.1958, 53.4613], [37.2576, 53.4627], [37.3187, 53.3858], [37.3553, 53.4023], [37.3873, 53.3668], [37.4063, 53.3714], [37.3919, 53.3921], [37.4305, 53.4154], [37.3996, 53.445], [37.4075, 53.4824], [37.3866, 53.5065], [37.4262, 53.5206], [37.4375, 53.5459], [37.5353, 53.5809], [37.4377, 53.6265], [37.4801, 53.6338], [37.4805, 53.6579], [37.5135, 53.6592], [37.5114, 53.692], [37.4788, 53.6949], [37.4838, 53.7083], [37.4387, 53.7127], [37.4412, 53.7252], [37.3794, 53.7244], [37.3743, 53.7388], [37.3394, 53.7295], [37.35, 53.7574], [37.3196, 53.7729], [37.3504, 53.7967], [37.257, 53.833], [37.2297, 53.8171], [37.165, 53.8091], [37.0978, 53.8244], [37.0818, 53.7894], [37.0484, 53.7887], [37.0504, 53.7759], [37.0019, 53.7765], [36.9833, 53.7522], [37.0304, 53.7502], [37.0428, 53.7338], [36.9553, 53.7014], [36.9507, 53.6892]],
     [[36.3849, 53.4495], [36.4299, 53.4206], [36.4683, 53.4292], [36.489, 53.3903], [36.5475, 53.376], [36.6229, 53.3991], [36.6356, 53.4202], [36.6996, 53.395], [36.6959, 53.3705], [36.6757, 53.3636], [36.7312, 53.3437], [36.7391, 53.3256], [36.7615, 53.3246], [36.746, 53.3091], [36.7747, 53.3158], [36.7841, 53.2958], [36.832, 53.2862], [36.9108, 53.2943], [36.8988, 53.273], [36.9962, 53.2902], [36.9967, 53.2993], [37.0125, 53.2963], [37.0078, 53.267], [37.0958, 53.2862], [37.127, 53.2629], [37.2218, 53.256], [37.3669, 53.291], [37.366, 53.3017], [37.4666, 53.2878], [37.4603, 53.3313], [37.4844, 53.3286], [37.5002, 53.3569], [37.4786, 53.3618], [37.4387, 53.3497], [37.4063, 53.3714], [37.3873, 53.3668], [37.3553, 53.4023], [37.3187, 53.3858], [37.2576, 53.4627], [37.1958, 53.4613], [37.1934, 53.4764], [37.1697, 53.4743], [37.1248, 53.5033], [37.1423, 53.5315], [37.1215, 53.5535], [37.1591, 53.5795], [37.1433, 53.5936], [37.1155, 53.5904], [36.9538, 53.6473], [36.8931, 53.6138], [36.8529, 53.619], [36.8521, 53.6279], [36.8274, 53.6222], [36.7911, 53.5845], [36.7238, 53.5824], [36.7338, 53.5643], [36.7132, 53.5513], [36.594, 53.538], [36.5656, 53.5283], [36.5657, 53.5063], [36.5327, 53.5114], [36.48, 53.4901], [36.4594, 53.4616], [36.4109, 53.4739], [36.3849, 53.4495]],
     [[36.9775, 54.0046], [37.0005, 54.0035], [37.0035, 53.9924], [36.9912, 53.9441], [37.0488, 53.9363], [37.0406, 53.9035], [37.0733, 53.9102], [37.1103, 53.8825], [37.0687, 53.8329], [37.0923, 53.8174], [37.1193, 53.8238], [37.165, 53.8091], [37.2649, 53.8324], [37.2699, 53.8194], [37.3393, 53.8073], [37.3502, 53.7911], [37.3196, 53.7729], [37.35, 53.7574], [37.3394, 53.7295], [37.3743, 53.7388], [37.3794, 53.7244], [37.4412, 53.7252], [37.4387, 53.7127], [37.4838, 53.7083], [37.4788, 53.6949], [37.5114, 53.692], [37.557, 53.697], [37.5609, 53.7274], [37.6217, 53.7489], [37.6691, 53.7378], [37.6828, 53.7507], [37.7099, 53.7496], [37.7226, 53.7932], [37.6793, 53.8065], [37.6692, 53.8248], [37.6963, 53.8408], [37.6958, 53.8808], [37.6752, 53.8826], [37.6792, 53.8917], [37.7207, 53.9], [37.669, 53.9128], [37.6453, 53.9614], [37.7176, 54.0041], [37.6869, 54.0211], [37.6817, 54.0139], [37.631, 54.0219], [37.6058, 54.05], [37.5356, 54.0837], [37.4598, 54.0745], [37.4464, 54.0533], [37.4169, 54.0522], [37.3836, 54.0891], [37.3236, 54.054], [37.2453, 54.0693], [37.1463, 54.068], [37.1095, 54.052], [37.064, 54.0555], [37.0266, 54.0422], [37.0189, 54.0228], [36.9775, 54.0046]],
     [[34.4018, 53.7477], [34.4255, 53.6937], [34.5007, 53.6707], [34.4951, 53.637], [34.4726, 53.6358], [34.4899, 53.6181], [34.512, 53.6167], [34.519, 53.5883], [34.4976, 53.583], [34.5015, 53.5431], [34.5293, 53.5411], [34.5155, 53.5084], [34.5685, 53.4704], [34.5548, 53.4546], [34.5717, 53.4287], [34.606, 53.4267], [34.6443, 53.3814], [34.6735, 53.3808], [34.6703, 53.4096], [34.652, 53.4161], [34.6769, 53.4263], [34.6666, 53.4328], [34.7084, 53.4287], [34.7129, 53.4606], [34.7336, 53.4578], [34.7647, 53.4978], [34.7847, 53.4971], [34.7729, 53.5197], [34.875, 53.5535], [34.9235, 53.5364], [34.9476, 53.5517], [34.9576, 53.5806], [34.9425, 53.5813], [34.9812, 53.6495], [35.0371, 53.6538], [35.0463, 53.6881], [35.0688, 53.6761], [35.1043, 53.6841], [35.0937, 53.7312], [35.0652, 53.711], [35.0306, 53.7186], [35.0565, 53.7703], [35.0857, 53.7786], [35.0737, 53.7901], [35.0503, 53.785], [34.9964, 53.8023], [34.9343, 53.7795], [34.8627, 53.7813], [34.8536, 53.8201], [34.8139, 53.8402], [34.8286, 53.856], [34.7074, 53.8953], [34.6914, 53.8532], [34.6267, 53.8291], [34.6115, 53.8084], [34.5842, 53.8063], [34.5842, 53.7854], [34.5506, 53.7836], [34.5472, 53.7684], [34.5232, 53.7715], [34.5, 53.751], [34.4018, 53.7477]],
     [[35.1587, 53.7174], [35.1765, 53.6788], [35.255, 53.6513], [35.2571, 53.6379], [35.3202, 53.6457], [35.3326, 53.6184], [35.3198, 53.6051], [35.3409, 53.5819], [35.3179, 53.5564], [35.3385, 53.5611], [35.3415, 53.5376], [35.3598, 53.537], [35.4365, 53.5882], [35.4765, 53.5911], [35.4912, 53.5798], [35.4536, 53.5655], [35.4484, 53.5332], [35.4618, 53.539], [35.5107, 53.5235], [35.5085, 53.5382], [35.4815, 53.5449], [35.4892, 53.5562], [35.5487, 53.5544], [35.5573, 53.535], [35.5357, 53.5141], [35.5859, 53.5123], [35.6233, 53.5239], [35.6118, 53.5336], [35.626, 53.5383], [35.612, 53.5386], [35.6851, 53.5454], [35.7001, 53.5301], [35.6841, 53.5193], [35.7534, 53.5223], [35.7721, 53.506], [35.8225, 53.5876], [35.8753, 53.5963], [35.9253, 53.6524], [35.9545, 53.6471], [35.9606, 53.6252], [35.9912, 53.6263], [36.0033, 53.6598], [36.074, 53.6819], [36.0877, 53.7029], [36.0304, 53.712], [36.0288, 53.7262], [35.9585, 53.7185], [35.9584, 53.7519], [35.9335, 53.7528], [35.9206, 53.7664], [35.9155, 53.8145], [35.8052, 53.8076], [35.7999, 53.7811], [35.7059, 53.8306], [35.7025, 53.8517], [35.6675, 53.8662], [35.6366, 53.8579], [35.6366, 53.8843], [35.567, 53.903], [35.5027, 53.885], [35.4873, 53.89], [35.5081, 53.9029], [35.4916, 53.9048], [35.4848, 53.8813], [35.4027, 53.871], [35.4073, 53.8638], [35.3684, 53.873], [35.3783, 53.8876], [35.3552, 53.8871], [35.3118, 53.8325], [35.2586, 53.8353], [35.2442, 53.7484], [35.1587, 53.7174]],
     [[34.652, 53.4161], [34.6703, 53.4096], [34.6739, 53.3806], [34.8051, 53.3863], [34.8326, 53.3775], [34.8607, 53.3896], [34.8708, 53.3534], [34.8564, 53.3429], [34.9065, 53.3462], [34.8991, 53.3733], [35.0017, 53.37], [35.0244, 53.3614], [35.0251, 53.3369], [35.0843, 53.3248], [35.0745, 53.3088], [35.089, 53.296], [35.1541, 53.2772], [35.202, 53.291], [35.1886, 53.2804], [35.2384, 53.2804], [35.2557, 53.2899], [35.2398, 53.3275], [35.2668, 53.3191], [35.3062, 53.3348], [35.3836, 53.3374], [35.3842, 53.3976], [35.4638, 53.4181], [35.4658, 53.4329], [35.4392, 53.4351], [35.4403, 53.4442], [35.5285, 53.444], [35.544, 53.4568], [35.5373, 53.4356], [35.5016, 53.4222], [35.5402, 53.4346], [35.5469, 53.4695], [35.5846, 53.5117], [35.5357, 53.5141], [35.5573, 53.535], [35.5487, 53.5544], [35.4892, 53.5562], [35.4815, 53.5449], [35.5085, 53.5382], [35.5107, 53.5235], [35.4454, 53.5345], [35.4547, 53.5667], [35.4912, 53.5798], [35.4765, 53.5911], [35.4365, 53.5882], [35.3598, 53.537], [35.3415, 53.5376], [35.3385, 53.5611], [35.3179, 53.5564], [35.3409, 53.5819], [35.3198, 53.6051], [35.3326, 53.6184], [35.3202, 53.6457], [35.2571, 53.6379], [35.255, 53.6513], [35.1765, 53.6788], [35.1597, 53.7195], [35.0907, 53.7178], [35.1043, 53.6841], [35.0688, 53.6761], [35.0463, 53.6881], [35.0371, 53.6538], [34.9812, 53.6495], [34.9425, 53.5813], [34.9576, 53.5806], [34.9476, 53.5517], [34.9222, 53.5359], [34.8818, 53.5541], [34.7942, 53.533], [34.7729, 53.5197], [34.7847, 53.4971], [34.7647, 53.4978], [34.7336, 53.4578], [34.7129, 53.4606], [34.7084, 53.4287], [34.6697, 53.4349], [34.6769, 53.4263], [34.652, 53.4161]],
     [[34.6799, 53.446], [34.6815, 53.4417], [34.687, 53.4422], [34.6887, 53.4429], [34.691, 53.4455], [34.6958, 53.4467], [34.7069, 53.4473], [34.7064, 53.4481], [34.7096, 53.4501], [34.7091, 53.4511], [34.6999, 53.4506], [34.6993, 53.449], [34.6965, 53.4493], [34.6962, 53.4479], [34.6924, 53.4467], [34.6887, 53.4475], [34.6822, 53.4474], [34.6799, 53.446]],
     [[35.6116, 53.5262], [35.6779, 53.513], [35.6992, 53.4808], [35.662, 53.4677], [35.6959, 53.4685], [35.73, 53.4268], [35.7553, 53.428], [35.7622, 53.4178], [35.7755, 53.4295], [35.7947, 53.4185], [35.7673, 53.3752], [35.7997, 53.3574], [35.8471, 53.3529], [35.8228, 53.3408], [35.8466, 53.3177], [35.8175, 53.2717], [35.9347, 53.2426], [35.9566, 53.2529], [36.012, 53.2523], [36.0477, 53.2258], [36.0858, 53.2394], [36.0835, 53.2183], [36.1005, 53.2186], [36.1031, 53.2557], [36.1655, 53.2533], [36.1798, 53.2646], [36.1786, 53.2912], [36.2113, 53.3161], [36.2007, 53.325], [36.2459, 53.4493], [36.2773, 53.4618], [36.2913, 53.4472], [36.3401, 53.4375], [36.3849, 53.4495], [36.3717, 53.4678], [36.3158, 53.4765], [36.3236, 53.4997], [36.2879, 53.5176], [36.3008, 53.5365], [36.2892, 53.5534], [36.2317, 53.5445], [36.2268, 53.5613], [36.1739, 53.5394], [36.0607, 53.5734], [36.0305, 53.5603], [36.0158, 53.5731], [36.037, 53.6102], [35.9606, 53.6252], [35.9414, 53.6512], [35.9091, 53.6407], [35.8753, 53.5963], [35.8225, 53.5876], [35.7721, 53.506], [35.7534, 53.5223], [35.6841, 53.5193], [35.7001, 53.5301], [35.6851, 53.5454], [35.612, 53.5386], [35.626, 53.5383], [35.6116, 53.5262]]
    ]
   },
   "geometry_note": {
    "en": "Outline from OpenStreetMap (© OpenStreetMap contributors, ODbL), district boundaries (relations 1748968, 1748969, 1748986, 1453190, 1524022, 1102713, 1102711, 1102715, 1618112), simplified to about 0.8 km; whole districts, so the outline overstates the contaminated land",
    "ru": "Контур из OpenStreetMap (© участники OpenStreetMap, ODbL), границы районов (relations 1748968, 1748969, 1748986, 1453190, 1524022, 1102713, 1102711, 1102715, 1618112), упрощены; районы целиком, поэтому контур преувеличивает загрязнённую землю"
   },
   "sources": [
    {
     "url": "http://government.ru/docs/all/103736/",
     "title": "Government of the Russian Federation, decree No. 1074 of 8 Oct 2015: list of settlements within the Chernobyl radioactive-contamination zones",
     "kind": "primary"
    }
   ],
   "advice": "full"
  },
  {
   "id": "de-bavaria-wild-food-areas",
   "severity": "info",
   "advice": "mushrooms",
   "approximate": true,
   "name": {
    "en": "Bavarian areas where wild mushrooms can still exceed the caesium limit",
    "ru": "Баварские районы, где дикие грибы всё ещё могут превышать предел по цезию"
   },
   "contamination": {
    "en": "caesium-137 from the 1986 Chernobyl accident",
    "ru": "цезий-137 после Чернобыльской аварии 1986 года"
   },
   "status": {
    "en": "The German Federal Office for Radiation Protection (BfS, September 2024) names the Bavarian Forest and adjoining areas, the Donaumoos south-west of Ingolstadt, the Mittenwald region and the Berchtesgadener Land, where some mushroom species can still exceed the limit of 600 Bq/kg (the limit applies to mushrooms sold, not to those you pick yourself); moderate consumption is considered harmless everywhere in Germany.",
    "ru": "Федеральное ведомство по радиационной защите Германии (BfS, сентябрь 2024 года) называет Баварский Лес и прилегающие районы, Донаумос к юго-западу от Ингольштадта, район Миттенвальда и Берхтесгаденер-Ланд, где некоторые виды грибов всё ещё могут превышать предел 600 Бк/кг (предел действует для продаваемых грибов, а не для собранных самостоятельно); умеренное потребление считается безвредным везде в Германии."
   },
   "event": {
    "en": "Chernobyl accident, 1986",
    "ru": "Чернобыльская авария 1986 года"
   },
   "geometry": {
    "type": "polygons",
    "rings": [
     [[12.0933, 49.0647], [12.1101, 49.0226], [12.1853, 49.0073], [12.2188, 49.028], [12.2691, 49.0102], [12.3132, 49.0152], [12.3439, 48.998], [12.3358, 48.9765], [12.372, 48.9711], [12.4068, 48.9821], [12.4647, 48.9663], [12.4716, 48.9522], [12.4936, 48.9589], [12.5222, 48.9443], [12.5089, 48.9296], [12.5196, 48.911], [12.5673, 48.8977], [12.57, 48.8864], [12.6294, 48.9089], [12.6854, 48.9027], [12.7488, 48.8779], [12.7665, 48.8401], [12.7924, 48.8265], [12.8248, 48.8258], [12.8554, 48.8432], [12.9135, 48.8437], [12.9641, 48.8232], [13.0051, 48.7875], [13.0381, 48.7441], [13.0174, 48.7184], [13.0506, 48.7273], [13.0841, 48.7168], [13.0983, 48.7034], [13.0853, 48.687], [13.1124, 48.6842], [13.1188, 48.6631], [13.15, 48.6596], [13.2475, 48.6095], [13.3766, 48.5974], [13.422, 48.5744], [13.4915, 48.5746], [13.5173, 48.5906], [13.567, 48.562], [13.5998, 48.5694], [13.7271, 48.513], [13.7478, 48.5294], [13.7557, 48.565], [13.7701, 48.5536], [13.8059, 48.5798], [13.8013, 48.5974], [13.8272, 48.628], [13.8135, 48.6918], [13.8374, 48.7005], [13.7949, 48.7151], [13.8396, 48.7716], [13.8034, 48.7808], [13.8152, 48.7971], [13.7929, 48.8301], [13.7644, 48.8345], [13.7379, 48.886], [13.6714, 48.8801], [13.6225, 48.9388], [13.6304, 48.9479], [13.6102, 48.9386], [13.5801, 48.9707], [13.5071, 48.9691], [13.4978, 48.9413], [13.4262, 48.9725], [13.4027, 48.9872], [13.3974, 49.0507], [13.2892, 49.1186], [13.2361, 49.1137], [13.1828, 49.1345], [13.1709, 49.1736], [13.1099, 49.2031], [13.1142, 49.2183], [13.0862, 49.2291], [13.0808, 49.2474], [13.034, 49.2639], [13.0291, 49.3043], [13.0067, 49.3058], [13.0105, 49.284], [12.933, 49.286], [12.9419, 49.2637], [12.9282, 49.2444], [12.8909, 49.2589], [12.858, 49.2516], [12.8567, 49.2785], [12.8297, 49.2846], [12.7875, 49.2535], [12.6662, 49.2153], [12.6399, 49.2307], [12.5916, 49.2141], [12.5323, 49.228], [12.5262, 49.2071], [12.4959, 49.1935], [12.5005, 49.1823], [12.4785, 49.1764], [12.3216, 49.1862], [12.264, 49.2068], [12.1887, 49.2109], [12.1763, 49.2233], [12.1436, 49.1557], [12.1546, 49.1467], [12.1183, 49.1256], [12.1066, 49.0997], [12.1182, 49.0862], [12.0933, 49.0647]],
     [[12.6958, 47.6822], [12.7327, 47.6796], [12.7572, 47.663], [12.7841, 47.6715], [12.7586, 47.6516], [12.8245, 47.6121], [12.7929, 47.6006], [12.7791, 47.5791], [12.8039, 47.5501], [12.8477, 47.546], [12.8517, 47.5308], [12.9087, 47.4969], [12.9682, 47.4745], [12.978, 47.4847], [13.001, 47.464], [13.0476, 47.4922], [13.0473, 47.5215], [13.0309, 47.5326], [13.0575, 47.5621], [13.0437, 47.5834], [13.0706, 47.587], [13.0626, 47.6015], [13.0989, 47.6352], [13.0807, 47.687], [13.0459, 47.7127], [13.0105, 47.7229], [12.9872, 47.7074], [12.9282, 47.7098], [12.9053, 47.7234], [12.9448, 47.7644], [12.9296, 47.773], [13.0041, 47.847], [12.9173, 47.955], [12.8759, 47.9626], [12.8758, 47.9372], [12.8485, 47.9367], [12.8543, 47.9024], [12.8865, 47.888], [12.8751, 47.8767], [12.7714, 47.8915], [12.738, 47.8712], [12.7283, 47.8398], [12.7441, 47.8064], [12.764, 47.8042], [12.7731, 47.7881], [12.8324, 47.7835], [12.8486, 47.7549], [12.7947, 47.7562], [12.7663, 47.7366], [12.7195, 47.7345], [12.7167, 47.698], [12.6958, 47.6822]],
     [[12.7474, 47.8877], [12.7502, 47.8856], [12.7522, 47.8863], [12.752, 47.889], [12.7559, 47.891], [12.7562, 47.8928], [12.7545, 47.8913], [12.748, 47.8897], [12.7474, 47.8877]],
     [[11.1567, 47.4344], [11.162, 47.4218], [11.25, 47.4323], [11.2223, 47.3973], [11.2699, 47.3976], [11.2901, 47.4073], [11.291, 47.4271], [11.3386, 47.4499], [11.4214, 47.4449], [11.4094, 47.4667], [11.3838, 47.4722], [11.41, 47.4958], [11.3346, 47.532], [11.3155, 47.5284], [11.2818, 47.4939], [11.27, 47.5001], [11.2358, 47.4753], [11.1969, 47.4727], [11.1942, 47.4441], [11.1647, 47.4443], [11.1567, 47.4344]],
     [[11.2538, 48.6811], [11.2447, 48.6659], [11.2575, 48.6495], [11.2831, 48.6609], [11.3069, 48.6519], [11.3447, 48.6698], [11.321, 48.6838], [11.323, 48.7007], [11.2825, 48.7055], [11.2468, 48.6882], [11.2538, 48.6811]]
    ]
   },
   "geometry_note": {
    "en": "Outline from OpenStreetMap (© OpenStreetMap contributors, ODbL), the Bayerischer Wald region (relation 611246), Landkreis Berchtesgadener Land (62712), Mittenwald (939341) and Karlshuld (943728), simplified; the BfS names the Donaumoos only as 'south-west of Ingolstadt', so the municipality of Karlshuld at its centre stands for it",
    "ru": "Контур из OpenStreetMap (© участники OpenStreetMap, ODbL), регион Bayerischer Wald (relation 611246), Landkreis Berchtesgadener Land (62712), Mittenwald (939341) и Karlshuld (943728), упрощены; BfS называет Донаумос лишь «к юго-западу от Ингольштадта», поэтому его заменяет община Карлсхульд в его центре"
   },
   "sources": [
    {
     "url": "https://www.bfs.de/SharedDocs/Pressemitteilungen/BfS/DE/2024/013.html",
     "title": "BfS press release of 10 Sep 2024: radioactive caesium in wild mushrooms — the amount eaten matters",
     "kind": "primary"
    }
   ]
  },
  {
   "id": "ru-yenisei-mcc-floodplain",
   "severity": "caution",
   "approximate": true,
   "name": {
    "en": "Yenisei floodplain downstream of the Zheleznogorsk Mining and Chemical Combine",
    "ru": "Пойма Енисея ниже Горно-химического комбината (Железногорск)"
   },
   "contamination": {
    "en": "artificial radionuclides from the combine's reactors and radiochemical plant, including radioactive particles",
    "ru": "искусственные радионуклиды реакторов и радиохимического завода комбината, в том числе радиоактивные частицы"
   },
   "status": {
    "en": "The combine, 60 km downstream from Krasnoyarsk, has operated for about 60 years and has contaminated the downstream floodplain; radioactive particles were found in sediments from near the combine to more than 800 km downstream (Scientific Reports, 2017).",
    "ru": "Комбинат в 60 км ниже Красноярска работает около 60 лет и загрязнил пойму ниже по течению; радиоактивные частицы найдены в отложениях от района комбината до расстояния более 800 км вниз по течению (Scientific Reports, 2017)."
   },
   "event": {
    "en": "discharges of the Mining and Chemical Combine",
    "ru": "сбросы Горно-химического комбината"
   },
   "geometry": {
    "type": "buffered_polyline",
    "lines": [
     [[93.5264, 56.3085], [93.5383, 56.309], [93.5551, 56.3131], [93.5641, 56.316], [93.5688, 56.3186], [93.5751, 56.324], [93.5789, 56.3337], [93.5799, 56.361], [93.5812, 56.3659], [93.584, 56.3711], [93.5873, 56.3742], [93.5992, 56.382], [93.6199, 56.3934], [93.629, 56.3966], [93.6758, 56.4021], [93.6866, 56.4046], [93.6921, 56.4073], [93.6975, 56.4129], [93.6991, 56.4207], [93.6857, 56.4452], [93.6727, 56.465], [93.6718, 56.4699], [93.6739, 56.475], [93.684, 56.4821], [93.7296, 56.5032], [93.7431, 56.5085], [93.776, 56.5189], [93.7828, 56.5241], [93.7833, 56.5292], [93.7812, 56.5351], [93.7726, 56.5425], [93.7683, 56.5504], [93.7702, 56.5743], [93.7597, 56.5998], [93.741, 56.6282], [93.7032, 56.6435], [93.6912, 56.6501], [93.6446, 56.6852], [93.6258, 56.6965], [93.6209, 56.7026], [93.6196, 56.7064], [93.6188, 56.7192], [93.6175, 56.7217], [93.6155, 56.7233], [93.5959, 56.7321], [93.5901, 56.7372], [93.5872, 56.7458], [93.5882, 56.7522], [93.5909, 56.7557], [93.6113, 56.7719], [93.6148, 56.7763], [93.6168, 56.7812], [93.6166, 56.7855], [93.614, 56.7899], [93.61, 56.7931], [93.603, 56.7966], [93.5916, 56.7997], [93.5722, 56.8012], [93.5544, 56.8002], [93.546, 56.8004], [93.5347, 56.8016], [93.5121, 56.8064], [93.4595, 56.8198], [93.4546, 56.8221], [93.452, 56.8248], [93.4434, 56.8638], [93.4435, 56.8784], [93.4417, 56.8891], [93.4349, 56.8997], [93.4305, 56.9043], [93.425, 56.9086], [93.4081, 56.9182], [93.402, 56.9254], [93.3863, 56.9521], [93.3671, 56.9887], [93.3657, 56.9993], [93.3665, 57.0057]]
    ],
    "half_width_km": 2.0
   },
   "geometry_note": {
    "en": "Outline from OpenStreetMap (© OpenStreetMap contributors, ODbL), relation 181988 (the Yenisei), the main channel from the vertex nearest to Zheleznogorsk about 100 km downstream, simplified; the source reports contamination far beyond that stretch, so only the first 100 km are outlined; the half-width of 2 km is an assumption for the floodplain",
    "ru": "Контур из OpenStreetMap (© участники OpenStreetMap, ODbL), relation 181988 (Енисей), основное русло от вершины, ближайшей к Железногорску, примерно на 100 км вниз по течению, упрощено; источник сообщает о загрязнении гораздо дальше, поэтому оконтурены только первые 100 км; полуширина 2 км — допущение для поймы"
   },
   "sources": [
    {
     "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC5593899/",
     "title": "Unique diversity of radioactive particles found in the Yenisei River floodplain, Scientific Reports 7:11132 (2017)",
     "kind": "primary"
    }
   ],
   "advice": "full"
  },
  {
   "id": "no-wild-mushroom-municipalities",
   "severity": "info",
   "advice": "mushrooms",
   "approximate": true,
   "name": {
    "en": "Norwegian mountain municipalities with the highest caesium in wild mushrooms",
    "ru": "Горные коммуны Норвегии с самым высоким содержанием цезия в диких грибах"
   },
   "contamination": {
    "en": "caesium-137 from the 1986 Chernobyl accident",
    "ru": "цезий-137 после Чернобыльской аварии 1986 года"
   },
   "status": {
    "en": "The Norwegian Radiation and Nuclear Safety Authority (DSA, report 2/2026) finds the highest caesium levels in wild mushrooms from the most contaminated areas of Innlandet, Trøndelag and Nordland (2017–2025: up to 17 000 Bq/kg in gypsy mushroom from Øystre Slidre, 12 000 Bq/kg in another edible species from Lierne) and no clear decline over the last decade. It advises against taking in more than 80 000 Bq of caesium a year, which concerns people who eat very large amounts of wild food from the hard-hit areas; the national limits were removed in 2025.",
    "ru": "Норвежское управление радиационной и ядерной безопасности (DSA, доклад 2/2026) находит самое высокое содержание цезия в диких грибах из наиболее загрязнённых районов Иннландета, Трёнделага и Нурланна (в 2017–2025 годах до 17 000 Бк/кг в колпаке кольчатом (норв. rimsopp) из Эйстре-Слидре, 12 000 Бк/кг в другом съедобном виде из Лирне) и не видит явного снижения за последнее десятилетие. Оно советует не получать более 80 000 Бк цезия в год, что касается людей, которые едят очень много дикой пищи из сильно пострадавших районов; национальные пределы отменены в 2025 году."
   },
   "event": {
    "en": "Chernobyl accident, 1986",
    "ru": "Чернобыльская авария 1986 года"
   },
   "geometry": {
    "type": "polygons",
    "rings": [
     [[8.7215, 61.3987], [8.8271, 61.3364], [8.8253, 61.2892], [8.7994, 61.2944], [8.7457, 61.2674], [8.7677, 61.2516], [8.8, 61.2535], [8.8239, 61.2327], [8.8526, 61.2351], [8.8978, 61.2066], [8.8791, 61.1677], [9.0125, 61.1527], [9.0062, 61.1182], [9.0681, 61.0904], [9.069, 61.0755], [9.1703, 61.0509], [9.3743, 61.0946], [9.4197, 61.1272], [9.4219, 61.1761], [9.466, 61.2407], [9.3009, 61.2925], [9.2949, 61.3133], [9.1914, 61.3547], [9.1932, 61.3416], [9.1732, 61.3434], [9.1424, 61.3673], [9.0162, 61.4066], [8.7806, 61.4508], [8.7215, 61.3987]],
     [[9.1121, 61.7183], [9.1382, 61.675], [9.115, 61.5919], [9.2112, 61.5604], [9.2943, 61.5859], [9.4011, 61.6492], [9.4374, 61.6383], [9.5552, 61.6705], [9.7464, 61.8249], [9.9254, 61.8333], [10.0155, 61.8844], [9.8044, 61.9123], [9.6659, 61.9132], [9.6245, 61.9483], [9.5774, 61.9574], [9.3689, 61.8863], [9.3158, 61.8891], [9.292, 61.8469], [9.3768, 61.832], [9.3834, 61.8217], [9.415, 61.8276], [9.4309, 61.8155], [9.3312, 61.7751], [9.2482, 61.7957], [9.2018, 61.7936], [9.2059, 61.776], [9.1195, 61.756], [9.1121, 61.7183]],
     [[9.0103, 62.0472], [9.015, 62.0176], [9.1069, 61.9593], [9.1654, 61.9457], [9.2173, 61.9105], [9.3158, 61.8891], [9.3689, 61.8863], [9.5774, 61.9574], [9.6245, 61.9483], [9.6659, 61.9132], [9.8482, 61.9038], [9.8702, 61.9495], [9.8388, 62.0134], [9.8764, 62.0405], [9.9267, 62.0466], [9.9141, 62.0667], [9.866, 62.095], [9.7652, 62.1232], [9.6508, 62.1393], [9.5838, 62.1846], [9.612, 62.199], [9.6438, 62.1969], [9.7309, 62.2651], [9.7925, 62.2879], [9.6019, 62.2557], [9.4839, 62.2923], [9.2127, 62.3431], [9.3192, 62.2532], [9.2874, 62.1964], [9.0943, 62.1266], [9.0789, 62.1116], [9.1078, 62.1053], [9.104, 62.0892], [9.0576, 62.0516], [9.0103, 62.0472]],
     [[9.5838, 62.1846], [9.6508, 62.1393], [9.7652, 62.1232], [9.866, 62.095], [9.9122, 62.0685], [9.928, 62.0475], [9.8764, 62.0405], [9.8388, 62.0134], [9.8702, 61.9495], [9.8482, 61.9038], [10.0155, 61.8844], [10.0134, 61.9101], [10.0861, 61.9066], [10.1317, 61.9495], [10.1626, 61.9515], [10.1221, 61.9716], [10.1657, 62.0416], [10.3916, 62.1967], [10.334, 62.2415], [10.339, 62.2884], [10.223, 62.3229], [10.2402, 62.376], [10.1661, 62.3911], [10.1655, 62.4034], [10.1058, 62.4006], [10.0976, 62.4278], [9.9518, 62.3972], [9.9342, 62.3552], [9.9003, 62.3444], [9.8393, 62.3621], [9.8214, 62.3428], [9.8548, 62.331], [9.8336, 62.3287], [9.8273, 62.2992], [9.7309, 62.2651], [9.6438, 62.1969], [9.612, 62.199], [9.5838, 62.1846]],
     [[13.0695, 64.4338], [13.1263, 64.3529], [13.2176, 64.3127], [13.248, 64.253], [13.2111, 64.0954], [13.7154, 64.0463], [13.9675, 64.008], [14.1571, 64.1951], [14.1139, 64.4625], [14.0852, 64.4782], [13.8912, 64.5071], [13.6543, 64.5803], [13.9313, 64.8221], [13.5267, 64.7655], [13.3767, 64.7265], [13.3847, 64.6973], [13.3334, 64.6669], [13.2673, 64.5884], [13.091, 64.503], [13.0695, 64.4338]],
     [[11.2719, 63.0038], [11.464, 62.9751], [11.5053, 62.9228], [11.5809, 62.88], [11.781, 62.8949], [11.8079, 62.8292], [12.1364, 62.7479], [12.0747, 62.9025], [12.2182, 63.0003], [12.0525, 63.1834], [11.932, 63.1942], [11.6308, 63.1807], [11.6318, 63.1446], [11.4862, 63.1113], [11.4345, 63.1135], [11.4148, 63.1021], [11.3712, 63.1099], [11.2719, 63.0038]],
     [[13.6256, 65.7239], [13.6865, 65.6253], [13.7409, 65.5982], [13.7228, 65.5764], [13.769, 65.5546], [13.7137, 65.5231], [13.8073, 65.5137], [13.8766, 65.4871], [13.823, 65.4505], [13.8338, 65.4235], [13.8638, 65.4148], [13.8412, 65.3988], [13.7874, 65.3932], [13.7952, 65.3328], [13.76, 65.3158], [13.817, 65.2955], [13.7817, 65.2632], [13.8728, 65.2574], [13.7961, 65.229], [13.7964, 65.2092], [13.7106, 65.1607], [13.6611, 65.1083], [14.0122, 65.1295], [14.0639, 65.122], [14.1643, 65.1392], [14.2525, 65.1314], [14.2967, 65.1151], [14.326, 65.1189], [14.3788, 65.2476], [14.5068, 65.3097], [14.4988, 65.5213], [14.5415, 65.7008], [14.6255, 65.8118], [14.6023, 65.8622], [14.3733, 65.8617], [14.3064, 65.8916], [14.1584, 65.8561], [14.1626, 65.8357], [14.0817, 65.7849], [14.0066, 65.7763], [13.9416, 65.7853], [13.8708, 65.7658], [13.8298, 65.7844], [13.7937, 65.7837], [13.7808, 65.7711], [13.6746, 65.7643], [13.6256, 65.7239]]
    ]
   },
   "geometry_note": {
    "en": "Outline from OpenStreetMap (© OpenStreetMap contributors, ODbL), municipalities Øystre Slidre (relation 412431), Sel (412411), Dovre (412408), Folldal (412547), Lierne (407217), Tydal (406502) and Hattfjelldal (408200), simplified; these are the municipalities of the three counties where DSA samples mushrooms and that the report singles out as most contaminated or names among its sampling sites, whole municipalities; Orkland, also sampled, is not outlined because the report does not single it out",
    "ru": "Контур из OpenStreetMap (© участники OpenStreetMap, ODbL), коммуны Øystre Slidre (relation 412431), Sel (412411), Dovre (412408), Folldal (412547), Lierne (407217), Tydal (406502) и Hattfjelldal (408200), упрощены; это коммуны трёх фюльке, где DSA берёт пробы грибов, которые доклад выделяет как самые загрязнённые или называет среди пунктов отбора, коммуны целиком; Orkland, где тоже берутся пробы, не оконтурена, потому что доклад её не выделяет"
   },
   "sources": [
    {
     "url": "https://www.dsa.no/publikasjoner/radioaktivitet-i-norsk-mat/DSA-rapport%2002-2026%20Radioaktivitet%20i%20norsk%20mat.pdf",
     "title": "DSA report 2/2026: Radioaktivitet i norsk mat, results of the food monitoring 2017–2025",
     "kind": "primary"
    }
   ]
  }
 ]
}
```

Create `skills/osm-day-route-day-plan/data/README.md`:

````markdown
# Radiation registry (`radiation_zones.json`)

A hand-curated list of contaminated or closed zones, read by
`scripts/day_plan/radiation.py`. It is static: nothing here is fetched at run time.

## Entry format

```json
{
  "id": "unique-slug",
  "severity": "danger | caution | info",
  "advice": "full | mushrooms",
  "approximate": true,
  "name": {"en": "...", "ru": "..."},
  "contamination": {"en": "...", "ru": "..."},
  "status": {"en": "...", "ru": "..."},
  "event": {"en": "short: Chernobyl accident, 1986", "ru": "..."},
  "geometry": {"type": "polygons", "rings": [[[lon, lat], "..."]]},
  "geometry_note": {"en": "...", "ru": "..."},
  "sources": [{"url": "https://...", "title": "...", "kind": "primary | secondary"}]
}
```

- `severity`: `danger` for land that is closed or heavily contaminated (a route
  entering it raises a danger warning); `caution` for a wider affected area
  (a caution warning); `info` for an advisory area (an info line only, and
  only when the route is inside it).
- `advice`: `full` (no mushrooms or berries, no natural water, no dust or open
  fires, wind and wildfire) or `mushrooms` (moderation and local advice, for
  advisory areas such as the Bavarian mushroom areas). `danger` zones need
  `full`, `info` zones use `mushrooms`.
- Geometry is one of `polygons` (a list of closed outer rings), `circle`
  (`center` `[lon, lat]`, `radius_km`) or `buffered_polyline` (`lines`,
  `half_width_km`). Coordinates are `[longitude, latitude]`.
- `scope.boxes` (in the file's header) are the rectangles the registry is meant
  to cover; a route outside all of them gets no radiation part.
- `approximate` is true whenever the shape is not a published outline; the
  `geometry_note` then says how it was made. It is required for approximate
  zones and shown to the reader.
- `status` and `contamination` say only what the sources say. Every entry needs
  at least one source, and one `primary` (an official, scientific or
  regulatory document) for a zone that raises a warning.
- Outlines taken from OpenStreetMap are simplified (Douglas–Peucker, a few
  hundred metres) and credited in `geometry_note` (ODbL).
- `tests/test_radiation_registry.py` validates every entry and pins where
  each zone must lie; add the new zone's box and a known inside/outside point
  there.

## Provenance of the shipped zones

| id | geometry | sources read for this entry |
|---|---|---|
| `ural-eurt-core` | OSM way 256825533 (East Ural reserve) | NRPA Bulletin 8-07 (about 180 km² still off-limits); Wikipedia (not open to the public) |
| `ural-eurt-trace` | centre line through Bagaryak, Kamensk-Uralsky and the area between Bogdanovich and Kamyshlov (the settlements named on the NRPA figure), starting 25 km downwind of Mayak (the outline has round ends) and spanning 300 km from Mayak, half-width 25 km | NRPA Bulletin 8-07 (300 km long, 30–50 km wide, 23 communities evacuated) |
| `ural-techa-river` | OSM relation 2124164 (waterway) plus ways 1104519187, 125750492, 786464969 upstream of its west end, half-width 1.5 km; the reservoir cascade is not outlined | NRPA Report 2008:3 (floodplain 240 km², 80 km² above 3.7×10¹⁰ Bq/km²) |
| `ural-mayak-site` | circle at 55°44′N 60°54′E, r = 6 km | NRPA Report 2008:3 (site about 90 km²) |
| `ural-karachay` | circle at 55.6783°N 60.7997°E (Wikipedia), r = 3 km assumed | NRPA Report 2008:3 (1967 dispersal); Wikipedia |
| `ua-chernobyl-exclusion-zone` | OSM relation 3311547 | IAEA/UIAR presentation (evacuated in 1986, 2 122 km²) |
| `by-polesie-reserve` | OSM relation 3397849 | Order No. 39 of the Belarus Ministry for Emergency Situations, 1995 (FAOLEX) |
| `ru-bryansk-contaminated-districts` | OSM boundaries of seven districts | Radiation Hygiene 2023;16(4):55-63 (districts, mushrooms up to 75–82 % of the internal dose); Government decree No. 1074 of 8 Oct 2015 |
| `kz-semipalatinsk-test-site` | OSM way 932505322 (boundary=hazard) | National Nuclear Center of Kazakhstan, radioecological surveys |
| `ru-central-chernobyl-districts` | OSM boundaries of nine districts (Tula: Arsenyevsky, Belevsky, Plavsky, Chernsky, Shchekinsky; Kaluga: Zhizdra, Ulyanovo, Khvastovichi; Orel: Bolkhov) | Government decree No. 1074 of 8 Oct 2015 (the list itself, read at government.ru: zone of residence with the right to resettle) |
| `de-bavaria-wild-food-areas` | OSM: Bayerischer Wald region, Landkreis Berchtesgadener Land, Mittenwald, Karlshuld (stands for the Donaumoos) | BfS press release of 10 Sep 2024 (regions, 600 Bq/kg, moderate consumption harmless) |
| `no-wild-mushroom-municipalities` | OSM boundaries of seven municipalities (Innlandet: Øystre Slidre, Sel, Dovre, Folldal; Trøndelag: Lierne, Tydal; Nordland: Hattfjelldal); Orkland is sampled too but not singled out, so it is not outlined | DSA report 2/2026 (April 2026): highest caesium in wild mushrooms from the most contaminated areas of Innlandet, Trøndelag and Nordland, 17 000 Bq/kg at Øystre Slidre, no clear decline, advice 80 000 Bq a year |
| `ru-yenisei-mcc-floodplain` | OSM relation 181988 (Yenisei), main channel, first 100 km below the vertex nearest to Zheleznogorsk, half-width 2 km assumed | Scientific Reports 7:11132 (2017): floodplain contaminated, particles from the combine to more than 800 km downstream |

## Researched and not added

| Candidate | What the sources say | Why it is not in the registry |
|---|---|---|
| Totskoye 1954 (52°38′N 52°48′E) | Read (abstracts; the full texts sit behind publishers): Dubasov et al., Radium Institute, Radiochemistry 46(6), 2004 — soil plutonium has the isotopic composition of global fallout, so either no long-lived fission products from the 1954 explosion or levels within the fluctuations of global fallout; induced cobalt-60 and europium-152 only at the epicentre. Boev et al. (Orenburg, 1994 data, 1996 symposium) — plutonium in topsoil 5–20 times background, strontium and caesium 1.5 times; Gig. Sanit. 1998 — caesium higher than in a control area. | The studies disagree, give no absolute levels or area, and the largest excess of caesium is a factor of 1.5: no basis for a warning or an outline. |
| Novaya Zemlya | IAEA reference (read): raised dose rates only on small plots in three test areas (Chernaya Bay, Matochkin Shar, Sukhoy Nos); elsewhere caesium-137 about 3.3 kBq/m², the regional background. | Local plots of at most about 1 km² without published coordinates; the archipelago is a closed test site, which is an access note (`people_hazards`), not a contamination zone. |
| Seversk (Tomsk-7), 1993 | IAEA report (read): the area above 0.2 µGy/h fell from 30 km² in May 1993 to nothing by January 1994. | No lasting outline. |
| Peaceful underground explosions (Taiga 61.30°N 56.60°E, Kraton-3 65°N 112°E, Crystal 66.8°N 113.9°E, Globus-1 in the Ivanovo region) | Sites and local raised dose rates appear in search results and news (for Kraton-3 0.5–1.4 µSv/h in places against 0.08 in the forest); the survey papers were not read. | No published extents; read the surveys first. |
| Sweden and Finland | The Swedish National Food Agency (search result and press release) says berries, mushrooms and game can be eaten throughout Sweden without a health risk from caesium, levels being generally low; STUK (Finland, search results) puts Chernobyl food contamination at under 1 % of the average annual dose. | The authorities themselves see no need for an advisory; not added. |
| Peaceful explosions, measured | Ramzaev et al., J. Environ. Radioact. 92 (2007): caesium-137 at the Crystal site (Yakutia) 1.3–64 kBq/m², at Kraton-3 1.7–6900 kBq/m² (the maximum on a decontaminated plot) against a background of about 0.84 kBq/m². | Confirms real local contamination, but the paper gives no extents or coordinates of the plots; no outline. |
| Sellafield, La Hague, Andreeva Bay, Wismut, Jáchymov, Balkan depleted uranium | Not researched. | Operating or closed facilities and point hazards (radon in mine workings, penetrator fragments): access notes rather than land-contamination zones. |
````

- [ ] **Step 4: Run the whole suite** — `cd skills/osm-day-route-day-plan && python3 -m pytest tests -q` (all green), and for the show skill `cd skills/osm-day-route-show && python3 -m pytest tests -q`.

- [ ] **Step 5: Commit**

```bash
git add skills README.md
git commit -m "Radiation registry: thirteen researched zones, validation and route search

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

### Task 4: The Radiation hazard plugin

`RadiationPlugin` reports the zones the route or its points are inside (warning `danger` for a closed or heavily contaminated zone, `caution` for a wider affected area, `info` for an advisory area such as the Bavarian mushroom areas, which is reported only when the route is inside it) or near (`caution` / `info`), with the four advisories (or, for advisory-only zones, the single moderation advice) (no mushrooms or berries, springs and streams may be contaminated, avoid dust and open fires, wind and wildfire), a suggestion to replan when a danger zone is entered, sources, the approximate-outline note and the OpenStreetMap credit. Its warnings are pinned. No hit is "no entry in the registry", never "safe"; a route outside the registry's area (boxes for Europe, Siberia, the Far East north of 49 N and Primorye; not China, Mongolia, Japan or Korea) gets no radiation part. It needs neither the network nor another plugin.

**Files:**
- Create: `skills/osm-day-route-day-plan/tests/test_radiation.py`
- Create: `skills/osm-day-route-day-plan/scripts/day_plan/plugins/radiation.py`

- [ ] **Step 1: Add the tests** (18 tests in the file(s) below)

Create `skills/osm-day-route-day-plan/tests/test_radiation.py`:

```python
import datetime

from day_plan.context import build_context
from day_plan.plugins.radiation import RadiationPlugin

DATE = datetime.date(2026, 7, 4)
CROSSING = ((29.0, 51.3, 150.0), (31.0, 51.3, 150.0))              # crosses the Chernobyl zone, both ends outside
BRYANSK = ((31.90, 52.54, 150.0), (31.95, 52.56, 150.0))
NEAR_CHERNOBYL = ((30.3851, 51.0634, 120.0), (30.3861, 51.0634, 120.0))    # about 2.2 km south of the zone
MADRID = ((-3.75, 40.42, 650.0), (-3.74, 40.43, 660.0))
SYDNEY = ((151.20, -33.86, 20.0), (151.21, -33.85, 25.0))
BEIJING = ((116.39, 39.90, 50.0), (116.41, 39.92, 50.0))
BAVARIAN_FOREST = ((13.35, 48.85, 700.0), (13.42, 48.88, 900.0))
NEAR_BAVARIAN_AREA = ((12.08, 49.075, 500.0), (12.081, 49.076, 500.0))     # about 1.5 km outside a Bavarian area
TULA = ((37.50, 54.00, 200.0), (37.55, 54.02, 210.0))
KYSHTYM = ((60.50, 55.70, 250.0), (60.62, 55.74, 255.0), (60.85, 55.80, 260.0))     # the reserve, Mayak and the trace


def run(make_route, fixed_now, coords, lang="en", folder="route", points=None, make_route_with_points=None):
    if points is not None:
        route_dir = make_route_with_points(points, coords=coords, folder=folder)
    else:
        route_dir = make_route(coords=coords, folder=folder)
    ctx = build_context(route_dir, DATE, lang=lang, http=lambda u: {}, now=fixed_now)
    return RadiationPlugin().run(ctx, {})


def test_a_route_crossing_a_closed_zone_gets_a_pinned_danger_and_the_four_advisories(make_route, fixed_now):
    section = run(make_route, fixed_now, CROSSING)
    md = section.markdown
    assert "Chernobyl exclusion zone (Ukraine)** (danger zone): the route or one of its points is inside the zone." in md
    assert "- Do not pick mushrooms or berries." in md
    assert "Springs, streams and other natural water may be contaminated: do not drink from them or collect water." in md
    assert "Avoid dust and open fires on the soil" in md and "Wind and wildfire lift contaminated dust and smoke" in md
    assert "Consider changing the route (osm-day-route-planning)" in md
    danger = [w for w in section.warnings if w.severity == "danger" and "Chernobyl exclusion zone" in w.text]
    assert danger and danger[0].pinned and "Do not pick mushrooms or berries" in danger[0].text
    assert section.confidence == "tag-backed" and section.omit is False
    assert "https://www.iaea.org/sites/default/files/21/07/_t1_02_kashparov_ukraine.pdf" in section.sources


def test_the_neighbouring_reserve_is_reported_as_near_with_its_distance(make_route, fixed_now):
    section = run(make_route, fixed_now, CROSSING)
    assert "Polesie State Radioecological Reserve (Belarus)** (danger zone): the route passes about 0.9 km from the zone." \
        in section.markdown
    assert any(w.severity == "caution" and "about 0.9 km from Polesie" in w.text for w in section.warnings)


def test_a_near_miss_is_a_caution_not_a_danger(make_route, fixed_now):
    section = run(make_route, fixed_now, NEAR_CHERNOBYL)
    assert [w.severity for w in section.warnings] == ["caution"] and section.warnings[0].pinned
    assert "passes about 2.2 km from the zone" in section.markdown
    assert "Consider changing the route" not in section.markdown          # only when a danger zone is entered


def test_an_affected_area_is_a_caution_inside_and_an_info_when_only_near(make_route, fixed_now):
    inside = run(make_route, fixed_now, BRYANSK)
    assert "(affected area): the route or one of its points is inside the zone" in inside.markdown
    assert [w.severity for w in inside.warnings] == ["caution"]
    assert "Only some settlements of each district are listed." in inside.markdown
    assert "Approximate outline:" in inside.markdown and "whole districts" in inside.markdown
    assert "Zone outlines from OpenStreetMap" in inside.markdown


def test_an_advisory_area_gets_an_info_line_and_only_the_mushroom_advice(make_route, fixed_now):
    section = run(make_route, fixed_now, BAVARIAN_FOREST)
    md = section.markdown
    assert "(advisory area): the route or one of its points is inside the zone" in md
    assert "moderate consumption is considered harmless everywhere in Germany" in md
    assert "- Wild mushrooms and game from these areas can still carry caesium-137: eat them in moderation" in md
    assert "Springs, streams" not in md and "Do not pick mushrooms or berries." not in md
    assert [(w.severity, w.pinned) for w in section.warnings] == [("info", False)]
    assert "Consider changing the route" not in md and section.confidence == "tag-backed"
    assert "https://www.bfs.de/SharedDocs/Pressemitteilungen/BfS/DE/2024/013.html" in section.sources


def test_the_norwegian_mountain_municipalities_are_an_info_line_with_the_dsa_source(make_route, fixed_now):
    section = run(make_route, fixed_now, ((8.90, 61.24, 900.0), (8.93, 61.26, 950.0)), folder="no")
    assert "Norwegian mountain municipalities with the highest caesium in wild mushrooms** (advisory area)" in section.markdown
    assert "80 000 Bq of caesium a year" in section.markdown and [w.severity for w in section.warnings] == ["info"]
    assert any("dsa.no/publikasjoner/radioaktivitet-i-norsk-mat" in u for u in section.sources)
    assert section.confidence == "tag-backed"


def test_being_near_an_advisory_area_says_nothing_but_tells_the_truth(make_route, fixed_now):
    section = run(make_route, fixed_now, NEAR_BAVARIAN_AREA, folder="near")
    assert section.warnings == []
    assert section.markdown.startswith(
        "- No danger zone or affected area of the radiation registry lies within 3 km of the route or its points.")
    assert "so no entry does not mean the land is clean" in section.markdown and "safe" not in section.markdown.lower()
    assert "No zone of the radiation registry" not in section.markdown


def test_the_advisory_wording_is_translated(make_route, fixed_now):
    section = run(make_route, fixed_now, NEAR_BAVARIAN_AREA, lang="ru", folder="nearru")
    assert section.markdown.startswith("- Ни опасная зона, ни затронутая территория реестра радиации не лежат в радиусе 3 км")


def test_a_route_inside_an_advisory_area_alone_gets_no_full_advice(make_route, fixed_now):
    section = run(make_route, fixed_now, ((13.0, 48.9, 500.0), (13.4, 48.9, 500.0)), folder="mixed")
    assert "(advisory area)" in section.markdown       # the Bavarian Forest
    assert "Wild mushrooms and game from these areas" in section.markdown and "Springs, streams" not in section.markdown


def test_a_small_near_miss_reads_in_tenths_of_a_kilometre(make_route, fixed_now):
    section = run(make_route, fixed_now, ((30.3851, 51.0805, 120.0), (30.3861, 51.0805, 120.0)), folder="tenth")
    near = [w.text for w in section.warnings if "about" in w.text]
    assert len(near) == 1 and near[0].startswith("The route passes about 0.3 km from ")
    assert "about 0 km" not in near[0]


def test_central_russian_districts_are_a_caution_with_the_decree_as_source(make_route, fixed_now):
    section = run(make_route, fixed_now, TULA)
    assert "Tula, Kaluga and Orel districts with Chernobyl-contaminated settlements** (affected area)" in section.markdown
    assert "decree No. 1074 of 2015" in section.markdown and [w.severity for w in section.warnings] == ["caution"]
    assert "http://government.ru/docs/all/103736/" in section.sources and "Only some settlements of each district" in section.markdown


def test_a_route_with_no_hit_says_no_entry_not_safe(make_route, fixed_now):
    section = run(make_route, fixed_now, MADRID)
    assert section.omit is False and section.warnings == [] and section.confidence == "derived"
    assert section.markdown.startswith("- No zone of the radiation registry lies within 3 km of the route or its points.")
    assert "so no entry does not mean the land is clean" in section.markdown and "safe" not in section.markdown.lower()


def test_a_route_far_outside_the_registry_area_gets_no_radiation_part(make_route, fixed_now):
    for coords, folder in ((SYDNEY, "syd"), (BEIJING, "bei")):
        section = run(make_route, fixed_now, coords, folder=folder)
        assert section.omit is True and section.markdown == "" and section.warnings == []


def test_a_point_off_the_track_inside_a_zone_counts(make_route, make_route_with_points, fixed_now):
    section = run(make_route, fixed_now, ((40.0, 55.0, 150.0), (40.1, 55.0, 150.0)), folder="p",
                  points=[("Spring", "spring", 30.099, 51.389, {})], make_route_with_points=make_route_with_points)
    assert "Chernobyl exclusion zone" in section.markdown and section.warnings[0].severity == "danger"


def test_the_east_urals_trace_is_an_approximate_caution_and_the_reserve_a_danger(make_route, fixed_now):
    section = run(make_route, fixed_now, KYSHTYM)
    assert "East Ural State Nature Reserve (core of the East Urals Radioactive Trace)** (danger zone)" in section.markdown
    assert "East Urals Radioactive Trace (fallout of 1957, approximate outline)** (affected area)" in section.markdown
    assert "Approximate outline: Centre line through Bagaryak" in section.markdown
    assert any(w.text == "The route crosses East Urals Radioactive Trace (fallout of 1957, approximate outline). "
               "Do not pick mushrooms or berries and do not drink from springs or streams."
               for w in section.warnings)
    assert all("contamination:" not in w.text for w in section.warnings)


def test_russian_text_uses_the_russian_names_and_advice(make_route, fixed_now):
    section = run(make_route, fixed_now, CROSSING, lang="ru")
    assert "Чернобыльская зона отчуждения (Украина)** (опасная зона)" in section.markdown
    assert "Не собирайте грибы и ягоды." in section.markdown
    assert "Родники, ручьи и другая природная вода могут быть заражены" in section.markdown
    assert section.warnings[0].text.startswith("Маршрут входит в зону: Чернобыльская зона отчуждения (Украина) — заражённая земля.")
    assert section.markdown.count("Источники:") == 1 and "Centre" not in section.markdown and "Outline" not in section.markdown


def test_osm_credit_is_its_own_paragraph(make_route, fixed_now):
    section = run(make_route, fixed_now, CROSSING, folder="osm_en")
    md = section.markdown
    assert "\n\n*Zone outlines from OpenStreetMap" in md
    # The line before the blank lines should be the sources line starting with "Sources:"
    sources_idx = md.index("Sources:")
    credit_idx = md.index("\n\n*Zone outlines from OpenStreetMap")
    assert sources_idx < credit_idx
    # Also test in Russian
    section_ru = run(make_route, fixed_now, CROSSING, lang="ru", folder="osm_ru")
    md_ru = section_ru.markdown
    assert "\n\n*Контуры зон — из OpenStreetMap" in md_ru
    sources_idx_ru = md_ru.index("Источники:")
    credit_idx_ru = md_ru.index("\n\n*Контуры зон — из OpenStreetMap")
    assert sources_idx_ru < credit_idx_ru


def test_radiation_needs_no_network_and_no_other_plugin(make_route, fixed_now):
    calls = []
    route_dir = make_route(coords=CROSSING)
    ctx = build_context(route_dir, DATE, http=lambda u: calls.append(u) or {}, now=fixed_now)
    section = RadiationPlugin().run(ctx, {})
    assert calls == [] and RadiationPlugin.depends_on == () and section.warnings
```

- [ ] **Step 2: Run them and see them fail** — `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_radiation.py -q` (import errors or assertion failures: the code does not exist yet).

- [ ] **Step 3: Write the implementation**

Create `skills/osm-day-route-day-plan/scripts/day_plan/plugins/radiation.py`:

```python
"""The "Radiation" hazard: the route and its points against the hand-curated
registry (`data/radiation_zones.json`, see `day_plan/radiation.py`).

Independent of the network and of every other plugin, so the warning survives
whatever else fails. Its warnings are `pinned`: the Summary lists them before
other warnings of the same severity, so five gust warnings cannot push a
contaminated zone out of the top five. A route with no hit is told "no entry
in the registry", never "safe". A route far outside the registry's area
(scope) gets no radiation part at all: nothing applies."""
from ..base import PlanWarning, Section, SectionPlugin
from ..i18n import tr
from ..radiation import find_hits, in_scope, load_registry
from .common import sources_line


def _unique(urls: list) -> list:
    seen, out = set(), []
    for url in urls:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


class RadiationPlugin(SectionPlugin):
    plugin_id = "radiation"
    section_id = "hazards"
    title_key = "hz_radiation"

    def run(self, ctx, shared: dict) -> Section:
        lang = ctx.lang
        registry = load_registry()
        lat, lon = ctx.centroid
        route = [(c[0], c[1]) for c in ctx.coords]
        points = [(p.lon, p.lat) for p in ctx.access_points + ctx.interest_points]
        if not any(in_scope(registry, c[1], c[0]) for c in route[:1] + route[-1:] + [(lon, lat)]):
            return Section("hazards", "", "derived", omit=True)             # far outside the registry's area
        margin = registry["margin_km"]
        all_hits = find_hits(registry, route, points)
        hits = [h for h in all_hits if h.inside or h.zone["severity"] != "info"]     # an advisory area matters only inside it
        if not hits:
            key = "rad_none_advisory" if all_hits else "rad_none"      # near-but-outside advisory areas were dropped
            return Section("hazards", "- " + tr(key, lang, km=f"{margin:g}", areas=tr("rad_areas", lang)), "derived")
        lines, warnings, urls = [], [], []
        any_danger_zone_reached = False
        for hit in hits:
            zone = hit.zone
            name = zone["name"].get(lang) or zone["name"]["en"]
            contamination = zone["contamination"].get(lang) or zone["contamination"]["en"]
            status = zone["status"].get(lang) or zone["status"]["en"]
            danger_zone = zone["severity"] == "danger"
            severity_label = tr("rad_sev_" + zone["severity"], lang)
            if hit.inside:
                line = tr("rad_inside", lang, name=name, severity=severity_label,
                          contamination=contamination[:1].upper() + contamination[1:], status=status)
            else:
                line = tr("rad_near", lang, name=name, severity=severity_label, km=f"{hit.distance_km:.1f}",
                          contamination=contamination[:1].upper() + contamination[1:], status=status)
            if zone["approximate"]:
                line += tr("rad_approx", lang, note=zone["geometry_note"].get(lang) or zone["geometry_note"]["en"])
            lines.append(line)
            urls += [s["url"] for s in zone["sources"]]
            if hit.inside and danger_zone:
                any_danger_zone_reached = True
                warnings.append(PlanWarning("danger", tr("rad_warn_inside_danger", lang, name=name), pinned=True))
            elif hit.inside and zone["severity"] == "info":
                warnings.append(PlanWarning("info", tr("rad_warn_inside_info", lang, name=name)))
            elif hit.inside:
                warnings.append(PlanWarning("caution", tr("rad_warn_inside_caution", lang, name=name), pinned=True))
            else:
                warnings.append(PlanWarning("caution" if danger_zone else "info",
                                            tr("rad_warn_near", lang, name=name, km=f"{hit.distance_km:.1f}"),
                                            pinned=True))
        if any(h.zone["advice"] == "full" for h in hits):
            lines += ["", tr("rad_advice_title", lang), tr("rad_advice_food", lang), tr("rad_advice_water", lang),
                      tr("rad_advice_dust", lang), tr("rad_advice_wind", lang)]
        else:
            lines += ["", tr("rad_advice_title", lang), tr("rad_advice_mushrooms", lang)]
        if any_danger_zone_reached:
            lines += ["", tr("rad_replan", lang)]
        urls = _unique(urls)
        lines += ["", sources_line(urls, lang)]
        if any("OpenStreetMap" in h.zone.get("geometry_note", {}).get("en", "") for h in hits):
            lines += ["", "*" + tr("rad_osm_credit", lang) + "*"]
        primary = all(any(s["kind"] == "primary" for s in h.zone["sources"]) for h in hits)
        return Section("hazards", "\n".join(lines), "tag-backed" if primary else "web-sourced",
                       sources=urls, warnings=warnings,
                       shared={"zones": [h.zone["id"] for h in hits]})
```

- [ ] **Step 4: Run the whole suite** — `cd skills/osm-day-route-day-plan && python3 -m pytest tests -q` (all green), and for the show skill `cd skills/osm-day-route-show && python3 -m pytest tests -q`.

- [ ] **Step 5: Commit**

```bash
git add skills README.md
git commit -m "Radiation hazard plugin with pinned warnings

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

### Task 5: People and access, and mobile coverage

`PeopleHazardsPlugin`: only facts recorded with a source (`record_fact.py --plugin people_hazards`); with none the part is left out. `CellCoveragePlugin`: counts the masts OpenStreetMap records within 5 km, says plainly that this is not a coverage measurement, gives the practical advice and the nPerf (country-specific when the country is known) and OpenCellID links; it never warns above `info`.

**Files:**
- Create: `skills/osm-day-route-day-plan/tests/test_people_and_coverage.py`
- Create: `skills/osm-day-route-day-plan/scripts/day_plan/plugins/people_hazards.py`
- Create: `skills/osm-day-route-day-plan/scripts/day_plan/plugins/cell_coverage.py`

- [ ] **Step 1: Add the tests** (12 tests in the file(s) below)

Create `skills/osm-day-route-day-plan/tests/test_people_and_coverage.py`:

```python
import datetime
import json

from day_plan.context import build_context
from day_plan.http import HttpError
from day_plan.osm_features import OsmFeature
from day_plan.plugins.cell_coverage import CellCoveragePlugin, nperf_url
from day_plan.plugins.people_hazards import PeopleHazardsPlugin

DATE = datetime.date(2026, 7, 4)
FACT = {"markdown": "The border zone here needs a permit from the border service.",
        "sources": ["https://example.org/permits"],
        "warnings": [{"severity": "caution", "text": "Permit needed near the border."}]}


def people(make_route, fixed_now, facts=None, lang="en"):
    route_dir = make_route()
    if facts is not None:
        (route_dir / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    ctx = build_context(route_dir, DATE, lang=lang, http=lambda u: {}, now=fixed_now)
    return PeopleHazardsPlugin().run(ctx, {})


def test_without_a_recorded_fact_the_people_part_is_left_out_not_listed_as_missing(make_route, fixed_now):
    section = people(make_route, fixed_now)
    assert section.omit is True and section.markdown == "" and section.warnings == []


def test_a_recorded_fact_is_shown_with_its_sources_and_warnings(make_route, fixed_now):
    section = people(make_route, fixed_now, facts={"all": {"people_hazards": FACT}})
    assert "The border zone here needs a permit from the border service." in section.markdown
    assert "Access and safety notes (from web sources, not verified in person)" in section.markdown
    assert "Sources: [example.org](https://example.org/permits)" in section.markdown
    assert section.confidence == "web-sourced" and section.sources == ["https://example.org/permits"]
    assert [(w.severity, w.text) for w in section.warnings] == [("caution", "Permit needed near the border.")]


def test_a_fact_without_a_source_is_ignored(make_route, fixed_now):
    bad = {"markdown": "Locals are aggressive.", "sources": []}
    section = people(make_route, fixed_now, facts={"all": {"people_hazards": bad}})
    assert section.omit is True


def test_the_russian_title_of_the_fact(make_route, fixed_now):
    section = people(make_route, fixed_now, facts={"all": {"people_hazards": FACT}}, lang="ru")
    assert "Доступ и безопасность (по веб-источникам, лично не проверено)" in section.markdown


def coverage(make_route, fixed_now, features=None, error=None, samples=True, lang="en", country=None, folder="route"):
    def http(url):
        if country and "nominatim" in url:
            return {"address": {"country_code": country}}
        return {}
    ctx = build_context(make_route(folder=folder), DATE, lang=lang, http=http, now=fixed_now)
    osm = {"features": features or [], "samples": [(c[1], c[0]) for c in ctx.coords] if samples else None,
           "error": error}
    return CellCoveragePlugin().run(ctx, {"osm_features": osm}), ctx


def mast(dlat):
    return OsmFeature("mast", 51.45 + dlat, -0.20, "", "")


def test_masts_near_the_route_are_counted_with_the_nearest_distance(make_route, fixed_now):
    section, _ = coverage(make_route, fixed_now, features=[mast(0.009), mast(0.02), mast(0.5)])
    md = section.markdown
    assert "Mobile masts recorded in OpenStreetMap within 5 km of the route: **2** (nearest about 1.0 km)." in md
    assert section.confidence == "tag-backed" and section.warnings == []
    assert section.section_id == "cell_coverage" and section.omit is False


def test_the_caveat_the_advice_and_the_map_links_are_always_there(make_route, fixed_now):
    section, _ = coverage(make_route, fixed_now, features=[mast(0.0)])
    md = section.markdown
    assert "a missing mast does not mean there is no signal" in md and "Coverage is not measured here." in md
    assert "Download offline maps and the GPX track" in md and "112" in md
    assert "[nPerf](https://www.nperf.com/en/map)" in md and "[OpenCellID](https://opencellid.org/)" in md


def test_no_mast_recorded_is_only_an_info_warning(make_route, fixed_now):
    section, _ = coverage(make_route, fixed_now, features=[mast(0.5)])
    assert "No mobile masts are recorded in OpenStreetMap within 5 km of the route." in section.markdown
    assert [w.severity for w in section.warnings] == ["info"]
    assert "signal may be weak or absent" in section.warnings[0].text


def test_when_openstreetmap_is_unavailable_the_section_is_no_data_but_keeps_the_links(make_route, fixed_now):
    section, _ = coverage(make_route, fixed_now, error="Overpass 504")
    assert section.confidence == "no-data" and section.warnings == []
    assert "Mast data from OpenStreetMap could not be loaded (Overpass 504)." in section.markdown
    assert "nPerf" in section.markdown and "112" in section.markdown


def test_a_missing_osm_plugin_is_handled(make_route, fixed_now):
    section, _ = coverage(make_route, fixed_now, samples=False)
    assert section.confidence == "no-data" and "could not be loaded (no data)" in section.markdown


def test_the_nperf_link_is_country_specific_when_the_country_is_known(make_route, fixed_now):
    section, ctx = coverage(make_route, fixed_now, features=[mast(0.0)], country="ru")
    assert "[nPerf](https://www.nperf.com/en/map/RU/-/-/signal)" in section.markdown
    assert nperf_url(ctx) == "https://www.nperf.com/en/map/RU/-/-/signal"


def test_a_failing_country_lookup_falls_back_to_the_global_map(make_route, fixed_now):
    def broken(url):
        raise HttpError("503")
    ctx = build_context(make_route(), DATE, http=broken, now=fixed_now)
    assert nperf_url(ctx) == "https://www.nperf.com/en/map"


def test_russian_text(make_route, fixed_now):
    section, _ = coverage(make_route, fixed_now, features=[mast(0.5)], lang="ru")
    assert "В OpenStreetMap нет вышек сотовой связи в радиусе 5 км от маршрута." in section.markdown
    assert "112 — номер экстренных служб" in section.markdown and "Покрытие здесь не измеряется." in section.markdown
```

- [ ] **Step 2: Run them and see them fail** — `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_people_and_coverage.py -q` (import errors or assertion failures: the code does not exist yet).

- [ ] **Step 3: Write the implementation**

Create `skills/osm-day-route-day-plan/scripts/day_plan/plugins/people_hazards.py`:

```python
"""The "People and access" hazard: only what Claude recorded with a source
(`record_fact.py --plugin people_hazards`): access restrictions and permit
zones for border areas, conflict-zone or travel-advisory notes for the
region, known problem sections. No generalisations about populations and
nothing without a source (the fact loader drops a source-less entry).

Deviation from the spec, which says "no data" without a source: with no fact
the part is left out, otherwise every plan would list "People and access"
as missing data although nothing is missing that a script could supply."""
from ..base import PlanWarning, Section, SectionPlugin
from ..facts import lookup
from ..i18n import tr
from .common import sources_line


class PeopleHazardsPlugin(SectionPlugin):
    plugin_id = "people_hazards"
    section_id = "hazards"
    title_key = "hz_people"

    def run(self, ctx, shared: dict) -> Section:
        fact = lookup(ctx.facts, ctx.date_iso, "people_hazards")
        if not fact or not fact["markdown"]:
            return Section("hazards", "", "derived", omit=True)
        lines = [tr("ppl_web_title", ctx.lang), "", fact["markdown"], "", sources_line(fact["sources"], ctx.lang)]
        warnings = [PlanWarning(w["severity"], w["text"]) for w in fact.get("warnings", [])]
        return Section("hazards", "\n".join(lines), "web-sourced", sources=list(fact["sources"]), warnings=warnings)
```

Create `skills/osm-day-route-day-plan/scripts/day_plan/plugins/cell_coverage.py`:

```python
"""The "Mobile coverage" section. Deliberately modest: OpenStreetMap records
only a share of the masts (a few hundred metres of forest road may have no
mast recorded in a place that has good signal, and the reverse), so the plugin
counts the masts recorded near the route, says plainly that this is not a
coverage measurement, gives the practical advice and links to the
coverage maps that can be opened from a browser (nPerf, OpenCellID). It never
warns above `info`.

Deviation from the spec, which asked for a terrain-aware weak-signal model:
without measured data such a model would be a guess presented as an estimate."""
from ..base import PlanWarning, Section, SectionPlugin
from ..calendar_info import country_code
from ..i18n import tr
from ..osm_features import MARGIN_KM, near

NPERF_GLOBAL = "https://www.nperf.com/en/map"
NPERF_COUNTRY = "https://www.nperf.com/en/map/{code}/-/-/signal"


def nperf_url(ctx) -> str:
    code = country_code(ctx)
    return NPERF_COUNTRY.format(code=code.upper()) if code and code.isalpha() and len(code) == 2 else NPERF_GLOBAL


class CellCoveragePlugin(SectionPlugin):
    plugin_id = "cell_coverage"
    section_id = "cell_coverage"
    depends_on = ("osm_features",)

    def run(self, ctx, shared: dict) -> Section:
        lang = ctx.lang
        osm = shared.get("osm_features") or {}
        tail = [tr("cell_caveat", lang), tr("cell_advice", lang), tr("cell_maps", lang, nperf=nperf_url(ctx))]
        if osm.get("error") or osm.get("samples") is None:
            reason = osm.get("error") or "no data"
            return Section("cell_coverage", "\n".join([tr("cell_osm_unavailable", lang, reason=reason)] + tail),
                           "no-data")
        masts = near(osm.get("features", []), osm["samples"], "mast", MARGIN_KM * 1000.0)
        km = f"{MARGIN_KM:g}"
        warnings = []
        if masts:
            nearest = tr("cell_nearest", lang, dist=f"{masts[0][1] / 1000.0:.1f}")
            lines = [tr("cell_masts", lang, km=km, count=len(masts), nearest=nearest)]
        else:
            lines = [tr("cell_none", lang, km=km)]
            warnings.append(PlanWarning("info", tr("cell_warn_none", lang)))
        return Section("cell_coverage", "\n".join(lines + tail), "tag-backed", warnings=warnings)
```

- [ ] **Step 4: Run the whole suite** — `cd skills/osm-day-route-day-plan && python3 -m pytest tests -q` (all green), and for the show skill `cd skills/osm-day-route-show && python3 -m pytest tests -q`.

- [ ] **Step 5: Commit**

```bash
git add skills README.md
git commit -m "People-and-access facts and mobile coverage section

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

### Task 6: Wire everything into the CLI and record_fact

`default_plugins()` registers radiation first in the Hazards group, then people and coverage; `record_fact.py` accepts `people_hazards`; the optional hint mentions it and can never fail a plan that was already written. The CLI tests are updated for the new sub-headings and the `## Mobile coverage` section and gain end-to-end tests (a route in a contaminated district, a route outside the registry area, a recorded people fact, a failing hint).

**Files:**
- Modify: `skills/osm-day-route-day-plan/tests/test_cli.py`
- Modify: `skills/osm-day-route-day-plan/scripts/build_day_plan.py`
- Modify: `skills/osm-day-route-day-plan/scripts/record_fact.py`

- [ ] **Step 1: Add the tests** (26 tests in the file(s) below)

Modify `skills/osm-day-route-day-plan/tests/test_cli.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-day-plan/tests/test_cli.py
+++ b/skills/osm-day-route-day-plan/tests/test_cli.py
@@ -87,12 +87,13 @@
     text = (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
     headings = [line for line in text.splitlines() if line.startswith("## ")]
     assert headings == ["## Summary", "## Daylight", "## Weather by hour", "## Getting there", "## Points of interest",
-                        "## Hazards"]
+                        "## Hazards", "## Mobile coverage"]
     subheadings = [line for line in text.splitlines() if line.startswith("### ")]
-    assert subheadings == ["### Mountain hazards", "### Fire danger", "### Ticks and biting insects",
+    assert subheadings == ["### Radiation", "### Mountain hazards", "### Fire danger", "### Ticks and biting insects",
                            "### Air: pollen and pollution"]
     assert "| Lago | start |" in text and "| Museo | sight | 10:00–18:00 |" in text and "| Lago | 41 | bus |" in text
-    assert "<!-- plugins: weather 1, light 1, osm_features 1, transit 1, poi_hours 1, mountain 1, fire 1, bio_hazards 1, air 1 -->" in text
+    assert ("<!-- plugins: weather 1, light 1, osm_features 1, radiation 1, transit 1, poi_hours 1, mountain 1, fire 1, "
+            "bio_hazards 1, air 1, people_hazards 1, cell_coverage 1 -->") in text
 
 
 def test_hint_asks_for_web_facts_until_they_are_recorded(make_route_with_points, weather_response, fixed_now, capsys):
@@ -226,8 +227,8 @@
     route_dir = _route_with_points(make_route_with_points)
     build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text, now=fixed_now)
     out = capsys.readouterr().out
-    assert "hint (optional): regional facts would improve the hazard sections: fire, mountain, bio_hazards" in out
-    for plugin in ("fire", "mountain", "bio_hazards"):
+    assert "hint (optional): regional facts would improve the hazard sections: fire, mountain, bio_hazards, people_hazards" in out
+    for plugin in ("fire", "mountain", "bio_hazards", "people_hazards"):
         record_fact.record(route_dir, "2026-06-21", plugin, "Local note.", ["https://example.org/x"])
     build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text, now=fixed_now)
     assert "hint (optional)" not in capsys.readouterr().out
@@ -235,7 +236,7 @@
     build_day_plan.main([str(flat), "2026-12-15"], http=_web(weather_response, date="2026-12-15"), http_text=_text,
                         now=fixed_now)
     winter = capsys.readouterr().out
-    assert "regional facts would improve the hazard sections: fire " in winter or "sections: fire —" in winter
+    assert "regional facts would improve the hazard sections: fire, people_hazards — " in winter
 
 
 def test_record_fact_accepts_the_hazard_plugins_and_their_warnings(tmp_path):
@@ -260,3 +261,62 @@
     text = (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
     assert "## Getting there" in text and "### Fire danger" in text and "could not be built" in text
     assert "plugin fire failed" in capsys.readouterr().err
+
+
+# ---- plan 3b: radiation, people, coverage ----------------------------------------------------------------
+
+BRYANSK_ROUTE = ((31.90, 52.54, 150.0), (31.95, 52.56, 150.0))
+
+
+def test_a_route_in_a_contaminated_district_shows_radiation_first_and_warns_in_the_summary(
+        make_route, weather_response, fixed_now):
+    route_dir = make_route(coords=BRYANSK_ROUTE)
+    assert build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text,
+                               now=fixed_now) == 0
+    text = (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
+    subheadings = [line for line in text.splitlines() if line.startswith("### ")]
+    assert subheadings[0] == "### Radiation"
+    summary = text.split("## Daylight")[0]
+    assert "South-western Bryansk region" in summary and "Do not pick mushrooms or berries" in summary
+    assert text.rstrip().split("## ")[-1].startswith("Mobile coverage")
+
+
+def test_a_route_outside_the_registry_area_has_no_radiation_part(make_route, weather_response, fixed_now):
+    route_dir = make_route(coords=((151.20, -33.86, 20.0), (151.21, -33.85, 25.0)))
+    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text, now=fixed_now)
+    text = (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
+    assert "### Radiation" not in text and "radiation registry" not in text
+
+
+def test_record_fact_accepts_people_hazards_and_the_plan_shows_it(make_route, weather_response, fixed_now):
+    import record_fact
+    route_dir = make_route()
+    record_fact.record(route_dir, "all", "people_hazards", "A permit is needed in the border zone.",
+                       ["https://example.org/permit"], warnings=[{"severity": "caution", "text": "Border permit needed."}])
+    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text, now=fixed_now)
+    text = (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
+    assert "### People and access" in text and "A permit is needed in the border zone." in text
+    assert "Border permit needed." in text.split("## Daylight")[0]
+    with pytest.raises(ValueError, match="does not use --last-departure"):
+        record_fact.record(route_dir, "all", "people_hazards", "x", ["https://example.org/x"], last_departure="21:00")
+
+
+def test_a_failing_hint_never_fails_the_written_plan(make_route, weather_response, fixed_now, monkeypatch, capsys):
+    def boom(ctx):
+        raise RuntimeError("hint exploded")
+    monkeypatch.setattr(build_day_plan, "optional_hazard_facts", boom)
+    route_dir = make_route()
+    assert build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text,
+                               now=fixed_now) == 0
+    assert (route_dir / "day-plan-2026-06-21.md").exists() and "hint (optional)" not in capsys.readouterr().out
+
+
+def test_a_failing_missing_facts_check_never_fails_the_written_plan(make_route, weather_response, fixed_now,
+                                                                     monkeypatch):
+    def boom(ctx):
+        raise RuntimeError("missing facts exploded")
+    monkeypatch.setattr(build_day_plan, "missing_web_facts", boom)
+    route_dir = make_route()
+    assert build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text,
+                               now=fixed_now) == 0
+    assert (route_dir / "day-plan-2026-06-21.md").exists()
```

- [ ] **Step 2: Run them and see them fail** — `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_cli.py -q` (import errors or assertion failures: the code does not exist yet).

- [ ] **Step 3: Write the implementation**

Modify `skills/osm-day-route-day-plan/scripts/build_day_plan.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-day-plan/scripts/build_day_plan.py
+++ b/skills/osm-day-route-day-plan/scripts/build_day_plan.py
@@ -23,20 +23,25 @@
 from day_plan.osm_features import OsmFeaturesPlugin
 from day_plan.plugins.air import AirPlugin
 from day_plan.plugins.bio_hazards import BioHazardsPlugin, TICK_MONTHS, in_season
+from day_plan.plugins.cell_coverage import CellCoveragePlugin
 from day_plan.plugins.fire import FirePlugin
 from day_plan.plugins.light import LightPlugin
 from day_plan.plugins.mountain import (
     MOUNTAIN_MIN_ELEVATION_M, MOUNTAIN_MIN_RELIEF_M, MountainPlugin, elevation_stats,
 )
+from day_plan.plugins.people_hazards import PeopleHazardsPlugin
 from day_plan.plugins.poi_hours import PoiHoursPlugin
+from day_plan.plugins.radiation import RadiationPlugin
 from day_plan.plugins.transit import TransitPlugin
 from day_plan.plugins.weather import WeatherPlugin
 from day_plan.service import build_plan
 
 
 def default_plugins() -> list:
-    return [WeatherPlugin(), LightPlugin(), OsmFeaturesPlugin(), TransitPlugin(), PoiHoursPlugin(),
-            MountainPlugin(), FirePlugin(), BioHazardsPlugin(), AirPlugin()]
+    # the order inside the Hazards group is the registration order: radiation first, it matters most
+    return [WeatherPlugin(), LightPlugin(), OsmFeaturesPlugin(), RadiationPlugin(), TransitPlugin(), PoiHoursPlugin(),
+            MountainPlugin(), FirePlugin(), BioHazardsPlugin(), AirPlugin(), PeopleHazardsPlugin(),
+            CellCoveragePlugin()]
 
 
 def missing_web_facts(ctx) -> list:
@@ -59,6 +64,7 @@
         wanted.append("mountain")
     if in_season(ctx.date.month, TICK_MONTHS, ctx.centroid[0]):
         wanted.append("bio_hazards")
+    wanted.append("people_hazards")
     return [pid for pid in wanted if lookup(ctx.facts, ctx.date_iso, pid) is None]
 
 
@@ -104,7 +110,10 @@
     print(f"wrote {out.resolve()}")
     for plugin_id, reason in result.failures:
         print(f"warning: plugin {plugin_id} failed: {reason}", file=sys.stderr)
-    missing = missing_web_facts(ctx)
+    try:
+        missing = missing_web_facts(ctx)
+    except Exception:  # noqa: BLE001 — a hint must never turn a written plan into a failure
+        missing = []
     if missing:
         print(f"hint: no web-sourced facts recorded for {', '.join(missing)} on {date.isoformat()}: search the "
               f"web (timetables, directions from the departure point, opening days), record what you find with "
@@ -112,11 +121,15 @@
               + (". calendar: check in the official calendar whether the date is a public holiday, a "
                  "transferred day off or a working Saturday, and record it with --plugin calendar "
                  "--day-type ..." if "calendar" in missing else ""))
-    optional = optional_hazard_facts(ctx)
+    try:
+        optional = optional_hazard_facts(ctx)
+    except Exception:  # noqa: BLE001 — a hint must never turn a written plan into a failure
+        optional = []
     if optional:
         print(f"hint (optional): regional facts would improve the hazard sections: {', '.join(optional)} — "
               f"fire: forest-access and open-fire restrictions; mountain: avalanche bulletin, closed huts or passes; "
-              f"bio_hazards: insect season and peaks, animals (bears, snakes, boar) and hunting; record them with "
+              f"bio_hazards: insect season and peaks, animals (bears, snakes, boar) and hunting; people_hazards: "
+              f"official travel advisories, permit or border-zone rules and access restrictions; record them with "
               f"record_fact.py --plugin <name>")
     return 0
 
```

Modify `skills/osm-day-route-day-plan/scripts/record_fact.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-day-plan/scripts/record_fact.py
+++ b/skills/osm-day-route-day-plan/scripts/record_fact.py
@@ -2,7 +2,8 @@
 """Record one web-sourced fact for a day plan in <route_dir>/facts.json.
 
 Standard-library only. Usage:
-    python3 record_fact.py <route_dir> --date <YYYY-MM-DD|all> --plugin <transit|poi_hours|calendar>
+    python3 record_fact.py <route_dir> --date <YYYY-MM-DD|all>
+        --plugin <transit|poi_hours|calendar|fire|mountain|bio_hazards|air|people_hazards>
         (--markdown TEXT | --markdown-file PATH) --source URL [--source URL ...]
         [--last-departure HH:MM] [--first-departure HH:MM]
         [--warning danger|caution|info:TEXT ...] [--day-type holiday|weekend|workday]
@@ -25,8 +26,8 @@
 from day_plan.base import SEVERITIES
 from day_plan.facts import DAY_TYPES, normalize_entry
 
-PLUGINS = ("transit", "poi_hours", "calendar", "fire", "mountain", "bio_hazards", "air")
-WARNING_PLUGINS = ("transit", "poi_hours", "fire", "mountain", "bio_hazards", "air")
+PLUGINS = ("transit", "poi_hours", "calendar", "fire", "mountain", "bio_hazards", "air", "people_hazards")
+WARNING_PLUGINS = ("transit", "poi_hours", "fire", "mountain", "bio_hazards", "air", "people_hazards")
 
 
 def record(route_dir, date: str, plugin: str, markdown: str, sources: list, last_departure: str | None = None,
```

- [ ] **Step 4: Run the whole suite** — `cd skills/osm-day-route-day-plan && python3 -m pytest tests -q` (all green), and for the show skill `cd skills/osm-day-route-show && python3 -m pytest tests -q`.

- [ ] **Step 5: Commit**

```bash
git add skills README.md
git commit -m "CLI: radiation, people and coverage registered; hint can never fail a plan

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

### Task 7: Documentation

SKILL.md (sections, sources, recording people facts, registry limits and the list of zones not yet covered, common mistakes, replanning on a radiation hit) and README.

**Files:**
- Modify: `README.md`
- Modify: `skills/osm-day-route-day-plan/SKILL.md`

- [ ] **Step 1: Write the implementation**

Modify `README.md` — apply this patch (`patch -p1`):

```diff
--- a/README.md
+++ b/README.md
@@ -70,14 +70,16 @@
   - *Fire danger:* the official Fire Weather Index (Copernicus GWIS, up to 8 days ahead), the Russian Nesterov class for routes in Russia, and active fires detected near the route by satellite.
   - *Ticks and biting insects:* ticks, mosquitoes, blackflies and midges, horseflies, estimated from temperature, wind, humidity and water near the route. Especially useful for Siberia and the Urals.
   - *Air:* pollen (Europe up to about 45° E; for the rest of Russia the plan points to Yandex Weather) and pollution (European AQI, PM10, PM2.5, ozone), up to about 4 days ahead.
+  - *Radiation*, listed first when it applies: the route and its points are checked against a hand-made registry of contaminated or closed areas (the East Urals trace and reserve, the Techa river, Mayak and Lake Karachay, the Chernobyl zones in Ukraine and Belarus, the Bryansk, Tula, Kaluga and Orel districts, the Semipalatinsk test site, the Yenisei below Zheleznogorsk, wild-mushroom areas in Bavaria and Norway). A route inside a danger zone or an affected area gives a warning at the top of the plan; an advisory area only adds an info line. The warning says: do not pick mushrooms or berries, springs and streams may be contaminated, avoid dust and open fires. No hit means "no entry in the registry", not "safe". The registry is incomplete and some outlines are approximate; the plan says which.
+  - *People and access:* only sourced notes Claude recorded (permit or border zones, travel advisories, access restrictions). Animals are recorded with the insect notes.
   - Regional knowledge Claude finds on the web (fire bans, avalanche bulletins, insect seasons) is added with its sources when recorded.
+- **Mobile coverage:** the masts OpenStreetMap knows near your route, practical advice (offline maps, tell someone your plan, power bank, 112) and links to coverage maps. OpenStreetMap lists only some masts, so this is not a signal forecast.
 
 Good to know:
 - Forecasts reach about 15 days ahead. For a later date you get the average of that date over the last five years, clearly labelled as *not a forecast*. Dates older than a week use recorded weather; the last week uses model data.
 - Ask for a plan for several dates: each gets its own file, and re-running a date overwrites only that date.
 - The plan records where you start from only as a city or station, never a street address, because the file is embedded in `map.html`, which is meant to be forwarded.
 - Everything that comes from the web rather than from OpenStreetMap is labelled *web-sourced* and carries its sources; a fact without a source is refused. For Russia and its neighbours, Claude checks the date against the official calendar, because the free holiday list is incomplete for Russia: it misses 8 January and the transferred days off (for example 9 March and 11 May 2026). The script reminds Claude to record such a date as a `calendar` fact (per date; `holiday` for any official day off including transferred ones, `workday` for working days including working Saturdays).
-- Radiation zones, animals, people and mobile coverage are planned next.
 
 ## Skill: osm-day-route-show
 
```

Modify `skills/osm-day-route-day-plan/SKILL.md` — apply this patch (`patch -p1`):

````diff
--- a/skills/osm-day-route-day-plan/SKILL.md
+++ b/skills/osm-day-route-day-plan/SKILL.md
@@ -27,19 +27,23 @@
    features.
 
 6. **Hazards**, with a `###` sub-heading for each part that applies:
-   **Mountain hazards** (only where the route reaches 600 m or more, or its relief is
+   **Radiation** (first: the route and its points against a hand-curated
+   registry of contaminated or closed zones), **Mountain hazards** (only where the route reaches 600 m or more, or its relief is
    at least 300 m: cold and freezing level, wind, thunderstorms, snow, terrain from OSM), **Fire
    danger** (official Fire Weather Index from the Copernicus GWIS service,
    the Russian Nesterov class for routes in Russia, active fires near the
    route), **Ticks and biting insects** (ticks, mosquitoes, blackflies and
    midges, horseflies — estimated from weather and water nearby) and **Air:
-   pollen and pollution** (Open-Meteo CAMS model). A part that does not apply
-   (mountains on a flat route, ticks in winter) is left out, not listed as
-   missing.
-
-Radiation zones, animals, people and mobile coverage are a separate follow-up
-plan; until it exists the plan has no such sections — never invent them by
-hand.
+   pollen and pollution** (Open-Meteo CAMS model) and **People and access**
+   (only what Claude recorded with a source: permit or border zones, travel
+   advisories, access restrictions). A part that does not apply (mountains on
+   a flat route, ticks in winter, people notes nobody recorded) is left out,
+   not listed as missing. Animals (bears, snakes, boar, hunting) are recorded
+   as `bio_hazards` facts and appear under **Ticks and biting insects**.
+7. **Mobile coverage** — the masts OpenStreetMap records near the route, the
+   advice (offline maps and GPX, tell someone, power bank, 112) and links to
+   the coverage maps. It is not a coverage measurement and never warns above
+   `info`.
 
 Every script is **stdlib-only** (`urllib.request`/`json`/`zoneinfo`), no API
 keys, same rule as the other two skills. Sources: Open-Meteo (weather and air
@@ -47,7 +51,9 @@
 industry near the route; mirrors and one retry, because the public servers
 answer 429/504 under load), Copernicus GWIS (Fire Weather Index and active
 fires), Nominatim (the route's country, asked once per route and remembered)
-and Nager.Date (public holidays).
+and Nager.Date (public holidays). The radiation registry
+(`data/radiation_zones.json`) is a static file: no network. Coverage maps
+are only linked (nPerf, OpenCellID), never fetched.
 
 ## When to Use
 
@@ -90,7 +96,8 @@
    ask about; a section without facts says so plainly, which is honest.
 6. Report the file path and read the **Summary** section back to the person.
    If the plan shows the route does not fit the day (finish after sunset,
-   thunderstorm, last bus before the return, a point closed), say so and offer
+   thunderstorm, last bus before the return, a point closed, **a radiation
+   zone on the track**), say so and offer
    to go back to osm-day-route-planning — this skill never changes the route.
 7. Offer to re-render the map so the new date is inside it:
    `python3 ../../osm-day-route-show/scripts/render_map.py <route_dir> --user-lang <code>`.
@@ -104,7 +111,7 @@
 
 ```bash
 python3 record_fact.py <route_dir> --date <YYYY-MM-DD|all> \
-    --plugin <transit|poi_hours|calendar|fire|mountain|bio_hazards|air> \
+    --plugin <transit|poi_hours|calendar|fire|mountain|bio_hazards|air|people_hazards> \
     --markdown "text" | --markdown-file note.md \
     --source https://... [--source https://...] \
     [--last-departure HH:MM] [--first-departure HH:MM] \
@@ -112,8 +119,8 @@
 ```
 
 `--last-departure`, `--first-departure` and `--warning` belong to `transit`
-(`--warning` also to `poi_hours`, `fire`, `mountain`, `bio_hazards` and
-`air`); `--day-type` belongs to `calendar`. The helper refuses an option the
+(`--warning` also to `poi_hours`, `fire`, `mountain`, `bio_hazards`, `air`
+and `people_hazards`); `--day-type` belongs to `calendar`. The helper refuses an option the
 plugin would ignore.
 
 - `--plugin transit`: timetables and **directions from the departure point**
@@ -149,6 +156,11 @@
   The text appears under the matching hazard sub-heading, labelled
   web-sourced. The script prints an optional `hint (optional):` line for the
   hazard sections that apply to the route and date; it never blocks the plan.
+- `--plugin people_hazards`: only verifiable, sourced items for the region —
+  permit or border zones (parts of Russia and its neighbours), conflict-zone
+  or access restrictions, official travel advisories, known problem sections.
+  Never a statement about a population or a group of people. Without a
+  source it is refused; the part appears under **People and access**.
 - Every fact needs at least one `http(s)` source, or it is refused (and, if
   found in the file, ignored). Say only what the source says.
 - **Privacy:** facts end up in `day-plan-<date>.md`, embedded in a `map.html`
@@ -196,8 +208,35 @@
   map in Yandex Weather. The Nesterov class is a simplified computation and is
   shown for Russian routes only.
 - Insect levels are a weather and habitat estimate, not a measurement.
-- Radiation zones, animals, people and mobile coverage are not in this
-  version.
+- **Radiation registry:** curated by hand and incomplete. It holds the East
+  Urals trace (the reserve as the core, the trace as an approximate outline),
+  the Techa river and floodplain, the Mayak site and Lake Karachay, the
+  Chernobyl exclusion zone (Ukraine), the Polesie reserve (Belarus), the
+  Chernobyl-contaminated districts of the Bryansk, Tula, Kaluga and Orel
+  regions (government decree No. 1074), the Semipalatinsk test site, the
+  Yenisei floodplain below Zheleznogorsk (first 100 km) and, as an
+  advisory-only tier, four Bavarian areas where wild mushrooms can still
+  exceed the caesium limit (BfS) and seven Norwegian mountain municipalities
+  with the highest caesium in wild mushrooms (DSA). **Researched and left out
+  on purpose** (the sources show only local plots, a contamination that has
+  decayed away, contradict each other or say no warning is needed): Totskoye
+  1954, Novaya Zemlya, the Seversk 1993 trace, the peaceful underground
+  explosions, Sweden and Finland. **Not researched yet:** Wismut, Jachymov, La
+  Hague, Sellafield, Andreeva Bay and Balkan depleted-uranium sites;
+  `data/README.md` says why for each. A route with no hit is told "no entry in
+  the registry", never "safe". Zones have three tiers: `danger` (closed or
+  heavily contaminated land), `caution` (a wide affected area) and `info` (an
+  advisory area, only mushroom and game advice, no pinned warning). The
+  registry covers Europe with the Urals
+  (north of 36 N), Siberia, northern Kazakhstan and the Far East north of
+  49 N, and Primorye; a route outside those boxes (China, Mongolia, Japan,
+  Korea, the Americas, ...) gets no radiation part at all, and a route just
+  inside a box edge in China or Mongolia is a known limitation of rough
+  rectangles. The Mayak reservoir cascade on the Techa is not outlined.
+  Outlines marked *approximate* are built from published figures (a
+  centre and an area, named settlements, whole districts) and say how; they
+  are not survey isolines. There is no live dose-rate feed.
+- Mobile coverage counts OpenStreetMap masts only and does not model signal.
 
 ## Common Mistakes
 
@@ -211,6 +250,13 @@
 - Editing `facts.json` by hand (use `record_fact.py`: it validates, refuses
   source-less facts and never overwrites a file it cannot parse).
 - Forgetting to re-render `map.html` after adding a plan.
+- Treating a radiation hit as a trivia line: a route that enters a danger zone
+  is a reason to offer going back to osm-day-route-planning (this skill never
+  changes the route itself), and the Radiation section says so (the Summary
+  lists the danger warning).
+- Recording a radiation zone as a fact: there is no `radiation` fact plugin.
+  New zones go into `data/radiation_zones.json` with a cited source, both
+  languages and geometry, and `tests/test_radiation_registry.py` must pass.
 - Recording a `mountain` fact for a flat route (neither 600 m high nor 300 m
   of relief): the section does not exist then and the fact is never shown. A
   `bio_hazards` fact recorded out of season is different: it is still shown
````

- [ ] **Step 2: Run the whole suite** — `cd skills/osm-day-route-day-plan && python3 -m pytest tests -q` (all green), and for the show skill `cd skills/osm-day-route-show && python3 -m pytest tests -q`.

- [ ] **Step 3: Commit**

```bash
git add skills README.md
git commit -m "Docs: radiation, people and mobile coverage

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

### Task 8: Live smoke test and a look at the map

No new code unless a defect is found (then fix it with a test in the owning task's test file). Uses the real network; run from `skills/osm-day-route-day-plan/scripts`; route folders live outside the repository and are not committed.

- [ ] **Step 1: A route crossing the East Urals trace.** Write a `route.geojson` (a LineString with `[lon, lat, ele]` points) through Kyshtym, e.g. `[[60.50,55.70,250],[60.62,55.74,255],[60.85,55.80,260]]`, run `python3 build_day_plan.py <route_dir> <a date 2–3 days ahead> --lang ru`. Expected: the Summary starts with the radiation `danger` and `caution` lines, `### Радиация` is the first sub-section, the advice list and the source line are there, the outline note is in Russian, and `## Сотовая связь` closes the plan.
- [ ] **Step 2: A route in the Bryansk districts** (e.g. around Novozybkov, 52.54 N 31.93 E) with `--lang en`: an affected-area caution, no "danger zone" line, the OpenStreetMap credit.
- [ ] **Step 3: Clean and out-of-area routes.** Madrid: "No zone of the radiation registry lies within 3 km", no warning. Sydney and Beijing: no `### Radiation` at all. Yekaterinburg centre: no hit.
- [ ] **Step 4: Two zones at once.** A route from the Polesie reserve edge to the Chernobyl zone: both zones listed, nearest first, one advice block.
- [ ] **Step 5: Record a people fact** with `record_fact.py --plugin people_hazards` (a real permit rule with its source), re-run: `### People and access` appears with the source and the hint disappears.
- [ ] **Step 6: Render `map.html`** (`python3 ../../osm-day-route-show/scripts/render_map.py <route_dir> --user-lang ru`) and check its DOM in a headless browser, or open it in a real one if the Chrome extension is connected: `Радиация` first among the hazard sub-sections, the radiation danger first in the sidebar summary, coverage section last.
- [ ] **Step 7: Final state.** `git status` clean, full suites green in all three skills.
