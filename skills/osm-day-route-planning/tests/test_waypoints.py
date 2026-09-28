import pytest
from waypoints import is_point_restricted, validate_user_waypoint, RestrictedWaypointError

_SQUARE_RING = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)]
_ASYMMETRIC_RING = [(0.0, 0.0), (0.0, 3.0), (1.0, 3.0), (1.0, 0.0)]  # lat in [0,1], lon in [0,3]


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


def test_is_point_restricted_detects_lat_lon_argument_order_correctly():
    # Inside the ring: lat=0.5 (within [0,1]), lon=2.0 (within [0,3])
    assert is_point_restricted(0.5, 2.0, [_ASYMMETRIC_RING]) is True
    # Same numbers, swapped: lat=2.0 is outside [0,1] even though lon=0.5 is inside [0,3]
    assert is_point_restricted(2.0, 0.5, [_ASYMMETRIC_RING]) is False
