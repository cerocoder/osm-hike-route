# Day Plan Hazards (part 3a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the hazards group to `day-plan-<date>.md` — mountain hazards, fire danger, ticks and biting insects, air (pollen and pollution) — with regional web facts, everything embedded in `map.html` like the rest of the plan.

**Architecture:** New `SectionPlugin`s in the existing service. One invisible data plugin (`osm_features`) runs a single combined Overpass query and shares its result; the weather plugin shares extra variables; `fire` calls the Copernicus GWIS WMS (Fire Weather Index and hotspots); `air` calls Open-Meteo Air Quality. A part that does not apply returns `Section(omit=True)`. The `hazards` group renders `###` sub-headings from each plugin's `title_key`.

**Tech Stack:** Python 3 stdlib only (`urllib`, `json`, `re`, `zoneinfo`), pytest. No API keys.

**Spec:** `docs/superpowers/specs/2026-09-29-osm-day-route-day-plan-design.md`. Plans 1 and 2 (core; transit and points of interest) are merged. This is part **3a** of the third plan. Part **3b** (radiation registry, animals and people as facts-only hazards, mobile coverage) follows separately.

**Deviations from the spec (decided while researching live services):**
- The spec's own stdlib Fire Weather Index is replaced by the official FWI from the Copernicus GWIS WMS (`ecmwf.query`): the FWI's Drought Code needs a season-long spin-up that a per-day plan cannot reproduce, and GWIS gives global values with no key up to 8 days ahead.
- NASA FIRMS (needs a key) is replaced by GWIS VIIRS hotspots (`viirs.hs.query`), no key.

## Global Constraints

- Every script is stdlib-only; no API keys, no new dependencies. Tests never touch the network (`http` and `http_text` are injected fakes; fixtures come from real answers).
- Confidence tiers: `tag-backed` (OSM), `web-sourced` (facts.json and online services), `derived` (computed or model output), `no-data`. "Not applicable" is `omit=True`, never "missing data".
- The plan is embedded in a `map.html` that is forwarded: no street addresses, phone numbers or personal data in plan text or facts; facts need an `http(s)` source; plugin failures are isolated (`plugin <id> failed: …` on stderr, a no-data section) and never break the plan.
- No astronomy events beyond sunrise, sunset and day length. Departure point city/station level only.
- Localized body text for English and Russian (English fallback), headings in seven languages.
- Fire classes: EFFIS FWI thresholds 5.2/11.2/21.3/38/50; Nesterov ≤300/1000/4000/10000 (Rosleskhoz order No. 287), Russian routes only. Pollen NAB scale; European AQI (EEA) classes.
- Fixed section order: summary, light, weather, transit, pois, hazards (mountain, fire, bio, air), cell_coverage.
- Commit trailer on every commit: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

- A route without elevation data or below 600 m: no mountain part, and it is not listed as "sections without data".
- Winter or freezing day: no tick or insect part (omitted, not "no data"); fire part with snow cover on the ground is not alarming.
- GWIS or Overpass down, slow, non-JSON, or an unexpected HTML layout: the part becomes a no-data line with a reason, the rest of the plan is intact, exit code 0.
- A route abroad, east of 45° E, or past the FWI (8 days) and air-quality (about 4 days) horizons: the section says what is missing instead of showing zeros or stale values.
- A regional fact recorded for a hazard part that does not apply (flat route, winter): stored but never shown, and the docs say so.

---

### Task 1: Sections that do not apply, and hazard sub-headings

Foundation for every hazard part. A `Section` may set `omit=True` (the part does not apply: no mountains on a flat route, no ticks in winter) and it then disappears from the plan and from the list of missing data. The `hazards` group gets its `###` sub-heading from each plugin's `title_key`, and the summary tolerates an unknown severity. All new localized strings for plan 3a (en and ru) are added here so later tasks only use them.

**Files:**
- Create: `skills/osm-day-route-day-plan/tests/test_omit_and_titles.py`
- Modify: `skills/osm-day-route-day-plan/scripts/day_plan/base.py`
- Modify: `skills/osm-day-route-day-plan/scripts/day_plan/service.py`
- Modify: `skills/osm-day-route-day-plan/scripts/day_plan/summary.py`
- Modify: `skills/osm-day-route-day-plan/scripts/day_plan/i18n.py`

- [ ] **Step 1: Add the tests** (7 tests in the file(s) below)

Create `skills/osm-day-route-day-plan/tests/test_omit_and_titles.py`:

```python
import datetime

from day_plan.base import PlanWarning, Section, SectionPlugin
from day_plan.context import build_context
from day_plan.service import assemble_markdown, build_plan, run_plugins
from day_plan.summary import build_summary_section


class Stub(SectionPlugin):
    def __init__(self, plugin_id, section_id="hazards", markdown="body", confidence="derived", omit=False,
                 title_key=None, title=None, raises=False, warnings=()):
        self.plugin_id, self.section_id, self.title_key = plugin_id, section_id, title_key
        self._section = dict(markdown=markdown, confidence=confidence, omit=omit, title=title, warnings=list(warnings))
        self._raises = raises

    def run(self, ctx, shared):
        if self._raises:
            raise RuntimeError("boom")
        return Section(self.section_id, **self._section)


def _ctx(make_route, fixed_now, lang="en"):
    return build_context(make_route(), datetime.date(2026, 6, 21), lang=lang, http=lambda u: {}, now=fixed_now)


def test_an_omitted_section_is_left_out_of_the_file(make_route, fixed_now):
    ctx = _ctx(make_route, fixed_now)
    shown = Section("hazards", "visible text", "derived", title="Visible")
    hidden = Section("hazards", "SECRET should not appear", "derived", omit=True, title="Hidden")
    text = assemble_markdown(ctx, [hidden, shown], Section("summary", "- s"),
                             datetime.datetime(2026, 6, 20, tzinfo=datetime.timezone.utc))
    assert "visible text" in text and "SECRET" not in text
    assert "### Visible" not in text          # a group with a single visible section has no sub-heading


def test_a_group_of_only_omitted_sections_has_no_heading(make_route, fixed_now):
    ctx = _ctx(make_route, fixed_now)
    only_hidden = Section("hazards", "x", "no-data", omit=True)
    text = assemble_markdown(ctx, [only_hidden], Section("summary", "- s"),
                             datetime.datetime(2026, 6, 20, tzinfo=datetime.timezone.utc))
    assert "## Hazards" not in text


def test_an_omitted_no_data_section_is_not_listed_as_missing_in_the_summary():
    summary = build_summary_section([Section("hazards", "", "no-data", omit=True, title="Mountain hazards"),
                                     Section("weather", "", "no-data")], "en")
    assert "Weather by hour" in summary.markdown and "Mountain hazards" not in summary.markdown


def test_warnings_of_an_omitted_section_still_reach_the_summary():
    section = Section("hazards", "", "derived", omit=True, warnings=[PlanWarning("danger", "kept")])
    assert "kept" in build_summary_section([section], "en").markdown


def test_the_service_fills_the_sub_heading_from_the_plugin_title_key(make_route, fixed_now):
    ctx = _ctx(make_route, fixed_now)
    a = Stub("a", title_key="hz_fire", markdown="fire text")
    b = Stub("b", title_key="hz_mountain", markdown="mountain text")
    result = build_plan(ctx, [a, b])
    assert "### Fire danger\n\nfire text" in result.markdown
    assert "### Mountain hazards\n\nmountain text" in result.markdown


def test_a_title_set_by_the_plugin_wins_and_the_failed_plugin_keeps_its_heading(make_route, fixed_now):
    ctx = _ctx(make_route, fixed_now)
    own = Stub("own", title_key="hz_fire", title="My own title")
    failing = Stub("bad", title_key="hz_air", raises=True)
    sections, _, failures = run_plugins(ctx, [own, failing])
    assert sections[0].title == "My own title"
    assert sections[1].title == "Air: pollen and pollution" and sections[1].confidence == "no-data"
    assert failures[0][0] == "bad"


def test_titles_are_localized(make_route, fixed_now):
    ctx = _ctx(make_route, fixed_now, lang="ru")
    sections, _, _ = run_plugins(ctx, [Stub("a", title_key="hz_bio"), Stub("b", title_key="hz_mountain")])
    assert [s.title for s in sections] == ["Клещи и кровососущие насекомые", "Горные опасности"]
```

- [ ] **Step 2: Run them and see them fail** — `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_omit_and_titles.py -q` (import errors or assertion failures: the code does not exist yet).

- [ ] **Step 3: Write the implementation**

Modify `skills/osm-day-route-day-plan/scripts/day_plan/base.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-day-plan/scripts/day_plan/base.py
+++ b/skills/osm-day-route-day-plan/scripts/day_plan/base.py
@@ -27,6 +27,7 @@
     warnings: list = field(default_factory=list)
     shared: dict = field(default_factory=dict)  # data for dependent plugins
     title: str | None = None  # sub-heading, used when a group has >1 plugin
+    omit: bool = False  # "not applicable" or a data-only plugin: left out of the file and not listed as missing data
 
 
 class SectionPlugin(ABC):
@@ -34,6 +35,7 @@
     section_id: str
     version: str = "1"
     depends_on: tuple = ()
+    title_key: str | None = None  # i18n key of the sub-heading when the plugin shares a section group
 
     @abstractmethod
     def run(self, ctx, shared: dict) -> Section:
```

Modify `skills/osm-day-route-day-plan/scripts/day_plan/service.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-day-plan/scripts/day_plan/service.py
+++ b/skills/osm-day-route-day-plan/scripts/day_plan/service.py
@@ -67,6 +67,8 @@
             section = Section(plugin.section_id, tr("plugin_failed", ctx.lang, reason=reason), "no-data")
         else:
             shared[plugin.plugin_id] = section.shared
+        if section.title is None and plugin.title_key:
+            section.title = tr(plugin.title_key, ctx.lang)
         by_id[plugin.plugin_id] = section
     return [by_id[p.plugin_id] for p in plugins], shared, failures
 
@@ -102,7 +104,7 @@
     for section_id in SECTION_ORDER:
         if section_id == "summary":
             continue
-        group = [s for s in sections if s.section_id == section_id]
+        group = [s for s in sections if s.section_id == section_id and not s.omit]
         if not group:
             continue
         body = []
@@ -113,7 +115,7 @@
                 body.append(s.markdown)
         parts.append(f"## {tr('h_' + section_id, lang)}\n\n" + "\n\n".join(body))
     for s in sections:  # never drop a section whose id is not in SECTION_ORDER
-        if s.section_id not in SECTION_ORDER:
+        if s.section_id not in SECTION_ORDER and not s.omit:
             parts.append(f"## {s.section_id}\n\n{s.markdown}")
     return "\n\n".join(parts) + "\n"
 
```

Modify `skills/osm-day-route-day-plan/scripts/day_plan/summary.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-day-plan/scripts/day_plan/summary.py
+++ b/skills/osm-day-route-day-plan/scripts/day_plan/summary.py
@@ -28,7 +28,7 @@
     lines = [f"- **{_severity_label(w.severity, lang)}:** {_flat(w.text)}" for w in warnings[:MAX_ITEMS]]
     if not lines:
         lines.append("- " + tr("summary_none", lang))
-    missing = [s.title or tr("h_" + s.section_id, lang) for s in sections if s.confidence == "no-data"]
+    missing = [s.title or tr("h_" + s.section_id, lang) for s in sections if s.confidence == "no-data" and not s.omit]
     if missing:
         lines.append("- " + tr("summary_no_data", lang, names=", ".join(missing)))
     return Section("summary", "\n".join(lines), "derived", warnings=[])
```

Modify `skills/osm-day-route-day-plan/scripts/day_plan/i18n.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-day-plan/scripts/day_plan/i18n.py
+++ b/skills/osm-day-route-day-plan/scripts/day_plan/i18n.py
@@ -61,6 +61,95 @@
         "sky_thunder": "thunderstorm", "sky_unknown": "–",
         "compass": ["N", "NE", "E", "SE", "S", "SW", "W", "NW"],
         # calendar (day type)
+        # fire danger
+        "fire_fwi_line": "Fire Weather Index (FWI, ECMWF model via the Copernicus GWIS service): **{fwi}** — {cls}. Components: {components}.",
+        "fire_class_very_low": "very low", "fire_class_low": "low", "fire_class_moderate": "moderate",
+        "fire_class_high": "high", "fire_class_very_high": "very high", "fire_class_extreme": "extreme",
+        "fire_fwi_note": "Model output; the classes are the ones EFFIS uses for Europe (boreal and mountain forests may deserve other thresholds) and other models can differ noticeably.",
+        "fire_fwi_beyond": "No official fire-weather forecast this far ahead (the service covers about {days} days).",
+        "fire_fwi_none": "The fire-weather service has no value for this point and date.",
+        "fire_fwi_unavailable": "The fire-weather service could not be reached ({reason}).",
+        "fire_kpo_line": "Russian forest fire danger by weather (Rosleskhoz order No. 287, Nesterov index): **{value}** — class {roman} ({name}).",
+        "fire_kpo_names": ["absent", "low", "moderate", "high", "extreme"],
+        "fire_kpo_note": "Simplified: the sum of t·(t − dew point) at 12:00 over the days since the last day with more than 3 mm of precipitation.",
+        "fire_kpo_unavailable": "The Nesterov index could not be computed ({reason}).",
+        "fire_hotspots_none": "No satellite-detected active fires within {km} km of the route in the last three days (VIIRS, via GWIS).",
+        "fire_hotspots_some": "Satellite-detected active fires within {km} km of the route (VIIRS via GWIS, last three days):",
+        "fire_hotspot_item": "- {dist} km from the route: {date} {time} UTC, {sat}, confidence {conf}{frp}",
+        "fire_hotspot_frp": ", FRP {frp} MW",
+        "fire_hotspots_unavailable": "Active-fire detections could not be loaded ({reason}).",
+        "fire_wind": "Wind from {dir} ({deg}°) up to {speed} m/s: a fire and its smoke would move toward {to}.",
+        "fire_web_title": "**Restrictions and local information (web-sourced, not verified in person)**",
+        "fire_warn_fwi": "Fire danger is {cls} (FWI {fwi}): no open fire, cigarettes or stoves in forest and dry grass.",
+        "fire_warn_kpo": "Forest fire danger class {roman} ({name}) by the Nesterov index: forest access may be restricted.",
+        "fire_warn_hotspot": "An active fire was detected {km} km from the route ({date}).",
+        # mountain hazards
+        "mt_header": "Route elevation {min}–{max} m (relief {relief} m).",
+        "mt_no_elevation": "The route archive has no elevation data, so mountain hazards were not assessed.",
+        "mt_sac": "Path difficulty in OpenStreetMap near the track: up to **{scale}** ({count} path segment(s) rated).",
+        "mt_sac_names": {"hiking": "T1 hiking", "mountain_hiking": "T2 mountain hiking",
+                         "demanding_mountain_hiking": "T3 demanding mountain hiking", "alpine_hiking": "T4 alpine hiking",
+                         "demanding_alpine_hiking": "T5 demanding alpine hiking", "difficult_alpine_hiking": "T6 difficult alpine hiking"},
+        "mt_rock": "Loose or steep ground within 300 m of the track (OpenStreetMap): {parts} — slips and rockfall are possible.",
+        "mt_rock_scree": "scree {n}", "mt_rock_cliff": "cliffs {n}", "mt_rock_bare_rock": "bare rock {n}",
+        "mt_glacier": "A glacier lies within {m} m of the track: crevasses and ice — do not step onto it without equipment and experience.",
+        "mt_osm_unavailable": "Terrain data from OpenStreetMap could not be loaded ({reason}).",
+        "mt_freezing": "Freezing level down to {fzl} m ({relation} the highest point, {top} m): {effect}",
+        "mt_freezing_below": "below", "mt_freezing_above": "above",
+        "mt_freezing_below_effect": "snow and ice are possible on the upper part of the route.",
+        "mt_freezing_above_effect": "no snow or ice expected from the temperature.",
+        "mt_top_temp": "About **{temp} °C** at the highest point ({top} m), estimated from the valley temperature at −6.5 °C per km.",
+        "mt_thunder": "Thunderstorm risk on ridges and summits (CAPE up to {cape} J/kg): be off exposed ground by early afternoon.",
+        "mt_thunder_forecast": "Thunderstorms are forecast: keep off ridges and summits.",
+        "mt_wind": "The model does not correct wind for height: at the top the wind will be stronger than the {gust} m/s gusts shown.",
+        "mt_rain": "About {mm} mm of rain in the day: rockfall, mudflows and stream crossings become dangerous.",
+        "mt_high": "Above 1500 m: stronger UV (about +10 % per 1000 m), colder air, faster dehydration and sunburn — carry water and sun protection.",
+        "mt_ams": "From 2500 m unacclimatized people can get altitude sickness (headache, nausea, poor sleep) 4–12 hours after arriving: climb gradually and descend if symptoms appear. Oxygen shortage is not a factor below this height.",
+        "mt_snow": "Snow cover and steep ground: check the regional avalanche bulletin (for Europe: https://www.avalanches.org/) before going.",
+        "mt_shade": "In the mountains the sun sets behind the ridges earlier than the computed sunset: plan to be down before then.",
+        "mt_web_title": "**Regional information (web-sourced, not verified in person)**",
+        "mt_warn_sac": "Demanding terrain ({scale}): scrambling, exposure or ropes may be needed.",
+        "mt_warn_glacier": "A glacier is within {m} m of the track.",
+        "mt_warn_freezing": "Freezing level ({fzl} m) is below the highest point ({top} m): snow and ice on the upper route.",
+        "mt_warn_top_cold": "Below freezing at the highest point (about {temp} °C).",
+        "mt_warn_thunder": "Thunderstorm risk on ridges (CAPE {cape} J/kg).",
+        "mt_warn_rain": "Heavy rain expected ({mm} mm): rockfall and stream-crossing risk.",
+        "mt_warn_ams": "Altitude above 3500 m: acclimatization matters, altitude sickness is likely without it.",
+        "mt_warn_snow": "Snow cover on steep ground: avalanche risk — check the bulletin.",
+        # ticks and biting insects
+        "bio_band": {"low": "low", "moderate": "moderate", "high": "high"},
+        "bio_tick": "Ticks: **{band}** (daily mean temperature {temp} °C; they are active from about +5 to +7 °C and wait in grass and shrubs).",
+        "bio_tick_advice": "Long sleeves, trousers tucked into socks, repellent; check clothes and skin afterwards and remove ticks at once. Where tick-borne encephalitis occurs, vaccination matters.",
+        "bio_insect_names": {"mosquito": "Mosquitoes", "blackfly": "Blackflies and midges", "horsefly": "Horseflies"},
+        "bio_insect": "{name}: **{band}**{hours}",
+        "bio_insect_hours": " — {hours}",
+        "bio_insect_none": " (cold, wind or no suitable water nearby)",
+        "bio_insect_note_water": "Water near the route could not be checked, so these bands assume a habitat is present.",
+        "bio_insect_advice": "Repellent and long light clothing; a head net helps against blackflies and mosquitoes; rest on open, windy ground away from still water, especially at dawn and dusk.",
+        "bio_rules": "Insect bands are a weather and habitat estimate (temperature, wind, humidity, time of day, water within 1–1.5 km in OpenStreetMap), not a measurement; the season and peaks of your region matter — see the regional notes when recorded.",
+        "bio_web_title": "**Regional information (web-sourced, not verified in person)**",
+        "bio_warn_tick": "High tick activity (daily mean {temp} °C).",
+        "bio_warn_insect": "High activity of {name} expected ({hours}).",
+        # air: pollen, pollution, emissions
+        "air_level": {"low": "low", "moderate": "moderate", "high": "high", "very_high": "very high"},
+        "air_pollen_kinds": {"alder_pollen": "alder", "birch_pollen": "birch", "olive_pollen": "olive",
+                             "grass_pollen": "grass", "mugwort_pollen": "mugwort", "ragweed_pollen": "ragweed"},
+        "air_pollen_none": "Pollen: none or negligible in the model for this date.",
+        "air_pollen_line": "Pollen (daytime maximum, grains/m³): {parts}.",
+        "air_pollen_scale": "Levels follow the US National Allergy Bureau scale (trees 15/90/1500, grasses 5/20/200, weeds 10/50/500 grains/m³); other scales exist and sensitivity varies.",
+        "air_pollen_no_data": "Pollen: no data for this location (the CAMS Europe pollen model covers roughly 30–71° N and up to about 45° E). For Russia beyond that, look at the pollen map in Yandex Weather (https://yandex.ru/pogoda/).",
+        "air_pollution_line": "Air quality (daytime maximum): PM2.5 {pm25} µg/m³, PM10 {pm10} µg/m³, ozone {o3} µg/m³, NO₂ {no2} µg/m³, SO₂ {so2} µg/m³, dust {dust} µg/m³; European AQI **{aqi}** — {aqi_class}.",
+        "air_aqi": ["good", "fair", "moderate", "poor", "very poor", "extremely poor"],
+        "air_pollution_no_data": "Air quality: no model data for this date (the air-quality model reaches only about four days ahead).",
+        "air_unavailable": "The air-quality service could not be reached ({reason}).",
+        "air_emissions": "Industrial sites within {km} km of the route (OpenStreetMap): {count}. The wind carries emissions from {down} of them toward the route around {hours}.",
+        "air_emissions_none_downwind": "Industrial sites within {km} km of the route (OpenStreetMap): {count}; the wind does not carry their emissions toward the route.",
+        "air_web_title": "**Regional information (web-sourced, not verified in person)**",
+        "air_warn_pollen": "High pollen ({kind}: {value} grains/m³): allergy sufferers should take medication and expect symptoms.",
+        "air_warn_aqi": "Poor air quality (European AQI {aqi}): avoid heavy exertion, especially with asthma or heart conditions.",
+        "air_warn_emissions": "Industrial emissions may be carried toward the route ({hours}).",
+        "hz_bio": "Ticks and biting insects", "hz_mountain": "Mountain hazards", "hz_fire": "Fire danger",
+        "hz_air": "Air: pollen and pollution",
         "weekday_names": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
         "cal_line": "Date: {weekday} {date} — {kind}; {holiday} {source}",
         "cal_weekend": "weekend", "cal_workday": "working day", "cal_dayoff": "day off",
@@ -150,6 +239,91 @@
         "sky_drizzle": "морось", "sky_rain": "дождь", "sky_snow": "снег", "sky_showers": "ливни",
         "sky_thunder": "гроза", "sky_unknown": "–",
         "compass": ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"],
+        "fire_fwi_line": "Индекс пожарной погоды (FWI, модель ECMWF через сервис Copernicus GWIS): **{fwi}** — {cls}. Составляющие: {components}.",
+        "fire_class_very_low": "очень низкая", "fire_class_low": "низкая", "fire_class_moderate": "умеренная",
+        "fire_class_high": "высокая", "fire_class_very_high": "очень высокая", "fire_class_extreme": "экстремальная",
+        "fire_fwi_note": "Расчёт модели; классы — те, что использует EFFIS для Европы (для северных и горных лесов пороги могут быть другими); другие модели могут заметно расходиться.",
+        "fire_fwi_beyond": "Официального прогноза пожарной погоды на такой срок нет (сервис покрывает около {days} дней).",
+        "fire_fwi_none": "У сервиса пожарной погоды нет значения для этой точки и даты.",
+        "fire_fwi_unavailable": "Сервис пожарной погоды недоступен ({reason}).",
+        "fire_kpo_line": "Пожарная опасность в лесах по условиям погоды в России (приказ Рослесхоза № 287, показатель Нестерова): **{value}** — класс {roman} ({name}).",
+        "fire_kpo_names": ["отсутствует", "малая", "средняя", "высокая", "чрезвычайная"],
+        "fire_kpo_note": "Упрощённо: сумма t·(t − точка росы) в 12:00 за дни после последнего дня с осадками более 3 мм.",
+        "fire_kpo_unavailable": "Показатель Нестерова рассчитать не удалось ({reason}).",
+        "fire_hotspots_none": "Спутниковых обнаружений активных пожаров в {km} км от маршрута за последние три дня нет (VIIRS, через GWIS).",
+        "fire_hotspots_some": "Спутниковые обнаружения активных пожаров в {km} км от маршрута (VIIRS через GWIS, последние три дня):",
+        "fire_hotspot_item": "- в {dist} км от маршрута: {date} {time} UTC, {sat}, достоверность {conf}{frp}",
+        "fire_hotspot_frp": ", мощность {frp} МВт",
+        "fire_hotspots_unavailable": "Обнаружения активных пожаров загрузить не удалось ({reason}).",
+        "fire_wind": "Ветер с {dir} ({deg}°) до {speed} м/с: огонь и дым понесёт на {to}.",
+        "fire_web_title": "**Ограничения и местная информация (по веб-источникам, лично не проверено)**",
+        "fire_warn_fwi": "Пожарная опасность {cls} (FWI {fwi}): никакого открытого огня, сигарет и горелок в лесу и на сухой траве.",
+        "fire_warn_kpo": "Класс пожарной опасности леса {roman} ({name}) по показателю Нестерова: вход в лес могут ограничить.",
+        "fire_warn_hotspot": "В {km} км от маршрута обнаружен активный пожар ({date}).",
+        "mt_header": "Высоты маршрута {min}–{max} м (перепад {relief} м).",
+        "mt_no_elevation": "В архиве маршрута нет данных о высотах, поэтому горные опасности не оценивались.",
+        "mt_sac": "Сложность тропы по OpenStreetMap рядом с треком: до **{scale}** (оценено участков: {count}).",
+        "mt_sac_names": {"hiking": "T1 пешеходная", "mountain_hiking": "T2 горная пешеходная",
+                         "demanding_mountain_hiking": "T3 сложная горная", "alpine_hiking": "T4 альпийская",
+                         "demanding_alpine_hiking": "T5 сложная альпийская", "difficult_alpine_hiking": "T6 очень сложная альпийская"},
+        "mt_rock": "Осыпи и крутой рельеф в пределах 300 м от трека (OpenStreetMap): {parts} — возможны падения и камнепады.",
+        "mt_rock_scree": "осыпи {n}", "mt_rock_cliff": "скалы {n}", "mt_rock_bare_rock": "голый камень {n}",
+        "mt_glacier": "Ледник в {m} м от трека: трещины и лёд — без снаряжения и опыта не выходите на него.",
+        "mt_osm_unavailable": "Данные рельефа из OpenStreetMap загрузить не удалось ({reason}).",
+        "mt_freezing": "Нулевая изотерма опускается до {fzl} м ({relation} высшей точки, {top} м): {effect}",
+        "mt_freezing_below": "ниже", "mt_freezing_above": "выше",
+        "mt_freezing_below_effect": "в верхней части маршрута возможны снег и лёд.",
+        "mt_freezing_above_effect": "по температуре снега и льда не ожидается.",
+        "mt_top_temp": "Около **{temp} °C** в высшей точке ({top} м) — оценка по температуре в долине с градиентом −6,5 °C на км.",
+        "mt_thunder": "Риск грозы на гребнях и вершинах (CAPE до {cape} Дж/кг): к полудню сойдите с открытых мест.",
+        "mt_thunder_forecast": "Прогнозируется гроза: держитесь подальше от гребней и вершин.",
+        "mt_wind": "Модель не поправляет ветер на высоту: на вершине ветер будет сильнее, чем порывы {gust} м/с в таблице.",
+        "mt_rain": "За день около {mm} мм осадков: камнепады, сели и переправы через ручьи становятся опасными.",
+        "mt_high": "Выше 1500 м: сильнее ультрафиолет (около +10 % на 1000 м), холоднее, быстрее обезвоживание и ожоги — возьмите воду и защиту от солнца.",
+        "mt_ams": "С 2500 м у неакклиматизированных людей бывает высотная болезнь (головная боль, тошнота, плохой сон) через 4–12 часов после подъёма: поднимайтесь постепенно и спускайтесь при симптомах. Ниже этой высоты нехватка кислорода не проблема.",
+        "mt_snow": "Снежный покров и крутой склон: перед выходом проверьте лавинный бюллетень региона (для Европы: https://www.avalanches.org/).",
+        "mt_shade": "В горах солнце заходит за хребты раньше расчётного заката: спланируйте спуск до этого времени.",
+        "mt_web_title": "**Региональная информация (по веб-источникам, лично не проверено)**",
+        "mt_warn_sac": "Сложный рельеф ({scale}): возможны скалолазание, экспозиция или верёвки.",
+        "mt_warn_glacier": "Ледник в {m} м от трека.",
+        "mt_warn_freezing": "Нулевая изотерма ({fzl} м) ниже высшей точки ({top} м): в верхней части маршрута снег и лёд.",
+        "mt_warn_top_cold": "В высшей точке ниже нуля (около {temp} °C).",
+        "mt_warn_thunder": "Риск грозы на гребнях (CAPE {cape} Дж/кг).",
+        "mt_warn_rain": "Ожидаются сильные осадки ({mm} мм): риск камнепадов и опасных переправ.",
+        "mt_warn_ams": "Высота выше 3500 м: важна акклиматизация, без неё высотная болезнь вероятна.",
+        "mt_warn_snow": "Снежный покров на крутом склоне: лавинная опасность — проверьте бюллетень.",
+        "bio_band": {"low": "низкая", "moderate": "умеренная", "high": "высокая"},
+        "bio_tick": "Клещи: активность **{band}** (среднесуточная температура {temp} °C; они активны примерно от +5…+7 °C и ждут в траве и кустах).",
+        "bio_tick_advice": "Длинные рукава, брюки заправить в носки, репеллент; после прогулки осмотрите одежду и кожу и сразу удалите клеща. Там, где встречается клещевой энцефалит, важна прививка.",
+        "bio_insect_names": {"mosquito": "Комары", "blackfly": "Мошка и мокрецы", "horsefly": "Слепни"},
+        "bio_insect": "{name}: **{band}**{hours}",
+        "bio_insect_hours": " — {hours}",
+        "bio_insect_none": " (холодно, ветер или рядом нет подходящей воды)",
+        "bio_insect_note_water": "Воду рядом с маршрутом проверить не удалось, поэтому оценки исходят из того, что место обитания есть.",
+        "bio_insect_advice": "Репеллент и длинная светлая одежда; накомарник помогает от мошки и комаров; отдыхайте на открытых продуваемых местах вдали от стоячей воды, особенно на рассвете и закате.",
+        "bio_rules": "Уровни для насекомых — оценка по погоде и местам обитания (температура, ветер, влажность, время суток, вода в 1–1,5 км по OpenStreetMap), а не измерение; важны сезон и пики вашего региона — см. региональные заметки, если они записаны.",
+        "bio_web_title": "**Региональная информация (по веб-источникам, лично не проверено)**",
+        "bio_warn_tick": "Высокая активность клещей (среднесуточная {temp} °C).",
+        "bio_warn_insect": "Ожидается высокая активность: {name} ({hours}).",
+        "air_level": {"low": "низкий", "moderate": "умеренный", "high": "высокий", "very_high": "очень высокий"},
+        "air_pollen_kinds": {"alder_pollen": "ольха", "birch_pollen": "берёза", "olive_pollen": "олива",
+                             "grass_pollen": "злаки", "mugwort_pollen": "полынь", "ragweed_pollen": "амброзия"},
+        "air_pollen_none": "Пыльца: по модели на эту дату нет или ничтожна.",
+        "air_pollen_line": "Пыльца (дневной максимум, зёрен/м³): {parts}.",
+        "air_pollen_scale": "Уровни по шкале Национального бюро аллергий США (деревья 15/90/1500, злаки 5/20/200, сорные травы 10/50/500 зёрен/м³); бывают и другие шкалы, чувствительность у всех разная.",
+        "air_pollen_no_data": "Пыльца: для этой точки данных нет (модель пыльцы CAMS Europe покрывает примерно 30–71° с. ш. и до 45° в. д.). Для России дальше на восток смотрите карту пыльцы в Яндекс Погоде (https://yandex.ru/pogoda/).",
+        "air_pollution_line": "Качество воздуха (дневной максимум): PM2.5 {pm25} мкг/м³, PM10 {pm10} мкг/м³, озон {o3} мкг/м³, NO₂ {no2} мкг/м³, SO₂ {so2} мкг/м³, пыль {dust} мкг/м³; европейский индекс AQI **{aqi}** — {aqi_class}.",
+        "air_aqi": ["хорошее", "приемлемое", "умеренное", "плохое", "очень плохое", "крайне плохое"],
+        "air_pollution_no_data": "Качество воздуха: на эту дату данных модели нет (модель качества воздуха заглядывает только примерно на четыре дня).",
+        "air_unavailable": "Сервис качества воздуха недоступен ({reason}).",
+        "air_emissions": "Промышленных объектов в {km} км от маршрута (OpenStreetMap): {count}. Ветер несёт выбросы от {down} из них на маршрут примерно в {hours}.",
+        "air_emissions_none_downwind": "Промышленных объектов в {km} км от маршрута (OpenStreetMap): {count}; ветер не несёт их выбросы на маршрут.",
+        "air_web_title": "**Региональная информация (по веб-источникам, лично не проверено)**",
+        "air_warn_pollen": "Высокая пыльца ({kind}: {value} зёрен/м³): аллергикам стоит принять лекарства и ждать симптомов.",
+        "air_warn_aqi": "Плохое качество воздуха (европейский AQI {aqi}): избегайте больших нагрузок, особенно при астме и болезнях сердца.",
+        "air_warn_emissions": "Выбросы промышленных объектов могут нести на маршрут ({hours}).",
+        "hz_bio": "Клещи и кровососущие насекомые", "hz_mountain": "Горные опасности",
+        "hz_fire": "Пожарная опасность", "hz_air": "Воздух: пыльца и загрязнение",
         "weekday_names": ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"],
         "cal_line": "Дата: {weekday} {date} — {kind}; {holiday} {source}",
         "cal_weekend": "выходной", "cal_workday": "рабочий день", "cal_dayoff": "выходной день",
```

- [ ] **Step 4: Run the whole suite** — `cd skills/osm-day-route-day-plan && python3 -m pytest tests -q` (all green), and for the show skill `cd skills/osm-day-route-show && python3 -m pytest tests -q`.

- [ ] **Step 5: Commit**

```bash
git add skills README.md
git commit -m "Sections can be omitted when they do not apply; hazard sub-headings; strings for the hazard parts

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

### Task 2: Weather variables for the hazards

The single Open-Meteo forecast request gains the fields the hazard parts need (dew point, relative humidity, freezing level, CAPE, model elevation) and the weather plugin shares them as `shared['weather_rows']` extras without changing the visible weather table.

**Files:**
- Create: `skills/osm-day-route-day-plan/tests/test_weather_variables.py`
- Modify: `skills/osm-day-route-day-plan/scripts/day_plan/plugins/weather.py`

- [ ] **Step 1: Add the tests** (7 tests in the file(s) below)

Create `skills/osm-day-route-day-plan/tests/test_weather_variables.py`:

```python
import datetime

import pytest

import day_plan.plugins.weather as weather
from day_plan.context import build_context
from day_plan.plugins.weather import WeatherPlugin, average_rows, parse_hourly

NEW_VARS = ("relative_humidity_2m", "dew_point_2m", "freezing_level_height", "cape")


def _ctx(make_route, fixed_now, http, date=datetime.date(2026, 6, 21), folder="route"):
    return build_context(make_route(folder=folder), date, http=http, now=fixed_now)


def _response(weather_response, **extra):
    response = weather_response(**extra)
    response["hourly"]["relative_humidity_2m"] = [55] * 24
    response["hourly"]["dew_point_2m"] = [8.0] * 24
    response["hourly"]["freezing_level_height"] = [2500.0 + h for h in range(24)]
    response["hourly"]["cape"] = [h * 10.0 for h in range(24)]
    response["elevation"] = 640.0
    return response


def test_the_forecast_request_asks_for_humidity_dew_point_freezing_level_and_cape(make_route, fixed_now, weather_response):
    urls = []
    WeatherPlugin().run(_ctx(make_route, fixed_now, lambda u: urls.append(u) or _response(weather_response)), {})
    for name in NEW_VARS:
        assert name in urls[0]


def test_the_archive_request_leaves_out_what_the_archive_does_not_have(make_route, fixed_now, weather_response):
    urls = []
    ctx = _ctx(make_route, fixed_now, lambda u: urls.append(u) or _response(weather_response, date="2026-01-10"),
               date=datetime.date(2026, 1, 10))
    WeatherPlugin().run(ctx, {})
    assert "archive-api" in urls[0]
    assert "relative_humidity_2m" in urls[0] and "dew_point_2m" in urls[0]
    assert "freezing_level_height" not in urls[0] and "cape" not in urls[0]


def test_rows_carry_the_new_values_and_tolerate_their_absence(weather_response):
    rows = parse_hourly(_response(weather_response))
    assert (rows[12]["rh"], rows[12]["dew"], rows[12]["fzl"], rows[12]["cape"]) == (55, 8.0, 2512.0, 120.0)
    bare = parse_hourly(weather_response())
    assert bare[12]["rh"] is None and bare[12]["fzl"] is None and bare[12]["cape"] is None


def test_the_climatology_averages_the_new_values(weather_response):
    a = parse_hourly(_response(weather_response))
    b = parse_hourly(_response(weather_response))
    for row in b:
        row["fzl"] = (row["fzl"] or 0) + 100.0
        row["rh"] = 45
    mean = average_rows([a, b])
    assert mean[12]["fzl"] == pytest.approx(2562.0) and mean[12]["rh"] == pytest.approx(50.0)


def test_the_model_elevation_is_shared_for_the_mountain_plugin(make_route, fixed_now, weather_response):
    section = WeatherPlugin().run(_ctx(make_route, fixed_now, lambda u: _response(weather_response)), {})
    assert section.shared["elevation_m"] == 640.0
    no_elevation = WeatherPlugin().run(_ctx(make_route, fixed_now, lambda u: weather_response(), folder="second"), {})
    assert no_elevation.shared["elevation_m"] is None


def test_a_cache_entry_written_before_the_new_variables_is_not_reused(make_route, fixed_now, weather_response):
    calls = []
    ctx = _ctx(make_route, fixed_now, lambda u: calls.append(u) or _response(weather_response))
    lat, lon = ctx.centroid
    old_key = f"weather|forecast|{lat:.3f}|{lon:.3f}|{ctx.date_iso}"
    ctx.cache.put(old_key, {"rows": parse_hourly(weather_response()), "utc_offset_seconds": 3600})
    section = WeatherPlugin().run(ctx, {})
    assert len(calls) == 1                                  # the stale entry (no freezing level) was ignored
    assert section.shared["rows"][12]["fzl"] is not None


def test_changing_the_variable_set_changes_the_cache_key(make_route, fixed_now, weather_response, monkeypatch):
    calls = []
    ctx = _ctx(make_route, fixed_now, lambda u: calls.append(u) or _response(weather_response))
    WeatherPlugin().run(ctx, {})
    WeatherPlugin().run(ctx, {})
    assert len(calls) == 1
    monkeypatch.setattr(weather, "FORECAST_VARS", weather.FORECAST_VARS + ("uv_index",))
    WeatherPlugin().run(ctx, {})
    assert len(calls) == 2 and "uv_index" in calls[1]
```

- [ ] **Step 2: Run them and see them fail** — `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_weather_variables.py -q` (import errors or assertion failures: the code does not exist yet).

- [ ] **Step 3: Write the implementation**

Modify `skills/osm-day-route-day-plan/scripts/day_plan/plugins/weather.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-day-plan/scripts/day_plan/plugins/weather.py
+++ b/skills/osm-day-route-day-plan/scripts/day_plan/plugins/weather.py
@@ -11,6 +11,7 @@
 the direction the wind blows FROM. Open-Meteo applies no elevation
 correction to wind, so mountain gusts are likely underestimated."""
 import datetime
+import hashlib
 import math
 from collections import Counter
 from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
@@ -30,16 +31,19 @@
 FORECAST_VARS = (
     "temperature_2m", "apparent_temperature", "precipitation", "precipitation_probability",
     "cloud_cover", "visibility", "weather_code", "wind_speed_10m", "wind_direction_10m",
-    "wind_gusts_10m", "snow_depth",
+    "wind_gusts_10m", "snow_depth", "relative_humidity_2m", "dew_point_2m", "freezing_level_height", "cape",
 )
-ARCHIVE_VARS = tuple(v for v in FORECAST_VARS if v not in ("precipitation_probability", "visibility"))
+# The archive has no probability, visibility, freezing level or CAPE.
+ARCHIVE_VARS = tuple(v for v in FORECAST_VARS if v not in (
+    "precipitation_probability", "visibility", "freezing_level_height", "cape"))
 
 # Row keys <- Open-Meteo hourly variable names
 _ROW_KEYS = {
     "temperature_2m": "temp", "apparent_temperature": "feels", "precipitation": "precip",
     "precipitation_probability": "prob", "cloud_cover": "cloud", "visibility": "vis_m",
     "weather_code": "code", "wind_speed_10m": "wind", "wind_direction_10m": "wdir",
-    "wind_gusts_10m": "gust", "snow_depth": "snow_m",
+    "wind_gusts_10m": "gust", "snow_depth": "snow_m", "relative_humidity_2m": "rh", "dew_point_2m": "dew",
+    "freezing_level_height": "fzl", "cape": "cape",
 }
 
 THRESHOLDS = {
@@ -75,7 +79,7 @@
 def parse_hourly(response: dict) -> list[dict]:
     """Open-Meteo response -> list of 24 row dicts (missing variables are
     None). Row keys: hour (int), temp, feels, precip, prob, cloud, vis_m,
-    code, wind, wdir, gust, snow_m."""
+    code, wind, wdir, gust, snow_m, rh, dew, fzl (freezing level, m), cape."""
     hourly = response["hourly"]
     times = hourly["time"]
     rows = []
@@ -104,7 +108,8 @@
     for hour in range(24):
         samples = [r for rows in per_year_rows for r in rows if r["hour"] == hour]
         row = {"hour": hour}
-        for key in ("temp", "feels", "precip", "cloud", "wind", "gust", "snow_m", "vis_m", "prob"):
+        for key in ("temp", "feels", "precip", "cloud", "wind", "gust", "snow_m", "vis_m", "prob",
+                    "rh", "dew", "fzl", "cape"):
             values = [s[key] for s in samples if s.get(key) is not None]
             row[key] = sum(values) / len(values) if values else None
         codes = [s["code"] for s in samples if s.get("code") is not None]
@@ -137,31 +142,41 @@
         return date.replace(year=year, day=28)
 
 
+def _vars_id(variables) -> str:
+    """Short id of a variable set: part of the cache key, so adding a variable
+    never reuses an entry that was cached without it."""
+    return hashlib.sha1(",".join(variables).encode("utf-8")).hexdigest()[:8]
+
+
 def _fetch(ctx, source: str, lat: float, lon: float):
-    """Returns (rows, utc_offset_seconds, fetched_at_epoch)."""
-    key = f"weather|{source}|{lat:.3f}|{lon:.3f}|{ctx.date_iso}"
+    """Returns (rows, utc_offset_seconds, fetched_at_epoch, model_elevation_m)."""
+    variables = FORECAST_VARS if source == "forecast" else ARCHIVE_VARS
+    key = f"weather|{source}|{_vars_id(variables)}|{lat:.3f}|{lon:.3f}|{ctx.date_iso}"
     max_age = FORECAST_TTL_S if source == "forecast" else None
     cached = ctx.cache.get_entry(key, max_age)
     if cached is not None:
         value, stored_at = cached
-        return value["rows"], value["utc_offset_seconds"], stored_at
+        return value["rows"], value["utc_offset_seconds"], stored_at, value.get("elevation")
 
     if source == "forecast":
         response = ctx.http(_url(FORECAST_URL, FORECAST_VARS, lat, lon, ctx.date))
         rows, offset = parse_hourly(response), utc_offset_for(response, ctx.date)
+        elevation = response.get("elevation")
     elif source == "archive":
         response = ctx.http(_url(ARCHIVE_URL, ARCHIVE_VARS, lat, lon, ctx.date))
         rows, offset = parse_hourly(response), utc_offset_for(response, ctx.date)
+        elevation = response.get("elevation")
     else:
-        per_year, offset = [], None
+        per_year, offset, elevation = [], None, None
         for back in range(1, CLIMATE_YEARS + 1):
             past = _same_day_in_year(ctx.date, ctx.today.year - back)
             response = ctx.http(_url(ARCHIVE_URL, ARCHIVE_VARS, lat, lon, past))
             per_year.append(parse_hourly(response))
             offset = offset if offset is not None else utc_offset_for(response, ctx.date)
+            elevation = elevation if elevation is not None else response.get("elevation")
         rows = average_rows(per_year)
-    stored_at = ctx.cache.put(key, {"rows": rows, "utc_offset_seconds": offset})
-    return rows, offset, stored_at
+    stored_at = ctx.cache.put(key, {"rows": rows, "utc_offset_seconds": offset, "elevation": elevation})
+    return rows, offset, stored_at, elevation
 
 
 def daytime_rows(rows: list[dict], date: datetime.date, lat: float, lon: float,
@@ -298,7 +313,7 @@
         lat, lon = ctx.centroid
         source = choose_source(ctx.date, ctx.today)
         try:
-            rows, offset, fetched_at = _fetch(ctx, source, lat, lon)
+            rows, offset, fetched_at, elevation = _fetch(ctx, source, lat, lon)
         except (HttpError, KeyError, IndexError, ValueError, TypeError) as e:
             return Section("weather", tr("w_unavailable", ctx.lang, reason=str(e) or type(e).__name__),
                            "no-data")
@@ -316,6 +331,6 @@
             "weather", markdown, "derived", sources=["https://open-meteo.com/"],
             warnings=warnings_for(day, ctx.lang, source),
             shared={"utc_offset_seconds": offset, "rows": rows, "daytime_rows": day, "source": source,
-                    "fetched_at": fetched_at,
+                    "fetched_at": fetched_at, "elevation_m": elevation,
                     "daily_mean_temp": sum(means) / len(means) if means else None},
         )
```

- [ ] **Step 4: Run the whole suite** — `cd skills/osm-day-route-day-plan && python3 -m pytest tests -q` (all green), and for the show skill `cd skills/osm-day-route-show && python3 -m pytest tests -q`.

- [ ] **Step 5: Commit**

```bash
git add skills README.md
git commit -m "Weather: dew point, humidity, freezing level, CAPE and model elevation shared for the hazard parts

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

### Task 3: Shared OpenStreetMap features and text HTTP

One combined Overpass query around the route (mobile masts, water, glaciers, scree and cliffs, waterways, `sac_scale` paths, industry, power plants) run once by an invisible data plugin (`osm_features`, produces no section) and shared with the hazard plugins. Adds `get_text` (HTTP returning text, for GWIS) and `ctx.http_text`.

**Files:**
- Create: `skills/osm-day-route-day-plan/tests/test_osm_features.py`
- Modify: `skills/osm-day-route-day-plan/scripts/day_plan/http.py`
- Modify: `skills/osm-day-route-day-plan/scripts/day_plan/context.py`
- Create: `skills/osm-day-route-day-plan/scripts/day_plan/osm_features.py`
- Create: `skills/osm-day-route-day-plan/tests/fixtures/osm_features_dombay.json`
- Create: `skills/osm-day-route-day-plan/tests/fixtures/osm_features_casa_de_campo.json`

- [ ] **Step 1: Add the tests** (19 tests in the file(s) below)

Create `skills/osm-day-route-day-plan/tests/test_osm_features.py`:

```python
import datetime
import json
from collections import Counter
from pathlib import Path

import pytest

from day_plan.context import build_context
from day_plan.http import HttpError
from day_plan.osm_features import (
    OsmFeature, OsmFeaturesPlugin, classify, features_query, haversine_m, near, parse_features, route_bbox,
    route_samples,
)

FIXTURES = Path(__file__).parent / "fixtures"
DOMBAY = json.loads((FIXTURES / "osm_features_dombay.json").read_text(encoding="utf-8"))
CASA = json.loads((FIXTURES / "osm_features_casa_de_campo.json").read_text(encoding="utf-8"))


def kinds(data):
    return Counter(f.kind for f in parse_features(data))


def test_real_mountain_area_has_glaciers_streams_and_a_demanding_path():
    got = kinds(DOMBAY)
    assert got["glacier"] == 21 and got["waterway"] == 38 and got["water"] == 4
    assert got["bare_rock"] == 1 and got["sac"] == 1 and got["mast"] == 0
    sac = next(f for f in parse_features(DOMBAY) if f.kind == "sac")
    assert sac.detail == "demanding_alpine_hiking"


def test_real_park_has_masts_water_hiking_paths_and_industry():
    got = kinds(CASA)
    assert got["mast"] == 2 and got["water"] == 39 and got["sac"] == 7 and got["industrial"] == 1
    rivers = [f for f in parse_features(CASA) if f.kind == "waterway"]
    assert {f.detail for f in rivers} == {"river", "canal", "stream"}


def test_an_element_can_be_several_things_and_elements_without_coordinates_are_skipped():
    data = {"elements": [
        {"type": "way", "id": 1, "center": {"lat": 1.0, "lon": 2.0}, "tags": {"natural": "water", "waterway": "river", "name": "Lago"}},
        {"type": "node", "id": 2, "lat": 3.0, "lon": 4.0, "tags": {"man_made": "mast", "tower:type": "communication"}},
        {"type": "way", "id": 3, "tags": {"natural": "water"}},                        # no coordinates
        {"type": "node", "id": 4, "lat": "x", "lon": 1.0, "tags": {"natural": "water"}},  # not numbers
        {"type": "node", "id": 5, "lat": 5.0, "lon": 6.0},                              # no tags
    ]}
    features = parse_features(data)
    assert [(f.kind, f.detail, f.name) for f in features] == [("water", "", "Lago"), ("waterway", "river", "Lago"),
                                                              ("mast", "", "")]


@pytest.mark.parametrize("tags,expected", [
    ({"natural": "glacier"}, [("glacier", "")]),
    ({"natural": "peak"}, []),
    ({"waterway": "ditch"}, []),
    ({"communication:mobile_phone": "yes"}, [("mast", "")]),
    ({"man_made": "tower"}, []),                                    # a tower that is not a communication tower
    ({"landuse": "industrial"}, [("industrial", "")]),
    ({"power": "plant"}, [("industrial", "")]),
    ({"sac_scale": "alpine_hiking"}, [("sac", "alpine_hiking")]),
])
def test_classify(tags, expected):
    assert classify(tags) == expected


def test_route_bbox_adds_a_margin_that_grows_in_longitude_at_high_latitudes():
    s, w, n, e = route_bbox([(60.0, 56.0, 0), (60.1, 56.1, 0)], margin_km=5.0)
    assert s == pytest.approx(56.0 - 5 / 111.0) and n == pytest.approx(56.1 + 5 / 111.0)
    assert (60.0 - w) > (5 / 111.0) * 1.5           # 1/cos(56 deg) is about 1.8


def test_features_query_contains_the_bbox_and_every_kind():
    ql = features_query((40.4, -3.8, 40.5, -3.7))
    for text in ("40.40000,-3.80000,40.50000,-3.70000", "communication:mobile_phone", "glacier", "sac_scale",
                 "industrial", "power", "waterway", "out tags center", "[timeout:9]"):
        assert text in ql


def test_route_samples_keep_both_ends_and_cap_the_count():
    coords = [(10.0 + i * 0.001, 50.0, 0) for i in range(1000)]
    samples = route_samples(coords, max_points=50)
    assert len(samples) <= 50 and samples[0] == (50.0, 10.0) and samples[-1] == (50.0, 10.999)
    assert route_samples(coords[:3], max_points=50) == [(50.0, 10.0), (50.0, 10.001), (50.0, 10.002)]


def test_near_returns_the_features_within_the_radius_nearest_first():
    samples = [(50.0, 10.0), (50.0, 10.1)]
    features = [OsmFeature("water", 50.001, 10.0), OsmFeature("water", 50.0, 10.1005),
                OsmFeature("water", 51.0, 10.0), OsmFeature("mast", 50.0005, 10.0)]
    found = near(features, samples, "water", 500)
    assert [round(d) for _, d in found] == [36, 111]                # nearest first
    assert [f.kind for f, _ in near(features, samples, ("water", "mast"), 500)].count("mast") == 1
    assert near(features, samples, "glacier", 1e9) == []
    assert haversine_m(50.0, 10.0, 50.0, 10.0) == 0.0


class Web:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def __call__(self, url):
        self.calls.append(url)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def _ctx(make_route, fixed_now, web, folder="route"):
    return build_context(make_route(folder=folder, coords=((41.70, 43.25, 2000.0), (41.72, 43.26, 2400.0))),
                         datetime.date(2026, 7, 4), http=web, now=fixed_now)


def test_the_plugin_shares_features_and_writes_nothing_into_the_plan(make_route, fixed_now):
    section = OsmFeaturesPlugin().run(_ctx(make_route, fixed_now, Web(DOMBAY)), {})
    assert section.omit is True and section.markdown == ""
    assert Counter(f.kind for f in section.shared["features"])["glacier"] == 21
    assert section.shared["error"] is None and section.shared["samples"][0] == (43.25, 41.70)


def test_one_overpass_query_per_route_and_it_is_cached_for_later_runs(make_route, fixed_now):
    web = Web(DOMBAY)
    ctx = _ctx(make_route, fixed_now, web)
    OsmFeaturesPlugin().run(ctx, {})
    OsmFeaturesPlugin().run(ctx, {})
    assert len(web.calls) == 1 and "sac_scale" in web.calls[0]


def test_an_overpass_failure_is_reported_in_shared_not_raised(make_route, fixed_now):
    section = OsmFeaturesPlugin().run(_ctx(make_route, fixed_now, Web(HttpError("504"))), {})
    assert section.omit and section.shared["features"] == [] and "504" in section.shared["error"]
    assert section.confidence == "no-data"


def test_an_empty_answer_is_cached_for_a_day_not_a_week(make_route, fixed_now):
    web = Web({"elements": []})
    ctx = _ctx(make_route, fixed_now, web)
    OsmFeaturesPlugin().run(ctx, {})
    OsmFeaturesPlugin().run(ctx, {})
    assert len(web.calls) == 1
    later = build_context(make_route(folder="later"), ctx.date, http=web,
                          now=fixed_now + datetime.timedelta(days=2))
    later.cache = ctx.cache                                    # same cache file, two days later
    later.coords = ctx.coords
    OsmFeaturesPlugin().run(later, {})
    assert len(web.calls) == 2
```

- [ ] **Step 2: Run them and see them fail** — `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_osm_features.py -q` (import errors or assertion failures: the code does not exist yet).

- [ ] **Step 3: Write the implementation**

Modify `skills/osm-day-route-day-plan/scripts/day_plan/http.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-day-plan/scripts/day_plan/http.py
+++ b/skills/osm-day-route-day-plan/scripts/day_plan/http.py
@@ -16,6 +16,17 @@
     return urllib.request.urlopen(req, timeout=timeout)
 
 
+def get_text(url: str, timeout: float = 10.0) -> str:
+    """The body of a GET as text (for services that answer HTML, such as the
+    GWIS WMS GetFeatureInfo). Same failure contract as get_json."""
+    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
+    try:
+        with _open(req, timeout) as resp:
+            return resp.read().decode("utf-8", "replace")
+    except (urllib.error.URLError, OSError, ValueError) as e:
+        raise HttpError(str(e)) from e
+
+
 def get_json(url: str, timeout: float = 10.0) -> dict:
     req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
     try:
```

Modify `skills/osm-day-route-day-plan/scripts/day_plan/context.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-day-plan/scripts/day_plan/context.py
+++ b/skills/osm-day-route-day-plan/scripts/day_plan/context.py
@@ -9,7 +9,7 @@
 
 from .cache import JsonCache
 from .facts import load_facts
-from .http import get_json
+from .http import get_json, get_text
 
 
 @dataclass
@@ -45,6 +45,7 @@
     cache: JsonCache
     now: datetime.datetime  # timezone-aware UTC
     today: datetime.date = field(init=False)
+    http_text: Callable = get_text                        # GET -> text, for services that answer HTML
     access_points: list = field(default_factory=list)    # [RoutePoint] with type == "access"
     interest_points: list = field(default_factory=list)  # [RoutePoint], every other Point feature
 
@@ -98,7 +99,7 @@
 
 
 def build_context(route_dir, date: datetime.date, lang: str = "en", departure: str | None = None,
-                  start_time: datetime.time | None = None, http: Callable = get_json,
+                  start_time: datetime.time | None = None, http: Callable = get_json, http_text: Callable = get_text,
                   cache: JsonCache | None = None, now: datetime.datetime | None = None) -> PlanContext:
     route_dir = Path(route_dir)
     geojson = json.loads((route_dir / "route.geojson").read_text(encoding="utf-8"))
@@ -126,7 +127,7 @@
         duration_hours=props.get("duration_estimate_hours"),
         centroid=centroid,
         facts=load_facts(route_dir),
-        http=http,
+        http=http, http_text=http_text,
         cache=cache if cache is not None else JsonCache(route_dir / "day_plan_cache.json", now=now.timestamp),
         now=now,
         access_points=access_points, interest_points=interest_points,
```

Create `skills/osm-day-route-day-plan/scripts/day_plan/osm_features.py`:

```python
"""One combined Overpass query per route for everything the hazard plugins
need from OpenStreetMap: mobile masts, still and running water, glaciers,
scree, cliffs and bare rock, `sac_scale` paths, industrial sites. A separate
query per plugin would multiply the 429/504 failures seen on the public
servers, so this data-only plugin fetches once, caches it for a week and
shares it (`shared["osm_features"]`); it never writes text into the plan
(`omit=True`).

Features are located by their centre point (`out center`), which is exact for
nodes and small areas but crude for a long river: distances are therefore
approximate and every consumer labels its result `derived`."""
import math
from dataclasses import asdict, dataclass

from .base import Section, SectionPlugin
from .overpass import EMPTY_TTL_S, ROUTES_TTL_S, OverpassError, run

MARGIN_KM = 5.0
SAMPLE_MAX = 120
QUERY_VERSION = "1"
_QL = ('[out:json][timeout:9];('
       'nwr["communication:mobile_phone"="yes"]({b});'
       'nwr["man_made"~"^(mast|tower)$"]["tower:type"="communication"]({b});'
       'nwr["natural"~"^(water|wetland|glacier|scree|cliff|bare_rock)$"]({b});'
       'way["waterway"~"^(river|stream|canal)$"]({b});'
       'way["sac_scale"]({b});'
       'nwr["landuse"="industrial"]({b});nwr["power"="plant"]({b});'
       ');out tags center 4000;')


@dataclass
class OsmFeature:
    kind: str      # mast | water | wetland | waterway | glacier | scree | cliff | bare_rock | sac | industrial
    lat: float
    lon: float
    name: str = ""
    detail: str = ""   # waterway type, or the sac_scale value


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * 6371000.0 * math.asin(min(1.0, math.sqrt(a)))


def route_bbox(coords: list, margin_km: float = MARGIN_KM) -> tuple:
    """(south, west, north, east) of the route plus a margin."""
    lats = [c[1] for c in coords]
    lons = [c[0] for c in coords]
    lat_margin = margin_km / 111.0
    lon_margin = margin_km / (111.0 * max(0.2, math.cos(math.radians((min(lats) + max(lats)) / 2))))
    return (min(lats) - lat_margin, min(lons) - lon_margin, max(lats) + lat_margin, max(lons) + lon_margin)


def features_query(bbox: tuple) -> str:
    return _QL.format(b=",".join(f"{x:.5f}" for x in bbox))


def route_samples(coords: list, max_points: int = SAMPLE_MAX) -> list:
    """Up to max_points (lat, lon) taken evenly along the route, always including both ends."""
    if len(coords) <= max_points:
        return [(c[1], c[0]) for c in coords]
    step = (len(coords) - 1) / (max_points - 1)
    picked = sorted({round(i * step) for i in range(max_points)})
    return [(coords[i][1], coords[i][0]) for i in picked]


def classify(tags: dict) -> list:
    """[(kind, detail)] for one OSM element (an element can be several things)."""
    out = []
    if tags.get("communication:mobile_phone") == "yes" or (
            tags.get("man_made") in ("mast", "tower") and tags.get("tower:type") == "communication"):
        out.append(("mast", ""))
    if tags.get("natural") in ("water", "wetland", "glacier", "scree", "cliff", "bare_rock"):
        out.append((tags["natural"], ""))
    if tags.get("waterway") in ("river", "stream", "canal"):
        out.append(("waterway", tags["waterway"]))
    if "sac_scale" in tags:
        out.append(("sac", str(tags["sac_scale"])))
    if tags.get("landuse") == "industrial" or tags.get("power") == "plant":
        out.append(("industrial", ""))
    return out


def parse_features(data: dict) -> list:
    features = []
    for element in data.get("elements", []):
        centre = element.get("center") or element
        lat, lon = centre.get("lat"), centre.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue
        tags = element.get("tags") or {}
        for kind, detail in classify(tags):
            features.append(OsmFeature(kind, float(lat), float(lon), str(tags.get("name", "")), detail))
    return features


def nearest_m(samples: list, lat: float, lon: float) -> float:
    return min(haversine_m(lat, lon, s_lat, s_lon) for s_lat, s_lon in samples)


def near(features: list, samples: list, kinds, radius_m: float) -> list:
    """[(feature, distance_m)] of the given kinds within radius_m of the route, nearest first."""
    kinds = (kinds,) if isinstance(kinds, str) else tuple(kinds)
    found = []
    for feature in features:
        if feature.kind in kinds:
            distance = nearest_m(samples, feature.lat, feature.lon)
            if distance <= radius_m:
                found.append((feature, distance))
    return sorted(found, key=lambda pair: pair[1])


class OsmFeaturesPlugin(SectionPlugin):
    """Data only: fetches and shares the features; adds nothing to the plan."""
    plugin_id = "osm_features"
    section_id = "hazards"

    def run(self, ctx, shared: dict) -> Section:
        samples = route_samples(ctx.coords)
        bbox = route_bbox(ctx.coords)
        key = f"osm_features|{QUERY_VERSION}|" + "|".join(f"{x:.2f}" for x in bbox)
        cached = ctx.cache.get_entry(key, ROUTES_TTL_S)
        if cached is not None and (cached[0] or ctx.now.timestamp() - cached[1] <= EMPTY_TTL_S):
            features = [OsmFeature(**f) for f in cached[0]]
            return self._section(features, samples, None)
        try:
            features = parse_features(run(ctx.http, features_query(bbox)))
        except OverpassError as e:
            return self._section([], samples, str(e))
        ctx.cache.put(key, [asdict(f) for f in features])
        return self._section(features, samples, None)

    @staticmethod
    def _section(features: list, samples: list, error) -> Section:
        return Section("hazards", "", "tag-backed" if error is None else "no-data", omit=True,
                       shared={"features": features, "samples": samples, "error": error})
```

Create `skills/osm-day-route-day-plan/tests/fixtures/osm_features_dombay.json`:

```json
{
 "elements": [
  {
   "type": "way",
   "id": 34124548,
   "center": {
    "lat": 43.2669466,
    "lon": 41.7684175
   },
   "tags": {
    "boat": "yes",
    "name": "Буульген",
    "name:en": "Buulgen",
    "source": "landsat",
    "waterway": "river"
   }
  },
  {
   "type": "way",
   "id": 67264610,
   "center": {
    "lat": 43.252743,
    "lon": 41.6898036
   },
   "tags": {
    "name": "Птыш",
    "waterway": "river"
   }
  },
  {
   "type": "way",
   "id": 82488581,
   "center": {
    "lat": 43.2659704,
    "lon": 41.6763387
   },
   "tags": {
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 82488582,
   "center": {
    "lat": 43.2649817,
    "lon": 41.69665
   },
   "tags": {
    "waterway": "river"
   }
  },
  {
   "type": "way",
   "id": 82488583,
   "center": {
    "lat": 43.2439903,
    "lon": 41.7008588
   },
   "tags": {
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 82488584,
   "center": {
    "lat": 43.2389384,
    "lon": 41.6922488
   },
   "tags": {
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 288745283,
   "center": {
    "lat": 43.28373,
    "lon": 41.6551223
   },
   "tags": {
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 288745297,
   "center": {
    "lat": 43.272702,
    "lon": 41.6918902
   },
   "tags": {
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 288745303,
   "center": {
    "lat": 43.2784549,
    "lon": 41.6773852
   },
   "tags": {
    "intermittent": "yes",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 288745304,
   "center": {
    "lat": 43.2787764,
    "lon": 41.6710558
   },
   "tags": {
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 288745306,
   "center": {
    "lat": 43.2786847,
    "lon": 41.6684607
   },
   "tags": {
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 291228221,
   "center": {
    "lat": 43.248601,
    "lon": 41.7521072
   },
   "tags": {
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 291228223,
   "center": {
    "lat": 43.2566613,
    "lon": 41.7446286
   },
   "tags": {
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 291228225,
   "center": {
    "lat": 43.2451324,
    "lon": 41.7557949
   },
   "tags": {
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 291488216,
   "center": {
    "lat": 43.2589599,
    "lon": 41.7524938
   },
   "tags": {
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 291488226,
   "center": {
    "lat": 43.2319591,
    "lon": 41.7326245
   },
   "tags": {
    "natural": "glacier"
   }
  },
  {
   "type": "way",
   "id": 297052727,
   "center": {
    "lat": 43.2772685,
    "lon": 41.6565892
   },
   "tags": {
    "name": "Домбай-Ульген",
    "waterway": "river"
   }
  },
  {
   "type": "way",
   "id": 299803678,
   "center": {
    "lat": 43.2694423,
    "lon": 41.6905146
   },
   "tags": {
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 319460527,
   "center": {
    "lat": 43.2733693,
    "lon": 41.6783767
   },
   "tags": {
    "intermittent": "yes",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 319460530,
   "center": {
    "lat": 43.3082664,
    "lon": 41.6809679
   },
   "tags": {
    "highway": "path",
    "informal": "yes",
    "note": "Notify rescue team at chairlifts before  going to this route",
    "sac_scale": "demanding_alpine_hiking",
    "surface": "bare_rock",
    "trail_visibility": "bad"
   }
  },
  {
   "type": "way",
   "id": 411097851,
   "center": {
    "lat": 43.277069,
    "lon": 41.6608271
   },
   "tags": {
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 448857822,
   "center": {
    "lat": 43.267054,
    "lon": 41.7205542
   },
   "tags": {
    "natural": "water"
   }
  },
  {
   "type": "way",
   "id": 703156422,
   "center": {
    "lat": 43.2618897,
    "lon": 41.6640374
   },
   "tags": {
    "natural": "glacier"
   }
  },
  {
   "type": "way",
   "id": 703401754,
   "center": {
    "lat": 43.2363553,
    "lon": 41.6850123
   },
   "tags": {
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 703401755,
   "center": {
    "lat": 43.2484811,
    "lon": 41.6779125
   },
   "tags": {
    "intermittent": "yes",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 703401756,
   "center": {
    "lat": 43.242737,
    "lon": 41.684762
   },
   "tags": {
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 703401757,
   "center": {
    "lat": 43.2476674,
    "lon": 41.6847123
   },
   "tags": {
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 703401758,
   "center": {
    "lat": 43.2398354,
    "lon": 41.6802272
   },
   "tags": {
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 703401759,
   "center": {
    "lat": 43.2404216,
    "lon": 41.6848057
   },
   "tags": {
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 703401760,
   "center": {
    "lat": 43.2394875,
    "lon": 41.6872224
   },
   "tags": {
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 703401761,
   "center": {
    "lat": 43.2446371,
    "lon": 41.6846207
   },
   "tags": {
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 703862907,
   "center": {
    "lat": 43.2676517,
    "lon": 41.7159529
   },
   "tags": {
    "intermittent": "yes",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 703862908,
   "center": {
    "lat": 43.2676192,
    "lon": 41.7183562
   },
   "tags": {
    "natural": "water"
   }
  },
  {
   "type": "way",
   "id": 703862909,
   "center": {
    "lat": 43.2661849,
    "lon": 41.7111994
   },
   "tags": {
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 703862910,
   "center": {
    "lat": 43.2653987,
    "lon": 41.7075737
   },
   "tags": {
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 703862911,
   "center": {
    "lat": 43.2657273,
    "lon": 41.6979155
   },
   "tags": {
    "intermittent": "yes",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 703862912,
   "center": {
    "lat": 43.2655481,
    "lon": 41.6982396
   },
   "tags": {
    "natural": "water"
   }
  },
  {
   "type": "way",
   "id": 703862921,
   "center": {
    "lat": 43.2480337,
    "lon": 41.7031372
   },
   "tags": {
    "intermittent": "yes",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 703862922,
   "center": {
    "lat": 43.2495107,
    "lon": 41.716826
   },
   "tags": {
    "natural": "glacier"
   }
  },
  {
   "type": "way",
   "id": 703862923,
   "center": {
    "lat": 43.2454802,
    "lon": 41.7015722
   },
   "tags": {
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 703862924,
   "center": {
    "lat": 43.2403376,
    "lon": 41.7082912
   },
   "tags": {
    "natural": "glacier"
   }
  },
  {
   "type": "way",
   "id": 703862925,
   "center": {
    "lat": 43.2334834,
    "lon": 41.6965863
   },
   "tags": {
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 704534968,
   "center": {
    "lat": 43.2309305,
    "lon": 41.7262502
   },
   "tags": {
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 860031001,
   "center": {
    "lat": 43.2906373,
    "lon": 41.7591625
   },
   "tags": {
    "boat": "yes",
    "name": "Буульген",
    "name:en": "Buulgen",
    "source": "landsat",
    "waterway": "river"
   }
  },
  {
   "type": "way",
   "id": 860031002,
   "center": {
    "lat": 43.2855967,
    "lon": 41.7580959
   },
   "tags": {
    "boat": "yes",
    "name": "Буульген",
    "name:en": "Buulgen",
    "source": "landsat",
    "waterway": "river"
   }
  },
  {
   "type": "way",
   "id": 1232396853,
   "center": {
    "lat": 43.2613482,
    "lon": 41.7391829
   },
   "tags": {
    "waterway": "stream"
   }
  },
  {
   "type": "relation",
   "id": 3869132,
   "center": {
    "lat": 43.2379373,
    "lon": 41.6719043
   },
   "tags": {
    "name": "Агбек",
    "name:en": "Ageyek Glacier",
    "natural": "glacier",
    "type": "multipolygon"
   }
  },
  {
   "type": "relation",
   "id": 3869137,
   "center": {
    "lat": 43.2490282,
    "lon": 41.667873
   },
   "tags": {
    "natural": "bare_rock",
    "type": "multipolygon"
   }
  },
  {
   "type": "relation",
   "id": 4437739,
   "center": {
    "lat": 43.225919,
    "lon": 41.7200714
   },
   "tags": {
    "natural": "glacier",
    "type": "multipolygon"
   }
  },
  {
   "type": "relation",
   "id": 6660525,
   "center": {
    "lat": 43.2471828,
    "lon": 41.7364003
   },
   "tags": {
    "natural": "glacier",
    "type": "multipolygon"
   }
  },
  {
   "type": "relation",
   "id": 6660529,
   "center": {
    "lat": 43.2868501,
    "lon": 41.7173191
   },
   "tags": {
    "natural": "glacier",
    "type": "multipolygon"
   }
  },
  {
   "type": "relation",
   "id": 6660531,
   "center": {
    "lat": 43.2841323,
    "lon": 41.7140683
   },
   "tags": {
    "natural": "glacier",
    "type": "multipolygon"
   }
  },
  {
   "type": "relation",
   "id": 6660535,
   "center": {
    "lat": 43.2858192,
    "lon": 41.7061504
   },
   "tags": {
    "natural": "glacier",
    "type": "multipolygon"
   }
  },
  {
   "type": "relation",
   "id": 6660539,
   "center": {
    "lat": 43.2606152,
    "lon": 41.7330422
   },
   "tags": {
    "natural": "glacier",
    "type": "multipolygon"
   }
  },
  {
   "type": "relation",
   "id": 6660542,
   "center": {
    "lat": 43.2528774,
    "lon": 41.7315686
   },
   "tags": {
    "natural": "glacier",
    "type": "multipolygon"
   }
  },
  {
   "type": "relation",
   "id": 6660543,
   "center": {
    "lat": 43.2461444,
    "lon": 41.7174643
   },
   "tags": {
    "natural": "glacier",
    "type": "multipolygon"
   }
  },
  {
   "type": "relation",
   "id": 6660545,
   "center": {
    "lat": 43.2291726,
    "lon": 41.7706955
   },
   "tags": {
    "name": "Буульген",
    "name:en": "Buulgen Glacier",
    "natural": "glacier",
    "type": "multipolygon"
   }
  },
  {
   "type": "relation",
   "id": 6660547,
   "center": {
    "lat": 43.2277229,
    "lon": 41.6971895
   },
   "tags": {
    "name": "Птыш",
    "name:en": "Ptish Glacier",
    "natural": "glacier",
    "type": "multipolygon"
   }
  },
  {
   "type": "relation",
   "id": 6663998,
   "center": {
    "lat": 43.2264334,
    "lon": 41.6723764
   },
   "tags": {
    "natural": "glacier",
    "type": "multipolygon"
   }
  },
  {
   "type": "relation",
   "id": 6663999,
   "center": {
    "lat": 43.2309767,
    "lon": 41.6580012
   },
   "tags": {
    "natural": "glacier",
    "type": "multipolygon"
   }
  },
  {
   "type": "relation",
   "id": 6664002,
   "center": {
    "lat": 43.2536812,
    "lon": 41.668528
   },
   "tags": {
    "natural": "glacier",
    "type": "multipolygon"
   }
  },
  {
   "type": "relation",
   "id": 6664005,
   "center": {
    "lat": 43.2540443,
    "lon": 41.6509837
   },
   "tags": {
    "name": "Северный Джугутурлючат",
    "natural": "glacier",
    "type": "multipolygon"
   }
  },
  {
   "type": "relation",
   "id": 9774320,
   "center": {
    "lat": 43.2462913,
    "lon": 41.661956
   },
   "tags": {
    "natural": "glacier",
    "type": "multipolygon"
   }
  },
  {
   "type": "relation",
   "id": 9786905,
   "center": {
    "lat": 43.2653704,
    "lon": 41.7179793
   },
   "tags": {
    "natural": "water",
    "type": "multipolygon"
   }
  },
  {
   "type": "relation",
   "id": 9786906,
   "center": {
    "lat": 43.2586625,
    "lon": 41.7187303
   },
   "tags": {
    "natural": "glacier",
    "type": "multipolygon"
   }
  }
 ]
}
```

Create `skills/osm-day-route-day-plan/tests/fixtures/osm_features_casa_de_campo.json`:

```json
{
 "elements": [
  {
   "type": "node",
   "id": 13760335456,
   "lat": 40.4109054,
   "lon": -3.7382121,
   "tags": {
    "communication:mobile_phone": "yes",
    "man_made": "tower",
    "tower:type": "communication"
   }
  },
  {
   "type": "node",
   "id": 13760335457,
   "lat": 40.4103373,
   "lon": -3.7387971,
   "tags": {
    "communication:mobile_phone": "yes",
    "man_made": "tower",
    "tower:type": "communication"
   }
  },
  {
   "type": "way",
   "id": 8820665,
   "center": {
    "lat": 40.4381631,
    "lon": -3.7383476
   },
   "tags": {
    "name": "Río Manzanares",
    "waterway": "river"
   }
  },
  {
   "type": "way",
   "id": 121098528,
   "center": {
    "lat": 40.4340002,
    "lon": -3.7460888
   },
   "tags": {
    "barrier": "fence",
    "designation": "Estanque del Repartidor",
    "name": "Estanque del Repartidor",
    "natural": "water",
    "url": "http://www.monumentamadrid.es/AM_Monumentos5/AM_Monumentos5_WEB/pdf/pdfP/mon5/8619.pdf",
    "water": "pond",
    "wikidata": "Q110746795"
   }
  },
  {
   "type": "way",
   "id": 122057547,
   "center": {
    "lat": 40.4342726,
    "lon": -3.7260197
   },
   "tags": {
    "highway": "path",
    "sac_scale": "hiking",
    "smoothness": "bad",
    "surface": "cobblestone"
   }
  },
  {
   "type": "way",
   "id": 122057583,
   "center": {
    "lat": 40.4348343,
    "lon": -3.7242736
   },
   "tags": {
    "highway": "path",
    "sac_scale": "hiking",
    "surface": "paving_stones"
   }
  },
  {
   "type": "way",
   "id": 122057688,
   "center": {
    "lat": 40.434301,
    "lon": -3.7258434
   },
   "tags": {
    "name": "Arroyo de San Bernardino",
    "waterway": "canal",
    "wikidata": "Q30071168",
    "wikipedia": "es:Manantial de la Salud del arroyo de San Bernardino"
   }
  },
  {
   "type": "way",
   "id": 122099420,
   "center": {
    "lat": 40.4293783,
    "lon": -3.7285465
   },
   "tags": {
    "natural": "water",
    "water": "pond"
   }
  },
  {
   "type": "way",
   "id": 129804508,
   "center": {
    "lat": 40.4156774,
    "lon": -3.7704505
   },
   "tags": {
    "intermittent": "yes",
    "name": "Arroyo de la Zorra",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 129804516,
   "center": {
    "lat": 40.4140411,
    "lon": -3.7484285
   },
   "tags": {
    "name": "Arroyo de los Meaques",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 129805207,
   "center": {
    "lat": 40.420525,
    "lon": -3.7625664
   },
   "tags": {
    "intermittent": "yes",
    "name": "Arroyo de la Zarza",
    "seasonal": "yes",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 129805208,
   "center": {
    "lat": 40.4280431,
    "lon": -3.7503346
   },
   "tags": {
    "name": "Arroyo de Valdeza",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 129908806,
   "center": {
    "lat": 40.4272674,
    "lon": -3.7618932
   },
   "tags": {
    "name": "Arroyo de Valdeza",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 129908807,
   "center": {
    "lat": 40.4257935,
    "lon": -3.7446464
   },
   "tags": {
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 129908808,
   "center": {
    "lat": 40.4227428,
    "lon": -3.7440162
   },
   "tags": {
    "intermittent": "yes",
    "name": "Barranco de los Romeros",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 129909147,
   "center": {
    "lat": 40.4234813,
    "lon": -3.7488424
   },
   "tags": {
    "intermittent": "yes",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 130669458,
   "center": {
    "lat": 40.4407059,
    "lon": -3.7547989
   },
   "tags": {
    "highway": "path",
    "sac_scale": "hiking",
    "surface": "ground",
    "trail_visibility": "excellent"
   }
  },
  {
   "type": "way",
   "id": 223118485,
   "center": {
    "lat": 40.4130533,
    "lon": -3.7484602
   },
   "tags": {
    "name": "Aserradero",
    "waterway": "canal"
   }
  },
  {
   "type": "way",
   "id": 223118486,
   "center": {
    "lat": 40.4129769,
    "lon": -3.7484554
   },
   "tags": {
    "bridge": "aqueduct",
    "name": "Aserradero",
    "waterway": "canal"
   }
  },
  {
   "type": "way",
   "id": 223118487,
   "center": {
    "lat": 40.4129083,
    "lon": -3.7481661
   },
   "tags": {
    "layer": "-1",
    "name": "Aserradero",
    "tunnel": "yes",
    "waterway": "canal"
   }
  },
  {
   "type": "way",
   "id": 223118488,
   "center": {
    "lat": 40.4129894,
    "lon": -3.748384
   },
   "tags": {
    "name": "Aserradero",
    "waterway": "canal"
   }
  },
  {
   "type": "way",
   "id": 223118491,
   "center": {
    "lat": 40.4110759,
    "lon": -3.7526471
   },
   "tags": {
    "bridge": "aqueduct",
    "layer": "1",
    "waterway": "canal"
   }
  },
  {
   "type": "way",
   "id": 223118492,
   "center": {
    "lat": 40.4108344,
    "lon": -3.7521075
   },
   "tags": {
    "name": "Los Fiordos",
    "waterway": "canal"
   }
  },
  {
   "type": "way",
   "id": 223118493,
   "center": {
    "lat": 40.4118856,
    "lon": -3.7527006
   },
   "tags": {
    "name": "Los Rápidos",
    "tunnel": "yes",
    "waterway": "canal"
   }
  },
  {
   "type": "way",
   "id": 223118494,
   "center": {
    "lat": 40.412244,
    "lon": -3.7521663
   },
   "tags": {
    "layer": "-1",
    "name": "Los Rápidos",
    "waterway": "canal"
   }
  },
  {
   "type": "way",
   "id": 309666645,
   "center": {
    "lat": 40.4136918,
    "lon": -3.7532762
   },
   "tags": {
    "natural": "water",
    "water": "reservoir"
   }
  },
  {
   "type": "way",
   "id": 309666646,
   "center": {
    "lat": 40.4129166,
    "lon": -3.7541667
   },
   "tags": {
    "natural": "water",
    "water": "reservoir"
   }
  },
  {
   "type": "way",
   "id": 309666647,
   "center": {
    "lat": 40.414104,
    "lon": -3.7521044
   },
   "tags": {
    "natural": "water",
    "water": "reservoir"
   }
  },
  {
   "type": "way",
   "id": 309666648,
   "center": {
    "lat": 40.4159329,
    "lon": -3.7451342
   },
   "tags": {
    "natural": "water",
    "water": "reservoir"
   }
  },
  {
   "type": "way",
   "id": 309666650,
   "center": {
    "lat": 40.4160074,
    "lon": -3.744537
   },
   "tags": {
    "natural": "water",
    "water": "reservoir"
   }
  },
  {
   "type": "way",
   "id": 309764875,
   "center": {
    "lat": 40.4179345,
    "lon": -3.7285232
   },
   "tags": {
    "access": "yes",
    "alt_name": "Acueducto de Sabatini",
    "architect": "Francisco Sabatini",
    "bridge": "aqueduct",
    "historic": "ruins",
    "historic:civilization": "modern",
    "inscription": "Francisco Sabatini siglo XVIII",
    "name": "Acueducto del Canal de La Partida",
    "ruins": "wall",
    "start_date": "1778",
    "waterway": "stream",
    "wikidata": "Q47798997",
    "wikipedia": "es:Acueducto de Sabatini"
   }
  },
  {
   "type": "way",
   "id": 335246479,
   "center": {
    "lat": 40.4357628,
    "lon": -3.7227061
   },
   "tags": {
    "natural": "water",
    "water": "pond"
   }
  },
  {
   "type": "way",
   "id": 432765281,
   "center": {
    "lat": 40.4342707,
    "lon": -3.7258722
   },
   "tags": {
    "waterway": "canal"
   }
  },
  {
   "type": "way",
   "id": 445382245,
   "center": {
    "lat": 40.4170615,
    "lon": -3.7355064
   },
   "tags": {
    "name": "Arroyo de los Meaques",
    "waterway": "canal"
   }
  },
  {
   "type": "way",
   "id": 445387931,
   "center": {
    "lat": 40.4174584,
    "lon": -3.7343735
   },
   "tags": {
    "layer": "-1",
    "name": "Arroyo de los Meaques",
    "tunnel": "culvert",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 445395055,
   "center": {
    "lat": 40.438365,
    "lon": -3.7513198
   },
   "tags": {
    "natural": "water",
    "water": "pond"
   }
  },
  {
   "type": "way",
   "id": 445590408,
   "center": {
    "lat": 40.4181878,
    "lon": -3.7265759
   },
   "tags": {
    "layer": "-3",
    "name": "Arroyo Meaques",
    "tunnel": "culvert",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 450126606,
   "center": {
    "lat": 40.4353545,
    "lon": -3.7228039
   },
   "tags": {
    "highway": "path",
    "lit": "yes",
    "sac_scale": "hiking",
    "surface": "dirt"
   }
  },
  {
   "type": "way",
   "id": 548816611,
   "center": {
    "lat": 40.4295918,
    "lon": -3.7241608
   },
   "tags": {
    "amenity": "fountain",
    "historic": "monument",
    "name": "Fuente Juan de Villanueva",
    "natural": "water",
    "water": "basin",
    "wikidata": "Q5870188",
    "wikimedia_commons": "Category:Fountain of Juan de Villanueva",
    "wikipedia": "es:Fuente de Juan de Villanueva"
   }
  },
  {
   "type": "way",
   "id": 548819802,
   "center": {
    "lat": 40.4309553,
    "lon": -3.7309192
   },
   "tags": {
    "amenity": "fountain",
    "natural": "water",
    "water": "basin"
   }
  },
  {
   "type": "way",
   "id": 561756313,
   "center": {
    "lat": 40.4108188,
    "lon": -3.7500227
   },
   "tags": {
    "amenity": "fountain",
    "barrier": "wall",
    "natural": "water"
   }
  },
  {
   "type": "way",
   "id": 575488005,
   "center": {
    "lat": 40.4395693,
    "lon": -3.7295018
   },
   "tags": {
    "amenity": "fountain",
    "barrier": "kerb",
    "natural": "water"
   }
  },
  {
   "type": "way",
   "id": 575501497,
   "center": {
    "lat": 40.4300564,
    "lon": -3.7237262
   },
   "tags": {
    "amenity": "fountain",
    "barrier": "kerb",
    "natural": "water"
   }
  },
  {
   "type": "way",
   "id": 732747735,
   "center": {
    "lat": 40.428801,
    "lon": -3.7512926
   },
   "tags": {
    "natural": "water"
   }
  },
  {
   "type": "way",
   "id": 764386652,
   "center": {
    "lat": 40.4341924,
    "lon": -3.729445
   },
   "tags": {
    "natural": "water",
    "water": "pond"
   }
  },
  {
   "type": "way",
   "id": 788666908,
   "center": {
    "lat": 40.4109687,
    "lon": -3.7521962
   },
   "tags": {
    "natural": "water",
    "water": "pond"
   }
  },
  {
   "type": "way",
   "id": 788839448,
   "center": {
    "lat": 40.4111988,
    "lon": -3.7509254
   },
   "tags": {
    "natural": "water",
    "water": "pond"
   }
  },
  {
   "type": "way",
   "id": 825499894,
   "center": {
    "lat": 40.4274688,
    "lon": -3.730294
   },
   "tags": {
    "name": "Arroyo de Valdeza",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 825499895,
   "center": {
    "lat": 40.426294,
    "lon": -3.7343376
   },
   "tags": {
    "name": "Arroyo de Valdeza",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 825499896,
   "center": {
    "lat": 40.4260751,
    "lon": -3.7351694
   },
   "tags": {
    "layer": "-1",
    "name": "Arroyo de Valdeza",
    "tunnel": "culvert",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 825499897,
   "center": {
    "lat": 40.4269026,
    "lon": -3.7321313
   },
   "tags": {
    "layer": "-1",
    "name": "Arroyo de Valdeza",
    "tunnel": "culvert",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 1019243608,
   "center": {
    "lat": 40.4358922,
    "lon": -3.7567805
   },
   "tags": {
    "natural": "water",
    "water": "pond"
   }
  },
  {
   "type": "way",
   "id": 1207550839,
   "center": {
    "lat": 40.4274248,
    "lon": -3.7555472
   },
   "tags": {
    "natural": "water",
    "water": "pond"
   }
  },
  {
   "type": "way",
   "id": 1207550840,
   "center": {
    "lat": 40.4240863,
    "lon": -3.7555758
   },
   "tags": {
    "natural": "water",
    "water": "pond"
   }
  },
  {
   "type": "way",
   "id": 1239195924,
   "center": {
    "lat": 40.4381521,
    "lon": -3.7388225
   },
   "tags": {
    "landuse": "industrial"
   }
  },
  {
   "type": "way",
   "id": 1239195940,
   "center": {
    "lat": 40.4330674,
    "lon": -3.7289006
   },
   "tags": {
    "natural": "water",
    "water": "pond"
   }
  },
  {
   "type": "way",
   "id": 1259162210,
   "center": {
    "lat": 40.4129717,
    "lon": -3.7484883
   },
   "tags": {
    "natural": "water",
    "water": "lake"
   }
  },
  {
   "type": "way",
   "id": 1288951590,
   "center": {
    "lat": 40.4275835,
    "lon": -3.7572924
   },
   "tags": {
    "name": "Arroyo de Valdeza",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 1288951591,
   "center": {
    "lat": 40.4275357,
    "lon": -3.7574748
   },
   "tags": {
    "layer": "-1",
    "name": "Arroyo de Valdeza",
    "tunnel": "culvert",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 1306326450,
   "center": {
    "lat": 40.4264479,
    "lon": -3.7220638
   },
   "tags": {
    "natural": "water",
    "water": "pond"
   }
  },
  {
   "type": "way",
   "id": 1323358977,
   "center": {
    "lat": 40.4259254,
    "lon": -3.7419142
   },
   "tags": {
    "tunnel": "yes",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 1323358978,
   "center": {
    "lat": 40.4261319,
    "lon": -3.7413337
   },
   "tags": {
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 1323359473,
   "center": {
    "lat": 40.4270827,
    "lon": -3.7434083
   },
   "tags": {
    "name": "Arroyo de Valdeza",
    "tunnel": "yes",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 1323359474,
   "center": {
    "lat": 40.4263486,
    "lon": -3.7394669
   },
   "tags": {
    "name": "Arroyo de Valdeza",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 1330837898,
   "center": {
    "lat": 40.4339052,
    "lon": -3.727421
   },
   "tags": {
    "highway": "path",
    "sac_scale": "hiking"
   }
  },
  {
   "type": "way",
   "id": 1332572097,
   "center": {
    "lat": 40.4274669,
    "lon": -3.7579724
   },
   "tags": {
    "name": "Arroyo de Valdeza",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 1332572098,
   "center": {
    "lat": 40.4274215,
    "lon": -3.7584383
   },
   "tags": {
    "layer": "-1",
    "name": "Arroyo de Valdeza",
    "tunnel": "culvert",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 1333033490,
   "center": {
    "lat": 40.4202325,
    "lon": -3.7492465
   },
   "tags": {
    "intermittent": "yes",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 1335583525,
   "center": {
    "lat": 40.4356254,
    "lon": -3.7228429
   },
   "tags": {
    "name": "Arroyo de San Bernardino",
    "waterway": "canal",
    "wikidata": "Q30071168",
    "wikipedia": "es:Manantial de la Salud del arroyo de San Bernardino"
   }
  },
  {
   "type": "way",
   "id": 1335583526,
   "center": {
    "lat": 40.4355615,
    "lon": -3.7228668
   },
   "tags": {
    "layer": "-1",
    "name": "Arroyo de San Bernardino",
    "tunnel": "culvert",
    "waterway": "canal",
    "wikidata": "Q30071168",
    "wikipedia": "es:Manantial de la Salud del arroyo de San Bernardino"
   }
  },
  {
   "type": "way",
   "id": 1340233496,
   "center": {
    "lat": 40.4160275,
    "lon": -3.722638
   },
   "tags": {
    "name": "Río Manzanares",
    "tunnel": "culvert",
    "waterway": "river"
   }
  },
  {
   "type": "way",
   "id": 1340233497,
   "center": {
    "lat": 40.4173276,
    "lon": -3.7222985
   },
   "tags": {
    "name": "Río Manzanares",
    "waterway": "river"
   }
  },
  {
   "type": "way",
   "id": 1340233501,
   "center": {
    "lat": 40.423766,
    "lon": -3.7253442
   },
   "tags": {
    "layer": "-1",
    "name": "Río Manzanares",
    "tunnel": "culvert",
    "waterway": "river"
   }
  },
  {
   "type": "way",
   "id": 1340233502,
   "center": {
    "lat": 40.4211824,
    "lon": -3.7236119
   },
   "tags": {
    "name": "Río Manzanares",
    "waterway": "river"
   }
  },
  {
   "type": "way",
   "id": 1340233504,
   "center": {
    "lat": 40.4314629,
    "lon": -3.7347908
   },
   "tags": {
    "name": "Río Manzanares",
    "waterway": "river"
   }
  },
  {
   "type": "way",
   "id": 1340233505,
   "center": {
    "lat": 40.4315574,
    "lon": -3.734813
   },
   "tags": {
    "layer": "-1",
    "name": "Río Manzanares",
    "tunnel": "culvert",
    "waterway": "river"
   }
  },
  {
   "type": "way",
   "id": 1340233506,
   "center": {
    "lat": 40.4276305,
    "lon": -3.7301686
   },
   "tags": {
    "name": "Río Manzanares",
    "waterway": "river"
   }
  },
  {
   "type": "way",
   "id": 1340233507,
   "center": {
    "lat": 40.4314978,
    "lon": -3.7349881
   },
   "tags": {
    "layer": "-1",
    "name": "Río Manzanares",
    "tunnel": "culvert",
    "waterway": "river"
   }
  },
  {
   "type": "way",
   "id": 1340233508,
   "center": {
    "lat": 40.4316588,
    "lon": -3.7349114
   },
   "tags": {
    "name": "Río Manzanares",
    "waterway": "river"
   }
  },
  {
   "type": "way",
   "id": 1340243110,
   "center": {
    "lat": 40.4116422,
    "lon": -3.722383
   },
   "tags": {
    "name": "Río Manzanares",
    "waterway": "river"
   }
  },
  {
   "type": "way",
   "id": 1424653063,
   "center": {
    "lat": 40.4383496,
    "lon": -3.7219425
   },
   "tags": {
    "amenity": "fountain",
    "barrier": "wall",
    "height": "0.5",
    "natural": "water",
    "source": "Bing"
   }
  },
  {
   "type": "way",
   "id": 1424653072,
   "center": {
    "lat": 40.4378634,
    "lon": -3.7212403
   },
   "tags": {
    "natural": "water"
   }
  },
  {
   "type": "way",
   "id": 1489982296,
   "center": {
    "lat": 40.4339741,
    "lon": -3.7273598
   },
   "tags": {
    "highway": "path",
    "sac_scale": "hiking",
    "smoothness": "bad",
    "surface": "cobblestone"
   }
  },
  {
   "type": "way",
   "id": 1500866914,
   "center": {
    "lat": 40.41655,
    "lon": -3.7547743
   },
   "tags": {
    "intermittent": "yes",
    "name": "Arroyo de la Zarza",
    "seasonal": "yes",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 1500866915,
   "center": {
    "lat": 40.4184433,
    "lon": -3.7583526
   },
   "tags": {
    "intermittent": "yes",
    "layer": "-1",
    "name": "Arroyo de la Zarza",
    "seasonal": "yes",
    "tunnel": "culvert",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 1501200019,
   "center": {
    "lat": 40.4130387,
    "lon": -3.7580196
   },
   "tags": {
    "intermittent": "yes",
    "layer": "-1",
    "name": "Arroyo de la Zorra",
    "tunnel": "culvert",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 1501200020,
   "center": {
    "lat": 40.4131723,
    "lon": -3.7589007
   },
   "tags": {
    "intermittent": "yes",
    "name": "Arroyo de la Zorra",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 1501200021,
   "center": {
    "lat": 40.4133522,
    "lon": -3.7597584
   },
   "tags": {
    "intermittent": "yes",
    "layer": "-1",
    "name": "Arroyo de la Zorra",
    "tunnel": "culvert",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 1501200022,
   "center": {
    "lat": 40.4124066,
    "lon": -3.7571015
   },
   "tags": {
    "intermittent": "yes",
    "name": "Arroyo de la Zorra",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 1501200023,
   "center": {
    "lat": 40.4197973,
    "lon": -3.7352104
   },
   "tags": {
    "layer": "-1",
    "name": "Barranco de los Romeros",
    "tunnel": "yes",
    "waterway": "stream"
   }
  },
  {
   "type": "way",
   "id": 1510283641,
   "center": {
    "lat": 40.4125019,
    "lon": -3.7518672
   },
   "tags": {
    "natural": "water",
    "water": "pond"
   }
  },
  {
   "type": "way",
   "id": 1510283642,
   "center": {
    "lat": 40.412245,
    "lon": -3.7517701
   },
   "tags": {
    "natural": "water",
    "water": "pond"
   }
  },
  {
   "type": "way",
   "id": 1510283643,
   "center": {
    "lat": 40.4124047,
    "lon": -3.7519316
   },
   "tags": {
    "natural": "water",
    "water": "pond"
   }
  },
  {
   "type": "way",
   "id": 1510283646,
   "center": {
    "lat": 40.4118869,
    "lon": -3.7521166
   },
   "tags": {
    "natural": "water",
    "water": "pond"
   }
  },
  {
   "type": "way",
   "id": 1510283649,
   "center": {
    "lat": 40.4119804,
    "lon": -3.7525142
   },
   "tags": {
    "layer": "-1",
    "name": "Los Rápidos",
    "waterway": "canal"
   }
  },
  {
   "type": "way",
   "id": 1510283650,
   "center": {
    "lat": 40.4119861,
    "lon": -3.7520951
   },
   "tags": {
    "layer": "-1",
    "name": "Los Rápidos",
    "tunnel": "culvert",
    "waterway": "canal"
   }
  },
  {
   "type": "way",
   "id": 1510283651,
   "center": {
    "lat": 40.4121734,
    "lon": -3.7524935
   },
   "tags": {
    "natural": "water",
    "water": "pond"
   }
  },
  {
   "type": "way",
   "id": 1510283664,
   "center": {
    "lat": 40.4122449,
    "lon": -3.7521807
   },
   "tags": {
    "natural": "water",
    "water": "canal"
   }
  },
  {
   "type": "way",
   "id": 1510283668,
   "center": {
    "lat": 40.4126425,
    "lon": -3.7516438
   },
   "tags": {
    "natural": "water",
    "water": "pond"
   }
  },
  {
   "type": "way",
   "id": 1510283689,
   "center": {
    "lat": 40.4120195,
    "lon": -3.750192
   },
   "tags": {
    "natural": "water",
    "water": "pond"
   }
  },
  {
   "type": "way",
   "id": 1510551683,
   "center": {
    "lat": 40.4107685,
    "lon": -3.7526195
   },
   "tags": {
    "bridge": "aqueduct",
    "layer": "1",
    "name": "Los Fiordos",
    "waterway": "canal"
   }
  },
  {
   "type": "way",
   "id": 1510739618,
   "center": {
    "lat": 40.4118254,
    "lon": -3.7487334
   },
   "tags": {
    "name": "La Jungla",
    "waterway": "canal"
   }
  },
  {
   "type": "way",
   "id": 1510739632,
   "center": {
    "lat": 40.4120914,
    "lon": -3.7490141
   },
   "tags": {
    "waterway": "river"
   }
  },
  {
   "type": "way",
   "id": 1550376429,
   "center": {
    "lat": 40.4352557,
    "lon": -3.7233187
   },
   "tags": {
    "highway": "path",
    "lit": "yes",
    "sac_scale": "hiking",
    "surface": "dirt"
   }
  },
  {
   "type": "relation",
   "id": 3615910,
   "center": {
    "lat": 40.4153974,
    "lon": -3.7175737
   },
   "tags": {
    "natural": "water",
    "type": "multipolygon",
    "water": "river"
   }
  },
  {
   "type": "relation",
   "id": 4136921,
   "center": {
    "lat": 40.4144747,
    "lon": -3.7494298
   },
   "tags": {
    "natural": "water",
    "type": "multipolygon",
    "water": "reservoir"
   }
  },
  {
   "type": "relation",
   "id": 10966919,
   "center": {
    "lat": 40.4118053,
    "lon": -3.7487393
   },
   "tags": {
    "name": "La Jungla",
    "natural": "water",
    "type": "multipolygon",
    "water": "canal"
   }
  },
  {
   "type": "relation",
   "id": 18080549,
   "center": {
    "lat": 40.4273253,
    "lon": -3.7497076
   },
   "tags": {
    "natural": "water",
    "type": "multipolygon"
   }
  },
  {
   "type": "relation",
   "id": 18273245,
   "center": {
    "lat": 40.4188234,
    "lon": -3.7319318
   },
   "tags": {
    "name": "Lago de la Casa de Campo",
    "natural": "water",
    "type": "multipolygon",
    "water": "lake",
    "wikidata": "Q5968929",
    "wikipedia": "es:Lago de la Casa de Campo"
   }
  }
 ]
}
```

- [ ] **Step 4: Run the whole suite** — `cd skills/osm-day-route-day-plan && python3 -m pytest tests -q` (all green), and for the show skill `cd skills/osm-day-route-show && python3 -m pytest tests -q`.

- [ ] **Step 5: Commit**

```bash
git add skills README.md
git commit -m "Shared OSM features (one Overpass query) and text HTTP for the hazard parts

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

### Task 4: Fire danger: GWIS Fire Weather Index, Nesterov, active fires

Deviation from the spec (rule agreed in plan-3 decomposition): the official Fire Weather Index from the Copernicus GWIS WMS (`ecmwf.query`, global, no key, horizon 8 days) replaces the spec's own stdlib FWI, and GWIS VIIRS hotspots (`viirs.hs.query`) replace NASA FIRMS, which needs a key. The Nesterov class (Rosleskhoz order No. 287) is computed for Russian routes only. A GWIS failure degrades to a no-data line and never breaks the plan.

**Files:**
- Create: `skills/osm-day-route-day-plan/tests/test_gwis.py`
- Create: `skills/osm-day-route-day-plan/tests/test_fire_index.py`
- Create: `skills/osm-day-route-day-plan/tests/test_fire.py`
- Create: `skills/osm-day-route-day-plan/scripts/day_plan/gwis.py`
- Create: `skills/osm-day-route-day-plan/scripts/day_plan/fire_index.py`
- Create: `skills/osm-day-route-day-plan/scripts/day_plan/plugins/fire.py`
- Create: `skills/osm-day-route-day-plan/tests/fixtures/gwis_fwi_ekb_2026-09-28.html`
- Create: `skills/osm-day-route-day-plan/tests/fixtures/gwis_hotspots_biscay.html`

- [ ] **Step 1: Add the tests** (63 tests in the file(s) below)

Create `skills/osm-day-route-day-plan/tests/test_gwis.py`:

```python
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
```

Create `skills/osm-day-route-day-plan/tests/test_fire_index.py`:

```python
import datetime

import pytest

from day_plan.fire_index import (
    NESTEROV_DAYS, daily_from_hourly, fwi_class, history_range, kpo_class, nesterov_index,
)


@pytest.mark.parametrize("fwi,cls", [(0.0, "very_low"), (5.19, "very_low"), (5.2, "low"), (11.19, "low"), (11.2, "moderate"),
                                     (21.29, "moderate"), (21.3, "high"), (37.99, "high"), (38.0, "very_high"),
                                     (49.99, "very_high"), (50.0, "extreme"), (120.0, "extreme")])
def test_fwi_classes_follow_the_effis_thresholds(fwi, cls):
    assert fwi_class(fwi) == cls


@pytest.mark.parametrize("value,cls", [(0, 1), (300, 1), (300.5, 2), (1000, 2), (1001, 3), (4000, 3), (4001, 4), (10000, 4),
                                       (10001, 5), (50000, 5)])
def test_kpo_classes_follow_order_287(value, cls):
    assert kpo_class(value) == cls


def _day(date, t, dew, precip=0.0):
    return {"date": date, "t": t, "dew": dew, "precip": precip}


def test_the_index_accumulates_t_times_the_dew_point_deficit_on_dry_days():
    days = [_day("d1", 20.0, 10.0), _day("d2", 25.0, 15.0)]
    assert nesterov_index(days) == pytest.approx(20 * 10 + 25 * 10)


def test_more_than_three_millimetres_of_rain_resets_the_index_and_three_does_not():
    dry = [_day("d1", 20.0, 10.0), _day("d2", 20.0, 10.0)]
    assert nesterov_index(dry + [_day("d3", 20.0, 10.0, precip=3.1)]) == 0.0
    assert nesterov_index(dry + [_day("d3", 20.0, 10.0, precip=3.0)]) == pytest.approx(600.0)
    assert nesterov_index(dry + [_day("d3", 20.0, 10.0, precip=3.5), _day("d4", 10.0, 5.0)]) == pytest.approx(50.0)


def test_frost_days_add_nothing_and_a_dew_point_above_the_temperature_adds_nothing():
    assert nesterov_index([_day("d1", -3.0, -5.0), _day("d2", 0.0, -1.0)]) == 0.0
    assert nesterov_index([_day("d1", 10.0, 12.0)]) == 0.0


def _hourly(days, t=15.0, dew=5.0, rain_per_day=0.0):
    times, temp, dp, rain = [], [], [], []
    for d in days:
        for h in range(24):
            times.append(f"{d}T{h:02d}:00")
            temp.append(t if h == 12 else t - 5)
            dp.append(dew if h == 12 else dew - 3)
            rain.append(rain_per_day / 24)
    return {"hourly": {"time": times, "temperature_2m": temp, "dew_point_2m": dp, "precipitation": rain}}


def test_daily_values_use_noon_and_the_whole_day_of_rain():
    days = daily_from_hourly(_hourly(["2026-09-01", "2026-09-02"], t=15.0, dew=5.0, rain_per_day=2.4))
    assert [d["date"] for d in days] == ["2026-09-01", "2026-09-02"]
    assert days[0]["t"] == 15.0 and days[0]["dew"] == 5.0 and days[0]["precip"] == pytest.approx(2.4)


def test_days_without_a_noon_value_or_with_missing_series_are_skipped():
    response = _hourly(["2026-09-01"])
    response["hourly"]["temperature_2m"][12] = None
    assert daily_from_hourly(response) == []
    bare = {"hourly": {"time": ["2026-09-01T12:00"]}}
    assert daily_from_hourly(bare) == []


def test_history_range_is_thirty_days_back():
    start, end = history_range(datetime.date(2026, 10, 3))
    assert (start, end) == (datetime.date(2026, 9, 3), datetime.date(2026, 10, 3)) and NESTEROV_DAYS == 30
```

Create `skills/osm-day-route-day-plan/tests/test_fire.py`:

```python
import datetime
import json
from pathlib import Path

import pytest

from day_plan.context import build_context
from day_plan.http import HttpError
from day_plan.plugins.fire import FirePlugin, prevailing_wind

FIXTURES = Path(__file__).parent / "fixtures"
FWI_HTML = (FIXTURES / "gwis_fwi_ekb_2026-09-28.html").read_text(encoding="utf-8")
HOTSPOT_HTML = (FIXTURES / "gwis_hotspots_biscay.html").read_text(encoding="utf-8")
TODAY = datetime.date(2026, 6, 20)          # the fixed_now fixture
BISCAY = ((-2.78, 43.21, 200.0), (-2.75, 43.25, 250.0))
EKB = ((60.60, 56.84, 260.0), (60.62, 56.86, 270.0))


def fwi_html(value):
    return FWI_HTML.replace("9.5045595", str(value))


class World:
    """Answers the text (GWIS) and JSON (Nominatim, Open-Meteo) calls of the fire plugin."""
    def __init__(self, fwi=9.5, hotspots=HOTSPOT_HTML, country="es", history=None, fwi_error=None, hotspot_error=None):
        self.fwi, self.hotspots, self.country, self.history = fwi, hotspots, country, history
        self.fwi_error, self.hotspot_error = fwi_error, hotspot_error
        self.text_calls, self.json_calls = [], []

    def text(self, url):
        self.text_calls.append(url)
        if "ecmwf.query" in url:
            if self.fwi_error:
                raise self.fwi_error
            return "" if self.fwi is None else fwi_html(self.fwi)
        if "viirs.hs.query" in url:
            if self.hotspot_error:
                raise self.hotspot_error
            return self.hotspots
        raise AssertionError(url)

    def json(self, url):
        self.json_calls.append(url)
        if "nominatim" in url:
            return {"address": {"country_code": self.country}}
        if "open-meteo" in url:
            if isinstance(self.history, Exception):
                raise self.history
            return self.history
        raise AssertionError(url)


def history(days, t=25.0, dew=10.0, rain=None, end=TODAY + datetime.timedelta(days=3)):
    """`days` days ending at the plan date (the plugin asks Open-Meteo for date-30 .. date)."""
    times, temp, dp, pr = [], [], [], []
    for i in range(days):
        d = (end - datetime.timedelta(days=days - 1 - i)).isoformat()
        for h in range(24):
            times.append(f"{d}T{h:02d}:00")
            temp.append(t)
            dp.append(dew)
            pr.append((rain or {}).get(d, 0.0) / 24)
    return {"hourly": {"time": times, "temperature_2m": temp, "dew_point_2m": dp, "precipitation": pr}}


def run(make_route, fixed_now, world, coords=BISCAY, date=TODAY + datetime.timedelta(days=2), lang="en", shared=None,
        facts=None, folder="route"):
    route_dir = make_route(coords=coords, folder=folder)
    if facts is not None:
        (route_dir / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    ctx = build_context(route_dir, date, lang=lang, http=world.json, http_text=world.text, now=fixed_now)
    return FirePlugin().run(ctx, shared or {})


def test_the_official_fwi_and_its_components_are_shown_with_the_class(make_route, fixed_now):
    section = run(make_route, fixed_now, World(fwi=9.5), date=TODAY + datetime.timedelta(days=3))
    md = section.markdown
    assert "**9.5** — low" in md and "ISI 4.7" in md and "DC 147.0" in md
    assert "Model output" in md and section.confidence == "derived" and section.warnings == []


@pytest.mark.parametrize("fwi,severity", [(22.0, "caution"), (40.0, "danger"), (60.0, "danger")])
def test_high_and_worse_fire_weather_warns(make_route, fixed_now, fwi, severity):
    section = run(make_route, fixed_now, World(fwi=fwi), date=TODAY + datetime.timedelta(days=3))
    assert [w.severity for w in section.warnings] == [severity]
    assert "no open fire" in section.warnings[0].text


def test_beyond_the_eight_day_horizon_there_is_no_query_and_no_data(make_route, fixed_now):
    world = World()
    section = run(make_route, fixed_now, world, date=TODAY + datetime.timedelta(days=9))
    assert "covers about 8 days" in section.markdown and section.confidence == "no-data"
    assert world.text_calls == []


def test_a_service_failure_or_an_empty_value_degrades_to_a_note(make_route, fixed_now):
    down = run(make_route, fixed_now, World(fwi_error=HttpError("503")), date=TODAY + datetime.timedelta(days=3))
    assert "could not be reached (503)" in down.markdown and down.confidence == "no-data" and down.warnings == []
    empty = run(make_route, fixed_now, World(fwi=None), date=TODAY + datetime.timedelta(days=3), folder="empty")
    assert "no value for this point and date" in empty.markdown


def test_active_fires_near_the_route_warn_and_show_the_detection(make_route, fixed_now):
    section = run(make_route, fixed_now, World(fwi=9.5), date=TODAY + datetime.timedelta(days=1))
    md = section.markdown
    assert "Satellite-detected active fires within 15 km" in md and "2026-09-29 02:17:00 UTC" in md
    assert "NOAA-21/VIIRS, confidence High, FRP 0.5 MW" in md
    assert section.warnings[0].severity == "danger" and "active fire was detected" in section.warnings[0].text
    assert section.confidence == "web-sourced"


def test_far_away_detections_are_not_reported_and_none_is_said_plainly(make_route, fixed_now):
    section = run(make_route, fixed_now, World(fwi=9.5), coords=((10.0, 50.0, 100.0), (10.02, 50.02, 110.0)),
                  date=TODAY + datetime.timedelta(days=1))
    assert "No satellite-detected active fires within 15 km" in section.markdown and section.warnings == []


def test_detections_are_only_looked_up_for_dates_around_today(make_route, fixed_now):
    world = World()
    run(make_route, fixed_now, world, date=TODAY + datetime.timedelta(days=5))
    assert not any("viirs" in u for u in world.text_calls)
    run(make_route, fixed_now, world, date=TODAY + datetime.timedelta(days=2), folder="near")
    assert any("viirs" in u for u in world.text_calls)


def test_a_failed_detection_query_is_a_note_not_a_crash(make_route, fixed_now):
    section = run(make_route, fixed_now, World(hotspot_error=HttpError("504")), date=TODAY + datetime.timedelta(days=1))
    assert "could not be loaded (504)" in section.markdown and "FWI" in section.markdown


def test_the_wind_that_would_carry_the_fire_is_added_only_when_the_danger_is_elevated(make_route, fixed_now):
    rows = [{"wind": 6.0, "wdir": 270}, {"wind": 8.5, "wdir": 280}, {"wind": 3.0, "wdir": None}]
    calm = run(make_route, fixed_now, World(fwi=9.5), date=TODAY + datetime.timedelta(days=3),
               shared={"weather": {"daytime_rows": rows}})
    assert "Wind from" not in calm.markdown
    windy = run(make_route, fixed_now, World(fwi=30.0), date=TODAY + datetime.timedelta(days=3),
                shared={"weather": {"daytime_rows": rows}}, folder="windy")
    assert "Wind from W (275°) up to 8.5 m/s: a fire and its smoke would move toward E." in windy.markdown


def test_prevailing_wind_handles_missing_data():
    assert prevailing_wind([]) is None and prevailing_wind([{"wind": 3.0, "wdir": None}]) is None
    assert prevailing_wind([{"wind": 5.0, "wdir": 90}, {"wind": 2.0, "wdir": 270}]) is None      # cancels out


def test_russian_routes_get_the_nesterov_index_and_others_do_not(make_route, fixed_now):
    ru = run(make_route, fixed_now, World(country="ru", history=history(31)), coords=EKB,
             date=TODAY + datetime.timedelta(days=3))
    assert "Nesterov index): **11625** — class V (extreme)" in ru.markdown
    es = run(make_route, fixed_now, World(country="es", history=history(31)), date=TODAY + datetime.timedelta(days=3),
             folder="es")
    assert "Nesterov" not in es.markdown


def test_nesterov_classes_and_warnings(make_route, fixed_now):
    # 25 C with dew point 10: 375 per dry day; 31 days -> 11625 -> class V, a "danger"
    extreme = run(make_route, fixed_now, World(country="ru", history=history(31)), coords=EKB,
                  date=TODAY + datetime.timedelta(days=3))
    assert "**11625** — class V (extreme)" in extreme.markdown
    assert any(w.severity == "danger" and "class V" in w.text for w in extreme.warnings)
    # a wet day resets it: only the days after the rain count
    rain_day = (TODAY + datetime.timedelta(days=3 - 5)).isoformat()
    reset = run(make_route, fixed_now, World(country="ru", history=history(31, rain={rain_day: 10.0})), coords=EKB,
                date=TODAY + datetime.timedelta(days=3), folder="reset")
    assert "**1875** — class III (moderate)" in reset.markdown and not any("Nesterov" in w.text for w in reset.warnings)


def test_a_nesterov_failure_is_a_note(make_route, fixed_now):
    section = run(make_route, fixed_now, World(country="ru", history=HttpError("boom")), coords=EKB,
                  date=TODAY + datetime.timedelta(days=3))
    assert "Nesterov index could not be computed (boom)" in section.markdown and "FWI" in section.markdown


def test_no_nesterov_beyond_the_open_meteo_horizon(make_route, fixed_now):
    world = World(country="ru", history=history(31))
    section = run(make_route, fixed_now, world, coords=EKB, date=TODAY + datetime.timedelta(days=16))
    assert "Nesterov" not in section.markdown and not any("open-meteo" in u for u in world.json_calls)


def test_restrictions_from_facts_are_shown_with_sources_and_warnings(make_route, fixed_now):
    fact = {"markdown": "Forest access is banned in the Comunidad de Madrid from 1 June to 15 October.",
            "sources": ["https://www.comunidad.madrid/x"],
            "warnings": [{"severity": "caution", "text": "Forest access ban in force."}]}
    section = run(make_route, fixed_now, World(), date=TODAY + datetime.timedelta(days=3), facts={"all": {"fire": fact}})
    assert "Forest access is banned" in section.markdown and "Sources: [www.comunidad.madrid]" in section.markdown
    assert [w.text for w in section.warnings] == ["Forest access ban in force."] and section.confidence == "web-sourced"


def test_russian_text(make_route, fixed_now):
    section = run(make_route, fixed_now, World(fwi=30.0, country="ru", history=history(31)), coords=EKB,
                  date=TODAY + datetime.timedelta(days=3), lang="ru")
    assert "Индекс пожарной погоды" in section.markdown and "высокая" in section.markdown
    assert "показатель Нестерова" in section.markdown


def test_the_plugin_declares_its_group_title():
    assert FirePlugin.title_key == "hz_fire" and FirePlugin.section_id == "hazards"
    assert FirePlugin.depends_on == ("weather", "osm_features")
```

- [ ] **Step 2: Run them and see them fail** — `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_gwis.py tests/test_fire_index.py tests/test_fire.py -q` (import errors or assertion failures: the code does not exist yet).

- [ ] **Step 3: Write the implementation**

Create `skills/osm-day-route-day-plan/scripts/day_plan/gwis.py`:

```python
"""Client for the Copernicus GWIS WMS (maps.effis.emergency.copernicus.eu):
official fire-weather indices and satellite-detected active fires, keyless.
Checked live while writing this (2026-09-30):

* the layer `ecmwf.query` answers GetFeatureInfo for any point on Earth
  (Yekaterinburg included) with the Fire Weather Index and its components,
  for dates from 2018 up to 8 days ahead (an empty body beyond that);
* only `info_format=text/html` returns values (text/plain and GML come back
  empty), so the HTML table is parsed;
* WMS 1.3.0 with EPSG:4326 takes the bbox latitude-first; a lon/lat swap
  silently queries another place. `styles=` must be sent, and https is needed
  (http answers 301). Without `time` the layer answers for 2019-01-01;
* `viirs.hs.query` returns the detections near the queried pixel (about 13
  pixels of tolerance): use a small bbox around each query point and filter
  by distance yourself.

Model output is labelled `derived`; a detection list is `web-sourced`."""
import datetime
import re
from dataclasses import asdict, dataclass

from .http import HttpError
from .osm_features import haversine_m

GWIS_URL = "https://maps.effis.emergency.copernicus.eu/gwis"
FWI_LAYER = "ecmwf.query"
HOTSPOT_LAYER = "viirs.hs.query"
FWI_HORIZON_DAYS = 8
FWI_FORECAST_TTL_S = 3 * 3600
HOTSPOT_TTL_S = 3600
HOTSPOT_RADIUS_KM = 15.0
HOTSPOT_WINDOW_DAYS = 2          # detections of today and the two days before
MAX_HOTSPOT_QUERIES = 6
_HALF_DEG = 0.5                  # 1 degree box, 101 px: about 1.1 km per pixel

_ROW = re.compile(r"<tr>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>", re.S | re.I)
_FWI_LABELS = (("(FWI)", "FWI"), ("(ISI)", "ISI"), ("(BUI)", "BUI"), ("(FFMC)", "FFMC"), ("(DMC)", "DMC"),
               ("(DC)", "DC"))


def _url(layer: str, lat: float, lon: float, time: str, extra: str = "") -> str:
    return (f"{GWIS_URL}?service=WMS&version=1.3.0&request=GetFeatureInfo&layers={layer}&query_layers={layer}"
            f"&styles=&crs=EPSG:4326&bbox={lat - _HALF_DEG:.4f},{lon - _HALF_DEG:.4f},{lat + _HALF_DEG:.4f},"
            f"{lon + _HALF_DEG:.4f}&width=101&height=101&i=50&j=50&info_format=text/html&time={time}{extra}")


def fwi_url(lat: float, lon: float, date: datetime.date) -> str:
    return _url(FWI_LAYER, lat, lon, date.isoformat())


def _number(text: str) -> float | None:
    m = re.match(r"\s*(-?\d+(?:\.\d+)?)", text)
    return float(m.group(1)) if m else None


def parse_fwi(html: str) -> dict | None:
    """{'FWI': .., 'ISI': .., 'BUI': .., 'FFMC': .., 'DMC': .., 'DC': ..} or None when there is no FWI row."""
    values = {}
    for label, value in _ROW.findall(html or ""):
        for marker, key in _FWI_LABELS:
            if marker in label and _number(value) is not None:
                values[key] = _number(value)
    return values if "FWI" in values else None


def fwi_at(ctx, lat: float, lon: float, date: datetime.date) -> dict | None:
    """The FWI components for a date, or None (beyond the horizon, or no value). Raises HttpError."""
    key = f"gwis_fwi|{lat:.2f}|{lon:.2f}|{date.isoformat()}"
    forecast = date >= ctx.today
    cached = ctx.cache.get_entry(key, FWI_FORECAST_TTL_S if forecast else None)
    if cached is not None:
        return cached[0] or None
    values = parse_fwi(ctx.http_text(fwi_url(lat, lon, date)))
    ctx.cache.put(key, values or {})
    return values


@dataclass
class Hotspot:
    lat: float
    lon: float
    date: str
    time: str
    satellite: str
    confidence: str
    frp_mw: float | None


def hotspots_url(lat: float, lon: float, date_from: datetime.date, date_to: datetime.date) -> str:
    return _url(HOTSPOT_LAYER, lat, lon, f"{date_from.isoformat()}/{date_to.isoformat()}", "&feature_count=50")


def parse_hotspots(html: str) -> list:
    hotspots = []
    for block in (html or "").split("<table")[1:]:
        fields = {re.sub(r"\s+", " ", k).strip(): re.sub(r"\s+", " ", v).strip() for k, v in _ROW.findall(block)}
        lat, lon = _number(fields.get("Latitude", "")), _number(fields.get("Longitude", ""))
        if lat is None or lon is None:
            continue
        hotspots.append(Hotspot(lat, lon, fields.get("Detection Date", ""), fields.get("Detection time", ""),
                                fields.get("Satellite", ""), fields.get("Confidence", ""),
                                _number(fields.get("Fire Radiative Power", ""))))
    return hotspots


def hotspots_near(ctx, samples: list, date_from: datetime.date, date_to: datetime.date,
                  radius_km: float = HOTSPOT_RADIUS_KM) -> list:
    """[(Hotspot, distance_km)] within radius_km of the route, nearest first. One small query per query point
    (at most MAX_HOTSPOT_QUERIES points spread along the route); raises HttpError if a query fails."""
    step = max(1, len(samples) // MAX_HOTSPOT_QUERIES)
    query_points = samples[::step][:MAX_HOTSPOT_QUERIES]
    if samples[-1] not in query_points and len(query_points) < MAX_HOTSPOT_QUERIES:
        query_points.append(samples[-1])
    seen, found = set(), []
    for lat, lon in query_points:
        key = f"gwis_hotspots|{lat:.2f}|{lon:.2f}|{date_from.isoformat()}|{date_to.isoformat()}"
        cached = ctx.cache.get_entry(key, HOTSPOT_TTL_S)
        if cached is not None:
            batch = [Hotspot(**h) for h in cached[0]]
        else:
            batch = parse_hotspots(ctx.http_text(hotspots_url(lat, lon, date_from, date_to)))
            ctx.cache.put(key, [asdict(h) for h in batch])
        for h in batch:
            ident = (round(h.lat, 5), round(h.lon, 5), h.date, h.time)
            if ident in seen:
                continue
            seen.add(ident)
            distance = min(haversine_m(h.lat, h.lon, s_lat, s_lon) for s_lat, s_lon in samples) / 1000.0
            if distance <= radius_km:
                found.append((h, distance))
    return sorted(found, key=lambda pair: pair[1])
```

Create `skills/osm-day-route-day-plan/scripts/day_plan/fire_index.py`:

```python
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
```

Create `skills/osm-day-route-day-plan/scripts/day_plan/plugins/fire.py`:

```python
"""The "Fire danger" hazard: the official Fire Weather Index (ECMWF via
Copernicus GWIS, keyless, global, 8 days ahead), for Russian routes also the
Nesterov index by Rosleskhoz order No. 287, satellite-detected active fires
near the route (last three days), the wind that would carry fire and smoke,
and — from facts.json, plugin id `fire` — forest-access and open-fire
restrictions found on the web.

The spec asked for an own stdlib FWI; the official GWIS values replace it
because the FWI's Drought Code needs a whole-season spin-up that a per-day
plan cannot reproduce. Tiers: FWI and Nesterov are `derived` (model output),
detections and facts are `web-sourced`."""
import datetime
import math

from ..base import PlanWarning, Section, SectionPlugin
from ..calendar_info import country_code
from ..facts import lookup
from ..fire_index import daily_from_hourly, fwi_class, history_range, kpo_class, nesterov_index
from ..gwis import (
    FWI_HORIZON_DAYS, FWI_FORECAST_TTL_S, HOTSPOT_RADIUS_KM, HOTSPOT_WINDOW_DAYS, fwi_at, hotspots_near,
)
from ..http import HttpError
from ..i18n import compass, tr
from .common import sources_line
from .weather import ARCHIVE_URL, FORECAST_HORIZON_DAYS as OM_HORIZON, FORECAST_PAST_DAYS, FORECAST_URL

ROMAN = ("I", "II", "III", "IV", "V")
_ELEVATED = ("high", "very_high", "extreme")


def _nesterov(ctx, lat: float, lon: float):
    """(index, class) for the date from the last NESTEROV_DAYS days of Open-Meteo data, or None when the date is
    beyond the forecast horizon. Raises HttpError / KeyError on a bad answer."""
    delta = (ctx.date - ctx.today).days
    if delta > OM_HORIZON:
        return None
    forecast = delta >= -FORECAST_PAST_DAYS
    start, end = history_range(ctx.date)
    key = f"nesterov|{'forecast' if forecast else 'archive'}|{lat:.2f}|{lon:.2f}|{ctx.date_iso}"
    cached = ctx.cache.get_entry(key, FWI_FORECAST_TTL_S if forecast else None)
    if cached is not None:
        value = cached[0]
    else:
        url = (f"{FORECAST_URL if forecast else ARCHIVE_URL}?latitude={lat:.4f}&longitude={lon:.4f}"
               f"&hourly=temperature_2m,dew_point_2m,precipitation&timezone=auto"
               f"&start_date={start.isoformat()}&end_date={end.isoformat()}")
        days = daily_from_hourly(ctx.http(url))
        if not days:
            raise KeyError("no daily values")
        value = nesterov_index(days)
        ctx.cache.put(key, value)
    return value, kpo_class(value)


def prevailing_wind(rows: list):
    """(direction_from_deg, max_speed_ms) over the given hourly rows, or None."""
    usable = [r for r in rows if r.get("wind") is not None and r.get("wdir") is not None]
    if not usable:
        return None
    x = sum(math.sin(math.radians(r["wdir"])) for r in usable)
    y = sum(math.cos(math.radians(r["wdir"])) for r in usable)
    if abs(x) < 1e-9 and abs(y) < 1e-9:
        return None
    return math.degrees(math.atan2(x, y)) % 360, max(r["wind"] for r in usable)


class FirePlugin(SectionPlugin):
    plugin_id = "fire"
    section_id = "hazards"
    depends_on = ("weather", "osm_features")
    title_key = "hz_fire"

    def run(self, ctx, shared: dict) -> Section:
        lang = ctx.lang
        lat, lon = ctx.centroid
        lines, warnings = [], []
        has_model = has_web = False
        elevated = False

        # 1. official FWI
        delta = (ctx.date - ctx.today).days
        if delta > FWI_HORIZON_DAYS:
            lines.append("- " + tr("fire_fwi_beyond", lang, days=FWI_HORIZON_DAYS))
        else:
            try:
                values = fwi_at(ctx, lat, lon, ctx.date)
            except HttpError as e:
                lines.append("- " + tr("fire_fwi_unavailable", lang, reason=str(e) or "error"))
            else:
                if values is None:
                    lines.append("- " + tr("fire_fwi_none", lang))
                else:
                    has_model = True
                    cls = fwi_class(values["FWI"])
                    elevated = cls in _ELEVATED
                    parts = ", ".join(f"{k} {values[k]:.1f}" for k in ("ISI", "BUI", "FFMC", "DMC", "DC") if k in values)
                    lines.append("- " + tr("fire_fwi_line", lang, fwi=f"{values['FWI']:.1f}",
                                           cls=tr("fire_class_" + cls, lang), components=parts or "–"))
                    lines.append("  *" + tr("fire_fwi_note", lang) + "*")
                    if cls in ("high", "very_high", "extreme"):
                        warnings.append(PlanWarning("caution" if cls == "high" else "danger", tr(
                            "fire_warn_fwi", lang, cls=tr("fire_class_" + cls, lang), fwi=f"{values['FWI']:.1f}")))

        # 2. Russia: the Nesterov index of order No. 287
        if country_code(ctx) == "RU":
            try:
                result = _nesterov(ctx, lat, lon)
            except (HttpError, KeyError, IndexError, ValueError, TypeError) as e:
                lines.append("- " + tr("fire_kpo_unavailable", lang, reason=str(e) or type(e).__name__))
            else:
                if result is not None:
                    value, cls = result
                    has_model = True
                    name = tr("fire_kpo_names", lang)[cls - 1]
                    lines.append("- " + tr("fire_kpo_line", lang, value=f"{value:.0f}", roman=ROMAN[cls - 1], name=name))
                    lines.append("  *" + tr("fire_kpo_note", lang) + "*")
                    if cls >= 4:
                        elevated = True
                        warnings.append(PlanWarning("caution" if cls == 4 else "danger", tr(
                            "fire_warn_kpo", lang, roman=ROMAN[cls - 1], name=name)))

        # 3. active fires near the route (only meaningful around today)
        hotspots = []
        if -1 <= delta <= HOTSPOT_WINDOW_DAYS:
            samples = shared.get("osm_features", {}).get("samples") or [(lat, lon)]
            try:
                hotspots = hotspots_near(ctx, samples, ctx.today - datetime.timedelta(days=HOTSPOT_WINDOW_DAYS),
                                         ctx.today)
            except HttpError as e:
                lines.append("- " + tr("fire_hotspots_unavailable", lang, reason=str(e) or "error"))
            else:
                has_web = True
                km = f"{HOTSPOT_RADIUS_KM:.0f}"
                if not hotspots:
                    lines.append("- " + tr("fire_hotspots_none", lang, km=km))
                else:
                    elevated = True
                    lines.append("- " + tr("fire_hotspots_some", lang, km=km))
                    for h, distance in hotspots[:5]:
                        frp = tr("fire_hotspot_frp", lang, frp=f"{h.frp_mw:.1f}") if h.frp_mw is not None else ""
                        lines.append(tr("fire_hotspot_item", lang, dist=f"{distance:.1f}", date=h.date, time=h.time,
                                        sat=h.satellite or "?", conf=h.confidence or "?", frp=frp))
                    nearest, distance = hotspots[0]
                    warnings.append(PlanWarning("danger" if distance <= 5.0 else "caution", tr(
                        "fire_warn_hotspot", lang, km=f"{distance:.0f}", date=nearest.date)))

        # 4. the wind that would carry it
        if elevated:
            wind = prevailing_wind((shared.get("weather") or {}).get("daytime_rows") or [])
            if wind:
                deg, speed = wind
                lines.append("- " + tr("fire_wind", lang, dir=compass(deg, lang), deg=f"{deg:.0f}",
                                       speed=f"{speed:.1f}", to=compass((deg + 180) % 360, lang)))

        # 5. restrictions recorded from the web
        fact = lookup(ctx.facts, ctx.date_iso, "fire")
        if fact:
            lines += ["", tr("fire_web_title", lang), "", fact["markdown"], "", sources_line(fact["sources"], lang)]
            for w in fact.get("warnings", []):
                warnings.append(PlanWarning(w["severity"], w["text"]))

        confidence = "web-sourced" if (fact or has_web) else "derived" if has_model else "no-data"
        return Section("hazards", "\n".join(lines), confidence, sources=list(fact["sources"]) if fact else [],
                       warnings=warnings)
```

Create `skills/osm-day-route-day-plan/tests/fixtures/gwis_fwi_ekb_2026-09-28.html`:

```html
<H2>Fire Danger</H2>
<table id="main">
    <tr><td>Fire Weather Index (FWI)</td><td>9.5045595</td></tr>
    <tr><td>Initial Spread Index (ISI)</td><td>4.747189</td></tr>
    <tr><td>Build Up Index (BUI)</td><td>29.865156</td></tr>
    <tr><td>Fine Fuel Moisture Code (FFMC)</td><td>87.779564</td></tr>
    <tr><td>Duff Moisture Code (DMC)</td><td>20.014561</td></tr>
    <tr><td>Drought Code (DC)</td><td>147.02386</td></tr>
    <tr><td>Anomaly Index</td><td>1.1616572</td></tr>
    <tr><td>Ranking Index</td><td>85.858498</td></tr>
</table>
```

Create `skills/osm-day-route-day-plan/tests/fixtures/gwis_hotspots_biscay.html`:

```html
<h2>Hotspots</h2>
<table id="main">
  <tr>
    <td>Satellite</td>
    <td>NOAA-21/VIIRS</td>
  </tr>        
  <tr>
    <td>Latitude</td>
    <td>43.20694 °</td>
  </tr>
  <tr>
    <td>Longitude</td>
    <td>-2.77349 °</td>
  </tr>
  <tr>
    <td>Detection Date</td>
    <td>2026-09-29</td>
  </tr>
  <tr>
    <td>Detection time</td>
    <td>02:17:00</td>
  </tr>
  <tr>
    <td>Confidence </td>
    <td>High</td>
  </tr>
  <tr>
    <td>Fire Radiative Power</td>
    <td>0.50000000000000000000 MW</td>
  </tr>
  <tr>
    <td>Day-Night </td>
    <td>Day</td>
  </tr>      
  <tr>
    <td>Along-Scan Pixel Size</td>
    <td>410 m</td>
  </tr>        
  <tr>
    <td>Along-Track Pixel Size</td>
    <td>370 m</td>
  </tr>      
  <tr>
    <td>MIR Brigntess Temperature</td>
    <td>301.0000000000000000 °K</td>
  </tr>
  <tr>
    <td>TIR Brightness Temperature</td>
    <td>286.8000000000000000 °K</td>
  </tr>
  <tr>
    <td>GLC Class</td>
    <td>0</td>
  </tr>
  <tr>
    <td>ISO3</td>
    <td>ESP</td>
  </tr>
  <tr>
    <td>Country</td>
    <td>Spain</td>
  </tr>
  <tr>
    <td>Admin 1</td>
    <td>País Vasco</td>
  </tr>
  <tr>
    <td>Admin 2</td>
    <td>Vizcaya</td>
  </tr>
  <tr>
      <td>Mask Flag</td>
      <td>-8</td>
  </tr>
</table>
<h2>Hotspots</h2>
<table id="main">
  <tr>
    <td>Satellite</td>
    <td>S-NPP/VIIRS</td>
  </tr>        
  <tr>
    <td>Latitude</td>
    <td>43.30372 °</td>
  </tr>
  <tr>
    <td>Longitude</td>
    <td>-3.01352 °</td>
  </tr>
  <tr>
    <td>Detection Date</td>
    <td>2026-09-29</td>
  </tr>
  <tr>
    <td>Detection time</td>
    <td>01:13:00</td>
  </tr>
  <tr>
    <td>Confidence </td>
    <td>High</td>
  </tr>
  <tr>
    <td>Fire Radiative Power</td>
    <td>2.0000000000000000 MW</td>
  </tr>
  <tr>
    <td>Day-Night </td>
    <td>Day</td>
  </tr>      
  <tr>
    <td>Along-Scan Pixel Size</td>
    <td>630 m</td>
  </tr>        
  <tr>
    <td>Along-Track Pixel Size</td>
    <td>720 m</td>
  </tr>      
  <tr>
    <td>MIR Brigntess Temperature</td>
    <td>310.7000000000000000 °K</td>
  </tr>
  <tr>
    <td>TIR Brightness Temperature</td>
    <td>280.8000000000000000 °K</td>
  </tr>
  <tr>
    <td>GLC Class</td>
    <td>0</td>
  </tr>
  <tr>
    <td>ISO3</td>
    <td>ESP</td>
  </tr>
  <tr>
    <td>Country</td>
    <td>Spain</td>
  </tr>
  <tr>
    <td>Admin 1</td>
    <td>País Vasco</td>
  </tr>
  <tr>
    <td>Admin 2</td>
    <td>Vizcaya</td>
  </tr>
  <tr>
      <td>Mask Flag</td>
      <td>-8</td>
  </tr>
</table>
<h2>Hotspots</h2>
<table id="main">
  <tr>
    <td>Satellite</td>
    <td>NOAA-20/VIIRS</td>
  </tr>        
  <tr>
    <td>Latitude</td>
    <td>43.20672 °</td>
  </tr>
  <tr>
    <td>Longitude</td>
    <td>-2.77217 °</td>
  </tr>
  <tr>
    <td>Detection Date</td>
    <td>2026-09-27</td>
  </tr>
  <tr>
    <td>Detection time</td>
    <td>02:11:00</td>
  </tr>
  <tr>
    <td>Confidence </td>
    <td>High</td>
  </tr>
  <tr>
    <td>Fire Radiative Power</td>
    <td>0.20000000000000000000 MW</td>
  </tr>
  <tr>
    <td>Day-Night </td>
    <td>Day</td>
  </tr>      
  <tr>
    <td>Along-Scan Pixel Size</td>
    <td>390 m</td>
  </tr>        
  <tr>
    <td>Along-Track Pixel Size</td>
    <td>360 m</td>
  </tr>      
  <tr>
    <td>MIR Brigntess Temperature</td>
    <td>299.3000000000000000 °K</td>
  </tr>
  <tr>
    <td>TIR Brightness Temperature</td>
    <td>287.7000000000000000 °K</td>
  </tr>
  <tr>
    <td>GLC Class</td>
    <td>190</td>
  </tr>
  <tr>
    <td>ISO3</td>
    <td>ESP</td>
  </tr>
  <tr>
    <td>Country</td>
    <td>Spain</td>
  </tr>
  <tr>
    <td>Admin 1</td>
    <td>País Vasco</td>
  </tr>
  <tr>
    <td>Admin 2</td>
    <td>Vizcaya</td>
  </tr>
  <tr>
      <td>Mask Flag</td>
      <td>-8</td>
  </tr>
</table>
<h2>Hotspots</h2>
<table id="main">
  <tr>
    <td>Satellite</td>
    <td>NOAA-20/VIIRS</td>
  </tr>        
  <tr>
    <td>Latitude</td>
    <td>43.30164 °</td>
  </tr>
  <tr>
    <td>Longitude</td>
    <td>-3.01555 °</td>
  </tr>
  <tr>
    <td>Detection Date</td>
    <td>2026-09-29</td>
  </tr>
  <tr>
    <td>Detection time</td>
    <td>01:34:00</td>
  </tr>
  <tr>
    <td>Confidence </td>
    <td>High</td>
  </tr>
  <tr>
    <td>Fire Radiative Power</td>
    <td>1.2000000000000000 MW</td>
  </tr>
  <tr>
    <td>Day-Night </td>
    <td>Day</td>
  </tr>      
  <tr>
    <td>Along-Scan Pixel Size</td>
    <td>600 m</td>
  </tr>        
  <tr>
    <td>Along-Track Pixel Size</td>
    <td>530 m</td>
  </tr>      
  <tr>
    <td>MIR Brigntess Temperature</td>
    <td>305.6000000000000000 °K</td>
  </tr>
  <tr>
    <td>TIR Brightness Temperature</td>
    <td>281.8000000000000000 °K</td>
  </tr>
  <tr>
    <td>GLC Class</td>
    <td>0</td>
  </tr>
  <tr>
    <td>ISO3</td>
    <td>ESP</td>
  </tr>
  <tr>
    <td>Country</td>
    <td>Spain</td>
  </tr>
  <tr>
    <td>Admin 1</td>
    <td>País Vasco</td>
  </tr>
  <tr>
    <td>Admin 2</td>
    <td>Vizcaya</td>
  </tr>
  <tr>
      <td>Mask Flag</td>
      <td>-8</td>
  </tr>
</table>
<h2>Hotspots</h2>
<table id="main">
  <tr>
    <td>Satellite</td>
    <td>NOAA-20/VIIRS</td>
  </tr>        
  <tr>
    <td>Latitude</td>
    <td>43.30441 °</td>
  </tr>
  <tr>
    <td>Longitude</td>
    <td>-3.0119 °</td>
  </tr>
  <tr>
    <td>Detection Date</td>
    <td>2026-09-29</td>
  </tr>
  <tr>
    <td>Detection time</td>
    <td>01:34:00</td>
  </tr>
  <tr>
    <td>Confidence </td>
    <td>High</td>
  </tr>
  <tr>
    <td>Fire Radiative Power</td>
    <td>1.7000000000000000 MW</td>
  </tr>
  <tr>
    <td>Day-Night </td>
    <td>Day</td>
  </tr>      
  <tr>
    <td>Along-Scan Pixel Size</td>
    <td>600 m</td>
  </tr>        
  <tr>
    <td>Along-Track Pixel Size</td>
    <td>530 m</td>
  </tr>      
  <tr>
    <td>MIR Brigntess Temperature</td>
    <td>307.9000000000000000 °K</td>
  </tr>
  <tr>
    <td>TIR Brightness Temperature</td>
    <td>281.5000000000000000 °K</td>
  </tr>
  <tr>
    <td>GLC Class</td>
    <td>0</td>
  </tr>
  <tr>
    <td>ISO3</td>
    <td>ESP</td>
  </tr>
  <tr>
    <td>Country</td>
    <td>Spain</td>
  </tr>
  <tr>
    <td>Admin 1</td>
    <td>País Vasco</td>
  </tr>
  <tr>
    <td>Admin 2</td>
    <td>Vizcaya</td>
  </tr>
  <tr>
      <td>Mask Flag</td>
      <td>-8</td>
  </tr>
</table>
```

- [ ] **Step 4: Run the whole suite** — `cd skills/osm-day-route-day-plan && python3 -m pytest tests -q` (all green), and for the show skill `cd skills/osm-day-route-show && python3 -m pytest tests -q`.

- [ ] **Step 5: Commit**

```bash
git add skills README.md
git commit -m "Fire danger: GWIS Fire Weather Index, Nesterov class for Russia, active fires near the route

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

### Task 5: Mountain hazards

Applies only when the route reaches 600 m or more (from the elevations stored in `route.geojson`). Uses freezing level, wind/gusts, CAPE thunderstorm risk, snow and rain from the weather rows, and `sac_scale`, scree/cliff/glacier from the shared OSM features. Never listed as missing when it does not apply.

**Files:**
- Create: `skills/osm-day-route-day-plan/tests/test_mountain.py`
- Create: `skills/osm-day-route-day-plan/scripts/day_plan/plugins/mountain.py`

- [ ] **Step 1: Add the tests** (27 tests in the file(s) below)

Create `skills/osm-day-route-day-plan/tests/test_mountain.py`:

```python
import datetime
import json

import pytest

from day_plan.context import build_context
from day_plan.osm_features import OsmFeature
from day_plan.plugins.mountain import MountainPlugin, elevation_stats

SUMMER = datetime.date(2026, 7, 4)
WINTER = datetime.date(2026, 1, 15)


def coords(*elevations):
    return tuple((41.70, 43.25 + i * 0.01, e) for i, e in enumerate(elevations))      # (lon, lat, ele)


def rows(**over):
    base = {"hour": 12, "temp": 12.0, "fzl": 4000.0, "cape": 0.0, "gust": 5.0, "precip": 0.0, "snow_m": 0.0, "code": 1}
    return [{**base, **over} for _ in range(3)]


def run(make_route, fixed_now, elevations, weather_rows=None, features=None, osm_error=None, date=SUMMER, lang="en",
        facts=None, elevation_m=None, folder="route", with_osm=True):
    route_dir = make_route(coords=coords(*elevations), folder=folder)
    if facts is not None:
        (route_dir / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    ctx = build_context(route_dir, date, lang=lang, http=lambda u: {}, now=fixed_now)
    shared = {}
    if weather_rows is not None:
        shared["weather"] = {"daytime_rows": weather_rows, "rows": weather_rows, "elevation_m": elevation_m}
    if with_osm:
        shared["osm_features"] = {"features": features or [], "samples": [(c[1], c[0]) for c in ctx.coords],
                                  "error": osm_error}
    return MountainPlugin().run(ctx, shared)


def feature(kind, lat_offset=0.0005, detail=""):
    return OsmFeature(kind, 43.25 + lat_offset, 41.70, "", detail)


def test_a_flat_route_is_not_applicable_and_left_out(make_route, fixed_now):
    section = run(make_route, fixed_now, (100.0, 150.0, 120.0))
    assert section.omit is True and section.markdown == ""


def test_a_route_without_elevations_says_so(make_route, fixed_now):
    section = run(make_route, fixed_now, (None, None))
    assert section.confidence == "no-data" and "no elevation data" in section.markdown and not section.omit


@pytest.mark.parametrize("elevations,applicable", [
    ((100.0, 599.0), True),       # top below 600 m, but a relief of 499 m still makes it a mountain route
    ((100.0, 600.0), True), ((300.0, 640.0), True), ((50.0, 349.0), False), ((50.0, 350.0), True),
    ((50.0, 250.0), False), ((400.0, 700.0), True)])
def test_the_activation_rule_is_600_m_high_or_300_m_relief(make_route, fixed_now, elevations, applicable):
    section = run(make_route, fixed_now, elevations, weather_rows=rows(), folder="r")
    assert (not section.omit) is applicable


def test_elevation_stats():
    assert elevation_stats([(0, 0, 100.0), (0, 0, None), (0, 0, 300.5)]) == (100.0, 300.5, 200.5)
    assert elevation_stats([(0, 0, None), (0, 0)]) is None


def test_header_and_tier_lines(make_route, fixed_now):
    mid = run(make_route, fixed_now, (900.0, 1400.0), weather_rows=rows())
    assert "Route elevation 900–1400 m (relief 500 m)." in mid.markdown
    assert "Above 1500 m" not in mid.markdown and "altitude sickness" not in mid.markdown
    high = run(make_route, fixed_now, (1200.0, 1800.0), weather_rows=rows(), folder="high")
    assert "Above 1500 m" in high.markdown and "altitude sickness" not in high.markdown
    ams = run(make_route, fixed_now, (2000.0, 2700.0), weather_rows=rows(), folder="ams")
    assert "altitude sickness" in ams.markdown and "Oxygen shortage is not a factor below this height" in ams.markdown
    assert not any("3500" in w.text for w in ams.warnings)
    very_high = run(make_route, fixed_now, (3000.0, 3800.0), weather_rows=rows(), folder="vh")
    assert any("3500" in w.text and w.severity == "caution" for w in very_high.warnings)


@pytest.mark.parametrize("scale,severity", [("hiking", None), ("mountain_hiking", None), ("demanding_mountain_hiking", "caution"),
                                            ("alpine_hiking", "danger"), ("difficult_alpine_hiking", "danger")])
def test_path_difficulty_from_osm(make_route, fixed_now, scale, severity):
    section = run(make_route, fixed_now, (900.0, 1700.0), weather_rows=rows(),
                  features=[feature("sac", detail="hiking"), feature("sac", 0.001, detail=scale)])
    assert "up to **" in section.markdown and "(2 path segment(s) rated)" in section.markdown
    sac_warnings = [w for w in section.warnings if "terrain" in w.text.lower()]
    assert [w.severity for w in sac_warnings] == ([severity] if severity else [])


def test_loose_ground_and_glaciers_near_the_track(make_route, fixed_now):
    features = [feature("scree"), feature("scree", 0.001), feature("cliff"), feature("bare_rock", 0.5),   # far away
                feature("glacier", 0.005)]
    section = run(make_route, fixed_now, (1500.0, 2600.0), weather_rows=rows(), features=features)
    assert "scree 2, cliffs 1" in section.markdown and "bare rock" not in section.markdown
    assert "A glacier lies within 5" in section.markdown          # about 550 m
    assert any(w.severity == "caution" and "glacier" in w.text for w in section.warnings)
    far = run(make_route, fixed_now, (1500.0, 2600.0), weather_rows=rows(), features=[feature("glacier", 0.05)], folder="far")
    assert "glacier" not in far.markdown


def test_osm_problems_are_a_note_and_a_missing_osm_plugin_is_tolerated(make_route, fixed_now):
    down = run(make_route, fixed_now, (900.0, 1700.0), weather_rows=rows(), osm_error="504")
    assert "could not be loaded (504)" in down.markdown
    absent = run(make_route, fixed_now, (900.0, 1700.0), weather_rows=rows(), with_osm=False, folder="absent")
    assert "OpenStreetMap" not in absent.markdown and "Route elevation" in absent.markdown


def test_freezing_level_below_the_top_warns_and_above_does_not(make_route, fixed_now):
    low = run(make_route, fixed_now, (1000.0, 2400.0), weather_rows=rows(fzl=1800.0))
    assert "Freezing level down to 1800 m (below the highest point, 2400 m)" in low.markdown
    assert any("Freezing level (1800 m)" in w.text and w.severity == "caution" for w in low.warnings)
    marginal = run(make_route, fixed_now, (1000.0, 2400.0), weather_rows=rows(fzl=2300.0), folder="marginal")
    assert "below the highest point" in marginal.markdown and not any("Freezing level" in w.text for w in marginal.warnings)
    high = run(make_route, fixed_now, (1000.0, 2400.0), weather_rows=rows(fzl=3500.0), folder="high")
    assert "above the highest point" in high.markdown and not any("Freezing level" in w.text for w in high.warnings)


def test_temperature_at_the_top_uses_the_lapse_rate_from_the_model_elevation(make_route, fixed_now):
    section = run(make_route, fixed_now, (500.0, 2500.0), weather_rows=rows(temp=12.0), elevation_m=500.0)
    assert "About **-1 °C** at the highest point (2500 m)" in section.markdown          # 12 - 6.5 * 2.0
    assert any("Below freezing at the highest point" in w.text for w in section.warnings)
    warm = run(make_route, fixed_now, (500.0, 1500.0), weather_rows=rows(temp=20.0), elevation_m=500.0, folder="warm")
    assert "About **14 °C**" in warm.markdown and not any("Below freezing" in w.text for w in warm.warnings)
    fallback = run(make_route, fixed_now, (500.0, 2500.0), weather_rows=rows(temp=12.0), folder="fb")   # first coordinate elevation
    assert "About **-1 °C**" in fallback.markdown


def test_thunderstorm_risk_by_cape_and_by_forecast(make_route, fixed_now):
    cape = run(make_route, fixed_now, (900.0, 1700.0), weather_rows=rows(cape=1500.0))
    assert "CAPE up to 1500 J/kg" in cape.markdown
    assert [w.severity for w in cape.warnings if "Thunderstorm" in w.text] == ["caution"]
    forecast = run(make_route, fixed_now, (900.0, 1700.0), weather_rows=rows(code=95), folder="storm")
    assert "Thunderstorms are forecast" in forecast.markdown
    assert [w.severity for w in forecast.warnings if "Thunderstorm" in w.text] == ["danger"]
    calm = run(make_route, fixed_now, (900.0, 1700.0), weather_rows=rows(cape=900.0), folder="calm")
    assert "Thunderstorm" not in calm.markdown


def test_wind_note_rain_note_and_shade_note(make_route, fixed_now):
    section = run(make_route, fixed_now, (900.0, 1700.0), weather_rows=rows(gust=14.0, precip=5.0))
    assert "wind will be stronger than the 14 m/s gusts" in section.markdown
    assert "About 15 mm of rain" in section.markdown and any(w.severity == "caution" and "Heavy rain" in w.text for w in section.warnings)
    assert "sun sets behind the ridges" in section.markdown
    gentle = run(make_route, fixed_now, (700.0, 900.0), weather_rows=rows(gust=14.0, precip=0.1), folder="gentle")
    assert "stronger than" not in gentle.markdown and "rain" not in gentle.markdown and "sun sets" not in gentle.markdown


def test_snow_on_steep_ground_points_to_the_avalanche_bulletin(make_route, fixed_now):
    winter = run(make_route, fixed_now, (900.0, 1700.0), weather_rows=rows(snow_m=0.3), date=WINTER)
    assert "avalanche bulletin" in winter.markdown and "https://www.avalanches.org/" in winter.markdown
    assert any(w.severity == "caution" and "avalanche" in w.text for w in winter.warnings)
    summer = run(make_route, fixed_now, (900.0, 1700.0), weather_rows=rows(snow_m=0.0), folder="summer")
    assert "avalanche" not in summer.markdown
    lowland_snow = run(make_route, fixed_now, (300.0, 620.0), weather_rows=rows(snow_m=0.3), date=WINTER, folder="low")
    assert "avalanche" not in lowland_snow.markdown         # top below 1000 m


def test_a_missing_weather_plugin_still_gives_the_terrain_part(make_route, fixed_now):
    section = run(make_route, fixed_now, (900.0, 1700.0), weather_rows=None, features=[feature("glacier")])
    assert "Route elevation" in section.markdown and "glacier" in section.markdown and "Freezing level" not in section.markdown


def test_regional_facts_are_added_with_sources(make_route, fixed_now):
    fact = {"markdown": "EAWS danger level 3 (considerable) above 2200 m.", "sources": ["https://lawinen.report/x"],
            "warnings": [{"severity": "danger", "text": "Avalanche danger level 3."}]}
    section = run(make_route, fixed_now, (1500.0, 2600.0), weather_rows=rows(), facts={"all": {"mountain": fact}})
    assert "EAWS danger level 3" in section.markdown and "Sources: [lawinen.report](https://lawinen.report/x)" in section.markdown
    assert section.confidence == "web-sourced" and [w.text for w in section.warnings][-1] == "Avalanche danger level 3."


def test_russian_text(make_route, fixed_now):
    section = run(make_route, fixed_now, (900.0, 2700.0), weather_rows=rows(), lang="ru")
    assert "Высоты маршрута 900–2700 м" in section.markdown and "высотная болезнь" in section.markdown


def test_the_plugin_declares_its_group_title_and_dependencies():
    assert MountainPlugin.title_key == "hz_mountain" and MountainPlugin.depends_on == ("weather", "osm_features")
```

- [ ] **Step 2: Run them and see them fail** — `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_mountain.py -q` (import errors or assertion failures: the code does not exist yet).

- [ ] **Step 3: Write the implementation**

Create `skills/osm-day-route-day-plan/scripts/day_plan/plugins/mountain.py`:

```python
"""The "Mountain hazards" hazard, reported only for mountain routes: highest
point at or above 600 m, or relief (highest minus lowest) of 300 m or more,
judged from the elevations stored in route.geojson. Without elevation data the
section says so (no-data); for a flat route it is left out ("not applicable").

Tiers by highest point: from 600 m terrain, weather at altitude and cold; from
1500 m stronger UV, cold and dehydration; from 2500 m altitude sickness (oxygen
shortage is not mentioned below that: it starts to matter only there).

Inputs: the route elevations, the weather rows (freezing level, CAPE, gusts,
rain, snow, model elevation), and the shared OpenStreetMap features (`sac_scale`
paths, scree, cliffs, bare rock, glaciers). Avalanche bulletins have no keyless
machine-readable source that maps a route to a region, so the plan gives the
pointer and takes region details from facts.json (plugin id `mountain`).
Everything here is `derived` from those inputs."""

from ..base import PlanWarning, Section, SectionPlugin
from ..facts import lookup
from ..i18n import tr
from ..osm_features import near
from .common import sources_line

MOUNTAIN_MIN_ELEVATION_M = 600
MOUNTAIN_MIN_RELIEF_M = 300
HIGH_M, AMS_M, AMS_STRONG_M = 1500, 2500, 3500
TRACK_RADIUS_M = 300.0
GLACIER_RADIUS_M = 1000.0
LAPSE_C_PER_KM = 6.5
CAPE_THUNDER = 1000.0
HEAVY_RAIN_MM = 10.0
SNOW_M = 0.10
SAC_ORDER = ("hiking", "mountain_hiking", "demanding_mountain_hiking", "alpine_hiking",
             "demanding_alpine_hiking", "difficult_alpine_hiking")
_THUNDER_CODES = (95, 96, 99)


def elevation_stats(coords: list):
    """(min, max, relief) of the route elevations, or None when the route carries none."""
    values = [c[2] for c in coords if len(c) > 2 and isinstance(c[2], (int, float))]
    if not values:
        return None
    return min(values), max(values), max(values) - min(values)


def _values(rows: list, key: str) -> list:
    return [r[key] for r in rows if r.get(key) is not None]


class MountainPlugin(SectionPlugin):
    plugin_id = "mountain"
    section_id = "hazards"
    depends_on = ("weather", "osm_features")
    title_key = "hz_mountain"

    def run(self, ctx, shared: dict) -> Section:
        lang = ctx.lang
        stats = elevation_stats(ctx.coords)
        if stats is None:
            return Section("hazards", "- " + tr("mt_no_elevation", lang), "no-data")
        low, top, relief = stats
        if top < MOUNTAIN_MIN_ELEVATION_M and relief < MOUNTAIN_MIN_RELIEF_M:
            return Section("hazards", "", "derived", omit=True)          # not a mountain route

        weather = shared.get("weather") or {}
        rows = weather.get("daytime_rows") or weather.get("rows") or []
        osm = shared.get("osm_features") or {}
        lines = ["- " + tr("mt_header", lang, min=f"{low:.0f}", max=f"{top:.0f}", relief=f"{relief:.0f}")]
        warnings = []

        # terrain from OpenStreetMap
        if osm.get("error"):
            lines.append("- " + tr("mt_osm_unavailable", lang, reason=osm["error"]))
        elif osm.get("samples") is not None:
            features, samples = osm.get("features", []), osm["samples"]
            sac = near(features, samples, "sac", TRACK_RADIUS_M)
            rated = [f for f, _ in sac if f.detail in SAC_ORDER]
            if rated:
                worst = max(rated, key=lambda f: SAC_ORDER.index(f.detail)).detail
                names = tr("mt_sac_names", lang)
                lines.append("- " + tr("mt_sac", lang, scale=names[worst], count=len(rated)))
                level = SAC_ORDER.index(worst)
                if level >= 2:
                    warnings.append(PlanWarning("caution" if level == 2 else "danger",
                                                tr("mt_warn_sac", lang, scale=names[worst])))
            parts = []
            for kind in ("scree", "cliff", "bare_rock"):
                count = len(near(features, samples, kind, TRACK_RADIUS_M))
                if count:
                    parts.append(tr("mt_rock_" + kind, lang, n=count))
            if parts:
                lines.append("- " + tr("mt_rock", lang, parts=", ".join(parts)))
            glaciers = near(features, samples, "glacier", GLACIER_RADIUS_M)
            if glaciers:
                metres = f"{glaciers[0][1]:.0f}"
                lines.append("- " + tr("mt_glacier", lang, m=metres))
                warnings.append(PlanWarning("caution", tr("mt_warn_glacier", lang, m=metres)))

        # weather at altitude
        fzl = _values(rows, "fzl")
        if fzl:
            lowest = min(fzl)
            below = lowest < top
            lines.append("- " + tr("mt_freezing", lang, fzl=f"{lowest:.0f}", top=f"{top:.0f}",
                                   relation=tr("mt_freezing_below" if below else "mt_freezing_above", lang),
                                   effect=tr("mt_freezing_below_effect" if below else "mt_freezing_above_effect", lang)))
            if lowest < top - 200:
                warnings.append(PlanWarning("caution", tr("mt_warn_freezing", lang, fzl=f"{lowest:.0f}", top=f"{top:.0f}")))
        temps = _values(rows, "temp")
        if temps:
            reference = weather.get("elevation_m")
            if reference is None:
                reference = next((c[2] for c in ctx.coords if len(c) > 2 and c[2] is not None), low)
            estimate = min(temps) - LAPSE_C_PER_KM * max(0.0, top - reference) / 1000.0
            lines.append("- " + tr("mt_top_temp", lang, temp=f"{estimate:.0f}", top=f"{top:.0f}"))
            if estimate <= 0:
                warnings.append(PlanWarning("caution", tr("mt_warn_top_cold", lang, temp=f"{estimate:.0f}")))
        cape = max(_values(rows, "cape"), default=0.0)
        forecast_thunder = any(r.get("code") in _THUNDER_CODES for r in rows)
        if forecast_thunder:
            lines.append("- " + tr("mt_thunder_forecast", lang))
        if cape >= CAPE_THUNDER or forecast_thunder:
            if cape >= CAPE_THUNDER:
                lines.append("- " + tr("mt_thunder", lang, cape=f"{cape:.0f}"))
            warnings.append(PlanWarning("danger" if forecast_thunder else "caution",
                                        tr("mt_warn_thunder", lang, cape=f"{cape:.0f}")))
        gusts = _values(rows, "gust")
        if gusts and relief >= 500:
            lines.append("- " + tr("mt_wind", lang, gust=f"{max(gusts):.0f}"))
        rain = sum(_values(rows, "precip"))
        if rain >= HEAVY_RAIN_MM:
            lines.append("- " + tr("mt_rain", lang, mm=f"{rain:.0f}"))
            warnings.append(PlanWarning("caution", tr("mt_warn_rain", lang, mm=f"{rain:.0f}")))

        # altitude tiers
        if top >= HIGH_M:
            lines.append("- " + tr("mt_high", lang))
        if top >= AMS_M:
            lines.append("- " + tr("mt_ams", lang))
            if top >= AMS_STRONG_M:
                warnings.append(PlanWarning("caution", tr("mt_warn_ams", lang)))

        # snow and avalanches
        snow = max(_values(rows, "snow_m"), default=0.0)
        winter = ctx.date.month in (11, 12, 1, 2, 3, 4)
        if top >= 1000 and relief >= 300 and (snow >= SNOW_M or (winter and snow > 0)):
            lines.append("- " + tr("mt_snow", lang))
            warnings.append(PlanWarning("caution", tr("mt_warn_snow", lang)))
        if relief >= 500:
            lines.append("- " + tr("mt_shade", lang))

        fact = lookup(ctx.facts, ctx.date_iso, "mountain")
        if fact:
            lines += ["", tr("mt_web_title", lang), "", fact["markdown"], "", sources_line(fact["sources"], lang)]
            for w in fact.get("warnings", []):
                warnings.append(PlanWarning(w["severity"], w["text"]))
        return Section("hazards", "\n".join(lines), "web-sourced" if fact else "derived",
                       sources=list(fact["sources"]) if fact else [], warnings=warnings)
```

- [ ] **Step 4: Run the whole suite** — `cd skills/osm-day-route-day-plan && python3 -m pytest tests -q` (all green), and for the show skill `cd skills/osm-day-route-show && python3 -m pytest tests -q`.

- [ ] **Step 5: Commit**

```bash
git add skills README.md
git commit -m "Mountain hazards for routes reaching 600 m

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

### Task 6: Ticks and biting insects

Ticks (temperature band, season), mosquitoes, blackflies and midges, horseflies from temperature, wind, humidity, time of day and water within 1–1.5 km in OSM — an estimate, labelled as such; regional facts (`--plugin bio_hazards`) add season and animals. Applies in the tick season only. Especially relevant for Siberia and the Urals.

**Files:**
- Create: `skills/osm-day-route-day-plan/tests/test_bio_hazards.py`
- Modify: `skills/osm-day-route-day-plan/scripts/day_plan/plugins/common.py`
- Create: `skills/osm-day-route-day-plan/scripts/day_plan/plugins/bio_hazards.py`

- [ ] **Step 1: Add the tests** (24 tests in the file(s) below)

Create `skills/osm-day-route-day-plan/tests/test_bio_hazards.py`:

```python
import datetime
import json

import pytest

from day_plan.context import build_context
from day_plan.osm_features import OsmFeature
from day_plan.plugins.bio_hazards import (
    BioHazardsPlugin, blackfly_band, horsefly_band, hour_ranges, in_season, mosquito_band, tick_band,
)

JULY = datetime.date(2026, 7, 4)
JANUARY = datetime.date(2026, 1, 15)
APRIL = datetime.date(2026, 4, 10)
ROUTE = ((60.60, 56.84, 260.0), (60.62, 56.86, 270.0))
SUNRISE, SUNSET = 4 * 60 + 30, 22 * 60 + 30        # a northern summer day


def rows(hours=range(5, 22), **over):
    base = {"temp": 20.0, "wind": 1.0, "rh": 60, "cloud": 20}
    return [{"hour": h, **base, **over} for h in hours]


def water(kind="water", dlat=0.001, detail=""):
    return OsmFeature(kind, 56.84 + dlat, 60.60, "", detail)


def run(make_route, fixed_now, weather_rows, mean=18.0, features=None, error=None, date=JULY, lang="en", facts=None,
        coords=ROUTE, light=True, with_osm=True, folder="route"):
    route_dir = make_route(coords=coords, folder=folder)
    if facts is not None:
        (route_dir / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    ctx = build_context(route_dir, date, lang=lang, http=lambda u: {}, now=fixed_now)
    shared = {"weather": {"daytime_rows": weather_rows, "rows": weather_rows, "daily_mean_temp": mean}}
    if light:
        shared["light"] = {"sunrise_local_min": SUNRISE, "sunset_local_min": SUNSET}
    if with_osm:
        shared["osm_features"] = {"features": features or [], "samples": [(c[1], c[0]) for c in ctx.coords], "error": error}
    return BioHazardsPlugin().run(ctx, shared)


# ---- pure helpers ------------------------------------------------------------------------------
@pytest.mark.parametrize("mean,band", [(-5, 0), (4.9, 0), (5.0, 1), (6.9, 1), (7.0, 2), (18.0, 2), (25.0, 2), (26.0, 1)])
def test_tick_bands(mean, band):
    assert tick_band(mean) == band


def test_mosquito_bands():
    assert mosquito_band({"temp": 9.0, "wind": 0.5}, False) == 0
    assert mosquito_band({"temp": 20.0, "wind": 4.0}, False) == 0                  # wind suppresses
    assert mosquito_band({"temp": 12.0, "wind": 1.0}, False) == 1
    assert mosquito_band({"temp": 20.0, "wind": 1.0}, False) == 2
    assert mosquito_band({"temp": 12.0, "wind": 1.0}, True) == 2                   # dawn or dusk
    assert mosquito_band({"temp": 12.0, "wind": 1.0, "rh": 80}, False) == 2       # humid air
    assert mosquito_band({"temp": 30.0, "wind": 1.0}, False) == 1                  # too hot
    assert mosquito_band({"temp": None, "wind": 1.0}, False) == 0


def test_blackfly_and_horsefly_bands():
    assert blackfly_band({"temp": 20.0, "wind": 1.0}, True) == 2
    assert blackfly_band({"temp": 10.0, "wind": 1.0}, True) == 1
    assert blackfly_band({"temp": 20.0, "wind": 3.0}, True) == 0
    assert blackfly_band({"temp": 20.0, "wind": 1.0}, False) == 0                   # not in daytime
    assert horsefly_band({"hour": 13, "temp": 25.0, "wind": 1.0, "cloud": 10}) == 2
    assert horsefly_band({"hour": 13, "temp": 21.0, "wind": 1.0, "cloud": 10}) == 1
    assert horsefly_band({"hour": 8, "temp": 25.0, "wind": 1.0, "cloud": 10}) == 0    # too early
    assert horsefly_band({"hour": 13, "temp": 25.0, "wind": 1.0, "cloud": 90}) == 0   # overcast
    assert horsefly_band({"hour": 13, "temp": 18.0, "wind": 1.0, "cloud": 10}) == 0


def test_hour_ranges_and_seasons():
    assert hour_ranges([5, 6, 7, 19, 20]) == "05:00–08:00, 19:00–21:00" and hour_ranges([]) == ""
    assert hour_ranges([23]) == "23:00–24:00"
    assert in_season(7, (6, 7, 8), 56.0) and not in_season(7, (6, 7, 8), -34.0) and in_season(1, (6, 7, 8), -34.0)


# ---- the plugin --------------------------------------------------------------------------------
def test_ticks_in_season_with_advice_and_warning(make_route, fixed_now):
    section = run(make_route, fixed_now, rows(), mean=14.0, date=APRIL)
    assert "Ticks: **high** (daily mean temperature 14 °C" in section.markdown and "Long sleeves" in section.markdown
    assert [w.severity for w in section.warnings if "tick" in w.text.lower()] == ["caution"]


def test_no_tick_line_in_winter_and_the_section_disappears_when_nothing_is_in_season(make_route, fixed_now):
    winter = run(make_route, fixed_now, rows(temp=-8.0), mean=-8.0, date=JANUARY)
    assert winter.omit is True and winter.markdown == ""


def test_summer_mosquitoes_with_still_water_and_dusk_peaks(make_route, fixed_now):
    section = run(make_route, fixed_now, rows(wind=1.0), features=[water("water")])
    md = section.markdown
    assert "Mosquitoes: **high** — 05:00–22:00" in md
    assert any(w.severity == "caution" and "mosquitoes" in w.text.lower() for w in section.warnings)
    assert "Repellent and long light clothing" in md and "not a measurement" in md


def test_without_still_water_the_mosquito_band_drops_by_one(make_route, fixed_now):
    with_water = run(make_route, fixed_now, rows(temp=20.0), features=[water("water")])
    no_water = run(make_route, fixed_now, rows(temp=20.0), features=[], folder="dry")
    assert "Mosquitoes: **high**" in with_water.markdown
    assert "Mosquitoes: **moderate**" in no_water.markdown and "Mosquitoes: **high**" not in no_water.markdown


def test_blackflies_need_running_water_and_calm_daylight(make_route, fixed_now):
    river = run(make_route, fixed_now, rows(temp=20.0, wind=1.0), features=[water("waterway", detail="river")])
    assert "Blackflies and midges: **high**" in river.markdown
    lake_only = run(make_route, fixed_now, rows(temp=20.0, wind=1.0), features=[water("water")], folder="lake")
    assert "Blackflies and midges: **moderate**" in lake_only.markdown
    windy = run(make_route, fixed_now, rows(temp=20.0, wind=6.0), features=[water("waterway")], folder="windy")
    assert "Blackflies and midges: **low** (cold, wind or no suitable water nearby)" in windy.markdown


def test_horseflies_peak_in_the_hot_sunny_afternoon(make_route, fixed_now):
    hot = run(make_route, fixed_now, rows(temp=26.0, wind=1.0, cloud=10), features=[water("water")])
    line = next(l for l in hot.markdown.splitlines() if l.startswith("- Horseflies"))
    assert "**high**" in line and "11:00–18:00" in line
    assert not any("horseflies" in w.text.lower() for w in hot.warnings)        # informational only


def test_group_seasons_gate_the_lines(make_route, fixed_now):
    may = run(make_route, fixed_now, rows(), features=[water()], date=datetime.date(2026, 5, 20), folder="may")
    assert "Mosquitoes" in may.markdown and "Horseflies" not in may.markdown         # horseflies are Jun-Aug
    october = run(make_route, fixed_now, rows(temp=8.0), mean=8.0, date=datetime.date(2026, 10, 10), folder="oct")
    assert "Mosquitoes" not in october.markdown and "Ticks" in october.markdown


def test_southern_hemisphere_seasons_are_shifted(make_route, fixed_now):
    south = ((-70.0, -33.0, 100.0), (-70.02, -33.02, 110.0))
    january = run(make_route, fixed_now, rows(), features=[], date=JANUARY, coords=south, mean=20.0, folder="s1")
    assert "Mosquitoes" in january.markdown          # January is midsummer there
    july = run(make_route, fixed_now, rows(), features=[], date=JULY, coords=south, mean=8.0, folder="s2")
    assert "Mosquitoes" not in july.markdown


def test_missing_osm_data_is_said_and_assumes_a_habitat(make_route, fixed_now):
    down = run(make_route, fixed_now, rows(temp=20.0), error="504")
    assert "Water near the route could not be checked" in down.markdown and "Mosquitoes: **high**" in down.markdown
    absent = run(make_route, fixed_now, rows(temp=20.0), with_osm=False, folder="absent")
    assert "could not be checked" in absent.markdown


def test_missing_weather_or_light_do_not_crash(make_route, fixed_now):
    no_rows = run(make_route, fixed_now, [], mean=None, features=[water()])
    assert no_rows.omit is True
    no_light = run(make_route, fixed_now, rows(temp=20.0), features=[water()], light=False, folder="nl")
    assert "Mosquitoes" in no_light.markdown


def test_regional_facts_keep_a_section_alive_out_of_season(make_route, fixed_now):
    fact = {"markdown": "Bears are active near the river; keep food sealed.", "sources": ["https://example.org/bears"]}
    section = run(make_route, fixed_now, rows(temp=-8.0), mean=-8.0, date=JANUARY, facts={"all": {"bio_hazards": fact}})
    assert not section.omit and "Bears are active" in section.markdown and section.confidence == "web-sourced"
    assert "Sources: [example.org](https://example.org/bears)" in section.markdown


def test_russian_text(make_route, fixed_now):
    section = run(make_route, fixed_now, rows(temp=20.0), features=[water("water")], lang="ru")
    assert "Комары: **высокая**" in section.markdown and "Репеллент" in section.markdown


def test_group_title_and_dependencies():
    assert BioHazardsPlugin.title_key == "hz_bio"
    assert BioHazardsPlugin.depends_on == ("weather", "light", "osm_features")
```

- [ ] **Step 2: Run them and see them fail** — `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_bio_hazards.py -q` (import errors or assertion failures: the code does not exist yet).

- [ ] **Step 3: Write the implementation**

Modify `skills/osm-day-route-day-plan/scripts/day_plan/plugins/common.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-day-plan/scripts/day_plan/plugins/common.py
+++ b/skills/osm-day-route-day-plan/scripts/day_plan/plugins/common.py
@@ -51,3 +51,19 @@
 
 def sources_line(urls: list, lang: str) -> str:
     return tr("tr_sources", lang, urls=", ".join(md_link(url) for url in urls))
+
+
+def hour_ranges(hours: list) -> str:
+    """[5, 6, 7, 19, 20] -> '05:00–08:00, 19:00–21:00'."""
+    ranges, start, prev = [], None, None
+    for h in sorted(set(hours)):
+        if start is None:
+            start = prev = h
+        elif h == prev + 1:
+            prev = h
+        else:
+            ranges.append((start, prev))
+            start = prev = h
+    if start is not None:
+        ranges.append((start, prev))
+    return ", ".join(f"{a:02d}:00–{b + 1:02d}:00" for a, b in ranges)
```

Create `skills/osm-day-route-day-plan/scripts/day_plan/plugins/bio_hazards.py`:

```python
"""Ticks and biting insects (mosquitoes, blackflies and midges, horseflies).

An estimate from the weather rows (temperature, wind, humidity, cloud, hour),
the season for the hemisphere, and — for the habitat — the water that
OpenStreetMap shows within 1-1.5 km of the route (shared `osm_features`). It is
labelled `derived`: the thresholds below are heuristics from general
entomology, kept in one table so a region can be tuned, not measurements.
Where the season or peaks of a region differ, facts.json (plugin id
`bio_hazards`, web-sourced) adds the local picture (also the place for
regional notes on animals). When nothing is in season and no fact exists the
section is left out.

Bands per hour: 0 low, 1 moderate, 2 high; a missing habitat lowers the band
by one (never below 0)."""
from ..base import PlanWarning, Section, SectionPlugin
from ..facts import lookup
from ..i18n import tr
from ..osm_features import near
from .common import hour_ranges, sources_line

TICK_ACTIVE_C = 5.0          # ticks become active at about +5..+7 C
TICK_HOT_C = 25.0            # dry heat lowers their activity
TICK_MONTHS = (3, 4, 5, 6, 7, 8, 9, 10, 11)      # northern hemisphere
INSECT_MONTHS = {"mosquito": (5, 6, 7, 8, 9), "blackfly": (5, 6, 7, 8, 9), "horsefly": (6, 7, 8)}
STILL_WATER_RADIUS_M = 1500.0
RUNNING_WATER_RADIUS_M = 1000.0
_BANDS = ("low", "moderate", "high")


def in_season(month: int, months: tuple, latitude: float) -> bool:
    """Northern seasons as given; the southern hemisphere is shifted by half a year."""
    return (month if latitude >= 0 else (month + 5) % 12 + 1) in months


def tick_band(mean_temp: float) -> int:
    if mean_temp < TICK_ACTIVE_C:
        return 0
    if mean_temp < 7.0 or mean_temp > TICK_HOT_C:
        return 1
    return 2


def mosquito_band(row: dict, dawn_dusk: bool) -> int:
    temp, wind = row.get("temp"), row.get("wind")
    if temp is None or temp < 10.0 or (wind is not None and wind >= 4.0):
        return 0
    band = 2 if 15.0 <= temp <= 28.0 else 1
    if dawn_dusk:
        band = min(2, band + 1)
    if (row.get("rh") or 0) >= 75:
        band = min(2, band + 1)
    return band


def blackfly_band(row: dict, daytime: bool) -> int:
    temp, wind = row.get("temp"), row.get("wind")
    if not daytime or temp is None or not 8.0 <= temp <= 28.0 or (wind is not None and wind >= 3.0):
        return 0
    return 2 if 15.0 <= temp <= 25.0 else 1


def horsefly_band(row: dict) -> int:
    temp, wind, cloud = row.get("temp"), row.get("wind"), row.get("cloud")
    if temp is None or temp < 20.0 or not 11 <= row["hour"] <= 17:
        return 0
    if (wind is not None and wind >= 5.0) or (cloud is not None and cloud >= 70):
        return 0
    return 2 if temp >= 24.0 else 1


class BioHazardsPlugin(SectionPlugin):
    plugin_id = "bio_hazards"
    section_id = "hazards"
    depends_on = ("weather", "light", "osm_features")
    title_key = "hz_bio"

    def run(self, ctx, shared: dict) -> Section:
        lang = ctx.lang
        lat, _ = ctx.centroid
        weather = shared.get("weather") or {}
        rows = weather.get("daytime_rows") or weather.get("rows") or []
        light = shared.get("light") or {}
        osm = shared.get("osm_features") or {}
        lines, warnings = [], []
        month = ctx.date.month

        # ticks
        mean = weather.get("daily_mean_temp")
        if mean is not None and in_season(month, TICK_MONTHS, lat):
            band = tick_band(mean)
            lines.append("- " + tr("bio_tick", lang, band=tr("bio_band", lang)[_BANDS[band]], temp=f"{mean:.0f}"))
            if band >= 1:
                lines.append("  " + tr("bio_tick_advice", lang))
            if band == 2:
                warnings.append(PlanWarning("caution", tr("bio_warn_tick", lang, temp=f"{mean:.0f}")))

        # biting insects
        habitat_known = bool(osm) and not osm.get("error") and osm.get("samples") is not None
        features, samples = osm.get("features", []), osm.get("samples") or []
        still = habitat_known and bool(near(features, samples, ("water", "wetland"), STILL_WATER_RADIUS_M))
        running = habitat_known and bool(near(features, samples, "waterway", RUNNING_WATER_RADIUS_M))
        any_water = habitat_known and bool(near(features, samples, ("water", "wetland", "waterway"), STILL_WATER_RADIUS_M))
        sunrise, sunset = light.get("sunrise_local_min"), light.get("sunset_local_min")

        def dawn_dusk(hour):
            if sunrise is None or sunset is None:
                return False
            mid = hour * 60 + 30
            return sunrise <= mid <= sunrise + 120 or sunset - 120 <= mid <= sunset

        def daytime(hour):
            return sunrise is None or sunset is None or sunrise + 60 <= hour * 60 + 30 <= sunset - 60

        groups = (("mosquito", lambda r: mosquito_band(r, dawn_dusk(r["hour"])), still),
                  ("blackfly", lambda r: blackfly_band(r, daytime(r["hour"])), running),
                  ("horsefly", horsefly_band, any_water))
        advice = False
        names = tr("bio_insect_names", lang)
        for key, band_of, habitat in groups:
            if not rows or not in_season(month, INSECT_MONTHS[key], lat):
                continue
            bands = [(r["hour"], band_of(r)) for r in rows]
            if habitat_known and not habitat:
                bands = [(h, max(0, b - 1)) for h, b in bands]
            peak = max(b for _, b in bands)
            peak_hours = [h for h, b in bands if b == peak]
            if peak == 0:
                lines.append("- " + tr("bio_insect", lang, name=names[key], band=tr("bio_band", lang)["low"],
                                       hours=tr("bio_insect_none", lang)))
                continue
            advice = True
            windows = hour_ranges(peak_hours)
            lines.append("- " + tr("bio_insect", lang, name=names[key], band=tr("bio_band", lang)[_BANDS[peak]],
                                   hours=tr("bio_insect_hours", lang, hours=windows)))
            if peak == 2 and key in ("mosquito", "blackfly"):
                warnings.append(PlanWarning("caution", tr("bio_warn_insect", lang, name=names[key], hours=windows)))
        if advice:
            lines.append("  " + tr("bio_insect_advice", lang))
        if any(l.startswith("- " + names[k]) for l in lines for k in names):
            if not habitat_known:
                lines.append("  *" + tr("bio_insect_note_water", lang) + "*")
            lines.append("  *" + tr("bio_rules", lang) + "*")

        fact = lookup(ctx.facts, ctx.date_iso, "bio_hazards")
        if fact:
            lines += ["", tr("bio_web_title", lang), "", fact["markdown"], "", sources_line(fact["sources"], lang)]
            for w in fact.get("warnings", []):
                warnings.append(PlanWarning(w["severity"], w["text"]))
        if not lines:
            return Section("hazards", "", "derived", omit=True)          # nothing in season: not applicable
        return Section("hazards", "\n".join(lines), "web-sourced" if fact else "derived",
                       sources=list(fact["sources"]) if fact else [], warnings=warnings)
```

- [ ] **Step 4: Run the whole suite** — `cd skills/osm-day-route-day-plan && python3 -m pytest tests -q` (all green), and for the show skill `cd skills/osm-day-route-show && python3 -m pytest tests -q`.

- [ ] **Step 5: Commit**

```bash
git add skills README.md
git commit -m "Ticks and biting insects (mosquitoes, blackflies, midges, horseflies)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

### Task 7: Air: pollen and pollution

Open-Meteo Air Quality (CAMS): European AQI classes (EEA), PM10, PM2.5, ozone, NO2 and pollen with the NAB scale. Pollen is null beyond about 45° E, so Russia east of that gets a pointer to the Yandex Weather pollen map; pollution reaches about four days ahead, beyond that the section says so.

**Files:**
- Create: `skills/osm-day-route-day-plan/tests/test_air.py`
- Create: `skills/osm-day-route-day-plan/scripts/day_plan/plugins/air.py`
- Create: `skills/osm-day-route-day-plan/tests/fixtures/air_madrid.json`
- Create: `skills/osm-day-route-day-plan/tests/fixtures/air_kazan.json`
- Create: `skills/osm-day-route-day-plan/tests/fixtures/air_moscow.json`

- [ ] **Step 1: Add the tests** (40 tests in the file(s) below)

Create `skills/osm-day-route-day-plan/tests/test_air.py`:

```python
import datetime
import json
from pathlib import Path

import pytest

from day_plan.context import build_context
from day_plan.http import HttpError
from day_plan.osm_features import OsmFeature
from day_plan.plugins.air import AirPlugin, angle_difference, aqi_class, bearing_deg, pollen_level

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / f"air_{name}.json").read_text(encoding="utf-8"))


MADRID, KAZAN, MOSCOW = fixture("madrid"), fixture("kazan"), fixture("moscow")
DATE = datetime.date(2026, 6, 22)                     # after fixed_now (2026-06-20)
ROUTE = ((60.60, 56.84, 260.0), (60.62, 56.86, 270.0))
DAY_ROWS = [{"hour": h, "wind": 3.0, "wdir": 270} for h in range(8, 20)]


def hourly(**series):
    """A synthetic 24-hour air answer; each series is a scalar, or {hour: value}."""
    out = {"time": [f"2026-06-22T{h:02d}:00" for h in range(24)]}
    for key in ("alder_pollen", "birch_pollen", "olive_pollen", "grass_pollen", "mugwort_pollen", "ragweed_pollen",
                "pm2_5", "pm10", "ozone", "nitrogen_dioxide", "sulphur_dioxide", "dust", "european_aqi"):
        spec = series.get(key, 0.0)
        out[key] = [spec.get(h, 0.0) if isinstance(spec, dict) else spec for h in range(24)]
    return out


def run(make_route, fixed_now, answer, shared_extra=None, lang="en", facts=None, folder="route", coords=ROUTE, day_rows=DAY_ROWS):
    calls = []
    if isinstance(answer, dict) and "time" in answer:        # a bare hourly block from hourly()
        answer = {"hourly": answer}

    def http(url):
        calls.append(url)
        if isinstance(answer, Exception):
            raise answer
        return answer

    route_dir = make_route(coords=coords, folder=folder)
    if facts is not None:
        (route_dir / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    ctx = build_context(route_dir, DATE, lang=lang, http=http, now=fixed_now)
    shared = {"weather": {"daytime_rows": day_rows}}
    shared.update(shared_extra or {})
    section = AirPlugin().run(ctx, shared)
    section.calls = calls
    return section


# ---- helpers -----------------------------------------------------------------------------------
@pytest.mark.parametrize("var,value,level", [("birch_pollen", 14, "low"), ("birch_pollen", 15, "moderate"), ("birch_pollen", 90, "high"),
                                             ("birch_pollen", 1500, "very_high"), ("grass_pollen", 4, "low"), ("grass_pollen", 5, "moderate"),
                                             ("grass_pollen", 20, "high"), ("grass_pollen", 200, "very_high"), ("ragweed_pollen", 9, "low"),
                                             ("mugwort_pollen", 10, "moderate"), ("ragweed_pollen", 50, "high"), ("ragweed_pollen", 500, "very_high")])
def test_pollen_levels_follow_the_nab_scale(var, value, level):
    assert pollen_level(var, value) == level


@pytest.mark.parametrize("aqi,cls", [(0, 0), (19.9, 0), (20, 1), (39, 1), (40, 2), (59, 2), (60, 3), (79, 3), (80, 4), (99, 4), (100, 5), (200, 5)])
def test_european_aqi_classes(aqi, cls):
    assert aqi_class(aqi) == cls


def test_bearing_and_angle_difference():
    assert bearing_deg(50.0, 10.0, 51.0, 10.0) == pytest.approx(0.0, abs=0.01)
    assert bearing_deg(50.0, 10.0, 50.0, 11.0) == pytest.approx(90.0, abs=0.5)
    assert angle_difference(350, 10) == 20 and angle_difference(90, 270) == 180


# ---- real answers ------------------------------------------------------------------------------
def test_real_madrid_answer_has_real_low_pollen_and_a_fair_air_quality(make_route, fixed_now):
    section = run(make_route, fixed_now, MADRID)
    md = section.markdown
    assert "Pollen (daytime maximum, grains/m³): mugwort 0.3 (low), grass 0.2 (low)" in md
    assert "US National Allergy Bureau" in md
    assert "European AQI **46** — moderate" in md and "PM10 29 µg/m³" in md
    assert section.warnings == [] and section.confidence == "derived"


def test_real_kazan_answer_has_null_pollen_reported_as_no_data_not_zero(make_route, fixed_now):
    section = run(make_route, fixed_now, KAZAN)
    assert "Pollen: no data for this location" in section.markdown and "https://yandex.ru/pogoda/" in section.markdown
    assert "none or negligible" not in section.markdown
    assert "European AQI **22** — fair" in section.markdown


def test_real_moscow_answer_has_poor_air_and_zero_pollen(make_route, fixed_now):
    section = run(make_route, fixed_now, MOSCOW)
    assert "Pollen: none or negligible in the model for this date." in section.markdown
    assert "European AQI **68** — poor" in section.markdown
    assert [w.severity for w in section.warnings] == ["caution"] and "Poor air quality" in section.warnings[0].text


# ---- synthetic behaviour -----------------------------------------------------------------------
def test_high_pollen_warns_with_the_worst_kind(make_route, fixed_now):
    section = run(make_route, fixed_now, hourly(birch_pollen={12: 250.0}, grass_pollen={12: 6.0}))
    assert "birch 250 (high), grass 6.0 (moderate)" in section.markdown
    assert any("High pollen (birch: 250 grains/m³)" in w.text for w in section.warnings)


def test_only_daytime_hours_count(make_route, fixed_now):
    section = run(make_route, fixed_now, hourly(birch_pollen={3: 5000.0}, european_aqi={3: 150}))
    assert "none or negligible" in section.markdown and "AQI **0** — good" in section.markdown
    assert section.warnings == []


def test_very_poor_air_is_a_danger(make_route, fixed_now):
    section = run(make_route, fixed_now, hourly(european_aqi={12: 105}))
    assert [w.severity for w in section.warnings] == ["danger"]


def test_all_null_pollution_after_the_model_horizon_is_no_data(make_route, fixed_now):
    nulls = {k: [None] * 24 for k in hourly()}
    nulls["time"] = hourly()["time"]
    section = run(make_route, fixed_now, nulls)
    assert "the air-quality model reaches only about four days ahead" in section.markdown
    assert "Pollen: no data" in section.markdown and section.confidence == "no-data"


def test_a_service_error_or_a_400_is_a_note_not_a_crash(make_route, fixed_now):
    down = run(make_route, fixed_now, HttpError("HTTP Error 400: Bad Request"))
    assert "could not be reached (HTTP Error 400: Bad Request)" in down.markdown and down.confidence == "no-data"
    odd = run(make_route, fixed_now, {"error": True, "reason": "out of allowed range"}, folder="odd")
    assert "out of allowed range" in odd.markdown


def test_the_answer_is_cached_for_three_hours(make_route, fixed_now):
    calls = []
    route_dir = make_route()
    ctx = build_context(route_dir, DATE, http=lambda u: calls.append(u) or MADRID, now=fixed_now)
    AirPlugin().run(ctx, {})
    AirPlugin().run(ctx, {})
    assert len(calls) == 1 and "hourly=alder_pollen" in calls[0] and "start_date=2026-06-22" in calls[0]


def factory(dlat, dlon):
    return OsmFeature("industrial", 56.84 + dlat, 60.60 + dlon, "", "")


def osm(*features, error=None):
    return {"osm_features": {"features": list(features), "samples": [(56.84, 60.60), (56.86, 60.62)], "error": error}}


def test_industry_upwind_of_the_route_is_reported_with_the_hours(make_route, fixed_now):
    west = factory(0.0, -0.03)           # about 1.8 km west of the route; the wind from the west carries it eastwards
    section = run(make_route, fixed_now, hourly(), shared_extra=osm(west))
    assert "Industrial sites within 5 km of the route (OpenStreetMap): 1. The wind carries emissions from 1 of them toward the route around 08:00–20:00." in section.markdown
    assert any(w.severity == "info" and "Industrial emissions" in w.text for w in section.warnings)


def test_industry_downwind_of_the_route_is_not_a_problem(make_route, fixed_now):
    east = factory(0.0, 0.10)            # east of the route: a westerly wind carries its smoke away
    close_east = factory(0.0, 0.05)
    section = run(make_route, fixed_now, hourly(), shared_extra=osm(close_east), folder="east")
    assert "the wind does not carry their emissions toward the route" in section.markdown
    assert not any("Industrial" in w.text for w in section.warnings)
    assert east.lat > 0


def test_calm_air_or_missing_wind_data_reports_no_downwind_hours(make_route, fixed_now):
    calm = [{"hour": h, "wind": 0.3, "wdir": 270} for h in range(8, 20)]
    section = run(make_route, fixed_now, hourly(), shared_extra=osm(factory(0.0, -0.03)), day_rows=calm)
    assert "does not carry" in section.markdown
    unknown = run(make_route, fixed_now, hourly(), shared_extra=osm(factory(0.0, -0.03)), day_rows=[{"hour": 12}], folder="nw")
    assert "does not carry" in unknown.markdown


def test_far_industry_and_osm_failures_add_nothing(make_route, fixed_now):
    far = run(make_route, fixed_now, hourly(), shared_extra=osm(factory(0.0, -0.5)))
    assert "Industrial" not in far.markdown
    failed = run(make_route, fixed_now, hourly(), shared_extra=osm(error="504"), folder="f")
    assert "Industrial" not in failed.markdown


def test_regional_advisories_from_facts(make_route, fixed_now):
    fact = {"markdown": "Wildfire smoke from the east is forecast.", "sources": ["https://example.org/smoke"],
            "warnings": [{"severity": "caution", "text": "Smoke advisory."}]}
    section = run(make_route, fixed_now, MADRID, facts={"all": {"air": fact}})
    assert "Wildfire smoke" in section.markdown and section.confidence == "web-sourced"
    assert [w.text for w in section.warnings] == ["Smoke advisory."]


def test_russian_text_and_group_title(make_route, fixed_now):
    section = run(make_route, fixed_now, MOSCOW, lang="ru")
    assert "европейский индекс AQI **68** — плохое" in section.markdown and "Пыльца: по модели" in section.markdown
    assert AirPlugin.title_key == "hz_air" and AirPlugin.depends_on == ("weather", "osm_features")
```

- [ ] **Step 2: Run them and see them fail** — `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_air.py -q` (import errors or assertion failures: the code does not exist yet).

- [ ] **Step 3: Write the implementation**

Create `skills/osm-day-route-day-plan/scripts/day_plan/plugins/air.py`:

```python
"""Air: pollen, pollution and industrial emissions.

* Pollen and pollution come from the Open-Meteo Air Quality API (CAMS models,
  keyless). Checked live: the pollen model returns `null` outside its European
  domain (about 30-71 N, up to about 45 E: Moscow yes, Kazan and Yekaterinburg
  no) and real zeros inside it, so `null` is reported as "no data", never as
  "no pollen". Pollution values exist for the whole world, for about four days
  ahead; two more days return only nulls and later dates answer HTTP 400.
* Pollen levels use the US National Allergy Bureau scale (tree 15/90/1500,
  grass 5/20/200, weed 10/50/500 grains/m3); the European AQI classes are the
  EEA ones (20/40/60/80/100).
* Emissions: industrial sites and power plants from the shared OpenStreetMap
  features within 5 km of the route, and the hours at which the wind carries
  them toward the route (within 45 degrees of the bearing site -> route).
All of it is `derived`; facts.json (plugin id `air`, web-sourced) can add
regional advisories (for example smoke)."""
import math

from ..base import PlanWarning, Section, SectionPlugin
from ..facts import lookup
from ..http import HttpError
from ..i18n import tr
from ..osm_features import haversine_m, near
from .common import hour_ranges, sources_line

AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
POLLEN_VARS = ("alder_pollen", "birch_pollen", "olive_pollen", "grass_pollen", "mugwort_pollen", "ragweed_pollen")
POLLUTION_VARS = ("pm2_5", "pm10", "ozone", "nitrogen_dioxide", "sulphur_dioxide", "dust", "european_aqi")
AQ_VARS = POLLEN_VARS + POLLUTION_VARS
AQ_TTL_S = 3 * 3600
POLLEN_SCALES = {                       # (moderate from, high from, very high from) in grains/m3
    "tree": (15, 90, 1500), "grass": (5, 20, 200), "weed": (10, 50, 500)}
POLLEN_GROUP = {"alder_pollen": "tree", "birch_pollen": "tree", "olive_pollen": "tree", "grass_pollen": "grass",
                "mugwort_pollen": "weed", "ragweed_pollen": "weed"}
AQI_STEPS = (20, 40, 60, 80, 100)       # European AQI: good, fair, moderate, poor, very poor, extremely poor
EMISSION_RADIUS_M = 5000.0
DOWNWIND_TOLERANCE_DEG = 45.0
DEFAULT_HOURS = range(6, 22)


def pollen_level(variable: str, value: float) -> str:
    moderate, high, very_high = POLLEN_SCALES[POLLEN_GROUP[variable]]
    if value >= very_high:
        return "very_high"
    if value >= high:
        return "high"
    if value >= moderate:
        return "moderate"
    return "low"


def aqi_class(aqi: float) -> int:
    for i, limit in enumerate(AQI_STEPS):
        if aqi < limit:
            return i
    return len(AQI_STEPS)


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def angle_difference(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _fetch(ctx, lat: float, lon: float) -> dict:
    """The hourly air-quality arrays for the date. Raises HttpError."""
    key = f"air|{lat:.2f}|{lon:.2f}|{ctx.date_iso}"
    cached = ctx.cache.get_entry(key, AQ_TTL_S if ctx.date >= ctx.today else None)
    if cached is not None:
        return cached[0]
    d = ctx.date_iso
    data = ctx.http(f"{AQ_URL}?latitude={lat:.4f}&longitude={lon:.4f}&hourly={','.join(AQ_VARS)}"
                    f"&timezone=auto&start_date={d}&end_date={d}")
    hourly = data.get("hourly") if isinstance(data, dict) else None
    if not isinstance(hourly, dict) or "time" not in hourly:
        raise HttpError((data or {}).get("reason", "unexpected answer") if isinstance(data, dict) else "unexpected answer")
    ctx.cache.put(key, hourly)
    return hourly


def _daytime_max(hourly: dict, variable: str, hours) -> float | None:
    series = hourly.get(variable)
    if not series:
        return None
    values = [v for t, v in zip(hourly["time"], series) if v is not None and int(t[11:13]) in hours]
    return max(values) if values else None


def _number(value, digits=0) -> str:
    return "–" if value is None else f"{value:.{digits}f}"


def _grains(value: float) -> str:
    """Small pollen counts keep a decimal (0.4 must not read as 0)."""
    return f"{value:.1f}" if value < 10 else f"{value:.0f}"


class AirPlugin(SectionPlugin):
    plugin_id = "air"
    section_id = "hazards"
    depends_on = ("weather", "osm_features")
    title_key = "hz_air"

    def run(self, ctx, shared: dict) -> Section:
        lang = ctx.lang
        lat, lon = ctx.centroid
        weather = shared.get("weather") or {}
        day_rows = weather.get("daytime_rows") or []
        hours = {r["hour"] for r in day_rows} or set(DEFAULT_HOURS)
        lines, warnings, has_data = [], [], False

        try:
            hourly = _fetch(ctx, lat, lon)
        except HttpError as e:
            lines.append("- " + tr("air_unavailable", lang, reason=str(e) or "error"))
        else:
            # pollen
            peaks = {v: _daytime_max(hourly, v, hours) for v in POLLEN_VARS}
            if all(p is None for p in peaks.values()):
                lines.append("- " + tr("air_pollen_no_data", lang))
            else:
                has_data = True
                present = {v: p for v, p in peaks.items() if p is not None and p > 0}
                if not present:
                    lines.append("- " + tr("air_pollen_none", lang))
                else:
                    names, levels = tr("air_pollen_kinds", lang), tr("air_level", lang)
                    parts = ", ".join(f"{names[v]} {_grains(p)} ({levels[pollen_level(v, p)]})"
                                      for v, p in sorted(present.items(), key=lambda kv: -kv[1]))
                    lines.append("- " + tr("air_pollen_line", lang, parts=parts))
                    lines.append("  *" + tr("air_pollen_scale", lang) + "*")
                    worst = max(present.items(), key=lambda kv: (pollen_level(kv[0], kv[1]) in ("high", "very_high"), kv[1]))
                    if pollen_level(*worst) in ("high", "very_high"):
                        warnings.append(PlanWarning("caution", tr("air_warn_pollen", lang, kind=names[worst[0]],
                                                                  value=_grains(worst[1]))))
            # pollution
            values = {v: _daytime_max(hourly, v, hours) for v in POLLUTION_VARS}
            if values["european_aqi"] is None and all(v is None for v in values.values()):
                lines.append("- " + tr("air_pollution_no_data", lang))
            else:
                has_data = True
                aqi = values["european_aqi"]
                cls = aqi_class(aqi) if aqi is not None else 0
                lines.append("- " + tr("air_pollution_line", lang, pm25=_number(values["pm2_5"]), pm10=_number(values["pm10"]),
                                       o3=_number(values["ozone"]), no2=_number(values["nitrogen_dioxide"]),
                                       so2=_number(values["sulphur_dioxide"]), dust=_number(values["dust"]),
                                       aqi=_number(aqi), aqi_class=tr("air_aqi", lang)[cls]))
                if aqi is not None and cls >= 3:
                    warnings.append(PlanWarning("danger" if cls >= 5 else "caution", tr("air_warn_aqi", lang, aqi=f"{aqi:.0f}")))

        # industrial emissions carried toward the route by the wind
        osm = shared.get("osm_features") or {}
        if osm.get("samples") and not osm.get("error"):
            sites = near(osm.get("features", []), osm["samples"], "industrial", EMISSION_RADIUS_M)
            if sites:
                km = f"{EMISSION_RADIUS_M / 1000:.0f}"
                downwind_sites, downwind_hours = set(), set()
                for row in day_rows:
                    if row.get("wind") is None or row.get("wdir") is None or row["wind"] < 1.0:
                        continue
                    carried_to = (row["wdir"] + 180.0) % 360.0
                    for feature, _ in sites:
                        nearest = min(osm["samples"], key=lambda s: haversine_m(feature.lat, feature.lon, s[0], s[1]))
                        if angle_difference(bearing_deg(feature.lat, feature.lon, nearest[0], nearest[1]), carried_to) \
                                <= DOWNWIND_TOLERANCE_DEG:
                            downwind_sites.add((feature.lat, feature.lon))
                            downwind_hours.add(row["hour"])
                if downwind_hours:
                    windows = hour_ranges(sorted(downwind_hours))
                    lines.append("- " + tr("air_emissions", lang, km=km, count=len({(f.lat, f.lon) for f, _ in sites}),
                                           down=len(downwind_sites), hours=windows))
                    warnings.append(PlanWarning("info", tr("air_warn_emissions", lang, hours=windows)))
                else:
                    lines.append("- " + tr("air_emissions_none_downwind", lang, km=km,
                                           count=len({(f.lat, f.lon) for f, _ in sites})))

        fact = lookup(ctx.facts, ctx.date_iso, "air")
        if fact:
            lines += ["", tr("air_web_title", lang), "", fact["markdown"], "", sources_line(fact["sources"], lang)]
            for w in fact.get("warnings", []):
                warnings.append(PlanWarning(w["severity"], w["text"]))
        confidence = "web-sourced" if fact else "derived" if has_data else "no-data"
        return Section("hazards", "\n".join(lines), confidence, sources=list(fact["sources"]) if fact else [],
                       warnings=warnings)
```

Create `skills/osm-day-route-day-plan/tests/fixtures/air_madrid.json`:

```json
{"hourly": {"time": ["2026-10-01T00:00", "2026-10-01T01:00", "2026-10-01T02:00", "2026-10-01T03:00", "2026-10-01T04:00", "2026-10-01T05:00", "2026-10-01T06:00", "2026-10-01T07:00", "2026-10-01T08:00", "2026-10-01T09:00", "2026-10-01T10:00", "2026-10-01T11:00", "2026-10-01T12:00", "2026-10-01T13:00", "2026-10-01T14:00", "2026-10-01T15:00", "2026-10-01T16:00", "2026-10-01T17:00", "2026-10-01T18:00", "2026-10-01T19:00", "2026-10-01T20:00", "2026-10-01T21:00", "2026-10-01T22:00", "2026-10-01T23:00"], "alder_pollen": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], "birch_pollen": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], "olive_pollen": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], "grass_pollen": [0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.2, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1], "mugwort_pollen": [0.5, 0.6, 0.7, 0.7, 0.5, 0.5, 0.3, 0.2, 0.3, 0.2, 0.2, 0.2, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.2, 0.2, 0.2, 0.2, 0.2], "ragweed_pollen": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], "pm2_5": [13.0, 12.8, 12.5, 12.4, 12.2, 12.1, 11.8, 12.9, 13.6, 12.9, 11.8, 10.4, 9.9, 10.3, 10.3, 10.3, 10.4, 10.0, 10.1, 10.1, 10.3, 11.8, 10.5, 8.9], "pm10": [34.5, 34.0, 32.9, 29.4, 25.7, 24.2, 26.3, 28.3, 28.6, 28.1, 25.9, 22.6, 20.5, 20.8, 23.3, 29.3, 26.3, 24.8, 24.4, 26.1, 27.6, 25.4, 22.0, 18.7], "ozone": [20.0, 21.0, 20.0, 25.0, 23.0, 22.0, 17.0, 10.0, 5.0, 5.0, 23.0, 35.0, 44.0, 52.0, 65.0, 73.0, 76.0, 77.0, 77.0, 65.0, 58.0, 48.0, 46.0, 41.0], "nitrogen_dioxide": [23.2, 25.1, 23.6, 19.8, 21.1, 20.2, 26.1, 29.2, 34.8, 33.7, 26.5, 19.1, 14.9, 11.4, 12.4, 10.7, 12.7, 14.7, 18.9, 26.1, 28.9, 27.2, 27.9, 27.2], "sulphur_dioxide": [2.0, 2.1, 2.0, 2.0, 2.2, 2.8, 2.6, 3.1, 3.4, 3.6, 2.0, 1.7, 1.5, 1.3, 1.5, 1.3, 1.2, 1.5, 1.5, 1.9, 2.2, 2.3, 2.4, 2.1], "dust": [13.0, 13.0, 12.0, 11.0, 11.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 9.0, 9.0, 10.0, 11.0, 13.0, 13.0, 14.0, 14.0, 13.0, 10.0, 9.0, 8.0, 6.0], "european_aqi": [38, 40, 38, 35, 35, 34, 41, 42, 46, 45, 41, 32, 30, 31, 31, 31, 31, 30, 32, 41, 42, 41, 42, 41]}}
```

Create `skills/osm-day-route-day-plan/tests/fixtures/air_kazan.json`:

```json
{"hourly": {"time": ["2026-10-01T00:00", "2026-10-01T01:00", "2026-10-01T02:00", "2026-10-01T03:00", "2026-10-01T04:00", "2026-10-01T05:00", "2026-10-01T06:00", "2026-10-01T07:00", "2026-10-01T08:00", "2026-10-01T09:00", "2026-10-01T10:00", "2026-10-01T11:00", "2026-10-01T12:00", "2026-10-01T13:00", "2026-10-01T14:00", "2026-10-01T15:00", "2026-10-01T16:00", "2026-10-01T17:00", "2026-10-01T18:00", "2026-10-01T19:00", "2026-10-01T20:00", "2026-10-01T21:00", "2026-10-01T22:00", "2026-10-01T23:00"], "alder_pollen": [null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null], "birch_pollen": [null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null], "olive_pollen": [null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null], "grass_pollen": [null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null], "mugwort_pollen": [null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null], "ragweed_pollen": [null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null], "pm2_5": [5.2, 5.3, 5.2, 4.9, 4.5, 4.0, 3.5, 3.1, 2.3, 1.9, 1.4, 1.2, 1.1, 1.0, 0.9, 0.8, 0.7, 0.7, 0.9, 0.9, 0.9, 0.8, 0.7, 0.7], "pm10": [5.2, 5.4, 5.3, 5.1, 4.7, 4.2, 3.7, 3.2, 2.4, 2.1, 1.7, 1.5, 1.4, 1.3, 1.2, 1.0, 0.9, 0.8, 0.9, 1.0, 1.0, 0.9, 0.8, 0.8], "ozone": [40.0, 40.0, 41.0, 42.0, 43.0, 44.0, 45.0, 47.0, 49.0, 52.0, 56.0, 61.0, 63.0, 62.0, 58.0, 56.0, 55.0, 56.0, 56.0, 57.0, 58.0, 59.0, 59.0, 60.0], "nitrogen_dioxide": [6.1, 5.9, 5.6, 5.2, 4.9, 4.6, 4.2, 3.5, 2.7, 2.0, 1.5, 1.1, 0.9, 0.9, 1.1, 1.3, 1.6, 2.0, 2.3, 2.3, 2.2, 2.0, 1.9, 1.7], "sulphur_dioxide": [1.2, 1.2, 1.2, 1.3, 1.4, 1.4, 1.5, 1.5, 1.5, 1.5, 1.4, 1.2, 1.1, 1.0, 1.0, 0.9, 0.9, 0.8, 0.8, 0.8, 0.7, 0.7, 0.7, 0.7], "dust": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], "european_aqi": [20, 21, 20, 20, 18, 16, 15, 16, 16, 17, 19, 21, 22, 21, 19, 19, 18, 19, 19, 19, 19, 20, 20, 20]}}
```

Create `skills/osm-day-route-day-plan/tests/fixtures/air_moscow.json`:

```json
{"hourly": {"time": ["2026-10-01T00:00", "2026-10-01T01:00", "2026-10-01T02:00", "2026-10-01T03:00", "2026-10-01T04:00", "2026-10-01T05:00", "2026-10-01T06:00", "2026-10-01T07:00", "2026-10-01T08:00", "2026-10-01T09:00", "2026-10-01T10:00", "2026-10-01T11:00", "2026-10-01T12:00", "2026-10-01T13:00", "2026-10-01T14:00", "2026-10-01T15:00", "2026-10-01T16:00", "2026-10-01T17:00", "2026-10-01T18:00", "2026-10-01T19:00", "2026-10-01T20:00", "2026-10-01T21:00", "2026-10-01T22:00", "2026-10-01T23:00"], "alder_pollen": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], "birch_pollen": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], "olive_pollen": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], "grass_pollen": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], "mugwort_pollen": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], "ragweed_pollen": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], "pm2_5": [26.8, 26.0, 24.1, 22.6, 22.5, 21.7, 22.2, 23.3, 31.9, 33.6, 29.5, 23.6, 18.6, 18.1, 19.1, 19.0, 18.9, 19.7, 20.4, 34.9, 35.1, 35.9, 34.7, 34.7], "pm10": [33.8, 32.4, 30.1, 28.3, 27.3, 27.2, 28.1, 29.9, 40.4, 37.0, 32.7, 25.8, 21.1, 22.1, 23.3, 23.2, 23.1, 24.1, 26.5, 46.2, 46.6, 47.5, 44.3, 43.8], "ozone": [3.0, 5.0, 9.0, 9.0, 7.0, 5.0, 3.0, 1.0, 2.0, 5.0, 9.0, 15.0, 18.0, 24.0, 24.0, 22.0, 19.0, 13.0, 5.0, 1.0, 2.0, 2.0, 1.0, 1.0], "nitrogen_dioxide": [54.5, 48.7, 38.6, 38.7, 39.7, 39.8, 41.0, 50.2, 57.6, 58.1, 52.4, 46.9, 44.2, 40.6, 41.9, 46.9, 52.4, 61.6, 73.0, 76.2, 71.4, 65.2, 62.1, 58.1], "sulphur_dioxide": [40.6, 40.0, 39.4, 39.4, 44.9, 46.4, 46.5, 49.6, 51.0, 48.4, 43.5, 30.9, 23.4, 23.1, 23.8, 24.9, 29.1, 32.2, 34.5, 50.7, 52.2, 51.9, 48.9, 47.6], "dust": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], "european_aqi": [57, 54, 48, 48, 48, 48, 49, 54, 59, 59, 56, 53, 51, 49, 50, 53, 56, 61, 67, 68, 66, 63, 61, 59]}}
```

- [ ] **Step 4: Run the whole suite** — `cd skills/osm-day-route-day-plan && python3 -m pytest tests -q` (all green), and for the show skill `cd skills/osm-day-route-show && python3 -m pytest tests -q`.

- [ ] **Step 5: Commit**

```bash
git add skills README.md
git commit -m "Air: pollen and pollution from the CAMS model

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

### Task 8: Wire the hazard plugins into the CLI and record_fact

`default_plugins()` gets `OsmFeaturesPlugin`, `MountainPlugin`, `FirePlugin`, `BioHazardsPlugin`, `AirPlugin`; `main()` gains `http_text`; `record_fact.py` accepts `fire`, `mountain`, `bio_hazards`, `air` (with `--warning`, without departure options); the CLI prints an optional `hint (optional):` line for the hazard sections that apply. CLI tests fake `http_text` so nothing touches the network.

**Files:**
- Modify: `skills/osm-day-route-day-plan/tests/test_cli.py`
- Modify: `skills/osm-day-route-day-plan/scripts/build_day_plan.py`
- Modify: `skills/osm-day-route-day-plan/scripts/record_fact.py`

- [ ] **Step 1: Add the tests** (21 tests in the file(s) below)

Modify `skills/osm-day-route-day-plan/tests/test_cli.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-day-plan/tests/test_cli.py
+++ b/skills/osm-day-route-day-plan/tests/test_cli.py
@@ -1,12 +1,21 @@
+import pytest
 import datetime
 
 import build_day_plan
 
 
+
+def _text(url):
+    """GWIS answers for the CLI tests: a calm fire-weather index, no active fires."""
+    if "ecmwf.query" in url:
+        return "<table id='main'><tr><td>Fire Weather Index (FWI)</td><td>9.5</td></tr></table>"
+    return ""
+
+
 def test_cli_writes_plan_file_and_reports_path(make_route, weather_response, fixed_now, capsys):
     route_dir = make_route()
     code = build_day_plan.main([str(route_dir), "2026-06-21", "--lang", "en", "--departure", "Waterloo",
-                                "--start", "09:00"], http=lambda url: weather_response(), now=fixed_now)
+                                "--start", "09:00"], http=lambda url: weather_response(), http_text=_text, now=fixed_now)
     assert code == 0
     text = (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
     assert "From: Waterloo" in text
@@ -17,10 +26,10 @@
 def test_cli_overwrites_the_same_date_and_keeps_other_dates(make_route, weather_response, fixed_now):
     route_dir = make_route()
     http = lambda url: weather_response()  # noqa: E731
-    build_day_plan.main([str(route_dir), "2026-06-21"], http=http, now=fixed_now)
+    build_day_plan.main([str(route_dir), "2026-06-21"], http=http, http_text=_text, now=fixed_now)
     build_day_plan.main([str(route_dir), "2026-06-22"], http=lambda url: weather_response(date="2026-06-22"),
-                        now=fixed_now)
-    build_day_plan.main([str(route_dir), "2026-06-21", "--lang", "ru"], http=http, now=fixed_now)
+                        http_text=_text, now=fixed_now)
+    build_day_plan.main([str(route_dir), "2026-06-21", "--lang", "ru"], http=http, http_text=_text, now=fixed_now)
     assert (route_dir / "day-plan-2026-06-22.md").exists()
     assert "Главное на день" in (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
 
@@ -28,7 +37,7 @@
 def test_cli_drops_departure_that_looks_like_a_street_address(make_route, weather_response, fixed_now, capsys):
     route_dir = make_route()
     build_day_plan.main([str(route_dir), "2026-06-21", "--departure", "Baker Street 221B"],
-                        http=lambda url: weather_response(), now=fixed_now)
+                        http=lambda url: weather_response(), http_text=_text, now=fixed_now)
     text = (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
     assert "Baker" not in text and "From:" not in text
     assert "street address" in capsys.readouterr().err
@@ -47,7 +56,7 @@
 
 def test_plan_written_by_cli_is_found_by_glob_used_in_show(make_route, weather_response, fixed_now):
     route_dir = make_route()
-    build_day_plan.main([str(route_dir), "2026-06-21"], http=lambda url: weather_response(), now=fixed_now)
+    build_day_plan.main([str(route_dir), "2026-06-21"], http=lambda url: weather_response(), http_text=_text, now=fixed_now)
     assert [p.name for p in route_dir.glob("day-plan-????-??-??.md")] == ["day-plan-2026-06-21.md"]
 
 
@@ -74,24 +83,28 @@
 
 def test_default_plan_has_getting_there_and_points_of_interest(make_route_with_points, weather_response, fixed_now):
     route_dir = _route_with_points(make_route_with_points)
-    assert build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), now=fixed_now) == 0
+    assert build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text, now=fixed_now) == 0
     text = (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
     headings = [line for line in text.splitlines() if line.startswith("## ")]
-    assert headings == ["## Summary", "## Daylight", "## Weather by hour", "## Getting there", "## Points of interest"]
+    assert headings == ["## Summary", "## Daylight", "## Weather by hour", "## Getting there", "## Points of interest",
+                        "## Hazards"]
+    subheadings = [line for line in text.splitlines() if line.startswith("### ")]
+    assert subheadings == ["### Mountain hazards", "### Fire danger", "### Ticks and biting insects",
+                           "### Air: pollen and pollution"]
     assert "| Lago | start |" in text and "| Museo | sight | 10:00–18:00 |" in text and "| Lago | 41 | bus |" in text
-    assert "<!-- plugins: weather 1, light 1, transit 1, poi_hours 1 -->" in text
+    assert "<!-- plugins: weather 1, light 1, osm_features 1, transit 1, poi_hours 1, mountain 1, fire 1, bio_hazards 1, air 1 -->" in text
 
 
 def test_hint_asks_for_web_facts_until_they_are_recorded(make_route_with_points, weather_response, fixed_now, capsys):
     route_dir = _route_with_points(make_route_with_points)
-    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), now=fixed_now)
+    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text, now=fixed_now)
     out = capsys.readouterr().out
     assert "hint: no web-sourced facts recorded for transit, poi_hours on 2026-06-21" in out and "record_fact.py" in out
 
     import record_fact
     for plugin in ("transit", "poi_hours"):
         record_fact.record(route_dir, "2026-06-21", plugin, "Found on the web.", ["https://example.org/x"])
-    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), now=fixed_now)
+    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text, now=fixed_now)
     out2 = capsys.readouterr().out
     assert "hint:" not in out2
     assert "Found on the web." in (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
@@ -99,7 +112,7 @@
 
 def test_hint_mentions_only_what_the_route_needs(make_route, weather_response, fixed_now, capsys):
     route_dir = make_route()                        # a route without points of interest
-    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), now=fixed_now)
+    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text, now=fixed_now)
     assert "recorded for transit on" in capsys.readouterr().out
 
 
@@ -113,7 +126,7 @@
             raise HttpError("504")
         return inner(url)
 
-    assert build_day_plan.main([str(route_dir), "2026-06-21"], http=http, now=fixed_now) == 0
+    assert build_day_plan.main([str(route_dir), "2026-06-21"], http=http, http_text=_text, now=fixed_now) == 0
     text = (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
     assert "OSM lists no lines for these access points" in text and "## Points of interest" in text
 
@@ -122,7 +135,7 @@
     import json
     route_dir = _route_with_points(make_route_with_points)
     (route_dir / "facts.json").write_text(json.dumps({"2026-06-21": {"transit": {"markdown": "UNSOURCED CLAIM"}, "poi_hours": "not a dict"}, "all": ["x"]}), encoding="utf-8")
-    assert build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), now=fixed_now) == 0
+    assert build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text, now=fixed_now) == 0
     text = (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
     assert "UNSOURCED CLAIM" not in text
     out = capsys.readouterr().out
@@ -132,7 +145,7 @@
 def test_facts_json_as_array_does_not_break_the_plan(make_route_with_points, weather_response, fixed_now, capsys):
     route_dir = _route_with_points(make_route_with_points)
     (route_dir / "facts.json").write_text("[]", encoding="utf-8")
-    assert build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), now=fixed_now) == 0
+    assert build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text, now=fixed_now) == 0
     out = capsys.readouterr().out
     assert "hint: no web-sourced facts recorded for transit" in out
 
@@ -140,7 +153,7 @@
 def test_facts_json_as_string_does_not_break_the_plan(make_route_with_points, weather_response, fixed_now, capsys):
     route_dir = _route_with_points(make_route_with_points)
     (route_dir / "facts.json").write_text('"just a string"', encoding="utf-8")
-    assert build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), now=fixed_now) == 0
+    assert build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text, now=fixed_now) == 0
     out = capsys.readouterr().out
     assert "hint: no web-sourced facts recorded for transit" in out
 
@@ -148,7 +161,7 @@
 def test_facts_json_with_bad_encoding_does_not_break_the_plan(make_route_with_points, weather_response, fixed_now, capsys):
     route_dir = _route_with_points(make_route_with_points)
     (route_dir / "facts.json").write_bytes(b"\xff\xfe\x00")
-    assert build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), now=fixed_now) == 0
+    assert build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text, now=fixed_now) == 0
     out = capsys.readouterr().out
     assert "hint: no web-sourced facts recorded for transit" in out
 
@@ -167,7 +180,7 @@
 
 def test_russian_route_hint_asks_for_a_calendar_fact_until_one_is_recorded(make_route, weather_response, fixed_now, capsys):
     route_dir = make_route()
-    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web_country(weather_response, "ru"), now=fixed_now)
+    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web_country(weather_response, "ru"), http_text=_text, now=fixed_now)
     out = capsys.readouterr().out
     assert "recorded for transit, calendar on 2026-06-21" in out
     assert ("calendar: check in the official calendar whether the date is a public holiday, a transferred day off "
@@ -175,7 +188,7 @@
 
     import record_fact
     record_fact.record(route_dir, "2026-06-21", "calendar", "", ["https://example.org/x"], day_type="weekend")
-    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web_country(weather_response, "ru"), now=fixed_now)
+    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web_country(weather_response, "ru"), http_text=_text, now=fixed_now)
     out2 = capsys.readouterr().out
     assert "recorded for transit on" in out2 and "calendar" not in out2
 
@@ -185,11 +198,65 @@
     route_dir = make_route()
     (route_dir / "facts.json").write_text(json.dumps({"all": {"calendar": {
         "day_type": "workday", "sources": ["https://example.org/x"]}}}), encoding="utf-8")
-    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web_country(weather_response, "ru"), now=fixed_now)
+    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web_country(weather_response, "ru"), http_text=_text, now=fixed_now)
     assert "calendar: check in the official calendar" in capsys.readouterr().out
 
 
 def test_a_route_outside_russia_never_mentions_the_calendar(make_route, weather_response, fixed_now, capsys):
     route_dir = make_route()
-    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web_country(weather_response, "es"), now=fixed_now)
+    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web_country(weather_response, "es"), http_text=_text, now=fixed_now)
     assert "calendar" not in capsys.readouterr().out
+
+
+# ---- plan 3a: hazards ---------------------------------------------------------------------------
+
+def test_the_hazard_group_is_assembled_and_the_data_plugin_stays_invisible(make_route_with_points, weather_response, fixed_now):
+    route_dir = _route_with_points(make_route_with_points)
+    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text, now=fixed_now)
+    text = (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
+    assert "Fire Weather Index (FWI, ECMWF model via the Copernicus GWIS service): **9.5** — low" in text
+    assert "Route elevation 600–640 m (relief 40 m)." in text
+    assert "## OSM" not in text and "osm_features" not in "\n".join(l for l in text.splitlines() if l.startswith("#"))
+    assert text.index("### Mountain hazards") < text.index("### Fire danger") < text.index("### Air: pollen and pollution")
+
+
+def test_the_optional_hazard_hint_lists_only_what_applies_and_disappears_when_recorded(
+        make_route_with_points, make_route, weather_response, fixed_now, capsys):
+    import record_fact
+    route_dir = _route_with_points(make_route_with_points)
+    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text, now=fixed_now)
+    out = capsys.readouterr().out
+    assert "hint (optional): regional facts would improve the hazard sections: fire, mountain, bio_hazards" in out
+    for plugin in ("fire", "mountain", "bio_hazards"):
+        record_fact.record(route_dir, "2026-06-21", plugin, "Local note.", ["https://example.org/x"])
+    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text, now=fixed_now)
+    assert "hint (optional)" not in capsys.readouterr().out
+    flat = make_route(folder="flat", coords=((-3.75, 40.42, 100.0), (-3.74, 40.43, 120.0)))
+    build_day_plan.main([str(flat), "2026-12-15"], http=_web(weather_response, date="2026-12-15"), http_text=_text,
+                        now=fixed_now)
+    winter = capsys.readouterr().out
+    assert "regional facts would improve the hazard sections: fire " in winter or "sections: fire —" in winter
+
+
+def test_record_fact_accepts_the_hazard_plugins_and_their_warnings(tmp_path):
+    import record_fact
+    for plugin in ("fire", "mountain", "bio_hazards", "air"):
+        entry = record_fact.record(tmp_path, "all", plugin, "Note.", ["https://example.org/x"], warnings=[
+            {"severity": "caution", "text": "Careful."}])
+        assert entry["warnings"] == [{"severity": "caution", "text": "Careful."}]
+    with pytest.raises(ValueError, match="fire plugin does not use --last-departure"):
+        record_fact.record(tmp_path, "all", "fire", "Note.", ["https://example.org/x"], last_departure="21:00")
+
+
+def test_a_failing_hazard_plugin_never_breaks_the_rest_of_the_plan(make_route_with_points, weather_response, fixed_now,
+                                                                     capsys):
+    route_dir = _route_with_points(make_route_with_points)
+
+    def broken_text(url):
+        raise RuntimeError("GWIS exploded")
+
+    assert build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=broken_text,
+                               now=fixed_now) == 0
+    text = (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
+    assert "## Getting there" in text and "### Fire danger" in text and "could not be built" in text
+    assert "plugin fire failed" in capsys.readouterr().err
```

- [ ] **Step 2: Run them and see them fail** — `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_cli.py -q` (import errors or assertion failures: the code does not exist yet).

- [ ] **Step 3: Write the implementation**

Modify `skills/osm-day-route-day-plan/scripts/build_day_plan.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-day-plan/scripts/build_day_plan.py
+++ b/skills/osm-day-route-day-plan/scripts/build_day_plan.py
@@ -19,8 +19,15 @@
 from day_plan import calendar_info
 from day_plan.context import build_context
 from day_plan.facts import lookup
-from day_plan.http import get_json
+from day_plan.http import get_json, get_text
+from day_plan.osm_features import OsmFeaturesPlugin
+from day_plan.plugins.air import AirPlugin
+from day_plan.plugins.bio_hazards import BioHazardsPlugin, TICK_MONTHS, in_season
+from day_plan.plugins.fire import FirePlugin
 from day_plan.plugins.light import LightPlugin
+from day_plan.plugins.mountain import (
+    MOUNTAIN_MIN_ELEVATION_M, MOUNTAIN_MIN_RELIEF_M, MountainPlugin, elevation_stats,
+)
 from day_plan.plugins.poi_hours import PoiHoursPlugin
 from day_plan.plugins.transit import TransitPlugin
 from day_plan.plugins.weather import WeatherPlugin
@@ -28,7 +35,8 @@
 
 
 def default_plugins() -> list:
-    return [WeatherPlugin(), LightPlugin(), TransitPlugin(), PoiHoursPlugin()]
+    return [WeatherPlugin(), LightPlugin(), OsmFeaturesPlugin(), TransitPlugin(), PoiHoursPlugin(),
+            MountainPlugin(), FirePlugin(), BioHazardsPlugin(), AirPlugin()]
 
 
 def missing_web_facts(ctx) -> list:
@@ -42,6 +50,18 @@
     return missing
 
 
+def optional_hazard_facts(ctx) -> list:
+    """Hazard plugins whose regional web facts would improve this plan and are not recorded yet: fire
+    restrictions always, mountain notes for mountain routes, insect/animal notes in the tick season."""
+    wanted = ["fire"]
+    stats = elevation_stats(ctx.coords)
+    if stats and (stats[1] >= MOUNTAIN_MIN_ELEVATION_M or stats[2] >= MOUNTAIN_MIN_RELIEF_M):
+        wanted.append("mountain")
+    if in_season(ctx.date.month, TICK_MONTHS, ctx.centroid[0]):
+        wanted.append("bio_hazards")
+    return [pid for pid in wanted if lookup(ctx.facts, ctx.date_iso, pid) is None]
+
+
 def coarse_departure(text: str | None) -> tuple[str | None, bool]:
     """(value_to_write, was_dropped). Digits suggest a street address."""
     if not text:
@@ -51,7 +71,7 @@
     return text.strip(), False
 
 
-def main(argv=None, http=get_json, now=None, plugins=None) -> int:
+def main(argv=None, http=get_json, now=None, plugins=None, http_text=get_text) -> int:
     parser = argparse.ArgumentParser(description=__doc__)
     parser.add_argument("route_dir")
     parser.add_argument("date", help="YYYY-MM-DD")
@@ -77,7 +97,7 @@
               "written to the plan. Pass a city, station or stop.", file=sys.stderr)
 
     ctx = build_context(route_dir, date, lang=args.lang, departure=departure, start_time=start,
-                        http=http, now=now)
+                        http=http, http_text=http_text, now=now)
     result = build_plan(ctx, plugins if plugins is not None else default_plugins())
     out = route_dir / f"day-plan-{date.isoformat()}.md"
     out.write_text(result.markdown, encoding="utf-8")
@@ -92,6 +112,12 @@
               + (". calendar: check in the official calendar whether the date is a public holiday, a "
                  "transferred day off or a working Saturday, and record it with --plugin calendar "
                  "--day-type ..." if "calendar" in missing else ""))
+    optional = optional_hazard_facts(ctx)
+    if optional:
+        print(f"hint (optional): regional facts would improve the hazard sections: {', '.join(optional)} — "
+              f"fire: forest-access and open-fire restrictions; mountain: avalanche bulletin, closed huts or passes; "
+              f"bio_hazards: insect season and peaks, animals (bears, snakes, boar) and hunting; record them with "
+              f"record_fact.py --plugin <name>")
     return 0
 
 
```

Modify `skills/osm-day-route-day-plan/scripts/record_fact.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-day-plan/scripts/record_fact.py
+++ b/skills/osm-day-route-day-plan/scripts/record_fact.py
@@ -25,7 +25,8 @@
 from day_plan.base import SEVERITIES
 from day_plan.facts import DAY_TYPES, normalize_entry
 
-PLUGINS = ("transit", "poi_hours", "calendar")
+PLUGINS = ("transit", "poi_hours", "calendar", "fire", "mountain", "bio_hazards", "air")
+WARNING_PLUGINS = ("transit", "poi_hours", "fire", "mountain", "bio_hazards", "air")
 
 
 def record(route_dir, date: str, plugin: str, markdown: str, sources: list, last_departure: str | None = None,
@@ -46,7 +47,7 @@
     for option, value, uses in (("--day-type", day_type, ("calendar",)),
                                 ("--last-departure", last_departure, ("transit",)),
                                 ("--first-departure", first_departure, ("transit",)),
-                                ("--warning", warnings, ("transit", "poi_hours"))):
+                                ("--warning", warnings, WARNING_PLUGINS)):
         if value and plugin not in uses:
             raise ValueError(f"the {plugin} plugin does not use {option} (only: {', '.join(uses)})")
     entry = {"markdown": markdown, "sources": sources}
```

- [ ] **Step 4: Run the whole suite** — `cd skills/osm-day-route-day-plan && python3 -m pytest tests -q` (all green), and for the show skill `cd skills/osm-day-route-show && python3 -m pytest tests -q`.

- [ ] **Step 5: Commit**

```bash
git add skills README.md
git commit -m "CLI: hazard plugins registered, optional hazard hints, record_fact accepts the hazard plugins

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

### Task 9: Documentation

SKILL.md (sections, sources, recording hazard facts, limitations, common mistakes) and README (what the plan contains now).

**Files:**
- Modify: `README.md`
- Modify: `skills/osm-day-route-day-plan/SKILL.md`

- [ ] **Step 1: Write the implementation**

Modify `README.md` — apply this patch (`patch -p1`):

```diff
--- a/README.md
+++ b/README.md
@@ -65,13 +65,19 @@
 - **Weather by hour:** temperature and feels-like, precipitation and its probability, cloud cover, visibility, **wind speed and the direction it blows from**, gusts, snow cover, and a plain-language sky description.
 - **Getting there:** what kind of day it is (weekday, weekend, public holiday), the opening hours of your access points on that date, the bus / train / metro lines that stop there (from OpenStreetMap, which rarely has schedules), and — when Claude has looked them up on the web and recorded them with sources — timetables and directions from where you start. If the last departure home is before your estimated return, or the return point closes before it, the summary says so; both checks need a start time (`--start`) and a route duration.
 - **Points of interest:** whether each one is open on that date (from its OpenStreetMap opening hours), your notes, and web-sourced opening days and special features when recorded.
+- **Hazards**, only the parts that apply to your route and date:
+  - *Mountain hazards* where the route reaches 600 m or more: cold and freezing level, wind, thunderstorms, snow, scree, cliffs, glaciers, path difficulty from OpenStreetMap.
+  - *Fire danger:* the official Fire Weather Index (Copernicus GWIS, up to 8 days ahead), the Russian Nesterov class for routes in Russia, and active fires detected near the route by satellite.
+  - *Ticks and biting insects:* ticks, mosquitoes, blackflies and midges, horseflies, estimated from temperature, wind, humidity and water near the route. Especially useful for Siberia and the Urals.
+  - *Air:* pollen (Europe up to about 45° E; for the rest of Russia the plan points to Yandex Weather) and pollution (European AQI, PM10, PM2.5, ozone), up to about 4 days ahead.
+  - Regional knowledge Claude finds on the web (fire bans, avalanche bulletins, insect seasons) is added with its sources when recorded.
 
 Good to know:
 - Forecasts reach about 15 days ahead. For a later date you get the average of that date over the last five years, clearly labelled as *not a forecast*. Dates older than a week use recorded weather; the last week uses model data.
 - Ask for a plan for several dates: each gets its own file, and re-running a date overwrites only that date.
 - The plan records where you start from only as a city or station, never a street address, because the file is embedded in `map.html`, which is meant to be forwarded.
 - Everything that comes from the web rather than from OpenStreetMap is labelled *web-sourced* and carries its sources; a fact without a source is refused. For Russia and its neighbours, Claude checks the date against the official calendar, because the free holiday list is incomplete for Russia: it misses 8 January and the transferred days off (for example 9 March and 11 May 2026). The script reminds Claude to record such a date as a `calendar` fact (per date; `holiday` for any official day off including transferred ones, `workday` for working days including working Saturdays).
-- Hazards (ticks, mosquitoes, mountains, air, radiation, fire) and mobile coverage are planned next.
+- Radiation zones, animals, people and mobile coverage are planned next.
 
 ## Skill: osm-day-route-show
 
```

Modify `skills/osm-day-route-day-plan/SKILL.md` — apply this patch (`patch -p1`):

````diff
--- a/skills/osm-day-route-day-plan/SKILL.md
+++ b/skills/osm-day-route-day-plan/SKILL.md
@@ -26,15 +26,28 @@
    from the route archive, and — from `facts.json` — opening days and special
    features.
 
-Hazards (ticks, biting insects, mountains, air, radiation, fire) and mobile
-coverage are separate follow-up plans; until they exist the plan simply has
-no such sections — never invent them by hand.
+6. **Hazards**, with a `###` sub-heading for each part that applies:
+   **Mountain hazards** (only where the route reaches 600 m or more: cold and
+   freezing level, wind, thunderstorms, snow, terrain from OSM), **Fire
+   danger** (official Fire Weather Index from the Copernicus GWIS service,
+   the Russian Nesterov class for routes in Russia, active fires near the
+   route), **Ticks and biting insects** (ticks, mosquitoes, blackflies and
+   midges, horseflies — estimated from weather and water nearby) and **Air:
+   pollen and pollution** (Open-Meteo CAMS model). A part that does not apply
+   (mountains on a flat route, ticks in winter) is left out, not listed as
+   missing.
+
+Radiation zones, animals, people and mobile coverage are a separate follow-up
+plan; until it exists the plan has no such sections — never invent them by
+hand.
 
 Every script is **stdlib-only** (`urllib.request`/`json`/`zoneinfo`), no API
-keys, same rule as the other two skills. Sources: Open-Meteo (weather),
-Overpass (lines through the access points; mirrors and one retry, because the
-public servers answer 429/504 under load), Nominatim (the route's country,
-asked once per route and remembered) and Nager.Date (public holidays).
+keys, same rule as the other two skills. Sources: Open-Meteo (weather and air
+quality), Overpass (lines through the access points and terrain, water and
+industry near the route; mirrors and one retry, because the public servers
+answer 429/504 under load), Copernicus GWIS (Fire Weather Index and active
+fires), Nominatim (the route's country, asked once per route and remembered)
+and Nager.Date (public holidays).
 
 ## When to Use
 
@@ -90,7 +103,8 @@
 never by hand-editing JSON:
 
 ```bash
-python3 record_fact.py <route_dir> --date <YYYY-MM-DD|all> --plugin <transit|poi_hours|calendar> \
+python3 record_fact.py <route_dir> --date <YYYY-MM-DD|all> \
+    --plugin <transit|poi_hours|calendar|fire|mountain|bio_hazards|air> \
     --markdown "text" | --markdown-file note.md \
     --source https://... [--source https://...] \
     [--last-departure HH:MM] [--first-departure HH:MM] \
@@ -98,8 +112,9 @@
 ```
 
 `--last-departure`, `--first-departure` and `--warning` belong to `transit`
-(`--warning` also to `poi_hours`); `--day-type` belongs to `calendar`. The
-helper refuses an option the plugin would ignore.
+(`--warning` also to `poi_hours`, `fire`, `mountain`, `bio_hazards` and
+`air`); `--day-type` belongs to `calendar`. The helper refuses an option the
+plugin would ignore.
 
 - `--plugin transit`: timetables and **directions from the departure point**
   (which train/metro/bus, how long, where to change), frequencies on that
@@ -127,6 +142,13 @@
   Russian route the script's `hint:` line asks for this fact until one is
   recorded for the date. It overrides the list and feeds the opening-hours
   rules (`PH`).
+- `--plugin fire|mountain|bio_hazards|air`: regional knowledge the models
+  cannot give — forest-access and open-fire bans, the avalanche bulletin or
+  closed huts and passes, the insect season and peaks of the region, animals
+  (bears, snakes, boar) and hunting seasons, a local pollen or smog alert.
+  The text appears under the matching hazard sub-heading, labelled
+  web-sourced. The script prints an optional `hint (optional):` line for the
+  hazard sections that apply to the route and date; it never blocks the plan.
 - Every fact needs at least one `http(s)` source, or it is refused (and, if
   found in the file, ignored). Say only what the source says.
 - **Privacy:** facts end up in `day-plan-<date>.md`, embedded in a `map.html`
@@ -168,8 +190,14 @@
   underestimated.
 - Weekends are Saturday and Sunday; countries with another weekend are not
   handled.
-- Pollen, radiation, fire danger, insects, mountain hazards and mobile
-  coverage are not in this version.
+- Fire Weather Index reaches 8 days ahead, air-quality and pollen data about
+  4 days; beyond that the section says so. Pollen is modelled for Europe only
+  (roughly up to 45° E); for the rest of Russia the plan points to the pollen
+  map in Yandex Weather. The Nesterov class is a simplified computation and is
+  shown for Russian routes only.
+- Insect levels are a weather and habitat estimate, not a measurement.
+- Radiation zones, animals, people and mobile coverage are not in this
+  version.
 
 ## Common Mistakes
 
@@ -183,3 +211,5 @@
 - Editing `facts.json` by hand (use `record_fact.py`: it validates, refuses
   source-less facts and never overwrites a file it cannot parse).
 - Forgetting to re-render `map.html` after adding a plan.
+- Recording a `mountain` fact for a flat route or a `bio_hazards` fact in
+  winter: the section does not exist then and the fact is never shown.
````

- [ ] **Step 2: Run the whole suite** — `cd skills/osm-day-route-day-plan && python3 -m pytest tests -q` (all green), and for the show skill `cd skills/osm-day-route-show && python3 -m pytest tests -q`.

- [ ] **Step 3: Commit**

```bash
git add skills README.md
git commit -m "Docs: hazard sections of the day plan

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

### Task 10: Live smoke test and a look in a real browser

No new code unless a defect is found (then fix it with a test in the owning task's test file). Uses the real network; run from `skills/osm-day-route-day-plan/scripts`.

- [ ] **Step 1: Madrid route (flat, Europe).** Save a small route near Casa de Campo with `osm-day-route-planning`'s output layout, or reuse an existing `routes/` folder. Run `python3 build_day_plan.py <route_dir> <a date 2–3 days ahead> --lang en`. Expected: `## Hazards` with `### Fire danger` (FWI value and class), `### Ticks and biting insects` (in season), `### Air: pollen and pollution` (AQI and pollen), no `### Mountain hazards`.
- [ ] **Step 2: Yekaterinburg route (Russia).** Same with `--lang ru`. Expected: Nesterov class beside the FWI, pollen line pointing to Yandex Weather (east of 45° E), the `hint:` for the calendar and the optional hazard hint.
- [ ] **Step 3: Caucasus / mountain route (elevations ≥ 600 m).** Expected: `### Mountain hazards` with freezing level, `sac_scale` and terrain lines from OSM.
- [ ] **Step 4: Horizon checks.** A date 10 days ahead: fire and air sections say what is beyond their horizon. A date in the past: no crash.
- [ ] **Step 5: Hotspot check.** Confirm the hotspot query answers (an empty result is valid); the fire section names the radius and window used.
- [ ] **Step 6: Record one regional fact** for `fire` and one for `bio_hazards` with `record_fact.py`, re-run, confirm the text appears under the right sub-heading labelled web-sourced and the optional hint disappears.
- [ ] **Step 7: Render and open `map.html`** (`python3 ../../osm-day-route-show/scripts/render_map.py <route_dir> --user-lang en`), open it in a browser: the sidebar summary lists hazard warnings, "Open full plan" shows the four `###` sub-sections with legible formatting, download and print work. Do not commit route folders.
- [ ] **Step 8: Final state.** `git status` clean, full suites green in all three skills.
