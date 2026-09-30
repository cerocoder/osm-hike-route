"""The fixed section headings of notes.md, one per section and language.

notes.md is written in the user's language, and osm-day-route-show reads its "Access" and "Points of interest"
sections back by heading. Free wording ("Порядок точек" instead of "Точки интереса") made the map panel say
the section was missing, so the headings are a closed table: write exactly `## <heading(key, lang)>`, and the
reader and `archive_validate` know the names in advance. The same table lives in
osm-day-route-show/scripts/render_map.py (the skills are separate and stdlib-only); a planning test compares the two.
"""

LANGUAGES = ("en", "ru", "es", "fr", "de", "pt", "it")

HEADINGS = {
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

# `skipped` and `curated` are written only when there is something to say; the rest are always present.
REQUIRED_KEYS = ("request", "access", "reasoning", "interest", "distance")


def heading(key: str, lang: str) -> str:
    """The heading text for `key` in `lang` (an unknown language falls back to English)."""
    return HEADINGS[key].get(lang) or HEADINGS[key]["en"]


def _normalized_headings(notes_text: str) -> set:
    return {line[3:].strip().casefold() for line in (notes_text or "").splitlines() if line.startswith("## ")}


def missing_sections(notes_text: str) -> list:
    """Keys of the required sections with no `## <heading>` line, in any language of the table."""
    present = _normalized_headings(notes_text)
    return [key for key in REQUIRED_KEYS
            if not any(text.casefold() in present for text in HEADINGS[key].values())]
