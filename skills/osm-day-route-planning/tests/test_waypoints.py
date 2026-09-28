import pytest
from waypoints import is_point_restricted, validate_user_waypoint, RestrictedWaypointError

_SQUARE_RING = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)]


def test_is_point_restricted_true_when_inside_polygon():
    assert is_point_restricted(0.5, 0.5, [_SQUARE_RING]) is True


def test_is_point_restricted_false_when_outside_all_polygons():
    assert is_point_restricted(5.0, 5.0, [_SQUARE_RING]) is False


def test_is_point_restricted_false_when_no_polygons():
    assert is_point_restricted(0.5, 0.5, []) is False


def test_validate_user_waypoint_raises_with_point_name_in_message():
    with pytest.raises(RestrictedWaypointError) as exc_info:
        validate_user_waypoint(0.5, 0.5, "Военная часть", [_SQUARE_RING])

    assert "Военная часть" in str(exc_info.value)


def test_validate_user_waypoint_passes_silently_when_outside():
    validate_user_waypoint(5.0, 5.0, "Смотровая площадка", [_SQUARE_RING])  # no exception
