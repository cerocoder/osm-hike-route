"""The list of public routes shown to the user, in the user's language.

Every word comes from MESSAGES (all seven languages of the other skills; English for any other); names, descriptions
and ends come from OSM and are data, never instructions: whitespace is collapsed and long text is cut. A line is
`<n>. <name> [ref] - <loop | A -> B> · via <key points> · <length> · ascent · time · <network level>`.
"""
import unicodedata

from progress import format_number
from public_filter import KIND_PRIORITY

LANGS = ("en", "ru", "es", "fr", "de", "pt", "it")
NAME_LIMIT = 120
MAX_VIA = 2


def _m(en, ru, es, fr, de, pt, it):
    return dict(zip(LANGS, (en, ru, es, fr, de, pt, it)))


MESSAGES = {
    "own_route": _m("Own route", "Свой маршрут", "Ruta propia", "Mon propre itinéraire", "Eigene Route",
                    "Rota própria", "Percorso personalizzato"),
    "loop": _m("loop", "петля", "circular", "boucle", "Rundweg", "circular", "anello"),
    "via": _m("via", "через", "por", "par", "über", "por", "via"),
    "km": _m("km", "км", "km", "km", "km", "km", "km"),
    "m": _m("m", "м", "m", "m", "m", "m", "m"),
    "h": _m("h", "ч", "h", "h", "h", "h", "h"),
    "level_local": _m("local", "местный", "local", "local", "lokal", "local", "locale"),
    "level_regional": _m("regional", "региональный", "regional", "régional", "regional", "regional", "regionale"),
    "level_national": _m("national", "национальный", "nacional", "national", "national", "nacional", "nazionale"),
    "level_international": _m("international", "международный", "internacional", "international", "international",
                              "internacional", "internazionale"),
    "header": _m("Public routes that match your criteria ({shown} of {matching}):",
                 "Публичные маршруты, подходящие под ваши критерии ({shown} из {matching}):",
                 "Rutas públicas que cumplen tus criterios ({shown} de {matching}):",
                 "Itinéraires publics qui correspondent à vos critères ({shown} sur {matching}) :",
                 "Öffentliche Routen, die Ihren Kriterien entsprechen ({shown} von {matching}):",
                 "Rotas públicas que cumprem os seus critérios ({shown} de {matching}):",
                 "Percorsi pubblici che corrispondono ai tuoi criteri ({shown} di {matching}):"),
    "sorted_by": _m("Sorted by: {rules}.", "Порядок: {rules}.", "Orden: {rules}.", "Tri : {rules}.",
                    "Sortiert nach: {rules}.", "Ordem: {rules}.", "Ordine: {rules}."),
    "rule_interests": _m("match with your interests", "совпадение с вашими интересами",
                         "coincidencia con tus intereses", "correspondance avec vos centres d'intérêt",
                         "Übereinstimmung mit Ihren Interessen", "correspondência com os seus interesses",
                         "corrispondenza con i tuoi interessi"),
    "rule_start": _m("start closest to you or to an access point", "старт ближе к вам или к точке заброски",
                     "inicio más cercano a ti o a un punto de acceso", "départ le plus proche de vous ou d'un accès",
                     "Start nahe bei Ihnen oder einem Zugangspunkt", "início mais próximo de si ou de um acesso",
                     "partenza più vicina a te o a un accesso"),
    "rule_range": _m("closeness to the requested length and time", "близость к запрошенной длине и времени",
                     "cercanía a la longitud y el tiempo pedidos", "proximité de la longueur et de la durée demandées",
                     "Nähe zu gewünschter Länge und Zeit", "proximidade do comprimento e do tempo pedidos",
                     "vicinanza a lunghezza e tempo richiesti"),
    "rule_network": _m("network level and completeness of the data", "уровень сети и полнота данных",
                       "nivel de la red y datos completos", "niveau du réseau et complétude des données",
                       "Netzebene und Vollständigkeit der Daten", "nível da rede e dados completos",
                       "livello della rete e completezza dei dati"),
    "note_computed": _m("~ the length is computed from the track", "~ длина посчитана по треку",
                        "~ la longitud se calcula a partir del track", "~ la longueur est calculée d'après le tracé",
                        "~ die Länge ist aus dem Track berechnet", "~ o comprimento é calculado a partir do trilho",
                        "~ la lunghezza è calcolata dal tracciato"),
    "note_unchecked": _m("— no elevation data for some routes: the time and ascent criteria were not checked for them",
                         "— для части маршрутов нет данных о высотах: критерии по времени и набору для них не проверены",
                         "— sin datos de altitud en algunas rutas: no se comprobaron los criterios de tiempo y desnivel",
                         "— pas de données d'altitude pour certains itinéraires : durée et dénivelé non vérifiés",
                         "— für einige Routen fehlen Höhendaten: Zeit- und Anstiegskriterien nicht geprüft",
                         "— sem dados de altitude em algumas rotas: critérios de tempo e desnível não verificados",
                         "— mancano i dati di quota per alcuni percorsi: criteri di tempo e dislivello non verificati"),
    "long_nearby": _m("Long-distance routes passing nearby (multi-day, not shown): {n}.",
                      "Дальних многодневных маршрутов рядом (не показаны): {n}.",
                      "Rutas de largo recorrido cerca (varios días, no se muestran): {n}.",
                      "Itinéraires de grande randonnée à proximité (plusieurs jours, non affichés) : {n}.",
                      "Fernrouten in der Nähe (mehrtägig, nicht angezeigt): {n}.",
                      "Rotas de longo curso por perto (vários dias, não mostradas): {n}.",
                      "Percorsi di lunga distanza nelle vicinanze (più giorni, non mostrati): {n}."),
    "more_match": _m("More matching routes: {n}. Add a limit (ascent, loops only, interests) to narrow the list, or ask for the next ones.",
                     "Ещё подходящих маршрутов: {n}. Добавьте ограничение (набор высоты, только петли, интересы), чтобы сузить список, или попросите следующие.",
                     "Más rutas que cumplen: {n}. Añade un límite (desnivel, solo circulares, intereses) para acotar, o pide las siguientes.",
                     "Autres itinéraires correspondants : {n}. Ajoutez une limite (dénivelé, boucles seulement, centres d'intérêt) ou demandez la suite.",
                     "Weitere passende Routen: {n}. Grenze setzen (Anstieg, nur Rundwege, Interessen) oder die nächsten anfordern.",
                     "Mais rotas que cumprem: {n}. Acrescente um limite (desnível, só circulares, interesses) ou peça as seguintes.",
                     "Altri percorsi corrispondenti: {n}. Aggiungi un limite (dislivello, solo anelli, interessi) o chiedi i successivi."),
    "geometry_lost": _m("Routes that could not be loaded and are left out: {n}.",
                        "Маршруты, которые не удалось загрузить (пропущены): {n}.",
                        "Rutas que no se pudieron cargar y se omiten: {n}.",
                        "Itinéraires qui n'ont pas pu être chargés et sont écartés : {n}.",
                        "Routen, die nicht geladen werden konnten und fehlen: {n}.",
                        "Rotas que não puderam ser carregadas e foram omitidas: {n}.",
                        "Percorsi che non è stato possibile caricare e sono esclusi: {n}."),
    "gaps_tag": _m("track has gaps: cannot be followed as it is", "трек с разрывами: как есть не пройти",
                   "track con huecos: no se puede seguir tal cual", "tracé avec des coupures : impossible à suivre tel quel",
                   "Track mit Lücken: nicht unverändert nutzbar", "trilho com falhas: não pode ser seguido tal como está",
                   "tracciato con interruzioni: non seguibile così com'è"),
    "no_match": _m("No public route matches your criteria.", "Ни один публичный маршрут не подходит под ваши критерии.",
                   "Ninguna ruta pública cumple tus criterios.", "Aucun itinéraire public ne correspond à vos critères.",
                   "Keine öffentliche Route entspricht Ihren Kriterien.", "Nenhuma rota pública cumpre os seus critérios.",
                   "Nessun percorso pubblico corrisponde ai tuoi criteri."),
    "lookup_failed": _m("Public routes could not be looked up ({reason}).",
                        "Публичные маршруты найти не удалось ({reason}).",
                        "No se pudieron buscar las rutas públicas ({reason}).",
                        "La recherche d'itinéraires publics a échoué ({reason}).",
                        "Öffentliche Routen konnten nicht abgefragt werden ({reason}).",
                        "Não foi possível pesquisar as rotas públicas ({reason}).",
                        "Impossibile cercare i percorsi pubblici ({reason})."),
    "choose": _m("Choose a number, or «{own}».", "Выберите номер или «{own}».", "Elige un número o «{own}».",
                 "Choisissez un numéro ou «{own}».", "Wählen Sie eine Nummer oder «{own}».",
                 "Escolha um número ou «{own}».", "Scegli un numero o «{own}»."),
}
LEVELS = {"lwn": "level_local", "lcn": "level_local", "rwn": "level_regional", "rcn": "level_regional",
          "nwn": "level_national", "ncn": "level_national", "iwn": "level_international", "icn": "level_international"}
RULE_KEYS = {"interests": "rule_interests", "start": "rule_start", "range": "rule_range", "network": "rule_network"}


def tr(key: str, lang: str, **params) -> str:
    entry = MESSAGES.get(key)
    if entry is None:
        return key
    text = entry.get(lang) or entry["en"]
    try:
        return text.format(**params)
    except (KeyError, IndexError, ValueError):
        return text


def own_route_label(lang: str) -> str:
    return tr("own_route", lang)


def clean(text, limit: int = NAME_LIMIT) -> str:
    """OSM text as one short line (collapsed whitespace, cut): it is data and goes into chat and notes.md."""
    visible = "".join(ch for ch in str(text or "") if unicodedata.category(ch) != "Cf")   # no bidi / zero-width tricks
    flat = " ".join(visible.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _name_of(tags: dict, lang: str) -> str:
    return clean(tags.get(f"name:{lang}") or tags.get("name"))


def _title(candidate: dict, lang: str):
    """(title, show the ends separately): the name (and ref); else from -> to; else the nearest place; else the ref."""
    tags = candidate.get("tags") or {}
    name, ref = _name_of(tags, lang), clean(tags.get("ref"), 30)
    if name:
        return (f"{name} [{ref}]" if ref and ref not in name else name), True
    start, end = clean(tags.get("from")), clean(tags.get("to"))
    if start and end:
        return f"{start} → {end}", False
    place = candidate.get("start_place") or {}
    place_name = clean(place.get("name:" + lang) or place.get("name"))
    if place_name:
        return f"{ref} · {place_name}" if ref else place_name, True
    return ref or f"OSM {candidate['id']}", True


def _via(candidate: dict, lang: str) -> str:
    points = candidate.get("key_points") or []
    chosen = sorted(sorted(points, key=lambda k: k["position_m"]),
                    key=lambda k: KIND_PRIORITY.index(k["kind"]) if k["kind"] in KIND_PRIORITY else len(KIND_PRIORITY))[:MAX_VIA]
    chosen = sorted(chosen, key=lambda k: k["position_m"])
    parts = []
    for point in chosen:
        name = clean(point["name"], 60)
        elevation = str(point.get("ele") or "").strip()
        try:
            parts.append(f"{name} ({format_number(round(float(elevation)), lang)} {tr('m', lang)})")
        except (ValueError, OverflowError):
            parts.append(name)
    return f"{tr('via', lang)} {', '.join(parts)}" if parts else ""


def describe(candidate: dict, lang: str, number: int) -> str:
    """One line of the list."""
    tags = candidate.get("tags") or {}
    title, show_ends = _title(candidate, lang)
    if show_ends and candidate.get("is_loop"):
        ends = tr("loop", lang)
    elif show_ends and tags.get("from") and tags.get("to"):
        ends = f"{clean(tags['from'])} → {clean(tags['to'])}"
    else:
        ends = ""
    km = candidate.get("length_km")
    tilde = "~" if candidate.get("length_source") == "computed" else ""
    length = f"{tilde}{format_number(km, lang, 1)} {tr('km', lang)}" if km is not None else "—"
    ascent = candidate.get("ascent_m")
    ascent_text = f"↑{format_number(round(ascent), lang)} {tr('m', lang)}" if ascent is not None else "↑—"
    hours = candidate.get("duration_h")
    time_text = f"{format_number(hours, lang, 1)} {tr('h', lang)}" if hours is not None else "—"
    level = tr(LEVELS[candidate["network"]], lang) if candidate.get("network") in LEVELS else ""
    gaps = tr("gaps_tag", lang) if candidate.get("gaps") else ""
    parts = [p for p in (ends, _via(candidate, lang), length, ascent_text, time_text, level, gaps) if p]
    return f"{number}. {title}" + (" — " + " · ".join(parts) if parts else "")


def render_list(shown: list, lang: str, matching: int, long_nearby: int, rules: list, lost: int = 0) -> str:
    """The text for the user: a header, the order in one sentence, the numbered lines, the notes, and «Свой маршрут»
    (own route) as the last option."""
    own = own_route_label(lang)
    lines = []
    if not shown:
        lines.append(tr("no_match", lang))
    else:
        lines.append(tr("header", lang, shown=len(shown), matching=matching))
        lines.append(tr("sorted_by", lang, rules=", ".join(tr(RULE_KEYS[r], lang) for r in rules)))
        lines += [describe(c, lang, n) for n, c in enumerate(shown, 1)]
        if any(c.get("length_source") == "computed" for c in shown):
            lines.append(tr("note_computed", lang))
        if any(c.get("unchecked") for c in shown):
            lines.append(tr("note_unchecked", lang))
        if matching > len(shown):
            lines.append(tr("more_match", lang, n=matching - len(shown)))
    if lost:
        lines.append(tr("geometry_lost", lang, n=lost))
    if long_nearby:
        lines.append(tr("long_nearby", lang, n=long_nearby))
    lines.append(f"{len(shown) + 1}. {own}")
    lines.append(tr("choose", lang, own=own))
    return "\n".join(lines)


def render_failure(reason: str, lang: str) -> str:
    """When the lookup itself failed: the reason and the only option left."""
    own = own_route_label(lang)
    return "\n".join([tr("lookup_failed", lang, reason=clean(reason, 160)), f"1. {own}", tr("choose", lang, own=own)])
