import cv2
import numpy as np

from app.floor_plans.recognition.openings import find_openings
from app.floor_plans.recognition.preprocess import dark_mask, wall_mask
from app.floor_plans.recognition.walls import WallSegment, detect_walls


def _find(image: np.ndarray):
    mask, thickness = wall_mask(image)
    assert thickness is not None
    return find_openings(detect_walls(mask, thickness), dark_mask(image), thickness)


def test_doorway_becomes_door_on_bridged_wall(shop_plan: np.ndarray) -> None:
    walls, openings = _find(shop_plan)

    assert [(o.kind, o.span) for o in openings] == [
        ("door", WallSegment("vertical", 300.0, 170.0, 230.0))
    ]
    assert WallSegment("vertical", 300.0, 50.0, 350.0) in walls


def test_glazed_gap_becomes_window(shop_plan: np.ndarray) -> None:
    # Replace part of the bottom wall with a window drawn as two thin lines.
    cv2.rectangle(shop_plan, (381, 345), (479, 355), (255, 255, 255), cv2.FILLED)
    cv2.line(shop_plan, (380, 347), (480, 347), (0, 0, 0), 1)
    cv2.line(shop_plan, (380, 353), (480, 353), (0, 0, 0), 1)

    _, openings = _find(shop_plan)

    windows = [o.span for o in openings if o.kind == "window"]
    assert windows == [WallSegment("horizontal", 350.0, 380.0, 480.0)]


def test_gap_to_perpendicular_wall_is_bridged() -> None:
    # A wall that stops 60 px short of a perpendicular wall (thickness 10).
    segments = [WallSegment("horizontal", 100, 0, 200), WallSegment("vertical", 260, 0, 300)]
    dark = np.zeros((300, 300), dtype=np.uint8)

    walls, openings = find_openings(segments, dark, thickness=10)

    assert [(o.kind, o.span) for o in openings] == [
        ("door", WallSegment("horizontal", 100, 200, 260))
    ]
    assert WallSegment("horizontal", 100, 0, 260) in walls


def test_wide_gap_is_not_an_opening() -> None:
    segments = [WallSegment("horizontal", 100, 0, 100), WallSegment("horizontal", 100, 300, 400)]
    dark = np.zeros((200, 400), dtype=np.uint8)

    walls, openings = find_openings(segments, dark, thickness=10)

    assert openings == []
    assert walls == segments
