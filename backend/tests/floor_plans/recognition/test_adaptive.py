from pathlib import Path

import cv2
import numpy as np
import pytest
from shapely.geometry import LineString
from shapely.ops import polygonize, unary_union

from app.floor_plans.recognition.interface import recognize_floor_plan
from app.floor_plans.recognition.pipeline import _recognize_orthogonal

FIXTURES = Path(__file__).parent / "fixtures"


def _graph(draft):
    return unary_union([LineString([(w.start.x, w.start.y), (w.end.x, w.end.y)])
                        for w in draft.floor_plan.layout.walls])


def _draw(tmp_path, ring, partitions, outer=10, inner=10):
    image = np.full((800, 1000, 3), 255, np.uint8)
    lines = list(zip(ring, ring[1:] + ring[:1]))
    for a, b in lines:
        cv2.line(image, a, b, (0, 0, 0), outer)
    for a, b in partitions:
        cv2.line(image, a, b, (0, 0, 0), inner)
    path = tmp_path / "plan.png"
    cv2.imwrite(str(path), image)
    return image, path, unary_union([LineString(p) for p in [*lines, *partitions]])


def _assert_graph(draft, expected, regions):
    graph = _graph(draft)
    assert expected.intersection(graph.buffer(3)).length / expected.length >= .99
    assert graph.intersection(expected.buffer(3)).length / graph.length >= .99
    assert len(list(polygonize(graph))) == regions
    assert draft.floor_plan.layout.indoor_domain is not None
    for wall in draft.floor_plan.layout.walls:
        for p in (wall.start, wall.end):
            assert 0 <= p.x <= draft.floor_plan.layout.width_px
            assert 0 <= p.y <= draft.floor_plan.layout.height_px


@pytest.mark.parametrize("outer,inner", [(20, 2), (20, 4), (40, 4), (40, 8), (8, 20)])
def test_recovers_mixed_width_partitions(tmp_path, outer, inner):
    _, path, expected = _draw(tmp_path, [(200, 200), (800, 200), (800, 600), (200, 600)],
                              [[(500, 200), (500, 600)]], outer, inner)
    result = recognize_floor_plan(path)
    _assert_graph(result, expected, 2)
    assert not result.floor_plan.layout.doors and not result.floor_plan.layout.windows


@pytest.mark.parametrize("ring,partitions,regions", [
    ([(150, 150), (750, 150), (850, 250), (850, 650), (150, 650)], [], 1),
    ([(200, 150), (750, 150), (850, 650), (100, 650)], [], 1),
    ([(200, 150), (800, 150), (800, 650), (200, 650)], [[(350, 150), (650, 650)]], 2),
    ([(200, 150), (800, 150), (800, 650), (200, 650)],
     [[(200, 400), (800, 400)], [(500, 400), (650, 650)]], 3),
])
def test_recovers_true_oblique_connections(tmp_path, ring, partitions, regions):
    _, path, expected = _draw(tmp_path, ring, partitions)
    _assert_graph(recognize_floor_plan(path), expected, regions)


@pytest.mark.parametrize("angle", [-10, -2, 2, 5, 15, 30, 45])
def test_deskew_preserves_openings_and_original_coordinates(tmp_path, cad_shop_plan, angle):
    height, width = cad_shop_plan.shape[:2]
    matrix = cv2.getRotationMatrix2D((width/2, height/2), angle, 1)
    cosine, sine = abs(matrix[0, 0]), abs(matrix[0, 1])
    out_width, out_height = int(np.ceil(height*sine + width*cosine)), int(np.ceil(height*cosine + width*sine))
    matrix[0, 2] += (out_width-width)/2
    matrix[1, 2] += (out_height-height)/2
    image = cv2.warpAffine(cad_shop_plan, matrix, (out_width, out_height), borderValue=(255, 255, 255))
    path = tmp_path / "rotated.png"
    cv2.imwrite(str(path), image)
    draft = recognize_floor_plan(path)
    layout = draft.floor_plan.layout
    assert (layout.width_px, layout.height_px) == (out_width, out_height)
    assert len(layout.doors) == 2 and len(layout.windows) == 1
    for kind, apertures in [("doors", [((400, 260), (400, 330)), ((500, 540), (570, 540))]),
                            ("windows", [((150, 60), (250, 60))])]:
        for a, b in apertures:
            expected = LineString([matrix @ np.array([*a, 1]), matrix @ np.array([*b, 1])])
            assert min(expected.hausdorff_distance(LineString([(o.start.x, o.start.y), (o.end.x, o.end.y)]))
                       for o in getattr(layout, kind)) <= 5
    assert layout.indoor_domain is not None


def _geometry(draft):
    layout = draft.floor_plan.layout
    return {
        "walls": sorted((w.start.x, w.start.y, w.end.x, w.end.y) for w in layout.walls),
        "doors": sorted((o.start.x, o.start.y, o.end.x, o.end.y) for o in layout.doors),
        "windows": sorted((o.start.x, o.start.y, o.end.x, o.end.y) for o in layout.windows),
        "domain": layout.indoor_domain.model_dump() if layout.indoor_domain else None,
        "warnings": draft.warnings,
    }


@pytest.mark.parametrize("name", ["cafe", "bakery_cafe", "apartment", "colored_home", "three_bed_home", "ground_floor", "porch_house"])
def test_reasonable_existing_plans_preserve_baseline_geometry(name):
    path = FIXTURES / f"{name}_plan.png"
    assert _geometry(recognize_floor_plan(path)) == _geometry(_recognize_orthogonal(cv2.imread(str(path))))


def test_blank_and_thin_grid_do_not_gain_closed_rooms(tmp_path):
    for grid in (False, True):
        image = np.full((500, 600, 3), 255, np.uint8)
        if grid:
            for x in range(25, 600, 25):
                cv2.line(image, (x, 0), (x, 499), (180, 180, 180), 1)
            for y in range(25, 500, 25):
                cv2.line(image, (0, y), (599, y), (180, 180, 180), 1)
        path = tmp_path / "negative.png"
        cv2.imwrite(str(path), image)
        result = recognize_floor_plan(path)
        assert not result.floor_plan.layout.walls
        assert result.floor_plan.layout.indoor_domain is None


def test_jamb_refinement_preserves_neighboring_apertures(cad_shop_plan):
    from app.floor_plans.models import PixelPoint
    from app.floor_plans.recognition.adaptive import _refine_apertures

    draft = _recognize_orthogonal(cad_shop_plan)
    window = draft.floor_plan.layout.windows[0]
    neighbor = window.model_copy(deep=True)
    neighbor.id = "neighbor"
    neighbor.start = PixelPoint(x=148, y=60)
    neighbor.end = PixelPoint(x=152, y=60)
    window.start = PixelPoint(x=155, y=60)
    window.end = PixelPoint(x=245, y=60)
    before = window.model_copy(deep=True)
    draft.floor_plan.layout.windows.append(neighbor)
    _refine_apertures(cad_shop_plan, draft)
    assert window == before
