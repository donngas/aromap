from pathlib import Path

import cv2
import numpy as np
import pytest

from app.floor_plans.models import Layout, PixelPoint, Wall
from app.floor_plans.recognition.interface import RecognitionError, recognize_floor_plan

CAFE_PLAN = Path(__file__).parent / "fixtures" / "cafe_plan.png"
TOLERANCE_PX = 3


def _near(point: PixelPoint, x: float, y: float) -> bool:
    return abs(point.x - x) <= TOLERANCE_PX and abs(point.y - y) <= TOLERANCE_PX


def _contains(wall: Wall, point: PixelPoint, strictly: bool = False) -> bool:
    """Whether an axis-aligned wall contains the point (excluding ends if strict)."""
    xs = sorted((wall.start.x, wall.end.x))
    ys = sorted((wall.start.y, wall.end.y))
    inside = xs[0] <= point.x <= xs[1] and ys[0] <= point.y <= ys[1]
    is_end = point in (wall.start, wall.end)
    return inside and not (strictly and is_end)


@pytest.fixture(scope="module")
def cafe() -> Layout:
    draft = recognize_floor_plan(CAFE_PLAN)
    assert draft.warnings == []
    return draft.floor_plan.layout


def test_draft_follows_contract(cafe: Layout) -> None:
    assert (cafe.width_px, cafe.height_px) == (1024, 1024)
    assert cafe.revision == 1
    assert cafe.calibration is None
    assert len({w.id for w in cafe.walls}) == len(cafe.walls)
    opening_ids = [o.id for o in cafe.doors + cafe.windows]
    assert len(set(opening_ids)) == len(opening_ids)


@pytest.mark.parametrize(
    "start, end",
    [
        ((309, 875), (443, 875)),  # double entrance door
        ((422, 224), (422, 282)),  # kitchen passage
        ((188, 196), (251, 196)),  # left restroom door
        ((347, 196), (422, 196)),  # right restroom door, ending at a wall
    ],
)
def test_detects_doors(cafe: Layout, start, end) -> None:
    assert any(_near(d.start, *start) and _near(d.end, *end) for d in cafe.doors), cafe.doors


def test_detects_window(cafe: Layout) -> None:
    assert len(cafe.doors) == 4
    assert len(cafe.windows) == 1
    window = cafe.windows[0]
    assert _near(window.start, 668, 875) and _near(window.end, 821, 875)


def test_openings_lie_on_their_wall(cafe: Layout) -> None:
    walls = {w.id: w for w in cafe.walls}
    for opening in cafe.doors + cafe.windows:
        wall = walls[opening.wall_id]
        assert _contains(wall, opening.start) and _contains(wall, opening.end)


def test_walls_are_split_at_junctions(cafe: Layout) -> None:
    endpoints = [p for w in cafe.walls for p in (w.start, w.end)]
    for wall in cafe.walls:
        assert not any(_contains(wall, p, strictly=True) for p in endpoints), wall


def test_blank_image_returns_empty_layout_with_warning(tmp_path: Path) -> None:
    path = tmp_path / "blank.png"
    cv2.imwrite(str(path), np.full((100, 100, 3), 255, dtype=np.uint8))

    draft = recognize_floor_plan(path)

    assert draft.floor_plan.layout.walls == []
    assert draft.warnings


def test_unreadable_image_raises_recognition_error(tmp_path: Path) -> None:
    path = tmp_path / "plan.png"
    path.write_bytes(b"not an image")

    with pytest.raises(RecognitionError):
        recognize_floor_plan(path)
