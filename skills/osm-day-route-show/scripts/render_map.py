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
chrome text and is first in the Wikipedia-language priority list).
--local-lang is the place's local/official language (second priority,
and the language geosearch/name-matching runs in by default). English
is always the final fallback for both UI text and Wikipedia links.
Point names are NEVER translated for display — only used, verbatim or
via an optional per-point `search_names` override, to search a given
Wikipedia language edition.
"""
import argparse
import difflib
import json
import math
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

LEAFLET_CSS = "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css"
LEAFLET_JS = "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js"
USER_AGENT = "osm-hike-route-show/1.0 (standalone map renderer)"


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
    },
    "ru": {
        "getting_there": "Как добраться",
        "interest_layers": "Точки интереса",
        "export_title": "Экспорт и открыть в другом приложении",
        "download_gpx": "Скачать GPX (Wikiloc / Garmin)",
        "open_google": "Открыть область в Google Maps",
        "open_osm": "Открыть область в OpenStreetMap",
        "wikipedia": "Википедия",
    },
    "es": {
        "getting_there": "Cómo llegar",
        "interest_layers": "Puntos de interés",
        "export_title": "Exportar y abrir en otra app",
        "download_gpx": "Descargar GPX (Wikiloc / Garmin)",
        "open_google": "Abrir la zona en Google Maps",
        "open_osm": "Abrir la zona en OpenStreetMap",
        "wikipedia": "Wikipedia",
    },
    "fr": {
        "getting_there": "Comment s'y rendre",
        "interest_layers": "Points d'intérêt",
        "export_title": "Exporter et ouvrir ailleurs",
        "download_gpx": "Télécharger le GPX (Wikiloc / Garmin)",
        "open_google": "Ouvrir la zone dans Google Maps",
        "open_osm": "Ouvrir la zone dans OpenStreetMap",
        "wikipedia": "Wikipédia",
    },
    "de": {
        "getting_there": "Anreise",
        "interest_layers": "Sehenswürdigkeiten",
        "export_title": "Exportieren & anderswo öffnen",
        "download_gpx": "GPX herunterladen (Wikiloc / Garmin)",
        "open_google": "Gebiet in Google Maps öffnen",
        "open_osm": "Gebiet in OpenStreetMap öffnen",
        "wikipedia": "Wikipedia",
    },
    "pt": {
        "getting_there": "Como chegar",
        "interest_layers": "Pontos de interesse",
        "export_title": "Exportar e abrir noutro sítio",
        "download_gpx": "Descarregar GPX (Wikiloc / Garmin)",
        "open_google": "Abrir a área no Google Maps",
        "open_osm": "Abrir a área no OpenStreetMap",
        "wikipedia": "Wikipédia",
    },
    "it": {
        "getting_there": "Come arrivare",
        "interest_layers": "Punti di interesse",
        "export_title": "Esporta e apri altrove",
        "download_gpx": "Scarica GPX (Wikiloc / Garmin)",
        "open_google": "Apri l'area in Google Maps",
        "open_osm": "Apri l'area in OpenStreetMap",
        "wikipedia": "Wikipedia",
    },
}

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
    otherwise need one alias per N)."""
    for alias in SECTION_ALIASES.get(section_key, []):
        pattern = rf"(?m)^##\s[^\n]*?{re.escape(alias)}[^\n]*\n(.*?)(?=\n##\s|\Z)"
        match = re.search(pattern, md_text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def _xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def _inline_markdown(s: str) -> str:
    """[text](url), **bold**, `code` -> HTML. The link regex tolerates one
    level of parens inside the URL (e.g. a Wikipedia article title like
    ...wiki/L%C3%ADnea_C-5_(Cercan%C3%ADas_Madrid)) — a naive [^)]+ would
    truncate at the first ')' inside the URL itself."""
    s = re.sub(
        r'\[([^\]]+)\]\(((?:[^()]|\([^()]*\))*)\)',
        r'<a href="\2" target="_blank" rel="noopener">\1</a>', s,
    )
    s = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', s)
    s = re.sub(r'`([^`]+)`', r'<code>\1</code>', s)
    return s


_LIST_MARKER = re.compile(r"^(?:-\s+|\d+\.\s+)")


def markdown_to_html(md_text: str) -> str:
    """Minimal markdown->HTML for notes.md sections: '- ' or '1. ' list
    items (with hard-wrapped continuation lines joined back together) plus
    inline links/bold/code. Not a general markdown parser — just what
    osm-hike-route-planning's notes.md template actually produces. Without
    the numbered-list branch, a "1. ... 2. ... 3. ..." list (seen in a real
    notes.md) collapses into one giant run-on bullet."""
    items = []
    current = None
    for raw_line in md_text.split("\n"):
        line = raw_line.strip()
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
    if current is not None:
        items.append(current)

    escaped_items = [_inline_markdown(_xml_escape(item)) for item in items]
    return "<ul>" + "".join(f"<li>{item}</li>" for item in escaped_items) + "</ul>"


# ---------------------------------------------------------------------------
# Wikipedia link resolution
#
# Never guess from a bare name search + nearest-hit: inside a park, the
# nearest article to almost any point is the park's own article. A candidate
# is only accepted if its title actually matches the point's name (fuzzy,
# accent/case/quote-insensitive). Preferred source order:
#   1. `wikidata` property on the point (OSM-curated QID) -> sitelinks.
#   2. `wikipedia` property ("lang:Title", OSM-curated) -> langlinks.
#   3. Coordinate + name search (CirrusSearch nearcoord) in the local
#      language edition, verified by name match, then langlinks from there.
# Display names are never translated; `search_names` (optional, per-point,
# {lang: translated-name}) is the only place a translation may be used, and
# only to query a specific-language Wikipedia edition.
# ---------------------------------------------------------------------------

def _normalize_name(s: str) -> str:
    """Casefold/accent/quote-insensitive normalization for name matching.
    Keeps the words inside a parenthetical (only the parenthesis characters
    themselves are punctuation-stripped, same as quotes/commas) — a Wikipedia
    disambiguator like "(Нижнесергинский район)" or a qualifier like
    "(пещера)" needs to survive as tokens for `_name_matches`'s order-
    independent token check, since a title like "Дружба (пещера)" for a
    query "Пещера Дружба" has the same words in a different order, which a
    plain substring check would never accept."""
    s = s.casefold()
    s = s.replace("ё", "е")  # ё -> е
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[«»\"'`,.()\[\]]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _name_matches(candidate: str, target: str, threshold: float = 0.72,
                   min_length_ratio: float = 0.4, max_extra_tokens: int = 3) -> bool:
    """Fuzzy, word-order-independent title match, with two separate guards
    against the same failure mode (a short name being a small fragment of a
    much longer, unrelated phrase — "Бажуково" inside "Памятный знак
    100-летия п. Бажуково" — must NOT count as a match; reproduced in
    testing, keep as the regression case when touching this function):

    - The plain ratio/substring checks are gated by `min_length_ratio`
      (character-length based).
    - The order-independent token-subset check is gated by
      `max_extra_tokens` instead — a *character*-length gate would also
      reject a real disambiguated title just because its qualifier is a
      multi-word region name ("Большой Провал" vs "Большой карстовый
      провал (Свердловская область)" is a real match with 3 extra tokens
      but a length ratio under 0.4, which the character-length gate alone
      rejected in testing). Extra *token count* stays low for a genuine
      type/region qualifier and high for an unrelated sentence that
      happens to contain the name."""
    a, b = _normalize_name(candidate), _normalize_name(target)
    if not a or not b:
        return False
    if a == b:
        return True
    length_ratio = min(len(a), len(b)) / max(len(a), len(b))
    if length_ratio >= min_length_ratio:
        if difflib.SequenceMatcher(None, a, b).ratio() >= threshold:
            return True
        shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
        if shorter in longer:
            return True
    # Order-independent: candidate title words may include the query's
    # words in a different order (Wikipedia often appends a type/region
    # qualifier as a parenthetical rather than a prefix).
    a_tokens, b_tokens = set(a.split()), set(b.split())
    smaller_tokens, larger_tokens = (a_tokens, b_tokens) if len(a_tokens) <= len(b_tokens) else (b_tokens, a_tokens)
    return (bool(smaller_tokens) and smaller_tokens.issubset(larger_tokens)
            and len(larger_tokens - smaller_tokens) <= max_extra_tokens)


class WikiLookupError(Exception):
    """A request to Wikipedia/Wikidata failed or was rate-limited — distinct
    from a clean "no matching article" result. Callers must NOT cache a
    null result on this exception: doing so would permanently poison
    wiki_links.json with false negatives from a transient rate limit,
    rather than retrying on the next render (see MIN_REQUEST_INTERVAL —
    this was reproduced in testing: a burst of requests during development
    tripped "You are making too many requests to the API", which is plain
    text, not JSON, and was previously swallowed by a blanket except."""


_last_request_time = [0.0]
MIN_REQUEST_INTERVAL = 1.0  # seconds between Wikimedia API calls, be a good citizen


def _throttle():
    import time
    elapsed = time.monotonic() - _last_request_time[0]
    if elapsed < MIN_REQUEST_INTERVAL:
        time.sleep(MIN_REQUEST_INTERVAL - elapsed)
    _last_request_time[0] = time.monotonic()


def _http_get_with_retry(url: str, timeout: float, max_retries: int = 2) -> bytes:
    """GET with one retry on HTTP 429, honoring the `Retry-After` header
    (verified present and set to a few seconds on Wikimedia's real 429
    responses — worth respecting instead of failing outright on the first
    burst). Any other error raises immediately."""
    import time
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_err = None
    for attempt in range(max_retries + 1):
        _throttle()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429 and attempt < max_retries:
                wait_s = float(e.headers.get("Retry-After", 5))
                time.sleep(min(wait_s, 30) + 0.5)
                continue
            raise WikiLookupError(f"{url} failed: HTTP {e.code}") from e
        except (urllib.error.URLError, OSError) as e:
            raise WikiLookupError(f"{url} request failed: {e}") from e
    raise WikiLookupError(f"{url} failed after retries: {last_err}")


def _wiki_api_get(lang: str, params: dict, timeout: float = 5.0) -> dict:
    query = dict(params, format="json")
    url = f"https://{lang}.wikipedia.org/w/api.php?" + urllib.parse.urlencode(query)
    raw = _http_get_with_retry(url, timeout)
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise WikiLookupError(
            f"{lang}.wikipedia.org returned non-JSON (likely rate-limited): {raw[:200]!r}"
        ) from e


def _wikidata_sitelinks(qid: str, timeout: float = 5.0) -> dict:
    url = f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
    raw = _http_get_with_retry(url, timeout)
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise WikiLookupError(f"wikidata.org returned non-JSON: {raw[:200]!r}") from e
    return data.get("entities", {}).get(qid, {}).get("sitelinks", {})


def _langlinks(lang: str, title: str, timeout: float = 5.0) -> dict:
    """{lang: title} for every language edition linked from `lang:title`.
    Propagates WikiLookupError — a failed langlinks call must not be
    silently treated as "no other language editions exist"."""
    data = _wiki_api_get(lang, {"action": "query", "titles": title,
                                 "prop": "langlinks", "lllimit": 500}, timeout)
    pages = data.get("query", {}).get("pages", {})
    for page in pages.values():
        return {ll["lang"]: ll["*"] for ll in page.get("langlinks", [])}
    return {}


def _search_near(lang: str, name: str, lat: float, lon: float,
                  radius_km: float = 2.0, timeout: float = 5.0) -> list[str]:
    """CirrusSearch full-text + location search in one query — combines the
    name with a coordinate proximity filter, so a common name doesn't return
    an unrelated same-named place on the other side of the world."""
    data = _wiki_api_get(lang, {
        "action": "query", "list": "search",
        "srsearch": f"{name} nearcoord:{radius_km}km,{lat},{lon}",
        "srlimit": 5,
    }, timeout)
    return [r["title"] for r in data.get("query", {}).get("search", [])]


def _geosearch(lang: str, lat: float, lon: float, radius_m: int = 1500,
               timeout: float = 5.0) -> list[str]:
    data = _wiki_api_get(lang, {
        "action": "query", "list": "geosearch",
        "gscoord": f"{lat}|{lon}", "gsradius": radius_m, "gslimit": 10,
    }, timeout)
    return [r["title"] for r in data.get("query", {}).get("geosearch", [])]


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _verified_by_coords(lang: str, title: str, lat: float, lon: float,
                         max_dist_km: float = 5.0, timeout: float = 5.0) -> bool:
    """A name match alone is not enough to trust: title collisions with an
    unrelated same-named place are real (a Bulgarian village called
    "Писаница" matched a Russian petroglyph site by exact title in testing;
    a generic-word disambiguation page like "Пирамида" matched too, since
    its title is *exactly* the point's name). Reject unless the candidate
    article's own coordinates land within max_dist_km, and reject outright
    if it's a disambiguation page. A candidate found via `_search_near`'s
    `nearcoord:` filter is NOT trustworthy on its own — that filter appears
    to boost rather than strictly restrict by distance in practice."""
    try:
        data = _wiki_api_get(lang, {
            "action": "query", "titles": title,
            "prop": "coordinates|pageprops", "ppprop": "disambiguation",
        }, timeout)
    except WikiLookupError:
        raise
    pages = data.get("query", {}).get("pages", {})
    for page in pages.values():
        if "disambiguation" in page.get("pageprops", {}):
            return False
        coords = page.get("coordinates")
        if not coords:
            return False
        dist = _haversine_km(lat, lon, coords[0]["lat"], coords[0]["lon"])
        return dist <= max_dist_km
    return False


def _best_verified_candidate(candidates: list[str], query_name: str, lang: str,
                              lat: float, lon: float, timeout: float,
                              max_dist_km: float = 5.0) -> tuple[str | None, bool]:
    """First candidate that both name-matches and coordinate-verifies.
    Returns (title_or_None, had_error) — had_error true means at least one
    verification call failed, so an eventual None here is inconclusive, not
    a confirmed absence (see WikiLookupError)."""
    had_error = False
    for candidate in candidates:
        if not _name_matches(candidate, query_name):
            continue
        try:
            if _verified_by_coords(lang, candidate, lat, lon, max_dist_km, timeout):
                return candidate, had_error
        except WikiLookupError:
            had_error = True
    return None, had_error


def _merged_candidates(lang: str, query_name: str, lat: float, lon: float,
                        timeout: float) -> tuple[list[str], bool]:
    """Merge CirrusSearch `nearcoord` results (name-relevant, but in testing
    `nearcoord` clearly boosts rather than strictly filters by distance —
    an unrelated same-named place elsewhere in the world came back in the
    top 5) with plain `geosearch` results (strictly coordinate-limited, but
    blind to the name). Querying only one of the two missed real matches
    that the other found; every candidate from either list still has to
    pass both the name match and the coordinate check downstream, so
    merging only widens the pool, it doesn't loosen verification."""
    had_error = False
    candidates: list[str] = []
    try:
        candidates.extend(_search_near(lang, query_name, lat, lon, 2.0, timeout))
    except WikiLookupError:
        had_error = True
    try:
        for title in _geosearch(lang, lat, lon, 1500, timeout):
            if title not in candidates:
                candidates.append(title)
    except WikiLookupError:
        had_error = True
    return candidates, had_error


def resolve_wikipedia(feature: dict, user_lang: str, local_lang: str | None,
                       timeout: float = 5.0) -> tuple[str | None, str | None]:
    """Returns (url, lang) for the best-matching Wikipedia article, or
    (None, None) if nothing trustworthy was found. Never returns a link
    whose title doesn't match the point's own name — an unrelated nearby
    article (e.g. the park's own page) is worse than no link."""
    props = feature.get("properties", {})
    name = props.get("name", "")
    lon, lat = feature["geometry"]["coordinates"]
    priority = lang_priority(user_lang, local_lang)
    search_lang = local_lang or user_lang

    found: dict[str, str] = {}
    had_error = False  # a lookup step failed (rate limit, network) — as
    # opposed to succeeding with zero/no-match results. Only the latter is
    # safe to cache as "confirmed no article"; see WikiLookupError's docstring.

    qid = props.get("wikidata")
    if qid:
        try:
            sitelinks = _wikidata_sitelinks(qid, timeout)
            for lang in priority:
                key = f"{lang}wiki"
                if key in sitelinks:
                    found[lang] = sitelinks[key]["title"]
        except WikiLookupError:
            had_error = True

    if not found:
        wp_tag = props.get("wikipedia")
        if wp_tag and ":" in wp_tag:
            src_lang, src_title = wp_tag.split(":", 1)
            found[src_lang] = src_title
            try:
                links = _langlinks(src_lang, src_title, timeout)
                found.update({lang: title for lang, title in links.items()
                              if lang in priority and lang not in found})
            except WikiLookupError:
                had_error = True

    if not found:
        search_names = props.get("search_names", {})
        query_name = search_names.get(search_lang, name)
        candidates, err1 = _merged_candidates(search_lang, query_name, lat, lon, timeout)
        had_error = had_error or err1
        matched_title, verify_err = _best_verified_candidate(
            candidates, query_name, search_lang, lat, lon, timeout)
        had_error = had_error or verify_err
        if matched_title:
            found[search_lang] = matched_title
            try:
                links = _langlinks(search_lang, matched_title, timeout)
                found.update({lang: title for lang, title in links.items()
                              if lang in priority and lang not in found})
            except WikiLookupError:
                had_error = True
        elif search_lang != "en":
            # last resort: try directly against English Wikipedia by name+coord
            en_query = search_names.get("en", name)
            en_candidates, err2 = _merged_candidates("en", en_query, lat, lon, timeout)
            had_error = had_error or err2
            matched_en, verify_err2 = _best_verified_candidate(
                en_candidates, en_query, "en", lat, lon, timeout)
            had_error = had_error or verify_err2
            if matched_en:
                found["en"] = matched_en

    for lang in priority:
        if lang in found:
            title = found[lang]
            url = f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
            return url, lang

    if had_error:
        # Inconclusive, not "confirmed absent" — caller must not cache this.
        raise WikiLookupError(f"one or more lookups failed for '{name}'; result is not conclusive")
    return None, None


def _wiki_cache_load(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _wiki_cache_key(feature: dict, user_lang: str, local_lang: str | None) -> str:
    props = feature.get("properties", {})
    lon, lat = feature["geometry"]["coordinates"]
    ident = props.get("osm_id") or props.get("wikidata") or props.get("name", "")
    return f"{ident}|{round(lat, 5)}|{round(lon, 5)}|{user_lang}|{local_lang or ''}"


def annotate_wikipedia_links(geojson: dict, user_lang: str, local_lang: str | None,
                              cache_path: Path | None, timeout: float = 5.0) -> None:
    """Mutates Point features in place, adding `_wikiUrl` / `_wikiLang` to
    their properties when a verified match is found. Cached by
    (identity, coords, languages) in wiki_links.json next to route.geojson,
    so re-rendering after a route tweak doesn't re-hit the network for
    every point every time, and so a render without network access still
    reuses whatever was already resolved."""
    cache = _wiki_cache_load(cache_path) if cache_path else {}

    def _save():
        if cache_path:
            try:
                cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass

    for feature in geojson.get("features", []):
        if feature["geometry"]["type"] != "Point":
            continue
        key = _wiki_cache_key(feature, user_lang, local_lang)
        if key in cache:
            url, lang = cache[key]["url"], cache[key]["lang"]
        else:
            try:
                url, lang = resolve_wikipedia(feature, user_lang, local_lang, timeout)
            except WikiLookupError as e:
                # Inconclusive (rate-limited/network failure), not "confirmed
                # no article" — leave uncached so the next render retries,
                # rather than permanently poisoning wiki_links.json with a
                # false negative from a transient failure.
                name = feature.get("properties", {}).get("name", "?")
                print(f"warning: wikipedia lookup skipped for '{name}': {e}", file=sys.stderr)
                continue
            cache[key] = {"url": url, "lang": lang}
            # Written after every resolution, not just once at the end: a
            # multi-point run against a slow/rate-limited API can take
            # longer than a caller's own timeout and get killed mid-run —
            # reproduced in testing (a 170s `timeout` wrapper killed a run
            # doing 2x the requests after the search/geosearch merge, and
            # an end-of-function-only write lost every resolution from that
            # run). Frequent small writes cost little against the network
            # round-trips already happening here.
            _save()
        if url:
            feature["properties"]["_wikiUrl"] = url
            feature["properties"]["_wikiLang"] = lang


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
            name = f.get("properties", {}).get("name")
            if name:
                return name
    return fallback


def build_map_html(geojson_path: Path, notes_path: Path | None, title: str,
                    user_lang: str = "en", local_lang: str | None = None,
                    resolve_wiki: bool = True, wiki_timeout: float = 5.0) -> str:
    geojson = json.loads(geojson_path.read_text(encoding="utf-8"))

    if resolve_wiki:
        cache_path = geojson_path.parent / "wiki_links.json"
        annotate_wikipedia_links(geojson, user_lang, local_lang, cache_path, wiki_timeout)

    access_html = ""
    confidence_html = ""
    if notes_path and notes_path.exists():
        notes = notes_path.read_text(encoding="utf-8")
        access = extract_md_section(notes, "access")
        confidence = extract_md_section(notes, "confidence")
        if access:
            access_html = f"<h3>{t('getting_there', user_lang)}</h3>{markdown_to_html(access)}"
        if confidence:
            confidence_html = f"<h3>{t('interest_layers', user_lang)}</h3>{markdown_to_html(confidence)}"

    geojson_json = json.dumps(geojson)

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
    wikipedia_label_js = json.dumps(t("wikipedia", user_lang))
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
  #sidebar .links-section a {{ display: inline-block; margin: 2px 0; }}
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
  {access_html}
  {confidence_html}
  {links_html}
</div>
<script src="{LEAFLET_JS}"></script>
<script>
  const data = {geojson_json};
  const WIKIPEDIA_LABEL = {wikipedia_label_js};
  const TYPE_LABELS = {type_labels_js};
  const TIER_LABELS = {tier_labels_js};
  // Known Leaflet/Chromium-on-Linux issue: tiles can flash/disappear during
  // the CSS-transform zoom animation. Disabling it trades a bit of polish
  // for tiles that stay put.
  const map = L.map('map', {{ zoomAnimation: false, fadeAnimation: false }});
  // Esri's public REST tile service (World_Street_Map) allows this kind of
  // no-key embedded use; OSM's own tile.openstreetmap.org, CARTO's Voyager
  // basemap, and Wikimedia's osm-intl tiles were all tried first and each
  // turned out to block or require a key for standalone-app hotlinking.
  L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
    attribution: 'Tiles &copy; Esri &mdash; Source: Esri, DeLorme, NAVTEQ, USGS, Intermap, iPC, NRCAN, Esri Japan, METI, Esri China (Hong Kong), Esri (Thailand), TomTom',
    maxZoom: 19
  }}).addTo(map);

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
      if (props._wikiUrl) {{
        const langNote = props._wikiLang && props._wikiLang !== "{user_lang}" ? ` (${{props._wikiLang}})` : '';
        popup += `<br><a href="${{props._wikiUrl}}" target="_blank" rel="noopener">${{WIKIPEDIA_LABEL}}${{langNote}}</a>`;
      }}
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
                         help="skip Wikipedia link resolution (offline / faster)")
    parser.add_argument("--wiki-timeout", type=float, default=5.0,
                         help="per-request timeout in seconds for Wikipedia/Wikidata lookups")
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

    html = build_map_html(
        geojson_path, notes_path if notes_path.exists() else None, title=title,
        user_lang=args.user_lang, local_lang=args.local_lang,
        resolve_wiki=not args.no_wikipedia, wiki_timeout=args.wiki_timeout,
    )
    output_path.write_text(html, encoding="utf-8")
    abs_path = output_path.resolve()
    print(f"wrote {abs_path}")
    print(f"open in browser: {abs_path.as_uri()}")


if __name__ == "__main__":
    main()
