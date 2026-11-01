import numpy as np
import pytest

from app.floor_plans.recognition.preprocess import wall_mask
from app.floor_plans.recognition.walls import WallSegment, detect_walls, snap_corners

TOLERANCE_PX = 2


def _detect(image: np.ndarray) -> list[WallSegment]:
    mask, thickness = wall_mask(image)
    assert thickness is not None
    return detect_walls(mask, thickness)


def _matches(segment: WallSegment, expected: tuple[str, float, float, float]) -> bool:
    orientation, offset, start, end = expected
    return segment.orientation == orientation and all(
        abs(actual - wanted) <= TOLERANCE_PX
        for actual, wanted in [(segment.offset, offset), (segment.start, start), (segment.end, end)]
    )


EXPECTED_WALLS = [
    ("horizontal", 50, 50, 550),
    ("horizontal", 350, 50, 550),
    ("vertical", 50, 50, 350),
    ("vertical", 550, 50, 350),
    ("vertical", 300, 50, 170),
    ("vertical", 300, 230, 350),
]


@pytest.mark.parametrize("expected", EXPECTED_WALLS)
def test_detects_each_wall(shop_plan: np.ndarray, expected) -> None:
    segments = _detect(shop_plan)

    assert any(_matches(segment, expected) for segment in segments), segments


def test_detects_no_extra_walls(shop_plan: np.ndarray) -> None:
    assert len(_detect(shop_plan)) == len(EXPECTED_WALLS)


def test_corners_share_endpoints(shop_plan: np.ndarray) -> None:
    segments = _detect(shop_plan)
    endpoints = [point for segment in segments for point in segment.endpoints]

    for corner in [(50, 50), (550, 50), (50, 350), (550, 350)]:
        assert endpoints.count(corner) == 2, (corner, endpoints)


def test_doorway_gap_is_kept(shop_plan: np.ndarray) -> None:
    interior = [s for s in _detect(shop_plan) if s.orientation == "vertical" and abs(s.offset - 300) <= 1]

    assert len(interior) == 2


def test_short_corner_return_is_kept_but_free_block_is_not() -> None:
    # A storefront wall at x=50 (10 px thick) with a 20 px corner return beside
    # a window, and a free-standing 20 px block (e.g. a display stand).
    mask = np.zeros((300, 300), dtype=np.uint8)
    mask[20:280, 45:55] = 255  # wall
    mask[255:265, 55:75] = 255  # corner return
    mask[100:110, 150:170] = 255  # display stand

    segments = detect_walls(mask, thickness=10)

    returns = [s for s in segments if s.orientation == "horizontal"]
    assert len(returns) == 1 and abs(returns[0].offset - 259.5) <= TOLERANCE_PX
    assert returns[0].end >= 70
    assert all(s.offset != 104.5 for s in segments)


def test_slightly_wider_wall_spots_are_not_short_pieces() -> None:
    # A 10 px storefront wall that is 11 px wide in a few rows (anti-aliasing):
    # its own width must not read as short wall pieces that split the wall.
    mask = np.zeros((300, 100), dtype=np.uint8)
    mask[20:280, 45:55] = 255
    mask[100:103, 44:55] = 255
    mask[200:202, 45:56] = 255

    segments = detect_walls(mask, thickness=10)

    assert len(segments) == 1, segments


def test_snap_corners_trims_overhang_past_a_later_wall() -> None:
    # The side wall ends at the wall's outer edge (y=230); the bottom wall, found
    # only after its windows were bridged, runs along y=221.
    side = WallSegment("vertical", 100, 20, 230)
    bottom = WallSegment("horizontal", 221, 0, 100)

    snapped = snap_corners([side, bottom], thickness=18)

    assert WallSegment("vertical", 100, 20, 221) in snapped


def test_corner_piece_beside_wall_thicker_than_estimate_is_kept() -> None:
    # A 12 px side wall (thickness estimated at 10) with an 18 px corner piece
    # before a window (30 px with the wall, under 3 thicknesses): the side wall
    # must not hide the piece.
    mask = np.zeros((300, 300), dtype=np.uint8)
    mask[20:280, 40:52] = 255  # side wall
    mask[262:274, 52:70] = 255  # corner piece

    segments = detect_walls(mask, thickness=10)

    pieces = [s for s in segments if s.orientation == "horizontal"]
    assert len(pieces) == 1 and pieces[0].end >= 67, segments


def test_short_wall_on_a_wall_line_is_kept() -> None:
    # Between a window and a door: a 20 px piece on the storefront line, 50 px
    # past the end of the storefront wall.
    mask = np.zeros((300, 300), dtype=np.uint8)
    mask[100:110, 20:150] = 255  # storefront wall
    mask[100:110, 200:220] = 255  # short piece

    segments = detect_walls(mask, thickness=10)

    assert any(s.orientation == "horizontal" and s.start >= 195 for s in segments), segments


def test_short_wall_between_two_crossing_walls_is_kept() -> None:
    # A bay's side wall: two windows with a 20 px piece between them, and the
    # walls it runs between crossing its line above and below.
    mask = np.zeros((300, 300), dtype=np.uint8)
    mask[45:55, 20:280] = 255  # wall above
    mask[245:255, 20:280] = 255  # wall below
    mask[140:160, 145:155] = 255  # short piece

    segments = detect_walls(mask, thickness=10)

    assert any(s.orientation == "vertical" and abs(s.offset - 149.5) <= 1 for s in segments)


def test_short_wall_crossing_a_partition_keeps_its_ends() -> None:
    # Between two windows a 17 px outer-wall piece meets a 4 px partition: its
    # ends must not both snap onto the partition.
    piece = WallSegment("horizontal", 50, 247, 264)
    partition = WallSegment("vertical", 255, 50, 200)

    snapped = snap_corners([piece, partition], thickness=10)

    assert piece in snapped


def test_wall_width_leftover_still_collapses() -> None:
    piece = WallSegment("horizontal", 50, 250, 260)
    partition = WallSegment("vertical", 255, 50, 200)

    snapped = snap_corners([piece, partition], thickness=10)

    assert all(s.orientation == "vertical" for s in snapped)
