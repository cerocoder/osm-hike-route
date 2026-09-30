"""The "Trail and road passability" hazard: for each leg between the points of
the route, how passable its trails and roads are in the snow and ice of the
date, for the activity the route was planned for (on foot, or by bicycle with
studded tires). Uses the road data the planner stores in the archive
(`segments`), the snow history of `snow_history` and the pure logic of
`passability.py` and `snowmodel.py`.

The part is left out when neither snow nor frost is plausible (and nothing was
recorded); an old archive without road data, a missing weather history or a
date beyond the forecast get a `no-data` line with the reason. Recorded
`trail_conditions` facts (reports of the current season from the web) are shown
next to the computed verdict and never change it."""
from ..base import PlanWarning, Section, SectionPlugin
from ..facts import lookup
from ..i18n import activity_label, tr
from ..passability import (
    Conditions, build_legs, judge_leg, profile_for, surface_summary,
)
from ..snowmodel import ICE_RANK, applies, in_cold_season, window_conditions
from .common import cell, sources_line

DEFAULT_WINDOW = tuple(range(6, 20))
SPIKES_ICE = ("moderate", "high")
SNOWSHOES_CM = 20.0
MAX_LEG_NAMES = 3


def _is_night(light: dict):
    sunrise, sunset = light.get("sunrise_local_min"), light.get("sunset_local_min")

    def is_night(hour):
        if hour is None:
            return False
        if sunrise is None or sunset is None:
            return hour < 6 or hour >= 20
        return not sunrise <= hour * 60 + 30 <= sunset
    return is_night


def _names(legs: list, lang: str) -> str:
    names = [l.name for l in legs]
    if len(names) <= MAX_LEG_NAMES:
        return "; ".join(names)
    return "; ".join(names[:MAX_LEG_NAMES]) + " " + tr("tp_more", lang, n=len(names) - MAX_LEG_NAMES)


def _snow_text(value: float) -> str:
    return "0" if value <= 0 else "<1" if value < 1 else f"{value:.0f}"


class TrailPassabilityPlugin(SectionPlugin):
    plugin_id = "trail_passability"
    section_id = "hazards"
    depends_on = ("weather", "light", "snow_history")
    title_key = "hz_trails"

    def run(self, ctx, shared: dict) -> Section:
        lang = ctx.lang
        profile = profile_for(ctx.mode, ctx.style)
        if profile is None:                                         # a mode that is not assessed (skiing)
            return Section("hazards", "", "derived", omit=True)
        fact = lookup(ctx.facts, ctx.date_iso, "trail_conditions")
        weather = shared.get("weather") or {}
        history = shared.get("snow_history") or {}
        lat, _ = ctx.centroid
        top = max((c[2] for c in ctx.coords if c[2] is not None), default=None)
        cold = in_cold_season(ctx.date.month, lat, top)
        rows = history.get("rows") or []

        if not rows:                                                # nothing to model with
            if history.get("error") and (cold or fact):
                return self._finish([tr("tp_unavailable", lang, reason=history["error"])], [], "no-data", fact, lang)
            if history.get("source") == "climate" and (cold or fact):
                return self._finish([tr("tp_beyond", lang)], [], "no-data", fact, lang)
            return self._facts_only(fact, lang)

        model_elev = history.get("elevation_m")
        day_start, day_end = history["day_start"], history["day_end"]
        window = [r["hour"] for r in weather.get("daytime_rows") or []] or list(DEFAULT_WINDOW)
        is_night = _is_night(shared.get("light") or {})
        legs = build_legs(ctx.coords, ctx.access_points + ctx.interest_points, ctx.segments or [],
                          tr("tp_start", lang), tr("tp_finish", lang), tr("tp_whole", lang))
        elevations = [l.mean_ele if l.mean_ele is not None else model_elev for l in legs]
        if not legs or not applies(rows, model_elev, elevations, day_start, day_end, window):
            return self._facts_only(fact, lang)
        if ctx.segments is None:
            return self._finish([tr("tp_no_segments", lang)], [], "no-data", fact, lang, applies=True)

        activity = activity_label(ctx.mode, ctx.style, lang)
        studs = tr("tp_studded", lang) if profile != "walk" else ""
        table, verdicts, per_leg = [], [], []
        snow_max, model_max = 0.0, 0.0
        ice_unc_worst = ice_clr_worst = "none"
        for leg, elev in zip(legs, elevations):
            snow, ice_unc, ice_clr, slush = window_conditions(rows, model_elev, elev, day_start, day_end, window, is_night)
            cond = Conditions(snow_cm=snow, ice=ice_unc, slush=slush, ice_cleared=ice_clr)
            verdict = judge_leg(profile, leg, cond)
            verdicts.append(verdict)
            per_leg.append((leg, cond))
            snow_max = max(snow_max, snow)
            model_max = max(model_max, max((rows[day_start + h].get("snow_cm") or 0.0) for h in window
                                           if 0 <= h <= day_end - day_start))
            ice_unc_worst = max(ice_unc_worst, ice_unc, key=ICE_RANK.__getitem__)
            ice_clr_worst = max(ice_clr_worst, ice_clr, key=ICE_RANK.__getitem__)
            leg_ice = max((cond.ice_on(s) for s, _ in leg.runs), key=ICE_RANK.__getitem__, default=cond.ice)
            surfaces = ", ".join(f"{tr('tp_other', lang) if label == 'other' else label} {pct} %"
                                 for label, pct in surface_summary(leg.runs)) or "–"
            table.append(f"| {cell(leg.name)} | {leg.length_km:.1f} | {cell(surfaces)} | {_snow_text(snow)} | "
                         f"{tr('tp_ice', lang)[leg_ice]} | {tr('tp_verdict', lang)[verdict.verdict]} |")

        ice_words = tr("tp_ice", lang)
        window_text = f"{min(window):02d}:00–{max(window) + 1:02d}:00"
        lines = [tr("tp_activity", lang, activity=activity, studs=studs),
                 tr("tp_conditions", lang, snow=_snow_text(snow_max), model=_snow_text(model_max),
                    ice_cleared=ice_words[ice_clr_worst], ice_uncleared=ice_words[ice_unc_worst], window=window_text),
                 "", "| " + " | ".join(tr("tp_cols", lang)) + " |", "|---|---|---|---|---|---|"] + table + [""]
        total = sum(length for leg in legs for _, length in leg.runs) or 1.0
        no_data = sum(v.no_data_share * sum(length for _, length in leg.runs) for v, leg in zip(verdicts, legs)) / total
        assumed = sum(length for leg in legs for s, length in leg.runs if s.assumed and not s.no_data) / total
        if no_data > 0:
            lines.append(tr("tp_no_data_share", lang, pct=f"{100 * no_data:.0f}"))
        if assumed >= 0.5:
            lines.append(tr("tp_assumed", lang, pct=f"{100 * assumed:.0f}"))
        if profile == "walk":
            if ice_unc_worst in SPIKES_ICE or ice_clr_worst in SPIKES_ICE:
                lines.append(tr("tp_advice_spikes", lang))
            if snow_max >= SNOWSHOES_CM:
                lines.append(tr("tp_advice_snowshoes", lang))
        elif any(v.verdict == "danger" and c.snow_cm > 0 for v, (_, c) in zip(verdicts, per_leg)):
            lines.append(tr("tp_advice_fatbike", lang))
        lines += ["", tr("tp_note", lang)]

        warnings = []
        bad = [l for l, v in zip(legs, verdicts) if v.verdict == "danger"]
        hard = [l for l, v in zip(legs, verdicts) if v.verdict == "caution"]
        if bad:
            ice_word = ice_words[max(ice_unc_worst, ice_clr_worst, key=ICE_RANK.__getitem__)]
            if snow_max >= 1.0:
                text = tr("tp_warn_danger", lang, activity=activity, legs=_names(bad, lang),
                          snow=_snow_text(snow_max), ice=ice_word)
            else:
                text = tr("tp_warn_danger_ice", lang, activity=activity, legs=_names(bad, lang), ice=ice_word)
            warnings.append(PlanWarning("danger", text))
        if hard:
            warnings.append(PlanWarning("caution", tr("tp_warn_caution", lang, n=len(hard), m=len(legs),
                                                      legs=_names(hard, lang))))
        return self._finish(lines, warnings, "derived", fact, lang, applies=True)

    @staticmethod
    def _facts_only(fact, lang):
        if not fact:
            return Section("hazards", "", "derived", omit=True)
        return TrailPassabilityPlugin._finish([], [], "derived", fact, lang)

    @staticmethod
    def _finish(lines, warnings, confidence, fact, lang, applies=False) -> Section:
        sources = ["https://open-meteo.com/"] if confidence == "derived" and lines else []
        if fact:
            lines = lines + ([""] if lines else []) + [tr("tp_web_title", lang), "", fact["markdown"], "",
                                                       sources_line(fact["sources"], lang)]
            warnings = warnings + [PlanWarning(w["severity"], w["text"]) for w in fact.get("warnings", [])]
            sources = sources + list(fact["sources"])
            confidence = "web-sourced" if confidence != "no-data" else confidence
        return Section("hazards", "\n".join(lines), confidence, sources=sources, warnings=warnings,
                       shared={"trail_applies": applies})
