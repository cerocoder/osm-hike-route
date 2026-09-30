"""Small planar geometry for the radiation registry: everything is projected to
kilometres around one reference latitude (equirectangular), which is exact
enough for zones a few hundred kilometres across. Routes are tested by
their segments, not only by their vertices: a straight segment can cross a
small zone with both ends far outside it."""
import math

KM_PER_DEG = 111.195


def project(lon: float, lat: float, lat0: float, lon0: float) -> tuple:
    """(x_km, y_km) east and north of (lat0, lon0); longitude differences wrap at the antimeridian."""
    dlon = (lon - lon0 + 180.0) % 360.0 - 180.0
    return dlon * KM_PER_DEG * math.cos(math.radians(lat0)), (lat - lat0) * KM_PER_DEG


def bbox_of(points: list) -> tuple:
    """(min_lon, min_lat, max_lon, max_lat) of [(lon, lat), ...]."""
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    return min(lons), min(lats), max(lons), max(lats)


def bboxes_close(a: tuple, b: tuple, margin_km: float) -> bool:
    """True when two (min_lon, min_lat, max_lon, max_lat) boxes are within margin_km (generous: uses the widest longitude scale)."""
    lat = max(abs(a[1]), abs(a[3]), abs(b[1]), abs(b[3]))
    dlat = margin_km / KM_PER_DEG
    dlon = margin_km / (KM_PER_DEG * max(0.05, math.cos(math.radians(min(lat, 85.0)))))
    return not (a[2] + dlon < b[0] or b[2] + dlon < a[0] or a[3] + dlat < b[1] or b[3] + dlat < a[1])


def point_in_ring(x: float, y: float, ring: list) -> bool:
    """Ray casting; ring is [(x, y), ...], closed or not."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def point_segment_distance(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _orient(ax, ay, bx, by, cx, cy) -> float:
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def segments_intersect(a1, a2, b1, b2) -> bool:
    d1 = _orient(*b1, *b2, *a1)
    d2 = _orient(*b1, *b2, *a2)
    d3 = _orient(*a1, *a2, *b1)
    d4 = _orient(*a1, *a2, *b2)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 != 0 and d2 != 0 and d3 != 0 and d4 != 0:
        return True
    return False


def segment_segment_distance(a1, a2, b1, b2) -> float:
    if segments_intersect(a1, a2, b1, b2):
        return 0.0
    return min(point_segment_distance(*a1, *b1, *b2), point_segment_distance(*a2, *b1, *b2),
               point_segment_distance(*b1, *a1, *a2), point_segment_distance(*b2, *a1, *a2))


def to_segments(line: list) -> list:
    """[(x, y), ...] -> [((x1, y1), (x2, y2)), ...]; a single point becomes one zero-length segment."""
    if len(line) == 1:
        return [(line[0], line[0])]
    return [(line[i], line[i + 1]) for i in range(len(line) - 1)]


def _box(segment) -> tuple:
    (x1, y1), (x2, y2) = segment
    return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)


def clip_segments(segments: list, box: tuple, margin: float) -> list:
    """The segments whose bounding box comes within `margin` of box = (min_x, min_y, max_x, max_y)."""
    kept = []
    for seg in segments:
        sx0, sy0, sx1, sy1 = _box(seg)
        if sx1 >= box[0] - margin and sx0 <= box[2] + margin and sy1 >= box[1] - margin and sy0 <= box[3] + margin:
            kept.append(seg)
    return kept


def segments_distance(segs_a: list, segs_b: list, cap: float = math.inf) -> float:
    """Minimum distance between two sets of segments; pairs whose bounding boxes are more than `cap` apart are skipped
    (the result is then math.inf when nothing lies within cap)."""
    best = math.inf
    boxes_b = [_box(s) for s in segs_b]
    for a in segs_a:
        ax0, ay0, ax1, ay1 = _box(a)
        for b, (bx0, by0, bx1, by1) in zip(segs_b, boxes_b):
            if max(ax0 - bx1, bx0 - ax1, ay0 - by1, by0 - ay1) > min(cap, best):
                continue
            best = min(best, segment_segment_distance(a[0], a[1], b[0], b[1]))
            if best == 0.0:
                return 0.0
    return best


def polyline_distance(line_a: list, line_b: list, cap: float = math.inf) -> float:
    """Minimum distance between two polylines [(x, y), ...]."""
    return segments_distance(to_segments(line_a), to_segments(line_b), cap)


def polygon_distance_segments(segments: list, ring: list, cap: float = math.inf) -> float:
    """0 when any route segment touches or lies inside the polygon ring, else the shortest distance to its edge."""
    if any(point_in_ring(*seg[0], ring) or point_in_ring(*seg[1], ring) for seg in segments):
        return 0.0
    closed = ring if ring[0] == ring[-1] else ring + [ring[0]]
    return segments_distance(segments, to_segments(closed), cap)


def polygon_distance(route: list, ring: list, cap: float = math.inf) -> float:
    """polygon_distance_segments for a route given as points [(x, y), ...]."""
    return polygon_distance_segments(to_segments(route), ring, cap)
