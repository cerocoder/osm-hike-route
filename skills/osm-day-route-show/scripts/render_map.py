#!/usr/bin/env python3
"""Render a route.geojson (+ notes.md) from osm-hike-route-planning's
archive into a self-contained interactive Leaflet/OSM map page.

Standard-library only. Usage:
    python3 render_map.py <route_dir> [output_html_path]
        [--user-lang <ISO 639-1>] [--local-lang <ISO 639-1>]
        [--no-wikipedia]

<route_dir> must contain route.geojson; notes.md is optional (used for
the access-point / confidence-tier sidebar). Default output is
<route_dir>/map.html.

--user-lang is the language the person is writing in (drives all UI
chrome text and is first in the place-info language priority list used
by the Wikipedia/Wikidata plugins). --local-lang is the place's
local/official language (second priority, and the language
geosearch/name-matching runs in by default). English is always the
final fallback for both UI text and place-info results. Point names
are NEVER translated for display — only used, verbatim or via an
optional per-point `search_names` override, to search a given
Wikipedia language edition.
"""
import argparse
import datetime
import json
import math
import re
import sys
import urllib.parse
from dataclasses import asdict
from pathlib import Path

from place_info import PlaceInfoService
from place_info.providers.wikipedia import WikipediaProvider
from place_info.providers.wikidata import WikidataProvider
from place_info.providers.wikimedia_commons import WikimediaCommonsProvider
from place_info.providers.opentripmap import OpenTripMapProvider
from day_plan_view import (
    DAY_PLAN_CSS, DAY_PLAN_SUMMARY_HEADINGS, DAY_PLAN_UI, build_day_plan_parts, load_day_plans,
)
from tile_providers import TileProviderService
from tile_providers.providers.esri_street import EsriStreetProvider
from tile_providers.providers.esri_satellite import EsriSatelliteProvider
from tile_providers.providers.cyclosm import CyclOsmProvider
from tile_providers.providers.ign_es_mtn import IgnEsMtnProvider

# Default active layer when --tile-provider isn't given: first of these
# that's actually available for the route (design spec: backward-
# compatible default stays esri_street).
TILE_PROVIDER_PRIORITY = ["esri_street", "ign_es_mtn", "cyclosm", "esri_satellite"]

LEAFLET_CSS = "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css"
LEAFLET_JS = "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js"


# ---------------------------------------------------------------------------
# i18n: UI chrome strings + notes.md heading aliases. English is always the
# fallback for any language/key not listed here (requirement: "the user's
# language, else English") — never leave a key untranslated-and-blank.
# ---------------------------------------------------------------------------

UI_STRINGS = {
    "en": {
        "getting_there": "Getting there",
        "interest_layers": "Points of interest",
        "export_title": "Export & open elsewhere",
        "download_gpx": "Download GPX (Wikiloc / Garmin)",
        "open_google": "Open area in Google Maps",
        "open_osm": "Open area in OpenStreetMap",
        "wikipedia": "Wikipedia",
        "route_title": "Route",
        "no_section": "Not in notes.md",
    },
    "ru": {
        "getting_there": "Как добраться",
        "interest_layers": "Точки интереса",
        "export_title": "Экспорт и открыть в другом приложении",
        "download_gpx": "Скачать GPX (Wikiloc / Garmin)",
        "open_google": "Открыть область в Google Maps",
        "open_osm": "Открыть область в OpenStreetMap",
        "wikipedia": "Википедия",
        "route_title": "Маршрут",
        "no_section": "Нет в notes.md",
    },
    "es": {
        "getting_there": "Cómo llegar",
        "interest_layers": "Puntos de interés",
        "export_title": "Exportar y abrir en otra app",
        "download_gpx": "Descargar GPX (Wikiloc / Garmin)",
        "open_google": "Abrir la zona en Google Maps",
        "open_osm": "Abrir la zona en OpenStreetMap",
        "wikipedia": "Wikipedia",
        "route_title": "Ruta",
        "no_section": "No está en notes.md",
    },
    "fr": {
        "getting_there": "Comment s'y rendre",
        "interest_layers": "Points d'intérêt",
        "export_title": "Exporter et ouvrir ailleurs",
        "download_gpx": "Télécharger le GPX (Wikiloc / Garmin)",
        "open_google": "Ouvrir la zone dans Google Maps",
        "open_osm": "Ouvrir la zone dans OpenStreetMap",
        "wikipedia": "Wikipédia",
        "route_title": "Itinéraire",
        "no_section": "Absent de notes.md",
    },
    "de": {
        "getting_there": "Anreise",
        "interest_layers": "Sehenswürdigkeiten",
        "export_title": "Exportieren & anderswo öffnen",
        "download_gpx": "GPX herunterladen (Wikiloc / Garmin)",
        "open_google": "Gebiet in Google Maps öffnen",
        "open_osm": "Gebiet in OpenStreetMap öffnen",
        "wikipedia": "Wikipedia",
        "route_title": "Route",
        "no_section": "Nicht in notes.md",
    },
    "pt": {
        "getting_there": "Como chegar",
        "interest_layers": "Pontos de interesse",
        "export_title": "Exportar e abrir noutro sítio",
        "download_gpx": "Descarregar GPX (Wikiloc / Garmin)",
        "open_google": "Abrir a área no Google Maps",
        "open_osm": "Abrir a área no OpenStreetMap",
        "wikipedia": "Wikipédia",
        "route_title": "Percurso",
        "no_section": "Não consta em notes.md",
    },
    "it": {
        "getting_there": "Come arrivare",
        "interest_layers": "Punti di interesse",
        "export_title": "Esporta e apri altrove",
        "download_gpx": "Scarica GPX (Wikiloc / Garmin)",
        "open_google": "Apri l'area in Google Maps",
        "open_osm": "Apri l'area in OpenStreetMap",
        "wikipedia": "Wikipedia",
        "route_title": "Percorso",
        "no_section": "Non presente in notes.md",
    },
}

# The fixed section headings of notes.md, one per section and language — the same table as
# osm-day-route-planning/scripts/notes_headings.py (a planning test compares them). The planner writes
# exactly these, so the panel finds "Access" and "Points of interest" by name; SECTION_ALIASES below only
# rescues notes written before the headings were fixed.
NOTES_HEADINGS = {
    "request": {
        "en": "Request", "ru": "Запрос", "es": "Solicitud", "fr": "Demande", "de": "Anfrage", "pt": "Pedido",
        "it": "Richiesta"},
    "access": {
        "en": "Access", "ru": "Доступ", "es": "Acceso", "fr": "Accès", "de": "Zugang", "pt": "Acesso",
        "it": "Accesso"},
    "reasoning": {
        "en": "Route reasoning", "ru": "Обоснование маршрута", "es": "Razonamiento de la ruta",
        "fr": "Justification de l'itinéraire", "de": "Begründung der Route", "pt": "Justificação do percurso",
        "it": "Motivazione del percorso"},
    "interest": {
        "en": "Points of interest", "ru": "Точки интереса", "es": "Puntos de interés", "fr": "Points d'intérêt",
        "de": "Sehenswürdigkeiten", "pt": "Pontos de interesse", "it": "Punti di interesse"},
    "skipped": {
        "en": "Optional points skipped for budget", "ru": "Пропущенные необязательные точки",
        "es": "Puntos opcionales omitidos", "fr": "Points facultatifs écartés",
        "de": "Übersprungene optionale Punkte", "pt": "Pontos opcionais omitidos",
        "it": "Punti facoltativi saltati"},
    "curated": {
        "en": "Curated routes nearby", "ru": "Готовые маршруты рядом", "es": "Rutas señalizadas cercanas",
        "fr": "Itinéraires balisés à proximité", "de": "Ausgewiesene Routen in der Nähe",
        "pt": "Percursos marcados próximos", "it": "Percorsi segnalati vicini"},
    "distance": {
        "en": "Distance and duration", "ru": "Дистанция и время", "es": "Distancia y duración",
        "fr": "Distance et durée", "de": "Distanz und Dauer", "pt": "Distância e duração",
        "it": "Distanza e durata"},
}

_EXACT_KEYS = {"access": "access", "confidence": "interest"}           # the panel's section key -> NOTES_HEADINGS key

# Heading aliases (any language) recognized in notes.md, so headings written
# in the user's / local language are picked up, not just the English
# defaults from osm-hike-route-planning's own template. Matching tries every
# alias below regardless of which language notes.md turns out to be in.
SECTION_ALIASES = {
    "access": [
        "Access", "Getting there",
        "Как добраться", "Доступ",
        "Cómo llegar", "Acceso",
        "Comment s'y rendre", "Accès",
        "Anreise", "Zugang",
        "Como chegar", "Acesso",
        "Come arrivare", "Accesso",
    ],
    "confidence": [
        "Interest-layer confidence", "Points of interest", "Interest layers",
        "Точки интереса", "Пункты интереса", "точек интереса", "Достопримечательности",
        "Puntos de interés", "Puntos de interes",
        "Points d'intérêt", "Points d'interet",
        "Sehenswürdigkeiten", "Interessante Orte",
        "Pontos de interesse",
        "Punti di interesse",
    ],
}


for _lang, _strings in DAY_PLAN_UI.items():
    UI_STRINGS[_lang].update(_strings)
SECTION_ALIASES["day_plan_summary"] = list(DAY_PLAN_SUMMARY_HEADINGS)


def t(key: str, lang: str) -> str:
    """UI string for `key` in `lang`, falling back to English."""
    return UI_STRINGS.get(lang, {}).get(key) or UI_STRINGS["en"][key]


# Popup content is also page chrome, not point data — `type`/`tier` are enum
# values from route.geojson (English, by the schema's own convention: "the
# same confidence vocabulary as osm-hike-route-planning"), so they need the
# same localization as the sidebar headings or a Russian-speaking user sees
# an English word like "viewpoint" in every popup despite everything else
# being in Russian.
TYPE_LABELS = {
    "en": {
        "viewpoint": "viewpoint", "cave": "cave", "river": "river", "meadow": "meadow",
        "historic": "historic site", "historic_viewpoint": "historic viewpoint",
        "karst": "karst feature", "access": "access point", "spring": "spring",
        "fountain": "fountain", "sight": "sight", "route": "route", "waypoint": "waypoint",
    },
    "ru": {
        "viewpoint": "видовая точка", "cave": "пещера", "river": "река", "meadow": "луг",
        "historic": "историческое место", "historic_viewpoint": "видовая/историческая точка",
        "karst": "карстовое образование", "access": "точка доступа", "spring": "родник",
        "fountain": "источник питьевой воды", "sight": "достопримечательность",
        "route": "маршрут", "waypoint": "путевая точка",
    },
    "es": {
        "viewpoint": "mirador", "cave": "cueva", "river": "río", "meadow": "prado",
        "historic": "lugar histórico", "historic_viewpoint": "mirador histórico",
        "karst": "formación kárstica", "access": "punto de acceso", "spring": "manantial",
        "fountain": "fuente", "sight": "punto de interés", "route": "ruta", "waypoint": "punto de paso",
    },
    "fr": {
        "viewpoint": "point de vue", "cave": "grotte", "river": "rivière", "meadow": "prairie",
        "historic": "site historique", "historic_viewpoint": "point de vue historique",
        "karst": "relief karstique", "access": "point d'accès", "spring": "source",
        "fountain": "fontaine", "sight": "site", "route": "itinéraire", "waypoint": "point de passage",
    },
    "de": {
        "viewpoint": "Aussichtspunkt", "cave": "Höhle", "river": "Fluss", "meadow": "Wiese",
        "historic": "historische Stätte", "historic_viewpoint": "historischer Aussichtspunkt",
        "karst": "Karsterscheinung", "access": "Zugangspunkt", "spring": "Quelle",
        "fountain": "Brunnen", "sight": "Sehenswürdigkeit", "route": "Route", "waypoint": "Wegpunkt",
    },
    "pt": {
        "viewpoint": "miradouro", "cave": "gruta", "river": "rio", "meadow": "prado",
        "historic": "local histórico", "historic_viewpoint": "miradouro histórico",
        "karst": "formação cársica", "access": "ponto de acesso", "spring": "nascente",
        "fountain": "fonte", "sight": "ponto de interesse", "route": "rota", "waypoint": "ponto de passagem",
    },
    "it": {
        "viewpoint": "punto panoramico", "cave": "grotta", "river": "fiume", "meadow": "prato",
        "historic": "sito storico", "historic_viewpoint": "punto panoramico storico",
        "karst": "fenomeno carsico", "access": "punto di accesso", "spring": "sorgente",
        "fountain": "fontana", "sight": "punto di interesse", "route": "percorso", "waypoint": "punto di passaggio",
    },
}

TIER_LABELS = {
    "en": {"tag-backed": "tag-backed", "web-sourced": "web-sourced", "derived": "derived", "no-data": "no data"},
    "ru": {"tag-backed": "по данным OSM", "web-sourced": "по веб-источнику", "derived": "оценочно", "no-data": "нет данных"},
    "es": {"tag-backed": "según OSM", "web-sourced": "según fuente web", "derived": "estimado", "no-data": "sin datos"},
    "fr": {"tag-backed": "d'après OSM", "web-sourced": "source web", "derived": "estimé", "no-data": "aucune donnée"},
    "de": {"tag-backed": "laut OSM", "web-sourced": "Web-Quelle", "derived": "geschätzt", "no-data": "keine Daten"},
    "pt": {"tag-backed": "segundo o OSM", "web-sourced": "fonte web", "derived": "estimado", "no-data": "sem dados"},
    "it": {"tag-backed": "da OSM", "web-sourced": "fonte web", "derived": "stimato", "no-data": "nessun dato"},
}

# The type of the outing, keyed by mode or "mode:style"; skiing has no producer yet, its label is ready.
_ACTIVITY_LABELS = {
    "en": {"walk": "on foot", "bike": "cycling", "bike:sport": "cycling (sport)", "bike:leisure": "cycling (leisure)",
           "ski": "skiing"},
    "ru": {"walk": "пешком", "bike": "вело", "bike:sport": "вело (спорт)", "bike:leisure": "вело (прогулка)",
           "ski": "лыжи"},
}


def activity_label(line_properties: dict, user_lang: str) -> str:
    """"пешком" / "вело (спорт)" / "cycling (leisure)" ...: the type of the outing from the route's mode and style.
    An unknown combination falls back to the mode label (or the raw mode) with the raw style in brackets."""
    labels = _ACTIVITY_LABELS.get(user_lang, _ACTIVITY_LABELS["en"])
    mode = line_properties.get("mode") or "walk"
    style = line_properties.get("style")
    if style and f"{mode}:{style}" in labels:
        return labels[f"{mode}:{style}"]
    label = labels.get(mode, mode)
    return f"{label} ({style})" if style else label


def route_stats_html(line_properties: dict, user_lang: str) -> str:
    """Built from computed LineString properties (spec §3.11), never from
    weights.json — this function never sees weights.json at all. A
    pre-this-round archive with none of these properties still renders a
    walk-labeled, mostly-empty block instead of raising."""
    parts = [f"<p>{_xml_escape(activity_label(line_properties, user_lang))}</p>"]

    if line_properties.get("distance_km") is not None:
        parts.append(f"<p>{line_properties['distance_km']:.1f} km</p>")
    if line_properties.get("elevation_gain_m") is not None:
        parts.append(
            f"<p>+{line_properties['elevation_gain_m']:.0f}m / "
            f"-{line_properties.get('elevation_loss_m', 0.0):.0f}m</p>"
        )
    if line_properties.get("duration_estimate_hours") is not None:
        parts.append(f"<p>~{line_properties['duration_estimate_hours']:.1f} h</p>")
    if line_properties.get("curated_routes_count"):
        parts.append(f"<p>{line_properties['curated_routes_count']} curated routes nearby</p>")
    if line_properties.get("duration_warning"):
        parts.append(f'<p class="duration-warning">{_xml_escape(line_properties["duration_warning"])}</p>')
    skipped = line_properties.get("skipped_interest_points") or []
    if skipped:
        skipped_list = ", ".join(_xml_escape(name) for name in skipped)
        parts.append(f"<p>Not included (over budget): {skipped_list}</p>")

    return "".join(parts)


def _localized_label_maps(lang: str) -> tuple[dict, dict]:
    """(type_labels, tier_labels) for `lang`, each value pre-falling-back to
    its English label — the page's JS then only needs one more fallback (to
    the raw enum value) for a type/tier this table doesn't cover at all."""
    type_map = dict(TYPE_LABELS["en"])
    type_map.update(TYPE_LABELS.get(lang, {}))
    tier_map = dict(TIER_LABELS["en"])
    tier_map.update(TIER_LABELS.get(lang, {}))
    return type_map, tier_map


def lang_priority(user_lang: str, local_lang: str | None) -> list[str]:
    """[user_lang, local_lang, 'en'] deduplicated, order preserved."""
    seq = [user_lang] + ([local_lang] if local_lang else []) + ["en"]
    seen = set()
    out = []
    for lang in seq:
        if lang and lang not in seen:
            seen.add(lang)
            out.append(lang)
    return out


# ---------------------------------------------------------------------------
# notes.md -> HTML
# ---------------------------------------------------------------------------

def extract_md_section(md_text: str, section_key: str) -> str:
    """Returns the body of the first '## ...<alias>...' heading matching any
    known alias for `section_key`, or '' if none match. The alias may
    appear anywhere on the heading line, with text before or after it
    tolerated in either direction — "## Как добраться (Екатеринбург →
    Бажуково)" matches "Как добраться", and "## 8 точек интереса" matches
    "точек интереса" (a numbered heading like "## N точек интереса" would
    otherwise need one alias per N).

    The fixed heading of the section (any language of NOTES_HEADINGS, the whole line) is tried first; the
    aliases are the fallback for notes written before the headings were fixed."""
    fixed = NOTES_HEADINGS.get(_EXACT_KEYS.get(section_key, ""), {})
    for text in fixed.values():
        match = re.search(rf"(?mi)^##[ \t]+{re.escape(text)}[ \t]*\n(.*?)(?=\n##\s|\Z)", md_text, re.DOTALL)
        if match:
            return match.group(1).strip()
    for alias in SECTION_ALIASES.get(section_key, []):
        pattern = rf"(?m)^##\s[^\n]*?{re.escape(alias)}[^\n]*\n(.*?)(?=\n##\s|\Z)"
        match = re.search(pattern, md_text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def _xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


# Only these schemes become links (javascript:, data:, vbscript:, file: ...
# stay plain text). Leading whitespace/control characters are ignored when
# checking, as browsers ignore them when parsing a URL.
_SAFE_LINK_PREFIXES = ("http://", "https://", "mailto:")
_LINK_STRIP_CHARS = "".join(chr(c) for c in range(0x21)) + "\x7f"


def _inline_markdown(s: str) -> str:
    """[text](url), **bold**, `code` -> HTML. The link regex tolerates one
    level of parens inside the URL (e.g. a Wikipedia article title like
    ...wiki/L%C3%ADnea_C-5_(Cercan%C3%ADas_Madrid)) — a naive [^)]+ would
    truncate at the first ')' inside the URL itself."""
    def link(m):
        text, url = m.group(1), m.group(2)
        target = url.lstrip(_LINK_STRIP_CHARS)
        if not target.lower().startswith(_SAFE_LINK_PREFIXES):
            return m.group(0)  # unsafe scheme or relative: leave as plain text
        return f'<a href="{target}" target="_blank" rel="noopener">{text}</a>'

    s = re.sub(r'\[([^\]]+)\]\(((?:[^()]|\([^()]*\))*)\)', link, s)
    s = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', s)
    s = re.sub(r'`([^`]+)`', r'<code>\1</code>', s)
    return s


_LIST_MARKER = re.compile(r"^(?:-\s+|\d+\.\s+)")

# A GFM delimiter row: cells of 3+ dashes (optionally `:`-aligned), pipe-
# separated, optional leading/trailing pipe — e.g. "|---|---|" or
# ":--- | ---:". Detecting a table requires this row right after a
# pipe-containing line (see markdown_to_html) — a bare "|" appearing in
# ordinary prose is not, by itself, enough to switch modes.
_TABLE_SEPARATOR_ROW = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$")


def _split_table_row(line: str) -> list[str]:
    """GFM pipe-row -> cell texts, tolerating an optional leading/trailing
    pipe (both "| a | b |" and "a | b" are valid GFM rows)."""
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [cell.strip() for cell in line.split("|")]


def _render_table(rows: list[str]) -> str:
    """rows[0] is the header, rows[1] the (already-validated, discarded)
    delimiter row, rows[2:] the data rows. Column alignment (`:---:` etc.)
    isn't rendered — no notes.md content seen so far has used it, and a
    plain left-aligned table is a fine default for the sidebar's width."""
    header_cells = [_inline_markdown(_xml_escape(c)) for c in _split_table_row(rows[0])]
    header_html = "".join(f"<th>{c}</th>" for c in header_cells)
    body_rows = []
    for data_row in rows[2:]:
        cells = [_inline_markdown(_xml_escape(c)) for c in _split_table_row(data_row)]
        body_rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    return (
        '<div class="table-wrap"><table><thead><tr>' + header_html + "</tr></thead><tbody>"
        + "".join(body_rows) + "</tbody></table></div>"
    )


def markdown_to_html(md_text: str) -> str:
    """Minimal markdown->HTML for notes.md sections: '- '/'1. ' list items
    (with hard-wrapped continuation lines joined back together), GFM pipe
    tables, plus inline links/bold/code. Not a general markdown parser —
    just what osm-hike-route-planning's notes.md template actually
    produces. Without the numbered-list branch, a "1. ... 2. ... 3. ..."
    list (seen in a real notes.md) collapses into one giant run-on bullet.

    Without the table branch, a markdown table (seen in a real notes.md's
    "Точки интереса" section, despite reference.md's own template using a
    bullet list for that section) is caught by the paragraph-continuation
    branch below like any other non-blank, non-list line: every row gets
    glued onto the previous one (no blank lines between table rows), so the
    whole table collapses into a single run-on `<li>` of bare
    pipes-and-dashes text — exactly the malformed output a user reported
    seeing in the sidebar."""
    lines = md_text.split("\n")
    fragments = []
    items = []
    current = None
    i = 0

    def flush_list():
        nonlocal current
        if current is not None:
            items.append(current)
            current = None
        if items:
            escaped_items = [_inline_markdown(_xml_escape(item)) for item in items]
            fragments.append("<ul>" + "".join(f"<li>{item}</li>" for item in escaped_items) + "</ul>")
            items.clear()

    while i < len(lines):
        line = lines[i].strip()

        if "|" in line and i + 1 < len(lines) and _TABLE_SEPARATOR_ROW.match(lines[i + 1].strip()):
            flush_list()
            table_rows = [line, lines[i + 1].strip()]
            i += 2
            while i < len(lines) and lines[i].strip() and "|" in lines[i]:
                table_rows.append(lines[i].strip())
                i += 1
            fragments.append(_render_table(table_rows))
            continue

        marker = _LIST_MARKER.match(line)
        if marker:
            if current is not None:
                items.append(current)
            current = line[marker.end():]
        elif not line:
            if current is not None:
                items.append(current)
                current = None
        else:
            current = f"{current} {line}" if current is not None else line
        i += 1

    flush_list()
    return "".join(fragments)


_PLAN_HEADING = re.compile(r"^(#{1,3})\s+(.*)$")


def _plan_inline(text: str) -> str:
    """_inline_markdown plus *italic* (day plans use it for the metadata and
    source lines). Bold is converted first, so a remaining single * pair is
    italic."""
    text = _inline_markdown(_xml_escape(text))
    return re.sub(r"(?<![*\w])\*([^*]+)\*(?![*\w])", r"<i>\1</i>", text)


def plan_markdown_to_html(md_text: str) -> str:
    """Markdown -> HTML for a whole day-plan file: '#'/'##'/'###' headings
    (rendered as h2/h3/h4), paragraphs, '- '/'1. ' lists, GFM tables, and
    inline links/bold/italic/code. markdown_to_html deliberately stays as it
    is for notes.md sections: it has no headings and turns bare lines into
    list items, which would mangle a plan."""
    lines = md_text.split("\n")
    out, items, paragraph = [], [], []
    current = None
    i = 0

    def flush_paragraph():
        if paragraph:
            out.append("<p>" + _plan_inline(" ".join(paragraph)) + "</p>")
            paragraph.clear()

    def flush_list():
        nonlocal current
        if current is not None:
            items.append(current)
            current = None
        if items:
            out.append("<ul>" + "".join(f"<li>{_plan_inline(item)}</li>" for item in items) + "</ul>")
            items.clear()

    while i < len(lines):
        line = lines[i].strip()

        if "|" in line and i + 1 < len(lines) and _TABLE_SEPARATOR_ROW.match(lines[i + 1].strip()):
            flush_paragraph()
            flush_list()
            table_rows = [line, lines[i + 1].strip()]
            i += 2
            while i < len(lines) and lines[i].strip() and "|" in lines[i]:
                table_rows.append(lines[i].strip())
                i += 1
            out.append(_render_table(table_rows))
            continue

        heading = _PLAN_HEADING.match(line)
        if heading:
            flush_paragraph()
            flush_list()
            level = len(heading.group(1)) + 1
            out.append(f"<h{level}>{_plan_inline(heading.group(2))}</h{level}>")
        elif _LIST_MARKER.match(line):
            flush_paragraph()
            if current is not None:
                items.append(current)
            current = line[_LIST_MARKER.match(line).end():]
        elif not line:
            flush_paragraph()
            flush_list()
        elif current is not None:
            current = f"{current} {line}"
        else:
            paragraph.append(line)
        i += 1

    flush_paragraph()
    flush_list()
    return "".join(out)


# ---------------------------------------------------------------------------
# Place-info enrichment (spec §5): queries every configured plugin
# (Wikipedia, Wikidata, Wikimedia Commons, OpenTripMap — see
# scripts/place_info/providers/) for every point and attaches every
# non-empty result. The Wikipedia-specific name-match/coordinate-
# verification discipline ("never guess from a bare name search +
# nearest-hit") now lives in providers/wikipedia.py's own docstring and
# resolve_wikipedia(), not here.
# ---------------------------------------------------------------------------


def annotate_place_info(geojson: dict, user_lang: str, local_lang: str | None,
                         cache_path: Path | None, opentripmap_api_key: str | None = None,
                         timeout: float = 5.0) -> None:
    """Mutates every Point feature in place, adding `_placeInfo`: a list of
    every plugin's non-empty result (spec §5 — show ALL sources, not the
    single best one, unlike the old resolve_wikipedia-only behavior)."""
    import os
    api_key = opentripmap_api_key or os.environ.get("OSM_DAY_ROUTE_OPENTRIPMAP_KEY")
    providers = [
        WikipediaProvider(user_lang, local_lang, timeout),
        WikidataProvider(user_lang, timeout),
        WikimediaCommonsProvider(timeout=timeout),
    ]
    if api_key:
        # Only constructed/queried once a key is configured — otherwise
        # PlaceInfoService.fetch_all would cache OpenTripMapProvider's
        # `None` as a permanent negative in place_info.json before the key
        # ever exists, permanently disabling it even after one is added
        # later (see final-review Fix 1).
        providers.append(OpenTripMapProvider(api_key, timeout=timeout))
    service = PlaceInfoService(providers, cache_path) if cache_path else PlaceInfoService(providers, Path("/dev/null"))

    for feature in geojson.get("features", []):
        if feature["geometry"]["type"] != "Point":
            continue
        props = feature.get("properties", {})
        coord = feature["geometry"]["coordinates"]
        lon, lat = coord[0], coord[1]
        names = props.get("search_names", {}) or {}
        if props.get("name"):
            names = {**names, (local_lang or user_lang): props["name"]}
        identity = props.get("osm_id") or props.get("wikidata") or props.get("name", "")

        results = service.fetch_all(names, lat, lon, props.get("wikidata"), identity)
        if results:
            props["_placeInfo"] = [
                {k: v for k, v in asdict(r).items() if v is not None} for r in results
            ]


# ---------------------------------------------------------------------------
# GPX / external links
# ---------------------------------------------------------------------------

def build_gpx(geojson: dict, title: str) -> str:
    """GPX 1.1 — the format both Wikiloc and Garmin devices/BaseCamp/Connect
    import natively. One <trk> from the route LineString, one <wpt> per
    Point feature. Coordinates may be [lon, lat] (older archives) or
    [lon, lat, ele] (spec §3.11) — ele is emitted only when present."""
    features = geojson.get("features", [])
    line = next((f for f in features if f["geometry"]["type"] == "LineString"), None)
    points = [f for f in features if f["geometry"]["type"] == "Point"]

    def _ele_tag(coord) -> str:
        return f"<ele>{coord[2]}</ele>" if len(coord) > 2 else ""

    wpts = []
    for f in points:
        coord = f["geometry"]["coordinates"]
        lon, lat = coord[0], coord[1]
        props = f.get("properties", {})
        name = _xml_escape(props.get("name", "Point"))
        desc = _xml_escape(props.get("type", ""))
        wpts.append(
            f'  <wpt lat="{lat}" lon="{lon}">{_ele_tag(coord)}<name>{name}</name><desc>{desc}</desc></wpt>'
        )

    trkpts = []
    if line:
        for coord in line["geometry"]["coordinates"]:
            lon, lat = coord[0], coord[1]
            trkpts.append(f'      <trkpt lat="{lat}" lon="{lon}">{_ele_tag(coord)}</trkpt>')

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="osm-day-route-show" '
        'xmlns="http://www.topografix.com/GPX/1/1">\n'
        f"  <metadata><name>{_xml_escape(title)}</name></metadata>\n"
        + "\n".join(wpts) + ("\n" if wpts else "")
        + "  <trk>\n"
        f"    <name>{_xml_escape(title)}</name>\n"
        "    <trkseg>\n"
        + "\n".join(trkpts) + ("\n" if trkpts else "")
        + "    </trkseg>\n"
        "  </trk>\n"
        "</gpx>\n"
    )


# ---------------------------------------------------------------------------
# Tile providers
# ---------------------------------------------------------------------------

def _tile_coverage_points(geojson: dict) -> list[tuple[float, float]]:
    """(lat, lon) points used to probe tile-provider coverage: access
    points if any exist, else interest points, else empty (design spec:
    Coverage point selection — an empty result means TileProviderService
    skips probing entirely and offers only always_available providers)."""
    access, interest = [], []
    for f in geojson.get("features", []):
        if f["geometry"]["type"] != "Point":
            continue
        coord = f["geometry"]["coordinates"]
        lat, lon = coord[1], coord[0]
        ptype = (f.get("properties") or {}).get("type")
        if ptype == "access":
            access.append((lat, lon))
        elif ptype == "interest":
            interest.append((lat, lon))
    return access or interest


def build_tile_layers_js(providers: list, active_id: str | None) -> str:
    """Pure JS-snippet builder — no network calls. One L.tileLayer(...)
    const per available provider, plus, when more than one provider is
    available, an L.control.layers(...) switcher (design spec: hybrid
    UX — default active layer + in-browser switcher, no chat prompt).
    `providers` must be non-empty. `active_id` selects which provider is
    added to the map directly; falls back to providers[0] when None or
    not found among `providers`."""
    active = next((p for p in providers if p.provider_id == active_id), providers[0])

    lines = []
    control_entries = []
    for i, p in enumerate(providers):
        var = f"tileLayer{i}"
        options = {"attribution": p.attribution, "maxZoom": p.max_zoom}
        if p.max_native_zoom is not None:
            options["maxNativeZoom"] = p.max_native_zoom
        lines.append(
            f"const {var} = L.tileLayer({json.dumps(p.tile_url_template)}, "
            f"{json.dumps(options, ensure_ascii=False)});"
        )
        control_entries.append((p.display_name, var))
        if p is active:
            lines.append(f"{var}.addTo(map);")

    if len(providers) > 1:
        pairs = ", ".join(
            f"{json.dumps(name, ensure_ascii=False)}: {var}" for name, var in control_entries
        )
        lines.append(f"L.control.layers({{{pairs}}}, null, {{position: 'topleft'}}).addTo(map);")

    return "\n  ".join(lines)


def bbox_center_zoom(geojson: dict) -> tuple[float, float, int]:
    """Rough center + zoom for external map links (Google/OSM) — an
    approximation for landing roughly on the right area, not a precise
    viewport match."""
    coords = []
    for f in geojson.get("features", []):
        g = f["geometry"]
        if g["type"] == "Point":
            coords.append(g["coordinates"])
        elif g["type"] == "LineString":
            coords.extend(g["coordinates"])
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    center_lat = (min(lats) + max(lats)) / 2
    center_lon = (min(lons) + max(lons)) / 2
    span = max(max(lats) - min(lats), max(lons) - min(lons), 0.001)
    zoom = round(14 - math.log2(span / 0.02))
    zoom = max(11, min(16, zoom))
    return center_lat, center_lon, zoom


def _route_title(geojson: dict, fallback: str) -> str:
    """Prefer the route LineString's own `name` (a local-language, untranslated
    title written by osm-hike-route-planning) over the archive folder's
    transliterated slug."""
    for f in geojson.get("features", []):
        if f["geometry"]["type"] == "LineString":
            # `properties` may be null (valid GeoJSON) as well as missing —
            # `.get("properties", {})` alone only covers the missing case,
            # since a present-but-null value isn't replaced by the default.
            name = (f.get("properties") or {}).get("name")
            if name:
                return name
    return fallback


def point_popup_html(properties: dict) -> str:
    """Server-side-rendered popup body — the parts of it that depend only
    on route.geojson properties (not on the client-side tier/type label
    lookup tables, which stay in the page's own JS since they're
    language-dependent, see build_map_html)."""
    parts = []
    if properties.get("opening_hours"):
        parts.append(f"<p>{_xml_escape(properties['opening_hours'])}</p>")
    if properties.get("access_notes"):
        parts.append(f"<p>{_xml_escape(properties['access_notes'])}</p>")
    for entry in properties.get("_placeInfo", []):
        provider_id = entry.get("provider_id", "")
        bits = [f"<b>{_xml_escape(provider_id)}</b>"]
        if entry.get("summary"):
            bits.append(_xml_escape(entry["summary"]))
        if entry.get("url"):
            bits.append(f'<a href="{entry["url"]}" target="_blank" rel="noopener">link</a>')
        if entry.get("image_url"):
            bits.append(f'<a href="{entry["image_url"]}" target="_blank" rel="noopener">photo</a>')
        parts.append(f"<p>{' — '.join(bits)}</p>")
    return "".join(parts)


def build_map_html(geojson_path: Path, notes_path: Path | None, title: str,
                    user_lang: str = "en", local_lang: str | None = None,
                    resolve_wiki: bool = True, wiki_timeout: float = 5.0,
                    tile_provider: str | None = None, tile_timeout: float = 5.0) -> str:
    geojson = json.loads(geojson_path.read_text(encoding="utf-8"))
    # Valid GeoJSON allows "properties": null or a missing key entirely;
    # normalize every feature's properties to a dict up front so every
    # downstream `.get()`/indexing on `properties` sees a dict, never None.
    for f in geojson.get("features", []):
        f["properties"] = f.get("properties") or {}

    if resolve_wiki:
        cache_path = geojson_path.parent / "place_info.json"
        annotate_place_info(geojson, user_lang, local_lang, cache_path, timeout=wiki_timeout)

    tile_cache_path = geojson_path.parent / "tile_coverage.json"
    tile_service = TileProviderService(
        [EsriStreetProvider(), EsriSatelliteProvider(), CyclOsmProvider(), IgnEsMtnProvider()],
        tile_cache_path,
    )
    coverage_points = _tile_coverage_points(geojson)
    available_tile_providers = tile_service.available_providers(coverage_points, timeout=tile_timeout)
    available_tile_ids = [p.provider_id for p in available_tile_providers]

    if tile_provider is not None:
        if tile_provider not in available_tile_ids:
            raise ValueError(
                f"tile provider {tile_provider!r} is not available for this route "
                f"(available: {available_tile_ids})"
            )
        active_tile_provider_id = tile_provider
    else:
        active_tile_provider_id = next(
            (pid for pid in TILE_PROVIDER_PRIORITY if pid in available_tile_ids),
            available_tile_ids[0],
        )
    tile_layers_js = build_tile_layers_js(available_tile_providers, active_tile_provider_id)

    # Every sidebar block is always present, in a fixed order; a block whose
    # source data is missing shows a placeholder instead of vanishing.
    notes = notes_path.read_text(encoding="utf-8") if notes_path and notes_path.exists() else ""
    placeholder = f'<p><em>{t("no_section", user_lang)}</em></p>'
    access = extract_md_section(notes, "access")
    confidence = extract_md_section(notes, "confidence")
    access_html = f"<h3>{t('getting_there', user_lang)}</h3>{markdown_to_html(access) if access else placeholder}"
    confidence_html = f"<h3>{t('interest_layers', user_lang)}</h3>{markdown_to_html(confidence) if confidence else placeholder}"

    line_feature = next((f for f in geojson.get("features", []) if f["geometry"]["type"] == "LineString"), None)
    stats_body = route_stats_html(line_feature['properties'], user_lang) if line_feature else f'<p><em>{t("no_section", user_lang)}</em></p>'
    stats_html = f"<h3>{t('route_title', user_lang)}</h3>{stats_body}"

    for feature in geojson.get("features", []):
        if feature["geometry"]["type"] == "Point":
            feature["properties"]["_popupExtra"] = point_popup_html(feature["properties"])

    # Every day-plan-<date>.md in the route folder is embedded, so the single
    # map.html can be forwarded with all planned days inside.
    day_plans = [
        {"date": p.date, "md": p.markdown, "html": plan_markdown_to_html(p.markdown),
         "summary_html": markdown_to_html(extract_md_section(p.markdown, "day_plan_summary")),
         "fetched_at": p.fetched_at}
        for p in load_day_plans(geojson_path.parent)
    ]
    day_plan_sidebar, day_plan_overlay, day_plan_script = build_day_plan_parts(
        day_plans, {key: t(key, user_lang) for key in DAY_PLAN_UI["en"]},
        file_base=re.sub(r'[\\/:*?"<>|]+', "_", title), today=datetime.date.today().isoformat(),
    )

    # Escape "</" so a provider's free-text summary containing a literal
    # "</script>" can't end this inline <script> tag early and break the
    # whole page's JS (map, arrows, popups). \/ and / are equivalent in a
    # JSON string, so this doesn't change the parsed meaning.
    geojson_json = json.dumps(geojson).replace("<", "\\u003c")

    gpx_content = build_gpx(geojson, title)
    gpx_data_uri = "data:application/gpx+xml;charset=utf-8," + urllib.parse.quote(gpx_content)
    center_lat, center_lon, zoom = bbox_center_zoom(geojson)
    google_url = f"https://www.google.com/maps/@{center_lat},{center_lon},{zoom}z"
    osm_url = f"https://www.openstreetmap.org/#map={zoom}/{center_lat}/{center_lon}"
    title_escaped = _xml_escape(title)
    links_html = (
        f"<h3>{t('export_title', user_lang)}</h3>"
        '<div class="links-section">'
        f'<a href="{gpx_data_uri}" download="{title_escaped}.gpx">{t("download_gpx", user_lang)}</a><br>'
        f'<a href="{google_url}" target="_blank" rel="noopener">{t("open_google", user_lang)}</a><br>'
        f'<a href="{osm_url}" target="_blank" rel="noopener">{t("open_osm", user_lang)}</a>'
        "</div>"
    )
    type_labels, tier_labels = _localized_label_maps(user_lang)
    type_labels_js = json.dumps(type_labels, ensure_ascii=False)
    tier_labels_js = json.dumps(tier_labels, ensure_ascii=False)

    return f"""<!doctype html>
<html lang="{user_lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>{title_escaped}</title>
<link rel="stylesheet" href="{LEAFLET_CSS}">
<style>
  html, body {{ margin: 0; height: 100%; font-family: system-ui, sans-serif; }}
  #map {{ position: absolute; top: 0; bottom: 0; left: 0; right: 0; }}
  #sidebar {{
    position: absolute; z-index: 1000; top: 10px; right: 10px;
    max-width: 320px; max-height: 80vh; overflow-y: auto;
    background: rgba(255,255,255,0.95); border-radius: 8px;
    padding: 10px 14px; box-shadow: 0 1px 6px rgba(0,0,0,0.3);
    font-size: 14px; line-height: 1.4;
  }}
  #sidebar h3 {{ margin: 8px 0 4px; font-size: 14px; }}
  #sidebar ul {{ margin: 0; padding-left: 18px; }}
  #sidebar li {{ margin-bottom: 6px; }}
  #sidebar a {{ color: #2563eb; }}
  #sidebar .table-wrap {{ overflow-x: auto; margin: 4px 0 8px; }}
  #sidebar table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
  #sidebar th, #sidebar td {{ border: 1px solid #d1d5db; padding: 3px 6px; text-align: left; vertical-align: top; }}
  #sidebar th {{ background: #f3f4f6; white-space: nowrap; }}
  #sidebar .links-section a {{ display: inline-block; margin: 2px 0; }}
  {DAY_PLAN_CSS}
  .route-arrow div {{ color: #2563eb; font-size: 16px; line-height: 16px; text-align: center; text-shadow: 0 0 2px #fff, 0 0 2px #fff; }}
  @media (max-width: 480px) {{
    #sidebar {{ left: 10px; right: 10px; max-width: none; top: auto; bottom: 10px; max-height: 40vh; }}
  }}
</style>
</head>
<body>
<div id="map"></div>
<div id="sidebar">
  <h3 style="margin-top:0">{title_escaped}</h3>
  {stats_html}
  {access_html}
  {confidence_html}
  {day_plan_sidebar}
  {links_html}
</div>
{day_plan_overlay}
<script src="{LEAFLET_JS}"></script>
<script>
  const data = {geojson_json};
  const TYPE_LABELS = {type_labels_js};
  const TIER_LABELS = {tier_labels_js};
  // Known Leaflet/Chromium-on-Linux issue: tiles can flash/disappear during
  // the CSS-transform zoom animation. Disabling it trades a bit of polish
  // for tiles that stay put.
  const map = L.map('map', {{ zoomAnimation: false, fadeAnimation: false }});
  // Tile provider(s) chosen for this route (design spec
  // 2026-09-28-osm-day-route-show-tile-providers-design.md): one
  // L.tileLayer per provider available for this route's location, the
  // active one added directly, an L.control.layers switcher added only
  // when more than one provider is available.
  {tile_layers_js}

  // Access-point coloring: single drop-off point -> green. Two distinct
  // points -> start green, end blue. An explicit properties.role
  // ("start"/"end") wins; otherwise infer from which end of the route
  // LineString each access point sits closest to.
  const accessFeatures = data.features.filter(
    f => f.geometry.type === 'Point' && (f.properties || {{}}).type === 'access'
  );
  const lineFeature = data.features.find(f => f.geometry.type === 'LineString');
  if (accessFeatures.length === 1) {{
    accessFeatures[0].properties._accessColor = 'green';
  }} else if (accessFeatures.length > 1 && lineFeature) {{
    const coords = lineFeature.geometry.coordinates;
    const startPt = coords[0];
    const endPt = coords[coords.length - 1];
    const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
    accessFeatures.forEach(f => {{
      const role = (f.properties || {{}}).role;
      if (role === 'start') {{ f.properties._accessColor = 'green'; return; }}
      if (role === 'end') {{ f.properties._accessColor = 'blue'; return; }}
      const c = f.geometry.coordinates;
      f.properties._accessColor = dist(c, startPt) <= dist(c, endPt) ? 'green' : 'blue';
    }});
  }}

  const ACCESS_COLORS = {{ green: ['#16a34a', '#4ade80'], blue: ['#2563eb', '#60a5fa'] }};
  const DEFAULT_COLOR = ['#dc2626', '#f87171'];

  const layer = L.geoJSON(data, {{
    style: {{ color: '#2563eb', weight: 4 }},
    pointToLayer: function (feature, latlng) {{
      const props = feature.properties || {{}};
      const tierLabel = props.tier ? (TIER_LABELS[props.tier] || props.tier) : null;
      const tier = tierLabel ? ` (${{tierLabel}})` : '';
      const [stroke, fill] = props.type === 'access'
        ? (ACCESS_COLORS[props._accessColor] || DEFAULT_COLOR)
        : DEFAULT_COLOR;
      const marker = L.circleMarker(latlng, {{
        radius: 7, color: stroke, fillColor: fill, fillOpacity: 0.9
      }});
      const label = (props.name || TYPE_LABELS.waypoint) + tier;
      let popup = `<b>${{label}}</b>`;
      if (props.type) popup += `<br>${{TYPE_LABELS[props.type] || props.type}}`;
      if (props.note) popup += `<br>${{props.note}}`;
      if (props.source) popup += `<br><i>${{props.source}}</i>`;
      if (props._popupExtra) popup += props._popupExtra;
      marker.bindPopup(popup);
      return marker;
    }}
  }}).addTo(map);

  if (layer.getBounds().isValid()) {{
    map.fitBounds(layer.getBounds(), {{ padding: [30, 30] }});
  }} else {{
    map.setView([40.4168, -3.7038], 12);
  }}

  // Direction-of-travel arrows along the route line — no plugin, just
  // rotated divIcons placed at regular distance intervals (not per-point,
  // since node density varies wildly along a real path).
  function haversineJS(lat1, lon1, lat2, lon2) {{
    const R = 6371000, toRad = d => d * Math.PI / 180;
    const dphi = toRad(lat2 - lat1), dlambda = toRad(lon2 - lon1);
    const a = Math.sin(dphi / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dlambda / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(a));
  }}

  function bearing(lat1, lon1, lat2, lon2) {{
    const toRad = d => d * Math.PI / 180, toDeg = r => r * 180 / Math.PI;
    const y = Math.sin(toRad(lon2 - lon1)) * Math.cos(toRad(lat2));
    const x = Math.cos(toRad(lat1)) * Math.sin(toRad(lat2)) -
              Math.sin(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.cos(toRad(lon2 - lon1));
    return (toDeg(Math.atan2(y, x)) + 360) % 360;
  }}

  function addDirectionArrows(coords) {{
    let totalLen = 0;
    for (let i = 0; i < coords.length - 1; i++) {{
      totalLen += haversineJS(coords[i][1], coords[i][0], coords[i + 1][1], coords[i + 1][0]);
    }}
    if (totalLen === 0) return;
    const intervalM = Math.max(150, totalLen / 25);  // ~25 arrows over the whole route, never denser than 150m
    let dist = 0, nextMark = intervalM;
    for (let i = 0; i < coords.length - 1; i++) {{
      const [lon1, lat1] = coords[i];
      const [lon2, lat2] = coords[i + 1];
      const segLen = haversineJS(lat1, lon1, lat2, lon2);
      while (segLen > 0 && dist + segLen >= nextMark) {{
        const frac = (nextMark - dist) / segLen;
        const lat = lat1 + (lat2 - lat1) * frac;
        const lon = lon1 + (lon2 - lon1) * frac;
        const brng = bearing(lat1, lon1, lat2, lon2);
        const icon = L.divIcon({{
          className: 'route-arrow',
          html: `<div style="transform: rotate(${{brng}}deg);">&#9650;</div>`,
          iconSize: [16, 16],
          iconAnchor: [8, 8],
        }});
        L.marker([lat, lon], {{ icon, interactive: false }}).addTo(map);
        nextMark += intervalM;
      }}
      dist += segLen;
    }}
  }}

  if (lineFeature) {{
    addDirectionArrows(lineFeature.geometry.coordinates);
  }}
</script>
<script>
{day_plan_script}
</script>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("route_dir")
    parser.add_argument("output_path", nargs="?")
    parser.add_argument("--user-lang", default="en",
                         help="ISO 639-1 code of the language the person is writing in (default: en)")
    parser.add_argument("--local-lang", default=None,
                         help="ISO 639-1 code of the route location's local/official language")
    parser.add_argument("--no-wikipedia", action="store_true",
                         help="skip all place-info enrichment (Wikipedia, Wikidata, "
                              "Wikimedia Commons, OpenTripMap) for offline / faster renders")
    parser.add_argument("--wiki-timeout", type=float, default=5.0,
                         help="per-request timeout in seconds, shared by all four "
                              "place-info plugins")
    parser.add_argument("--tile-provider", default=None,
                         choices=["esri_street", "esri_satellite", "cyclosm", "ign_es_mtn"],
                         help="force this tile provider as the active map layer "
                              "(esri_street, esri_satellite, cyclosm, ign_es_mtn); "
                              "must be available for the route's location or the "
                              "render fails with an error")
    parser.add_argument("--tile-timeout", type=float, default=5.0,
                         help="per-request timeout in seconds for tile-provider "
                              "coverage probes (cyclosm, ign_es_mtn only — the two "
                              "Esri layers are never probed)")
    args = parser.parse_args()

    route_dir = Path(args.route_dir)
    geojson_path = route_dir / "route.geojson"
    notes_path = route_dir / "notes.md"
    output_path = Path(args.output_path) if args.output_path else route_dir / "map.html"

    if not geojson_path.exists():
        print(f"error: {geojson_path} not found", file=sys.stderr)
        sys.exit(1)

    geojson_preview = json.loads(geojson_path.read_text(encoding="utf-8"))
    title = _route_title(geojson_preview, fallback=route_dir.name)

    try:
        html = build_map_html(
            geojson_path, notes_path if notes_path.exists() else None, title=title,
            user_lang=args.user_lang, local_lang=args.local_lang,
            resolve_wiki=not args.no_wikipedia, wiki_timeout=args.wiki_timeout,
            tile_provider=args.tile_provider, tile_timeout=args.tile_timeout,
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    output_path.write_text(html, encoding="utf-8")
    abs_path = output_path.resolve()
    print(f"wrote {abs_path}")
    print(f"open in browser: {abs_path.as_uri()}")


if __name__ == "__main__":
    main()
