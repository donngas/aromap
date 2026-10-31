import numpy as np
import pytest

from app.floor_plans.recognition.preprocess import wall_mask
from app.floor_plans.recognition.walls import WallSegment, detect_walls

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
