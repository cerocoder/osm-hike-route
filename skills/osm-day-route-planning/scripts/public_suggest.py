"""The whole "public routes at the start of planning" step in one call: find the candidates, load their tracks,
filter by the user's criteria (length, time from the mode's pace, ascent, loop), name them by key points, order them
and write the list for the user in the user's language.

Network trouble never blocks the planning: a failed lookup gives a text that offers only «Свой маршрут».
"""
from progress import NullProgress
from public_filter import (
    add_elevation, apply_final, assign_key_points, find_key_points, find_start_places, passes_tag_length, prefilter, rank,
)
from public_render import render_failure, render_list
from public_routes import dedupe, find_candidates, load_tracks

DEFAULT_RADIUS_M = 15000
MAX_SHOWN = 10


def suggest(lat: float, lon: float, mode: str, criteria, pace_kmh: float, ascent_minutes_per_100m: float, service,
            lang: str = "en", radius_m: int = DEFAULT_RADIUS_M, location=None, access_points=(), cache_dir=None,
            progress=None, max_shown: int = MAX_SHOWN) -> dict:
    """{"text": what to show, "shown": the numbered routes, "matching": how many match, "long_nearby", "lost",
    "failed", "rules"}. `service` is the shared ElevationService; `location` (lat, lon) and `access_points` serve the
    practical-start rule (the anchor place is used when no location is given)."""
    progress = progress or NullProgress()
    try:
        with progress.step("public_candidates") as step:
            found = find_candidates(lat, lon, radius_m, mode, cache_dir=cache_dir, progress=progress)
            step.detail("public_candidates_done", found=len(found["candidates"]), long=found["long_nearby"])
    except RuntimeError as error:
        return {"text": render_failure(str(error), lang), "shown": [], "matching": 0, "long_nearby": 0, "lost": 0,
                "failed": True, "rules": []}
    candidates = [c for c in found["candidates"] if passes_tag_length(c, criteria)]
    with progress.step("public_geometry"):
        loaded, lost = load_tracks(candidates, cache_dir=cache_dir, progress=progress)
    loaded, _duplicates = dedupe(loaded)
    survivors = [c for c in loaded if prefilter(c, criteria, pace_kmh)]
    with progress.step("public_elevation"):
        add_elevation(survivors, service, progress=progress)
    matching = apply_final(survivors, criteria, pace_kmh, ascent_minutes_per_100m)
    with progress.step("public_keypoints") as step:
        try:
            points = find_key_points(matching, cache_dir=cache_dir, progress=progress)
        except RuntimeError:
            points = []                                   # the routes are still listed, just without key points
        for candidate in matching:
            assign_key_points(candidate, points, lang)
        try:
            find_start_places(matching, cache_dir=cache_dir, progress=progress)
        except RuntimeError:
            for candidate in matching:
                candidate["start_place"] = None
        ordered, rules = rank(matching, criteria, location or (lat, lon), access_points)
        shown = ordered[:max_shown]
        step.detail("public_done", matching=len(ordered), shown=len(shown))
    return {"text": render_list(shown, lang, len(ordered), found["long_nearby"], rules, lost=lost), "shown": shown,
            "matching": len(ordered), "long_nearby": found["long_nearby"], "lost": lost, "failed": False,
            "rules": rules}
