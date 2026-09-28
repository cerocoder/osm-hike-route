"""Waypoint-level checks that run BEFORE the graph is built (spec §3.4):
a restricted-zone hit here must become an explicit message, never a
silent 'no path found' surfaced later from the router."""
from route_graph import point_in_ring


class RestrictedWaypointError(Exception):
    pass


def is_point_restricted(lat: float, lon: float, restricted_polygons: list) -> bool:
    return any(point_in_ring(lat, lon, ring) for ring in restricted_polygons)


def validate_user_waypoint(lat: float, lon: float, name: str, restricted_polygons: list) -> None:
    """Raises for a USER-supplied point (spec §3.4: 'скилл прямо сообщает
    пользователю, что не может построить маршрут через эту точку, и
    почему'). A skill-CHOSEN candidate should be filtered out with
    is_point_restricted before ever reaching this function — see SKILL.md."""
    if is_point_restricted(lat, lon, restricted_polygons):
        raise RestrictedWaypointError(
            f"Не могу построить маршрут через точку «{name}» — она находится "
            "в закрытой/охраняемой зоне (военный объект, частная территория "
            "или огороженный периметр)."
        )
