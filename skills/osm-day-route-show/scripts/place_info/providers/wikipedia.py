# skills/osm-day-route-show/scripts/place_info/providers/wikipedia.py
"""Wikipedia/Wikidata place-info provider.

Never guess from a bare name search + nearest-hit: inside a park, the
nearest article to almost any point is the park's own article. A candidate
is only accepted if its title actually matches the point's name (fuzzy,
accent/case/quote-insensitive). Preferred source order:
  1. `wikidata` property on the point (OSM-curated QID) -> sitelinks.
  2. `wikipedia` property ("lang:Title", OSM-curated) -> langlinks.
  3. Coordinate + name search (CirrusSearch nearcoord) in the local
     language edition, verified by name match, then langlinks from there.
Display names are never translated; `search_names` (optional, per-point,
{lang: translated-name}) is the only place a translation may be used, and
only to query a specific-language Wikipedia edition.
"""
import difflib
import json
import math
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from .base import PlaceInfoProvider, PlaceInfoResult

_USER_AGENT = "osm-day-route-show/1.0 (place_info wikipedia plugin)"


def _lang_priority(user_lang: str, local_lang: str | None) -> list[str]:
    """[user_lang, local_lang, 'en'] deduplicated, order preserved."""
    seq = [user_lang] + ([local_lang] if local_lang else []) + ["en"]
    seen = set()
    out = []
    for lang in seq:
        if lang and lang not in seen:
            seen.add(lang)
            out.append(lang)
    return out


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
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
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
    priority = _lang_priority(user_lang, local_lang)
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


class WikipediaProvider(PlaceInfoProvider):
    provider_id = "wikipedia"

    def __init__(self, user_lang: str, local_lang: str | None = None, timeout: float = 5.0):
        self.user_lang = user_lang
        self.local_lang = local_lang
        self.timeout = timeout

    def fetch(self, names: dict[str, str], lat: float, lon: float,
              wikidata_qid: str | None) -> PlaceInfoResult | None:
        search_lang = self.local_lang or self.user_lang
        name = names.get(search_lang) or names.get(self.user_lang) or next(iter(names.values()), "")
        feature = {
            "geometry": {"coordinates": [lon, lat]},
            "properties": {
                "name": name,
                "wikidata": wikidata_qid,
                "search_names": names,
            },
        }
        try:
            url, lang = resolve_wikipedia(feature, self.user_lang, self.local_lang, self.timeout)
        except WikiLookupError:
            return None
        if url is None:
            return None
        return PlaceInfoResult(provider_id=self.provider_id, url=url, summary=f"Wikipedia ({lang})")
