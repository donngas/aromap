from app.floor_plans.recognition.indoor import estimate_footprint, is_interior
from app.floor_plans.recognition.walls import WallSegment

SHAPE = (400, 400)


def _room(x0: float, y0: float, x1: float, y1: float) -> list[WallSegment]:
    return [
        WallSegment("horizontal", y0, x0, x1),
        WallSegment("horizontal", y1, x0, x1),
        WallSegment("vertical", x0, y0, y1),
        WallSegment("vertical", x1, y0, y1),
    ]


def _near(points, expected, tolerance: float = 8) -> bool:
    return len(points) == len(expected) and all(
        any(abs(px - ex) <= tolerance and abs(py - ey) <= tolerance for px, py in points)
        for ex, ey in expected
    )


def test_shop_with_stockroom_is_one_indoor_space() -> None:
    # Sales floor and stockroom split by a wall with a closed door: one outline.
    walls = [*_room(50, 50, 350, 300), WallSegment("vertical", 200, 50, 140)]
    door = WallSegment("vertical", 200, 140, 200)
    walls.append(WallSegment("vertical", 200, 200, 300))

    footprint = estimate_footprint([*walls, door], SHAPE, thickness=10)

    assert footprint is not None
    assert _near(footprint, [(45, 45), (355, 45), (355, 305), (45, 305)])


def test_storefront_door_and_window_count_as_closed() -> None:
    walls = [
        WallSegment("horizontal", 50, 50, 350),
        WallSegment("vertical", 50, 50, 300),
        WallSegment("vertical", 350, 50, 300),
        WallSegment("horizontal", 300, 50, 120),
        WallSegment("horizontal", 300, 180, 250),
        WallSegment("horizontal", 300, 320, 350),
    ]
    door = WallSegment("horizontal", 300, 120, 180)
    window = WallSegment("horizontal", 300, 250, 320)

    assert estimate_footprint([*walls, door, window], SHAPE, thickness=10) is not None


def test_l_shaped_shop_outline_has_six_corners() -> None:
    walls = [
        WallSegment("horizontal", 50, 50, 350),
        WallSegment("vertical", 350, 50, 200),
        WallSegment("horizontal", 200, 200, 350),
        WallSegment("vertical", 200, 200, 350),
        WallSegment("horizontal", 350, 50, 200),
        WallSegment("vertical", 50, 50, 350),
    ]

    footprint = estimate_footprint(walls, SHAPE, thickness=10)

    assert footprint is not None and len(footprint) == 6


def test_shop_with_missing_wall_has_no_estimate() -> None:
    # The front wall is missing: the outdoors fills the whole shop.
    walls = [w for w in _room(50, 50, 350, 300) if w.offset != 300]

    assert estimate_footprint(walls, SHAPE, thickness=10) is None


def test_no_walls_has_no_estimate() -> None:
    assert estimate_footprint([], SHAPE, thickness=10) is None


def test_stockroom_partition_is_interior_but_storefront_is_not() -> None:
    walls = [*_room(50, 50, 350, 300), WallSegment("vertical", 200, 50, 300)]
    outline = estimate_footprint(walls, SHAPE, thickness=10)
    assert outline is not None

    assert is_interior(WallSegment("vertical", 200, 140, 200), outline, thickness=10)
    assert not is_interior(WallSegment("horizontal", 300, 120, 180), outline, thickness=10)
    assert not is_interior(WallSegment("vertical", 350, 100, 160), outline, thickness=10)
