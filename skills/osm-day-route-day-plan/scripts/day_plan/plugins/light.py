"""Sunrise, sunset, day length and the margin between sunset and the
route's estimated finish. Confidence: derived (computed locally, no
network). Astronomical events beyond these times are out of scope (spec)."""
import datetime
import math

from ..base import PlanWarning, Section, SectionPlugin
from ..i18n import tr
from ..sun import sun_times

SAFETY_BUFFER_MIN = 60  # finish this long before sunset by default


def _hhmm(minutes: float) -> str:
    m = int(round(minutes)) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def _duration(minutes: float, lang: str) -> str:
    total = int(round(abs(minutes)))
    sign = "-" if minutes < 0 else ""
    return f"{sign}{total // 60} {tr('unit_h', lang)} {total % 60:02d} {tr('unit_min', lang)}"


class LightPlugin(SectionPlugin):
    plugin_id = "light"
    section_id = "light"
    depends_on = ("weather",)

    def run(self, ctx, shared: dict) -> Section:
        lang = ctx.lang
        lat, lon = ctx.centroid
        sun = sun_times(ctx.date, lat, lon)

        if sun.kind == "polar_day":
            return Section("light", "- " + tr("light_polar_day", lang), "derived",
                           warnings=[PlanWarning("info", tr("light_polar_day", lang))],
                           shared={"kind": sun.kind})
        if sun.kind == "polar_night":
            return Section("light", "- " + tr("light_polar_night", lang), "derived",
                           warnings=[PlanWarning("danger", tr("light_warn_polar_night", lang))],
                           shared={"kind": sun.kind})

        weather = shared.get("weather") or {}
        offset_s = weather.get("utc_offset_seconds")
        approximate = offset_s is None
        if approximate:
            offset_s = round(lon / 15.0 * 2) / 2 * 3600  # nearest half hour
        sunrise = sun.sunrise_utc_min + offset_s / 60.0
        sunset = sun.sunset_utc_min + offset_s / 60.0
        length = sunset - sunrise

        lines = ["- " + tr("light_line", lang, sunrise=_hhmm(sunrise), sunset=_hhmm(sunset),
                           length=_duration(length, lang))]
        warnings = []
        if approximate:
            lines.append("- " + tr("light_tz_approx", lang))

        duration_min = ctx.duration_hours * 60.0 if ctx.duration_hours else None
        if duration_min is None:
            lines.append("- " + tr("light_no_duration", lang))
        else:
            if ctx.start_time is not None:
                start = ctx.start_time.hour * 60 + ctx.start_time.minute
                finish = start + duration_min
                margin = sunset - finish
                lines.append("- " + tr("light_finish", lang, start=_hhmm(start), finish=_hhmm(finish),
                                       margin=_duration(margin, lang)))
                if margin < 0:
                    warnings.append(PlanWarning("danger", tr(
                        "light_warn_after_sunset", lang, minutes=int(round(-margin)))))
                elif margin < SAFETY_BUFFER_MIN:
                    warnings.append(PlanWarning("caution", tr("light_warn_tight", lang, buffer=SAFETY_BUFFER_MIN)))
            else:
                latest = sunset - SAFETY_BUFFER_MIN - duration_min
                lines.append("- " + tr("light_latest_start", lang, buffer=SAFETY_BUFFER_MIN, latest=_hhmm(latest)))
                if latest < sunrise and duration_min <= length:
                    warnings.append(PlanWarning("caution", tr("light_warn_tight", lang, buffer=SAFETY_BUFFER_MIN)))
            if duration_min > length:
                warnings.append(PlanWarning("danger", tr(
                    "light_warn_not_fit", lang, hours=round(duration_min / 60.0, 1), length=_duration(length, lang))))

        return Section("light", "\n".join(lines), "derived", warnings=warnings,
                       shared={"kind": "normal", "sunrise_local_min": sunrise, "sunset_local_min": sunset})
