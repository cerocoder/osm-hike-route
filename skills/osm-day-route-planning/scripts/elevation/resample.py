"""Samples a path's geometry at ~150m intervals for elevation lookups
instead of every graph node (5-20m apart — finer than any elevation
dataset's own 30-90m resolution, see spec §3.8), then interpolates back
to each original node's position."""
from overpass_query import haversine


def cumulative_distances(coords: list[tuple[float, float]]) -> list[float]:
    dists = [0.0]
    for (lat1, lon1), (lat2, lon2) in zip(coords, coords[1:]):
        dists.append(dists[-1] + haversine(lat1, lon1, lat2, lon2))
    return dists


def sample_positions(coords: list[tuple[float, float]], interval_m: float = 150.0):
    """Returns [(lat, lon, dist_m), ...] including both endpoints."""
    cum = cumulative_distances(coords)
    total = cum[-1]
    if total == 0.0:
        lat, lon = coords[0]
        return [(lat, lon, 0.0)]

    target_dists = [0.0]
    d = interval_m
    while d < total:
        target_dists.append(d)
        d += interval_m
    if target_dists[-1] != total:
        target_dists.append(total)

    samples = []
    seg = 0
    for target in target_dists:
        while seg < len(cum) - 2 and cum[seg + 1] < target:
            seg += 1
        lat1, lon1 = coords[seg]
        lat2, lon2 = coords[seg + 1]
        seg_len = cum[seg + 1] - cum[seg]
        frac = 0.0 if seg_len == 0 else (target - cum[seg]) / seg_len
        lat = lat1 + (lat2 - lat1) * frac
        lon = lon1 + (lon2 - lon1) * frac
        samples.append((lat, lon, target))
    return samples


def interpolate_at_distances(sample_dists: list[float], sample_elevations: list[float],
                              target_dists: list[float]) -> list[float]:
    """Linear interpolation of elevation at arbitrary distances-along-path,
    given known elevations at sample_dists. Targets outside the sampled
    range clamp to the nearest endpoint rather than extrapolating."""
    results = []
    for target in target_dists:
        if target <= sample_dists[0]:
            results.append(sample_elevations[0])
            continue
        if target >= sample_dists[-1]:
            results.append(sample_elevations[-1])
            continue
        i = 0
        while sample_dists[i + 1] < target:
            i += 1
        d0, d1 = sample_dists[i], sample_dists[i + 1]
        e0, e1 = sample_elevations[i], sample_elevations[i + 1]
        frac = 0.0 if d1 == d0 else (target - d0) / (d1 - d0)
        results.append(e0 + (e1 - e0) * frac)
    return results
