import cv2
import numpy as np

from app.floor_plans.recognition.openings import find_openings
from app.floor_plans.recognition.preprocess import detail_mask, line_mask, wall_mask
from app.floor_plans.recognition.walls import WallSegment, detect_walls


def _find(image: np.ndarray):
    mask, thickness = wall_mask(image)
    assert thickness is not None
    walls = detect_walls(mask, thickness)
    return find_openings(walls, line_mask(image), detail_mask(image), thickness)


def _blank(height: int = 300, width: int = 300) -> np.ndarray:
    return np.zeros((height, width), dtype=np.uint8)


def _swing(mask: np.ndarray, hinge: tuple[int, int], radius: int, start: int, end: int):
    """Draw a quarter-circle door swing; angles in degrees, clockwise from +x."""
    cv2.ellipse(mask, hinge, (radius, radius), 0, start, end, 255, 1)
    return mask


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


def test_gap_to_wall_with_swing_arc_is_bridged() -> None:
    # A wall attached at x=0 stops 60 px short of the wall at x=260 (thickness 10),
    # with a door hinged at its end.
    segments = [
        WallSegment("horizontal", 100, 0, 200),
        WallSegment("vertical", 0, 0, 300),
        WallSegment("vertical", 260, 0, 300),
    ]
    details = _swing(_blank(), (200, 100), 60, 0, 90)

    walls, openings = find_openings(segments, _blank(), details, thickness=10)

    assert [(o.kind, o.span) for o in openings] == [
        ("door", WallSegment("horizontal", 100, 200, 260))
    ]
    assert WallSegment("horizontal", 100, 0, 260) in walls


def _door_spans(openings) -> list[tuple[float, float]]:
    """Door spans rounded to 2 px: arcs are fitted, so ends can be a pixel off."""
    return [
        (2 * round(o.span.start / 2), 2 * round(o.span.end / 2))
        for o in openings
        if o.kind == "door"
    ]


def test_door_covers_its_swing_and_hinge_stub_stays_wall() -> None:
    # A stockroom wall stops 80 px short of the wall at x=280. The door hinges on
    # a 20 px stub (too short to detect) at x=260 and swings back to x=200.
    segments = [
        WallSegment("horizontal", 100, 0, 200),
        WallSegment("vertical", 0, 0, 300),
        WallSegment("vertical", 280, 0, 300),
    ]
    details = _swing(_blank(), (260, 100), 60, 180, 270)

    walls, openings = find_openings(segments, _blank(), details, thickness=10)

    assert _door_spans(openings) == [(200, 260)]
    assert WallSegment("horizontal", 100, 0, 280) in walls


def test_door_frame_beside_arc_joins_door() -> None:
    # The arc stops 5 px (under one wall thickness) short of each wall end: door frames.
    segments = [
        WallSegment("horizontal", 100, 0, 200),
        WallSegment("vertical", 0, 0, 300),
        WallSegment("vertical", 280, 0, 300),
    ]
    details = _swing(_blank(), (275, 100), 70, 180, 270)

    _, openings = find_openings(segments, _blank(), details, thickness=10)

    assert _door_spans(openings) == [(200, 280)]


def test_round_table_in_gap_is_not_a_door() -> None:
    segments = [
        WallSegment("horizontal", 100, 0, 200),
        WallSegment("vertical", 0, 0, 300),
        WallSegment("vertical", 280, 0, 300),
    ]
    details = cv2.circle(_blank(), (240, 60), 30, 255, 1)

    walls, openings = find_openings(segments, _blank(), details, thickness=10)

    assert openings == []
    assert WallSegment("horizontal", 100, 0, 200) in walls


def test_passage_between_two_room_corners_stays_open() -> None:
    # A kitchen and a restroom both end on the line y=100, 60 px apart, with their
    # side walls turning up: open floor between them, not a doorway.
    segments = [
        WallSegment("horizontal", 100, 0, 100),
        WallSegment("vertical", 100, 0, 100),
        WallSegment("horizontal", 100, 160, 300),
        WallSegment("vertical", 160, 0, 100),
    ]

    _, openings = find_openings(segments, _blank(), _blank(), thickness=10)

    assert openings == []


def test_gap_between_corners_turning_apart_is_a_doorway() -> None:
    # One side wall turns up, the other down: a doorway between two rooms.
    segments = [
        WallSegment("horizontal", 100, 0, 100),
        WallSegment("vertical", 100, 0, 100),
        WallSegment("horizontal", 100, 160, 300),
        WallSegment("vertical", 160, 100, 200),
    ]

    _, openings = find_openings(segments, _blank(), _blank(), thickness=10)

    assert [(o.kind, o.span) for o in openings] == [
        ("door", WallSegment("horizontal", 100, 100, 160))
    ]


def test_wall_ending_in_open_room_is_not_bridged() -> None:
    segments = [
        WallSegment("horizontal", 100, 0, 200),
        WallSegment("vertical", 0, 0, 300),
        WallSegment("vertical", 260, 0, 300),
    ]

    walls, openings = find_openings(segments, _blank(), _blank(), thickness=10)

    assert openings == []
    assert walls == segments


def test_isolated_piece_reaching_one_wall_is_not_bridged() -> None:
    # A stray stub (e.g. equipment) 60 px from a wall, touching nothing else.
    stub = WallSegment("horizontal", 100, 150, 200)
    segments = [stub, WallSegment("vertical", 260, 0, 300)]
    details = _swing(_blank(), (200, 100), 60, 0, 90)

    walls, openings = find_openings(segments, _blank(), details, thickness=10)

    assert openings == []
    assert stub in walls


def test_isolated_piece_between_two_doors_is_bridged() -> None:
    segments = [
        WallSegment("horizontal", 100, 100, 200),
        WallSegment("vertical", 40, 0, 300),
        WallSegment("vertical", 260, 0, 300),
    ]
    details = _swing(_blank(), (100, 100), 60, 90, 180)
    _swing(details, (200, 100), 60, 0, 90)

    walls, openings = find_openings(segments, _blank(), details, thickness=10)

    assert sorted(o.span.start for o in openings) == [40, 200]
    assert WallSegment("horizontal", 100, 40, 260) in walls


def test_wide_glazed_gap_is_a_window() -> None:
    # Thin walls (5 px): a 120 px gap is 24x the thickness, but glazing confirms it.
    segments = [WallSegment("horizontal", 100, 0, 100), WallSegment("horizontal", 100, 220, 600)]
    lines = _blank(200, 600)
    lines[98, 100:221] = 255
    lines[102, 100:221] = 255

    walls, openings = find_openings(segments, lines, _blank(200, 600), thickness=5)

    assert [(o.kind, o.span) for o in openings] == [
        ("window", WallSegment("horizontal", 100, 100, 220))
    ]
    assert WallSegment("horizontal", 100, 0, 600) in walls


def test_wide_gap_without_symbol_is_not_bridged() -> None:
    segments = [WallSegment("horizontal", 100, 0, 100), WallSegment("horizontal", 100, 220, 600)]

    walls, openings = find_openings(segments, _blank(200, 600), _blank(200, 600), thickness=5)

    assert openings == []
    assert walls == segments


def test_single_threshold_line_is_a_door() -> None:
    segments = [WallSegment("horizontal", 100, 0, 100), WallSegment("horizontal", 100, 160, 300)]
    lines = _blank(200)
    lines[100, 100:161] = 255  # one line across the gap

    _, openings = find_openings(segments, lines, _blank(200), thickness=10)

    assert [o.kind for o in openings] == ["door"]


def test_floor_color_edges_are_not_glazing() -> None:
    # Two bands wider than glazing lines, e.g. where floor colors meet a doorway strip.
    segments = [WallSegment("horizontal", 100, 0, 100), WallSegment("horizontal", 100, 160, 300)]
    lines = _blank(200)
    lines[94:100, 100:161] = 255
    lines[101:107, 100:161] = 255

    _, openings = find_openings(segments, lines, _blank(200), thickness=10)

    assert [o.kind for o in openings] == ["door"]


def test_filled_gap_is_a_door() -> None:
    segments = [WallSegment("horizontal", 100, 0, 100), WallSegment("horizontal", 100, 160, 300)]
    filled = np.full((200, 300), 255, dtype=np.uint8)  # e.g. a floor color

    _, openings = find_openings(segments, filled, filled, thickness=10)

    assert [o.kind for o in openings] == ["door"]


def test_wide_gap_is_not_an_opening() -> None:
    segments = [WallSegment("horizontal", 100, 0, 100), WallSegment("horizontal", 100, 300, 400)]

    walls, openings = find_openings(segments, _blank(200, 400), _blank(200, 400), thickness=10)

    assert openings == []
    assert walls == segments
