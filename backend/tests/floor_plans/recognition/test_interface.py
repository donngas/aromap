from pathlib import Path

import cv2
import numpy as np
import pytest

from app.floor_plans.models import Layout, PixelPoint, RecognitionDraft, Wall
from app.floor_plans.recognition.interface import RecognitionError, recognize_floor_plan
from app.floor_plans.recognition.pipeline import NO_INDOOR_WARNING, UNSUPPORTED_WARNING

FIXTURES = Path(__file__).parent / "fixtures"
# Committed plans recognized well.
PASS_IMAGES = [
    FIXTURES / "cafe_plan.png",
    FIXTURES / "bakery_cafe_plan.png",
    FIXTURES / "apartment_plan.png",
    FIXTURES / "colored_home_plan.png",
    FIXTURES / "three_bed_home_plan.png",
    FIXTURES / "ground_floor_plan.png",
]
# Images in fixtures/local/fail are git-ignored (unclear or unrecorded redistribution
# rights; see local/SOURCES.md) and recognized poorly. Their tests are skipped when
# the files are absent.
LOCAL_FAIL = FIXTURES / "local" / "fail"


def _images(folder: Path) -> list[Path]:
    return sorted(p for p in folder.glob("*") if p.suffix.lower() in {".png", ".jpg", ".jpeg"})


FAIL_IMAGES = _images(LOCAL_FAIL)
# Plans with specific accuracy checks below.
NAMED = {
    "cafe": FIXTURES / "cafe_plan.png",  # listing-style shop plan
    "three_bed_home": FIXTURES / "three_bed_home_plan.png",  # bold walls, many rooms
    "ground_floor": FIXTURES / "ground_floor_plan.png",  # CAD-style, corner column markers
    "cad_cafe": LOCAL_FAIL / "cad_cafe_plan.png",  # CAD drawing
    "colored_home": FIXTURES / "colored_home_plan.png",  # colored, dimensioned
    "warehouse": LOCAL_FAIL / "warehouse_plan.png",  # gray solid walls
}
TOLERANCE_PX = 3


def _image_id(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


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
    """Recognizes each image once on first use, skipping missing local images.

    Keys are image paths or names from NAMED.
    """

    def __missing__(self, key: str | Path) -> RecognitionDraft:
        path = NAMED.get(key, key) if isinstance(key, str) else key
        if not path.exists():
            pytest.skip(f"local fixture not present: {path.name}")
        self[key] = recognize_floor_plan(path)
        return self[key]


@pytest.fixture(scope="module")
def drafts() -> dict[str | Path, RecognitionDraft]:
    return _Drafts()


# Contract checks shared by every image, whether recognized well or not.


@pytest.mark.parametrize("path", PASS_IMAGES + FAIL_IMAGES, ids=_image_id)
def test_draft_follows_contract(drafts, path) -> None:
    layout = drafts[path].floor_plan.layout
    height, width = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR).shape[:2]
    assert (layout.width_px, layout.height_px) == (width, height)
    assert layout.revision == 1
    assert layout.calibration is None
    assert drafts[path].floor_plan.reference_image is None
    assert len({w.id for w in layout.walls}) == len(layout.walls)
    opening_ids = [o.id for o in layout.doors + layout.windows]
    assert len(set(opening_ids)) == len(opening_ids)


@pytest.mark.parametrize("path", PASS_IMAGES + FAIL_IMAGES, ids=_image_id)
def test_openings_lie_on_their_wall(drafts, path) -> None:
    layout = drafts[path].floor_plan.layout
    walls = {w.id: w for w in layout.walls}
    for opening in layout.doors + layout.windows:
        wall = walls[opening.wall_id]
        assert _contains(wall, opening.start) and _contains(wall, opening.end)


@pytest.mark.parametrize("path", PASS_IMAGES + FAIL_IMAGES, ids=_image_id)
def test_walls_are_split_at_junctions(drafts, path) -> None:
    layout = drafts[path].floor_plan.layout
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
        ((188, 196), (251, 196)),  # left restroom door
        ((347, 196), (404, 196)),  # right restroom door, hinged on a short stub
    ],
)
def test_cafe_doors(cafe: Layout, start, end) -> None:
    assert _has_opening(cafe.doors, start, end), cafe.doors


def test_cafe_indoor_domain_is_the_shop_outline(cafe: Layout) -> None:
    assert cafe.indoor_domain is not None
    boundary = cafe.indoor_domain.boundary
    expected = [(93, 16), (90, 878), (937, 881), (940, 19)]
    assert len(boundary) == len(expected)
    assert all(any(_near(point, x, y, tolerance=6) for point in boundary) for x, y in expected)
    assert cafe.indoor_domain.holes == []


def test_cafe_kitchen_passage_is_open_floor(cafe: Layout) -> None:
    # The passage into the kitchen has no door symbol, so it stays open.
    assert not any(d.start.x > 410 and d.start.x < 435 for d in cafe.doors), cafe.doors


def test_cafe_window(cafe: Layout) -> None:
    assert len(cafe.doors) == 3
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
        ((132, 338), (132, 402)),  # side door drawn half open: leaf and a short arc
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


# Well-recognized plans get no reliability warning.


@pytest.mark.parametrize("path", PASS_IMAGES, ids=_image_id)
def test_passing_plan_has_no_reliability_warning(drafts, path) -> None:
    assert UNSUPPORTED_WARNING not in drafts[path].warnings


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
    assert draft.floor_plan.layout.indoor_domain is None
    assert NO_INDOOR_WARNING in draft.warnings


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
        ((578, 212), (578, 242)),  # bathroom, frame line touching the bathtub
    ],
)
def test_colored_home_windows(colored_home: Layout, start, end) -> None:
    assert _has_opening(colored_home.windows, start, end), colored_home.windows


@pytest.mark.parametrize(
    "start, end",
    [
        ((174, 92), (174, 205)),  # sliding door, kitchen to living room
        ((236, 316), (236, 371)),  # sliding door, washroom to bedroom
        ((408, 203), (445, 203)),  # door leaf drawn as a thin rectangle
        ((494, 221), (494, 251)),  # bathroom door, once its window seals the outline
    ],
)
def test_colored_home_inner_glazing_is_door(colored_home: Layout, start, end) -> None:
    assert _has_opening(colored_home.doors, start, end), colored_home.doors
    assert not _has_opening(colored_home.windows, start, end)


# Bold-wall home plan: doors either side of an inner wall.


@pytest.mark.parametrize(
    "start, end",
    [
        ((1134, 595), (1198, 595)),  # bathroom, hinged left of the wall between rooms
        ((1223, 595), (1301, 595)),  # master bedroom, hinged right of it
    ],
)
def test_three_bed_home_doors_either_side_of_a_wall(drafts, start, end) -> None:
    draft = drafts["three_bed_home"]
    assert _has_opening(draft.floor_plan.layout.doors, start, end), draft.floor_plan.layout.doors
    assert not any("Skipped" in warning for warning in draft.warnings)


# CAD-style ground floor: every room door found, open passages stay open.


@pytest.mark.parametrize(
    "start, end",
    [
        ((207, 286), (207, 341)),  # back door into the kitchen
        ((207, 374), (207, 413)),  # restroom
        ((234, 463), (234, 513)),  # first bedroom
        ((251, 643), (294, 643)),  # second bedroom
        ((457, 643), (511, 643)),  # living area to the porch
    ],
)
def test_ground_floor_doors(drafts, start, end) -> None:
    doors = drafts["ground_floor"].floor_plan.layout.doors
    assert _has_opening(doors, start, end), doors


def test_ground_floor_has_five_doors_and_one_outline(drafts) -> None:
    layout = drafts["ground_floor"].floor_plan.layout
    assert len(layout.doors) == 5  # kitchen and living passages have no door symbol
    assert layout.indoor_domain is not None


# Synthetic plans covering each supported drawing style; they need no image files.


def _recognize(image: np.ndarray, tmp_path: Path) -> RecognitionDraft:
    path = tmp_path / "plan.png"
    cv2.imwrite(str(path), image)
    draft = recognize_floor_plan(path)
    assert UNSUPPORTED_WARNING not in draft.warnings  # synthetic plans are supported styles
    return draft


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


# Gray solid walls.


def test_warehouse_gray_outer_walls(drafts) -> None:
    layout = drafts["warehouse"].floor_plan.layout
    for corner in [(115, 61), (345, 61), (115, 245), (345, 245)]:
        assert any(_near(p, *corner, tolerance=5) for w in layout.walls for p in (w.start, w.end))
