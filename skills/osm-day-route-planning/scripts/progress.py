"""Console progress for long planning runs, in the user's language.

Everything the user reads comes from MESSAGES (every key in all seven languages of osm-day-route-show); callers
pass a message key and parameters, never free text. Without a terminal (Claude Code's tool output, a log file)
only plain lines are written, each flushed at once; on a terminal the sub-progress line is rewritten in place and
coloured (NO_COLOR is respected). `NullProgress` is what every function uses when the caller passes nothing.

    progress = Progress(total_steps=3, lang="ru")
    with progress.step("graph") as step:          # [1/3] Граф дорог …
        ...
        progress.tick(done, total, "tag_progress")    #       … рёбра 5 000 из 36 320 (14 %)
        progress.detail("graph_done", nodes=35398, edges=72658)
                                                   #       ✓ 0,1 с · 35 398 вершин, 72 658 рёбер

The same file is kept in osm-day-route-day-plan/scripts/day_plan/progress.py (a planning test compares them).
"""
import os
import sys
import time

LANGS = ("en", "ru", "es", "fr", "de", "pt", "it")
TICK_INTERVAL_S = 5.0
_NBSP = " "


def _m(en, ru, es, fr, de, pt, it):
    return dict(zip(LANGS, (en, ru, es, fr, de, pt, it)))


MESSAGES = {
    "unit_s": _m("s", "с", "s", "s", "s", "s", "s"),
    # planner steps
    "overpass": _m("Overpass query", "Запрос к Overpass", "Consulta a Overpass", "Requête Overpass",
                   "Overpass-Abfrage", "Consulta ao Overpass", "Interrogazione Overpass"),
    "overpass_done": _m("{walkable} ways, {restricted} restricted areas", "{walkable} путей, {restricted} закрытых зон",
                        "{walkable} vías, {restricted} zonas restringidas", "{walkable} voies, {restricted} zones interdites",
                        "{walkable} Wege, {restricted} Sperrgebiete", "{walkable} vias, {restricted} zonas restritas",
                        "{walkable} vie, {restricted} zone vietate"),
    "overpass_cache_hit": _m("using the cached answer ({age} h old)", "использован сохранённый ответ (возраст {age} ч)",
                             "usando la respuesta guardada ({age} h)", "réponse en cache utilisée ({age} h)",
                             "gespeicherte Antwort verwendet ({age} h alt)", "a usar a resposta guardada ({age} h)",
                             "uso la risposta in cache ({age} h)"),
    "overpass_attempt": _m("{endpoint}: attempt {n} of {m}", "{endpoint}: попытка {n} из {m}",
                           "{endpoint}: intento {n} de {m}", "{endpoint} : tentative {n} sur {m}",
                           "{endpoint}: Versuch {n} von {m}", "{endpoint}: tentativa {n} de {m}",
                           "{endpoint}: tentativo {n} di {m}"),
    "overpass_failed": _m("{endpoint} did not answer ({reason})", "{endpoint} не ответил ({reason})",
                          "{endpoint} no respondió ({reason})", "{endpoint} n'a pas répondu ({reason})",
                          "{endpoint} hat nicht geantwortet ({reason})", "{endpoint} não respondeu ({reason})",
                          "{endpoint} non ha risposto ({reason})"),
    "graph": _m("Road graph", "Граф дорог", "Grafo de caminos", "Graphe des chemins", "Wegegraph", "Grafo de caminhos",
                "Grafo dei percorsi"),
    "graph_done": _m("{nodes} nodes, {edges} edges", "{nodes} вершин, {edges} рёбер", "{nodes} nodos, {edges} aristas",
                     "{nodes} nœuds, {edges} arêtes", "{nodes} Knoten, {edges} Kanten", "{nodes} nós, {edges} arestas",
                     "{nodes} nodi, {edges} archi"),
    "tag_edges": _m("Tagging edges: highways, water, forest", "Разметка рёбер: шоссе, вода, лес",
                    "Etiquetado de aristas: carreteras, agua, bosque", "Étiquetage des arêtes : routes, eau, forêt",
                    "Kanten markieren: Straßen, Wasser, Wald", "Marcação de arestas: estradas, água, floresta",
                    "Etichettatura degli archi: strade, acqua, bosco"),
    "tag_progress": _m("edges {done} of {total}", "рёбра {done} из {total}", "aristas {done} de {total}",
                       "arêtes {done} sur {total}", "Kanten {done} von {total}", "arestas {done} de {total}",
                       "archi {done} di {total}"),
    "elevation": _m("Elevations", "Высоты", "Altitudes", "Altitudes", "Höhen", "Altitudes", "Quote"),
    "elevation_batch": _m("elevation request {done} of {total}", "запрос высот {done} из {total}",
                          "consulta de altitudes {done} de {total}", "requête d'altitudes {done} sur {total}",
                          "Höhenabfrage {done} von {total}", "pedido de altitudes {done} de {total}",
                          "richiesta di quote {done} di {total}"),
    "elevation_done": _m("{points} points, {cached} from the cache", "{points} точек, из кэша: {cached}",
                         "{points} puntos, {cached} de la caché", "{points} points, {cached} depuis le cache",
                         "{points} Punkte, {cached} aus dem Cache", "{points} pontos, {cached} da cache",
                         "{points} punti, {cached} dalla cache"),
    "routing": _m("Routing", "Прокладка маршрута", "Trazado de la ruta", "Calcul de l'itinéraire", "Routenberechnung",
                  "Traçado do percurso", "Calcolo del percorso"),
    "route_leg": _m("leg {done} of {total}", "участок {done} из {total}", "tramo {done} de {total}",
                    "tronçon {done} sur {total}", "Abschnitt {done} von {total}", "troço {done} de {total}",
                    "tratto {done} di {total}"),
    "optional": _m("Optional points", "Необязательные точки", "Puntos opcionales", "Points facultatifs",
                   "Optionale Punkte", "Pontos opcionais", "Punti facoltativi"),
    "optional_run": _m("route searches {done} of {total}", "поисков пути {done} из {total}",
                       "búsquedas de ruta {done} de {total}", "recherches d'itinéraire {done} sur {total}",
                       "Routensuchen {done} von {total}", "pesquisas de percurso {done} de {total}",
                       "ricerche di percorso {done} di {total}"),
}


def _translate(key: str, lang: str, **params) -> str:
    entry = MESSAGES.get(key)
    if entry is None:
        return key                                              # an unknown key is shown as it is, never an error
    text = entry.get(lang) or entry["en"]
    try:
        return text.format(**params)
    except (KeyError, IndexError, ValueError):
        return text


def format_number(value, lang: str, decimals: int = 0) -> str:
    """1234567.5 -> '1 234 567,5' (no-break space between thousands; decimal comma except in English)."""
    text = f"{value:,.{decimals}f}".replace(",", _NBSP)
    return text if lang == "en" else text.replace(".", ",")


class _NullStep:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def tick(self, *args, **kwargs):
        pass

    def detail(self, *args, **kwargs):
        pass

    def fail(self, *args, **kwargs):
        pass


class NullProgress:
    """The default: every call does nothing."""

    def step(self, *args, **kwargs):
        return _NullStep()

    def tick(self, *args, **kwargs):
        pass

    def detail(self, *args, **kwargs):
        pass

    def note(self, *args, **kwargs):
        pass

    def warn(self, *args, **kwargs):
        pass


class Progress:
    def __init__(self, total_steps=None, lang="en", stream=None, clock=time.monotonic, tty=None, color=None,
                 tick_interval=TICK_INTERVAL_S):
        self.total_steps = total_steps
        self.lang = lang if lang in LANGS else "en"
        self.stream = stream if stream is not None else sys.stderr
        self._clock = clock
        self._tty = bool(getattr(self.stream, "isatty", lambda: False)()) if tty is None else tty
        self._color = (self._tty and not os.environ.get("NO_COLOR")) if color is None else color
        self._interval = tick_interval
        encoding = (getattr(self.stream, "encoding", None) or "utf-8")
        try:
            "✓✗·…".encode(encoding)
            self._ok, self._bad, self._dot, self._dots = "✓", "✗", "·", "…"
        except (UnicodeEncodeError, LookupError):
            self._ok, self._bad, self._dot, self._dots = "ok", "x", "-", "..."
        self._count = 0
        self._current = None
        self._last_tick = None
        self._live = False                                      # a tick line is on screen (terminal only)

    # ---- output helpers -------------------------------------------------------------------------------------------
    def _paint(self, text: str, code: str) -> str:
        return f"\x1b[{code}m{text}\x1b[0m" if self._color else text

    def _write(self, line: str) -> None:
        if self._live:
            self.stream.write("\r\x1b[K")
            self._live = False
        self.stream.write(line + "\n")
        self.stream.flush()

    def _seconds(self, seconds: float) -> str:
        return f"{format_number(seconds, self.lang, 1)} {_translate('unit_s', self.lang)}"

    def _text(self, key, params) -> str:
        shown = {k: format_number(v, self.lang) if isinstance(v, int) and not isinstance(v, bool) else v
                 for k, v in params.items()}
        return _translate(key, self.lang, **shown)

    # ---- steps ----------------------------------------------------------------------------------------------------
    def step(self, key: str, text: str | None = None, **params):
        """Context manager for one pipeline step. `text` replaces the catalogue title (a caller-localized name,
        e.g. a section heading); otherwise the title is MESSAGES[key]."""
        return _Step(self, key, text, params)

    def tick(self, done, total, key: str = "tag_progress", **params) -> None:
        """Sub-progress of the current step: MESSAGES[key] gets done/total. Without a terminal at most one line
        every `tick_interval` seconds (and never for a step that finishes quickly)."""
        now = self._clock()
        percent = int(100 * done / total) if total else 100
        message = f"{self._dots} {self._text(key, dict(params, done=done, total=total))} ({percent} %)"
        if self._tty:
            self.stream.write("\r\x1b[K      " + message)
            self.stream.flush()
            self._live = True
            return
        if self._last_tick is None:
            self._last_tick = now if self._current is None else self._current.started
        if now - self._last_tick >= self._interval:
            self._last_tick = now
            self._write("      " + message)

    def detail(self, key: str, **params) -> None:
        if self._current is not None:
            self._current.detail_text = self._text(key, params)

    def note(self, key: str, **params) -> None:
        self._write(f"      {self._dot} {self._text(key, params)}")

    def warn(self, key: str, **params) -> None:
        self._write("  " + self._paint("!", "33") + f" {self._text(key, params)}")


class _Step:
    def __init__(self, progress, key, text, params):
        self.p = progress
        self.key, self.text, self.params = key, text, params
        self.detail_text = None
        self.failure = None
        self.started = 0.0

    def __enter__(self):
        p = self.p
        p._count += 1
        p._current = self
        p._last_tick = None
        title = self.text if self.text is not None else p._text(self.key, self.params)
        counter = f"[{p._count}/{p.total_steps}]" if p.total_steps else f"[{p._count}]"
        p._write(f"{counter} {title} {p._dots}")
        self.started = p._clock()
        return self

    def tick(self, done, total, key="tag_progress", **params):
        self.p.tick(done, total, key, **params)

    def detail(self, key, **params):
        self.detail_text = self.p._text(key, params)

    def fail(self, reason: str):
        self.failure = " ".join(str(reason).split())

    def __exit__(self, exc_type, exc, tb):
        p = self.p
        seconds = p._seconds(p._clock() - self.started)
        if exc_type is not None:
            reason = " ".join(f"{exc_type.__name__}: {exc}".split())
            p._write("      " + p._paint(p._bad, "31") + f" {seconds} {p._dot} {reason}")
        elif self.failure is not None:
            p._write("      " + p._paint(p._bad, "31") + f" {seconds} {p._dot} {self.failure}")
        else:
            extra = f" {p._dot} {self.detail_text}" if self.detail_text else ""
            p._write("      " + p._paint(p._ok, "32") + f" {seconds}{extra}")
        p._current = None
        return False
