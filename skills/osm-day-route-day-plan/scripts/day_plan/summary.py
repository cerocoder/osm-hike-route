"""The "Summary" section: the highest-severity warnings from every other
section, plus a list of sections that have no data. Built by the service
after all plugins ran (it needs their warnings), not a SectionPlugin."""
from .base import Section
from .i18n import tr

_SEVERITY_RANK = {"danger": 0, "caution": 1, "info": 2}
MAX_ITEMS = 5


def _severity_label(severity: str, lang: str) -> str:
    """Localized label; an unknown severity falls back to its own name so one
    bad plugin cannot take the whole summary down."""
    try:
        return tr("sev_" + severity, lang)
    except KeyError:
        return str(severity).capitalize()


def _flat(text) -> str:
    """One line: a newline in a warning must not start a heading or a list."""
    return " ".join(str(text).split())


def build_summary_section(sections: list, lang: str) -> Section:
    warnings = [w for s in sections for w in s.warnings]
    warnings.sort(key=lambda w: _SEVERITY_RANK.get(w.severity, 3))  # stable: keeps plugin order
    lines = [f"- **{_severity_label(w.severity, lang)}:** {_flat(w.text)}" for w in warnings[:MAX_ITEMS]]
    if not lines:
        lines.append("- " + tr("summary_none", lang))
    missing = [s.title or tr("h_" + s.section_id, lang) for s in sections if s.confidence == "no-data" and not s.omit]
    if missing:
        lines.append("- " + tr("summary_no_data", lang, names=", ".join(missing)))
    return Section("summary", "\n".join(lines), "derived", warnings=[])
