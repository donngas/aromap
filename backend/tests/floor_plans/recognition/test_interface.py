from pathlib import Path

import cv2
import numpy as np
import pytest

from app.floor_plans.models import Layout, PixelPoint, RecognitionDraft, Wall
from app.floor_plans.recognition.interface import RecognitionError, recognize_floor_plan

FIXTURES = Path(__file__).parent / "fixtures"
# Images in fixtures/local are git-ignored (unclear redistribution rights);
# their tests are skipped when the files are absent.
LOCAL = FIXTURES / "local"
PLANS = {
    "cafe": (FIXTURES / "cafe_plan.png", (1024, 1024)),  # listing-style shop plan
    "cad_cafe": (LOCAL / "cad_cafe_plan.png", (1179, 1217)),  # CAD drawing
    "house": (LOCAL / "house_plan.png", (1294, 2000)),  # colored, with landscaping
    "colored_home": (LOCAL / "colored_home_plan.png", (650, 459)),  # colored, dimensioned
    "line_home": (LOCAL / "line_home_plan.png", (399, 501)),  # hollow line-art walls
}
TOLERANCE_PX = 3


def _near(point: PixelPoint, x: float, y: float, tolerance: float = TOLERANCE_PX) -> bool:
    return abs(point.x - x) <= tolerance and abs(point.y - y) <= tolerance


def _has_opening(openings, start, end, tolerance: float = TOLERANCE_PX) -> bool:
    return any(
        _near(o.start, *start, tolerance) and _near(o.end, *end, tolerance) for o in openings
    )


def _contains(wall: Wall, point: PixelPoint, strictly: bool = False) -> bool:
    """Whether an axis-aligned wall contains the point (excluding ends if strict)."""
    xs = sorted((wall.start.x, wall.end.x))
    ys = sorted((wall.start.y, wall.end.y))
    inside = xs[0] <= point.x <= xs[1] and ys[0] <= point.y <= ys[1]
    is_end = point in (wall.start, wall.end)
    return inside and not (strictly and is_end)


class _Drafts(dict):
    """Recognizes each fixture once on first use, skipping missing local images."""

    def __missing__(self, name: str) -> RecognitionDraft:
        path = PLANS[name][0]
        if not path.exists():
            pytest.skip(f"local fixture not present: {path.name}")
        self[name] = recognize_floor_plan(path)
        return self[name]


@pytest.fixture(scope="module")
def drafts() -> dict[str, RecognitionDraft]:
    return _Drafts()


# Contract checks shared by every fixture.


@pytest.mark.parametrize("name", PLANS)
def test_draft_follows_contract(drafts, name) -> None:
    layout = drafts[name].floor_plan.layout
    assert (layout.width_px, layout.height_px) == PLANS[name][1]
    assert layout.revision == 1
    assert layout.calibration is None
    assert drafts[name].floor_plan.reference_image is None
    assert len({w.id for w in layout.walls}) == len(layout.walls)
    opening_ids = [o.id for o in layout.doors + layout.windows]
    assert len(set(opening_ids)) == len(opening_ids)


@pytest.mark.parametrize("name", PLANS)
def test_openings_lie_on_their_wall(drafts, name) -> None:
    layout = drafts[name].floor_plan.layout
    walls = {w.id: w for w in layout.walls}
    for opening in layout.doors + layout.windows:
        wall = walls[opening.wall_id]
        assert _contains(wall, opening.start) and _contains(wall, opening.end)


@pytest.mark.parametrize("name", PLANS)
def test_walls_are_split_at_junctions(drafts, name) -> None:
    layout = drafts[name].floor_plan.layout
    endpoints = [p for w in layout.walls for p in (w.start, w.end)]
    for wall in layout.walls:
        assert not any(_contains(wall, p, strictly=True) for p in endpoints), wall


# Listing-style cafe plan.


@pytest.fixture(scope="module")
def cafe(drafts) -> Layout:
    assert drafts["cafe"].warnings == []
    return drafts["cafe"].floor_plan.layout


@pytest.mark.parametrize(
    "start, end",
    [
        ((309, 875), (443, 875)),  # double entrance door
        ((422, 224), (422, 282)),  # kitchen passage
        ((188, 196), (251, 196)),  # left restroom door
        ((347, 196), (422, 196)),  # right restroom door, ending at a wall
    ],
)
def test_cafe_doors(cafe: Layout, start, end) -> None:
    assert _has_opening(cafe.doors, start, end), cafe.doors


def test_cafe_window(cafe: Layout) -> None:
    assert len(cafe.doors) == 4
    assert len(cafe.windows) == 1
    assert _has_opening(cafe.windows, (668, 875), (821, 875))


# CAD cafe plan: gray glazing lines, threshold lines, and an equipment drawing.


@pytest.fixture(scope="module")
def cad_cafe(drafts) -> Layout:
    return drafts["cad_cafe"].floor_plan.layout


@pytest.mark.parametrize(
    "start, end",
    [
        ((656, 160), (716, 160)),  # top
        ((209, 1104), (306, 1104)),  # storefront
        ((417, 1104), (514, 1104)),  # storefront
        ((759, 1104), (857, 1104)),  # storefront
        ((980, 484), (980, 609)),  # right side
    ],
)
def test_cad_cafe_gray_glazing_is_window(cad_cafe: Layout, start, end) -> None:
    assert _has_opening(cad_cafe.windows, start, end), cad_cafe.windows


@pytest.mark.parametrize(
    "start, end",
    [
        ((573, 1104), (701, 1104)),  # double entrance door
        ((132, 338), (132, 402)),  # side door
        ((276, 160), (340, 160)),  # back door with a single threshold line
    ],
)
def test_cad_cafe_doors(cad_cafe: Layout, start, end) -> None:
    assert _has_opening(cad_cafe.doors, start, end), cad_cafe.doors


def test_cad_cafe_ignores_equipment_drawing(drafts, cad_cafe: Layout) -> None:
    equipment = [
        p
        for w in cad_cafe.walls
        for p in (w.start, w.end)
        if 760 <= p.x <= 960 and 200 <= p.y <= 300
    ]
    assert equipment == []
    assert any("not connected" in warning for warning in drafts["cad_cafe"].warnings)


# Colored house plan with landscaping: a stress test outside the shop target.


def test_house_ignores_detached_plants(drafts) -> None:
    layout = drafts["house"].floor_plan.layout
    bush = [p for w in layout.walls for p in (w.start, w.end) if p.x > 1120 and p.y > 1250]
    assert bush == []
    assert any(_near(w.start, 260, 517, tolerance=5) for w in layout.walls)  # building corner


# Edge cases.


def test_large_image_coordinates_map_back(tmp_path: Path, shop_plan: np.ndarray) -> None:
    # 5x the synthetic shop plan (3000 px wide) is downscaled internally. Floor
    # colors are cleared so their edges at the doorway do not look like glazing.
    shop_plan[cv2.cvtColor(shop_plan, cv2.COLOR_BGR2GRAY) > 120] = 255
    path = tmp_path / "large.png"
    cv2.imwrite(str(path), cv2.resize(shop_plan, None, fx=5, fy=5, interpolation=cv2.INTER_NEAREST))

    layout = recognize_floor_plan(path).floor_plan.layout

    assert (layout.width_px, layout.height_px) == (3000, 2000)
    # Doorway drawn at x=295-305, y=171-229, so x 1475-1529, y 855-1149 at 5x.
    door = layout.doors[0]
    assert len(layout.doors) == 1
    assert _near(door.start, 1502, 855, tolerance=5) and _near(door.end, 1502, 1150, tolerance=5)


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


# Colored, dimensioned plan: pink door arcs and glazing, thin-drawn walls.


@pytest.fixture(scope="module")
def colored_home(drafts) -> Layout:
    return drafts["colored_home"].floor_plan.layout


@pytest.mark.parametrize(
    "start, end",
    [
        ((253, 67), (285, 67)),  # living room entrance
        ((242, 251), (273, 251)),  # lower bedroom
        ((425, 251), (456, 251)),  # study
    ],
)
def test_colored_home_arcs_mark_doors(colored_home: Layout, start, end) -> None:
    assert _has_opening(colored_home.doors, start, end), colored_home.doors


@pytest.mark.parametrize(
    "start, end",
    [
        ((153, 381), (219, 381)),  # washroom
        ((467, 381), (532, 381)),  # study
        ((434, 67), (553, 67)),  # bedroom, wider than 15x the thin walls
    ],
)
def test_colored_home_windows(colored_home: Layout, start, end) -> None:
    assert _has_opening(colored_home.windows, start, end), colored_home.windows


# Line drawing: walls are two thin gray lines with white between them.


def test_line_home_hollow_walls_are_detected(drafts) -> None:
    layout = drafts["line_home"].floor_plan.layout
    assert len(layout.walls) >= 30
    outer_left = [w for w in layout.walls if w.start.x == w.end.x and abs(w.start.x - 60) <= 3]
    assert sum(abs(w.end.y - w.start.y) for w in outer_left) > 300


# Synthetic plans covering each supported drawing style; they need no image files.


def _recognize(image: np.ndarray, tmp_path: Path) -> RecognitionDraft:
    path = tmp_path / "plan.png"
    cv2.imwrite(str(path), image)
    return recognize_floor_plan(path)


def test_synthetic_cad_style(tmp_path: Path, cad_shop_plan: np.ndarray) -> None:
    draft = _recognize(cad_shop_plan, tmp_path)
    layout = draft.floor_plan.layout

    assert _has_opening(layout.windows, (150, 60), (250, 60))  # gray glazing
    assert _has_opening(layout.doors, (400, 260), (400, 330))  # plain doorway
    assert _has_opening(layout.doors, (500, 540), (570, 540))  # threshold line and arc
    assert len(layout.doors) == 2 and len(layout.windows) == 1
    assert not [p for w in layout.walls for p in (w.start, w.end) if 590 <= p.x <= 680]
    assert any("not connected" in warning for warning in draft.warnings)


def test_synthetic_colored_style(tmp_path: Path, colored_shop_plan: np.ndarray) -> None:
    layout = _recognize(colored_shop_plan, tmp_path).floor_plan.layout

    assert _has_opening(layout.doors, (300, 100), (300, 140))  # frame lines and arc
    assert _has_opening(layout.doors, (450, 230), (490, 230))
    assert _has_opening(layout.windows, (100, 40), (200, 40))
    assert _has_opening(layout.windows, (340, 420), (500, 420))  # 32x the wall thickness
    assert len(layout.doors) == 2 and len(layout.windows) == 2


def test_synthetic_hollow_line_drawing(tmp_path: Path, hollow_line_plan: np.ndarray) -> None:
    layout = _recognize(hollow_line_plan, tmp_path).floor_plan.layout

    assert len(layout.walls) >= 6
    assert _has_opening(layout.doors, (250, 200), (250, 260), tolerance=4)
    outer = [w for w in layout.walls if w.start.x == w.end.x and abs(w.start.x - 53) <= 3]
    assert sum(abs(w.end.y - w.start.y) for w in outer) > 350
