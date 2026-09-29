"""Embedding of day-plan-<date>.md files (written by osm-day-route-day-plan)
into map.html: loading, the sidebar block, the full-plan overlay, and its
small script and print CSS. No imports from render_map — the caller passes
already-rendered HTML — so there is no import cycle.

Design: docs/superpowers/specs/2026-09-29-osm-day-route-day-plan-design.md
("Integration into osm-day-route-show")."""
import datetime
import html
import json
import re
from dataclasses import dataclass
from pathlib import Path

_FILE_RE = re.compile(r"^day-plan-(\d{4}-\d{2}-\d{2})\.md$")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_FETCHED_RE = re.compile(r"<!--\s*day-plan fetched_at:\s*(\S+)\s*-->")

# Headings osm-day-route-day-plan writes for its first section (its i18n
# h_summary in each language) — must stay in sync with that skill.
DAY_PLAN_SUMMARY_HEADINGS = [
    "Summary", "Главное на день", "Resumen del día", "L'essentiel du jour",
    "Das Wichtigste", "Resumo do dia", "In breve",
]

DAY_PLAN_UI = {
    "en": {
        "day_plan_title": "Day plan", "day_plan_open": "Open full plan",
        "day_plan_download": "Download .md", "day_plan_print": "Print / save as PDF",
        "day_plan_none": "No day plan yet — ask Claude to plan a specific date",
        "day_plan_fetched": "Forecast fetched", "day_plan_passed": "date has passed",
        "day_plan_close": "Close", "day_plan_date": "Date",
    },
    "ru": {
        "day_plan_title": "План дня", "day_plan_open": "Открыть полный план",
        "day_plan_download": "Скачать .md", "day_plan_print": "Печать / сохранить в PDF",
        "day_plan_none": "Плана дня пока нет — попросите спланировать конкретную дату",
        "day_plan_fetched": "Прогноз получен", "day_plan_passed": "дата прошла",
        "day_plan_close": "Закрыть", "day_plan_date": "Дата",
    },
    "es": {
        "day_plan_title": "Plan del día", "day_plan_open": "Abrir plan completo",
        "day_plan_download": "Descargar .md", "day_plan_print": "Imprimir / guardar como PDF",
        "day_plan_none": "Aún no hay plan del día — pide planificar una fecha concreta",
        "day_plan_fetched": "Previsión obtenida", "day_plan_passed": "la fecha ya pasó",
        "day_plan_close": "Cerrar", "day_plan_date": "Fecha",
    },
    "fr": {
        "day_plan_title": "Plan du jour", "day_plan_open": "Ouvrir le plan complet",
        "day_plan_download": "Télécharger .md", "day_plan_print": "Imprimer / enregistrer en PDF",
        "day_plan_none": "Pas encore de plan du jour — demandez de planifier une date précise",
        "day_plan_fetched": "Prévision récupérée", "day_plan_passed": "date passée",
        "day_plan_close": "Fermer", "day_plan_date": "Date",
    },
    "de": {
        "day_plan_title": "Tagesplan", "day_plan_open": "Vollständigen Plan öffnen",
        "day_plan_download": ".md herunterladen", "day_plan_print": "Drucken / als PDF speichern",
        "day_plan_none": "Noch kein Tagesplan – bitte ein bestimmtes Datum planen lassen",
        "day_plan_fetched": "Vorhersage abgerufen", "day_plan_passed": "Datum liegt in der Vergangenheit",
        "day_plan_close": "Schließen", "day_plan_date": "Datum",
    },
    "pt": {
        "day_plan_title": "Plano do dia", "day_plan_open": "Abrir plano completo",
        "day_plan_download": "Transferir .md", "day_plan_print": "Imprimir / guardar como PDF",
        "day_plan_none": "Ainda não há plano do dia — peça para planear uma data concreta",
        "day_plan_fetched": "Previsão obtida", "day_plan_passed": "a data já passou",
        "day_plan_close": "Fechar", "day_plan_date": "Data",
    },
    "it": {
        "day_plan_title": "Piano del giorno", "day_plan_open": "Apri il piano completo",
        "day_plan_download": "Scarica .md", "day_plan_print": "Stampa / salva come PDF",
        "day_plan_none": "Nessun piano del giorno — chiedi di pianificare una data precisa",
        "day_plan_fetched": "Previsione ottenuta", "day_plan_passed": "data trascorsa",
        "day_plan_close": "Chiudi", "day_plan_date": "Data",
    },
}


@dataclass
class RawPlan:
    date: str  # YYYY-MM-DD
    markdown: str  # HTML comments stripped
    fetched_at: str | None  # ISO timestamp from the file's machine-readable comment


def load_day_plans(route_dir) -> list[RawPlan]:
    """Every day-plan-YYYY-MM-DD.md in the folder, oldest date first.
    Unreadable files and names with an impossible date are skipped."""
    plans = []
    for path in sorted(Path(route_dir).glob("day-plan-*.md")):
        match = _FILE_RE.match(path.name)
        if not match:
            continue
        try:
            datetime.date.fromisoformat(match.group(1))
            text = path.read_text(encoding="utf-8-sig")  # tolerate a BOM from hand-edited files
        except (ValueError, OSError, UnicodeDecodeError):
            continue
        fetched = _FETCHED_RE.search(text)
        plans.append(RawPlan(match.group(1), _COMMENT_RE.sub("", text).strip() + "\n",
                             fetched.group(1) if fetched else None))
    plans.sort(key=lambda p: p.date)
    return plans


def default_plan_index(dates: list[str], today: str) -> int:
    """Index of the nearest upcoming date (today included); the latest date
    when every plan is in the past. `dates` is sorted ascending."""
    for i, d in enumerate(dates):
        if d >= today:
            return i
    return max(len(dates) - 1, 0)


DAY_PLAN_CSS = """
  #sidebar .dp-summary ul { margin: 4px 0; }
  #sidebar .dp-btn, #dp-panel .dp-btn {
    display: inline-block; padding: 4px 10px; margin: 4px 4px 0 0; font: inherit; font-size: 13px;
    color: #1f2937; background: #f3f4f6; border: 1px solid #9ca3af; border-radius: 6px;
    text-decoration: none; cursor: pointer;
  }
  #dp-overlay { position: fixed; inset: 0; z-index: 3000; background: rgba(0,0,0,0.45);
    display: flex; justify-content: center; }
  #dp-overlay[hidden] { display: none; }
  #dp-panel { background: #fff; width: 100%; max-width: 1100px; height: 100%; overflow-y: auto;
    box-sizing: border-box; padding: 12px 18px 24px; font-size: 14px; line-height: 1.45; }
  #dp-toolbar { position: sticky; top: -12px; background: #fff; padding: 8px 0; margin-top: -12px;
    display: flex; flex-wrap: wrap; gap: 6px; align-items: center; border-bottom: 1px solid #e5e7eb; }
  #dp-heading { font-weight: 600; font-size: 16px; margin-right: 8px; }
  #dp-meta { color: #6b7280; font-size: 12px; flex: 1 1 200px; }
  #dp-body h2 { font-size: 18px; margin: 16px 0 6px; }
  #dp-body h3 { font-size: 16px; margin: 14px 0 6px; border-bottom: 1px solid #e5e7eb; }
  #dp-body h4 { font-size: 14px; margin: 10px 0 4px; }
  #dp-body .table-wrap { overflow-x: auto; margin: 4px 0 10px; }
  #dp-body table { border-collapse: collapse; width: 100%; font-size: 12px; }
  #dp-body th, #dp-body td { border: 1px solid #d1d5db; padding: 3px 6px; text-align: left; vertical-align: top; }
  #dp-body th { background: #f3f4f6; white-space: nowrap; }
  #dp-body a { color: #2563eb; }
  @media print {
    body > *:not(#dp-overlay) { display: none !important; }
    #dp-overlay { position: static; display: block; background: none; }
    #dp-panel { max-width: none; height: auto; overflow: visible; padding: 0; }
    #dp-toolbar { display: none; }
    #dp-body tr, #dp-body h2, #dp-body h3 { break-inside: avoid; page-break-inside: avoid; }
    #dp-body .table-wrap { overflow: visible; }
    #dp-body table { font-size: 10px; }
  }
"""

_SCRIPT_TEMPLATE = """
  const DAY_PLANS = __PLANS__;
  const DP_LABELS = __LABELS__;
  const DP_FILE_BASE = __FILE_BASE__;
  (function () {
    if (!DAY_PLANS.length) return;
    const $ = id => document.getElementById(id);
    const select = $('dp-select');
    let current = __DEFAULT__;
    function isPassed(plan) { return new Date(plan.date + 'T23:59:59') < new Date(); }
    function show(i) {
      current = i;
      const plan = DAY_PLANS[i];
      $('dp-summary').innerHTML = plan.summary_html;
      $('dp-heading').textContent = DP_LABELS.title + ' — ' + plan.date;
      const parts = [];
      if (plan.fetched_at) parts.push(DP_LABELS.fetched + ': ' + plan.fetched_at.replace('T', ' ').replace('Z', ' UTC'));
      if (isPassed(plan)) parts.push(DP_LABELS.passed);
      $('dp-meta').textContent = parts.join(' · ');
      $('dp-body').innerHTML = plan.html;
      const link = $('dp-download');
      link.href = 'data:text/markdown;charset=utf-8,' + encodeURIComponent(plan.md);
      link.download = DP_FILE_BASE + '-day-plan-' + plan.date + '.md';
      if (select) select.value = String(i);
    }
    function openPanel() { $('dp-overlay').hidden = false; $('dp-panel').scrollTop = 0; }
    function closePanel() { $('dp-overlay').hidden = true; }
    if (select) select.addEventListener('change', () => show(Number(select.value)));
    $('dp-open').addEventListener('click', openPanel);
    $('dp-close').addEventListener('click', closePanel);
    $('dp-print').addEventListener('click', () => window.print());
    $('dp-overlay').addEventListener('click', e => { if (e.target === $('dp-overlay')) closePanel(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closePanel(); });
    show(current);
  })();
"""


def _json_for_script(value) -> str:
    # "</" would let a plan's text end the inline <script> early; \/ is the
    # same string to a JSON parser.
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def build_day_plan_parts(plans: list[dict], labels: dict, file_base: str, today: str) -> tuple[str, str, str]:
    """(sidebar_html, overlay_html, script_js). Each plan dict has: date,
    md (raw markdown), html (full plan as HTML), summary_html, fetched_at.
    `labels` has the localized UI strings under their day_plan_* names."""
    title = html.escape(labels["day_plan_title"])
    if not plans:
        sidebar = f'<h3>{title}</h3><p><em>{html.escape(labels["day_plan_none"])}</em></p>'
        return sidebar, "", "const DAY_PLANS = [];"

    default = default_plan_index([p["date"] for p in plans], today)
    if len(plans) > 1:
        options = "".join(f'<option value="{i}">{html.escape(p["date"])}</option>' for i, p in enumerate(plans))
        chooser = (f'<label>{html.escape(labels["day_plan_date"])}: '
                   f'<select id="dp-select">{options}</select></label>')
    else:
        chooser = f'<p>{html.escape(plans[0]["date"])}</p>'
    sidebar = (
        f'<h3>{title}</h3><div id="dp-block">{chooser}<div id="dp-summary" class="dp-summary"></div>'
        f'<button id="dp-open" class="dp-btn" type="button">{html.escape(labels["day_plan_open"])}</button></div>'
    )
    overlay = (
        '<div id="dp-overlay" hidden><div id="dp-panel" role="dialog" aria-modal="true" aria-labelledby="dp-heading">'
        '<div id="dp-toolbar"><span id="dp-heading"></span><span id="dp-meta"></span>'
        f'<a id="dp-download" class="dp-btn" href="#">{html.escape(labels["day_plan_download"])}</a>'
        f'<button id="dp-print" class="dp-btn" type="button">{html.escape(labels["day_plan_print"])}</button>'
        f'<button id="dp-close" class="dp-btn" type="button">{html.escape(labels["day_plan_close"])}</button></div>'
        '<div id="dp-body"></div></div></div>'
    )
    payload = [{"date": p["date"], "md": p["md"], "html": p["html"], "summary_html": p["summary_html"],
                "fetched_at": p["fetched_at"]} for p in plans]
    js_labels = {"title": labels["day_plan_title"], "fetched": labels["day_plan_fetched"],
                 "passed": labels["day_plan_passed"]}
    script = (_SCRIPT_TEMPLATE
              .replace("__PLANS__", _json_for_script(payload))
              .replace("__LABELS__", _json_for_script(js_labels))
              .replace("__FILE_BASE__", _json_for_script(file_base))
              .replace("__DEFAULT__", str(default)))
    return sidebar, overlay, script
