"""A small evaluator for the OSM `opening_hours` tag, covering the syntax that
real data actually uses (checked against 531 strings pulled from Madrid,
Yekaterinburg and Moscow): weekday lists and ranges (also wrapping, `Su-Th`),
several time ranges per rule, overnight ranges (`12:00-05:00`, `8:00-2:30`,
`24:00`), open-ended times (`19:30+`), `off`/`closed`, `24/7`, `PH`, month
ranges (`Jun-Aug`), `sunrise`/`sunset` bounds, and rules separated by `;` or by
a comma before a new weekday selector (`Su-Th 12:30-24:00, Fr,Sa 12:30-00:30`).
A rule after a comma is an additional rule: on the days it matches its hours are
open in addition to those of earlier rules (`Mo-Sa 09:00-12:00, We 15:00-18:00`
is open on Wednesday 09:00-12:00 and 15:00-18:00).

Anything else (`SH`, `week`, `[1]`, quoted comments, years, `easter`, `||`,
offsets such as `(sunrise+01:00)`) gives status "unknown" with the reason —
never a guess. A later rule after `;` overrides an earlier one on the days it matches
(OSM semantics); `off` always closes the day."""
import datetime
import re
from dataclasses import dataclass, field

WEEKDAYS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
SUN_BOUNDS = ("sunrise", "sunset")

_TOKEN = re.compile(
    r"""\s*(?:
        (?P<comment>"[^"]*")
      | (?P<h247>24/7)
      | (?P<time>\d{1,2}:\d{2})
      | (?P<word>[A-Za-z]+)
      | (?P<sym>[,;\-+:])
      | (?P<other>\S)
    )""", re.VERBOSE)


@dataclass
class OpeningResult:
    status: str                      # open_hours | open_all_day | closed | unknown
    intervals: list = field(default_factory=list)   # [(start_min, end_min)] for the date; end may exceed 1440
    note: str | None = None          # the reason when status is "unknown"
    uncertain: bool = False          # a PH rule exists but the holiday status was not known


class _Unsupported(Exception):
    pass


@dataclass
class _Rule:
    days: set = field(default_factory=set)      # weekday indexes, Monday = 0
    ph: bool = False
    months: set = field(default_factory=set)    # 1..12
    times: list = field(default_factory=list)   # [(start, end)]; a bound is minutes, or a name in SUN_BOUNDS, or end == "open_end"
    off: bool = False
    has_selector: bool = False
    additive: bool = False                      # started by a comma after a finished rule: adds to earlier rules

    @property
    def finished(self) -> bool:
        return bool(self.times) or self.off


def _tokenize(text: str) -> list:
    tokens, pos = [], 0
    while pos < len(text.rstrip()):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise _Unsupported(f"cannot read {text[pos:pos + 12].strip()!r}")
        pos = m.end()
        tokens.append((m.lastgroup, m.group(m.lastgroup)))
    return tokens


def _minutes(clock: str) -> int:
    hours, minutes = clock.split(":")
    if int(hours) > 24 or int(minutes) > 59:
        raise _Unsupported(f"bad time {clock!r}")
    return int(hours) * 60 + int(minutes)


def _expand(names: tuple, first: str, last: str | None) -> list:
    i, j = names.index(first), names.index(last if last else first)
    out = [i]
    while i != j:
        i = (i + 1) % len(names)
        out.append(i)
    return out


def _read_bound(tokens: list, i: int):
    """A time bound at tokens[i]: (minutes | 'sunrise' | 'sunset', next_index)."""
    if i >= len(tokens):
        raise _Unsupported("a time range without an end")
    kind, value = tokens[i]
    if kind == "time":
        return _minutes(value), i + 1
    if kind == "word" and value.lower() in SUN_BOUNDS:
        return value.lower(), i + 1
    raise _Unsupported("unsupported time range")


def _parse_chunk(tokens: list) -> list:
    """The tokens of one ';'-separated chunk -> [_Rule]."""
    rules, cur, i = [], _Rule(), 0

    def flush():
        nonlocal cur
        if cur.has_selector or cur.finished:
            rules.append(cur)
        cur = _Rule()

    while i < len(tokens):
        kind, value = tokens[i]
        if kind in ("comment", "other"):
            raise _Unsupported("unsupported syntax " + value)
        if kind == "h247":
            cur.times.append((0, 1440))
            i += 1
        elif kind == "sym":
            if value not in (",", ":"):   # ':' only as the separator in "Jun-Aug: 09:00-18:00"
                raise _Unsupported("unsupported syntax " + value)
            i += 1
        elif kind == "time":
            start = _minutes(value)
            if i + 1 < len(tokens) and tokens[i + 1] == ("sym", "+"):
                cur.times.append((start, "open_end"))
                i += 2
            elif i + 1 < len(tokens) and tokens[i + 1] == ("sym", "-"):
                end, i = _read_bound(tokens, i + 2)
                cur.times.append((start, end))
            else:
                raise _Unsupported("a single time without a range")
        elif value.lower() in SUN_BOUNDS:
            start = value.lower()
            if not (i + 1 < len(tokens) and tokens[i + 1] == ("sym", "-")):
                raise _Unsupported("unsupported sunrise/sunset usage")
            end, i = _read_bound(tokens, i + 2)
            cur.times.append((start, end))
        elif value.lower() in ("off", "closed"):
            cur.off = True
            i += 1
        elif value in WEEKDAYS or value in MONTHS or value == "PH":
            if cur.finished:              # a comma-separated new rule begins here
                flush()
                cur.additive = True
            cur.has_selector = True
            if value == "PH":
                cur.ph = True
                i += 1
                continue
            names = WEEKDAYS if value in WEEKDAYS else MONTHS
            last = None
            if (i + 2 < len(tokens) and tokens[i + 1] == ("sym", "-")
                    and tokens[i + 2][0] == "word" and tokens[i + 2][1] in names):
                last = tokens[i + 2][1]
                i += 2
            indexes = _expand(names, value, last)
            if names is WEEKDAYS:
                cur.days.update(indexes)
            else:
                cur.months.update(m + 1 for m in indexes)
            i += 1
        else:
            raise _Unsupported("unsupported word " + value)
    flush()
    for rule in rules:
        if rule.has_selector and not rule.finished:
            raise _Unsupported("a selector without times is not read")
    return rules


class _NeedsSun(Exception):
    pass


def _resolve(times: list, sun: dict | None) -> list:
    out = []
    for start, end in times:
        def bound(b):
            if b in SUN_BOUNDS:
                if not sun or sun.get(b) is None:
                    raise _NeedsSun()
                return sun[b]
            return b
        s = bound(start)
        if end == "open_end":
            e = 1440
        else:
            e = bound(end)
            if e <= s and not (s == 0 and e == 0):
                e += 1440        # overnight, and "10:00-00:00" meaning midnight
            if s == 0 and e == 0:
                e = 1440
        out.append((int(s), int(e)))
    return out


def _matches(rule: _Rule, day: datetime.date, holiday) -> bool:
    if rule.months and day.month not in rule.months:
        return False
    if rule.days or rule.ph:
        return day.weekday() in rule.days or (rule.ph and holiday is True)
    return True


def _day_intervals(rules: list, day: datetime.date, holiday, sun) -> list:
    times = []
    for rule in rules:
        if not _matches(rule, day, holiday):
            continue
        if rule.off:
            times = []                   # closed
        elif rule.additive and times:
            times = times + rule.times      # a comma rule adds to the earlier ones
        else:
            times = list(rule.times)       # a later rule overrides
    return _resolve(times, sun)


def _merge(intervals: list) -> list:
    merged = []
    for s, e in sorted(intervals):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def evaluate(spec: str, day: datetime.date, holiday: bool | None = None, sun: dict | None = None) -> OpeningResult:
    """Opening status of `spec` on `day`. `holiday` is True/False, or None when
    unknown; `sun` is {"sunrise": minute, "sunset": minute} local minutes."""
    text = (spec or "").strip()
    if not text:
        return OpeningResult("unknown", note="empty value")
    try:
        tokens = _tokenize(text)
        rules = []
        chunk = []
        for token in tokens + [("sym", ";")]:
            if token == ("sym", ";"):
                if chunk:
                    rules.extend(_parse_chunk(chunk))
                chunk = []
            else:
                chunk.append(token)
        if not rules:
            return OpeningResult("unknown", note="empty value")
        if not any(r.times for r in rules) and any(r.has_selector for r in rules):
            return OpeningResult("unknown", note="only closures are listed, the opening hours are not")
        today = _day_intervals(rules, day, holiday, sun)
        previous = _day_intervals(rules, day - datetime.timedelta(days=1), None, sun)
    except _Unsupported as e:
        return OpeningResult("unknown", note=str(e))
    except _NeedsSun:
        return OpeningResult("unknown", note="needs sunrise/sunset times")
    spill = [(0, e - 1440) for _, e in previous if e > 1440]
    intervals = _merge(spill + today)
    uncertain = holiday is None and any(r.ph for r in rules)
    if any(s <= 0 and e >= 1440 for s, e in intervals):
        return OpeningResult("open_all_day", [(0, 1440)], uncertain=uncertain)
    if intervals:
        return OpeningResult("open_hours", intervals, uncertain=uncertain)
    return OpeningResult("closed", [], uncertain=uncertain)


def _clock(minute: int, end: bool = False) -> str:
    if end and minute == 1440:
        return "24:00"
    return f"{(minute // 60) % 24:02d}:{minute % 60:02d}"


def format_intervals(intervals: list) -> str:
    """'09:00–18:00, 19:00–02:00 (+1)' (the +1 marks a close after midnight;
    a close exactly at midnight is written 24:00)."""
    parts = []
    for s, e in intervals:
        text = f"{_clock(s)}–{_clock(e, end=True)}"
        parts.append(text + (" (+1)" if e > 1440 else ""))
    return ", ".join(parts)


def open_at(result: OpeningResult, minute: int) -> bool:
    return any(s <= minute < e for s, e in result.intervals)


def latest_close(result: OpeningResult) -> int | None:
    """The last minute of the date at which the place is open (may exceed 1440), or None."""
    return max((e for _, e in result.intervals), default=None)
