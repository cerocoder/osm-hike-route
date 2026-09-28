"""Assembles route.geojson per the extended schema in spec §3.11: 3D
coordinates, and LineString properties that hold computed OUTPUTS only
(never duplicating weights.json's inputs)."""

_OPTIONAL_POINT_KEYS = (
    "note", "source", "osm_id", "wikidata", "wikipedia", "search_names",
    "opening_hours", "access_notes",
)


def _point_feature(pf: dict) -> dict:
    coords = [pf["lon"], pf["lat"]]
    if pf.get("ele") is not None:
        coords.append(pf["ele"])
    properties = {"name": pf["name"], "type": pf["type"]}
    if pf.get("tier") is not None:
        properties["tier"] = pf["tier"]
    if pf.get("role") is not None:
        properties["role"] = pf["role"]
    for key in _OPTIONAL_POINT_KEYS:
        if pf.get(key) is not None:
            properties[key] = pf[key]
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": coords}, "properties": properties}


def build_geojson(path_coords, route_name, mode, style, distance_km, elevation_gain_m,
                   elevation_loss_m, duration_estimate_hours, duration_warning,
                   curated_routes_count, is_loop, skipped_interest_points, point_features):
    line_feature = {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[lon, lat, ele if ele is not None else 0.0] for lon, lat, ele in path_coords],
        },
        "properties": {
            "name": route_name,
            "mode": mode,
            "style": style,
            "distance_km": distance_km,
            "elevation_gain_m": elevation_gain_m,
            "elevation_loss_m": elevation_loss_m,
            "duration_estimate_hours": duration_estimate_hours,
            "duration_warning": duration_warning,
            "curated_routes_count": curated_routes_count,
            "is_loop": is_loop,
            "skipped_interest_points": skipped_interest_points,
        },
    }
    features = [line_feature] + [_point_feature(pf) for pf in point_features]
    return {"type": "FeatureCollection", "features": features}
