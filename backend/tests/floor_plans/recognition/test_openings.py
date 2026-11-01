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


def _gap_between(left_end: int, right_start: int) -> list[WallSegment]:
    return [
        WallSegment("horizontal", 150, 0, left_end),
        WallSegment("horizontal", 150, right_start, 300),
        WallSegment("vertical", 0, 0, 300),
        WallSegment("vertical", 300, 0, 300),
    ]


def test_doors_either_side_of_a_wall_are_separate() -> None:
    # A restroom door (hinged at x=140) and a stockroom door (hinged at x=160)
    # swing away from the 20 px of wall between them, where the wall between those
    # rooms meets this one.
    details = _swing(_blank(), (140, 150), 60, 180, 270)
    _swing(details, (160, 150), 60, 270, 360)

    walls, openings = find_openings(_gap_between(80, 220), _blank(), details, thickness=10)

    assert _door_spans(openings) == [(80, 140), (160, 220)]
    assert WallSegment("horizontal", 150, 0, 300) in walls


def _wall_pixels(segments: list[WallSegment], thickness: int = 10) -> np.ndarray:
    mask = _blank()
    half = thickness // 2
    for s in segments:
        (x1, y1), (x2, y2) = s.endpoints
        corners = (int(x1) - half, int(y1) - half), (int(x2) + half, int(y2) + half)
        cv2.rectangle(mask, *corners, 255, -1)
    return mask


def test_open_floor_beside_door_is_not_filled_with_wall() -> None:
    # A stockroom door (hinged at x=80) and, past its swing, an open passage with
    # no wall drawn up to x=220.
    segments = _gap_between(80, 220)
    details = _swing(_blank(), (80, 150), 50, 270, 360)

    walls, openings = find_openings(
        segments, _blank(), details, thickness=10, wall_pixels=_wall_pixels(segments)
    )

    assert _door_spans(openings) == [(80, 130)]
    door_wall = [round(w.end) for w in walls if w.orientation == "horizontal" and w.start == 0]
    assert door_wall == [130]  # ends with the door
    assert WallSegment("horizontal", 150, 220, 300) in walls


def test_door_wall_reaches_post_before_open_floor() -> None:
    # Past the door swing a post wall comes down to the line at x=150; the wall
    # runs from the door to it and only the rest (x 150-220) is open floor.
    segments = [*_gap_between(80, 220), WallSegment("vertical", 150, 155, 300)]
    details = _swing(_blank(), (80, 150), 50, 270, 360)

    walls, openings = find_openings(
        segments, _blank(), details, thickness=10, wall_pixels=_wall_pixels(segments)
    )

    assert _door_spans(openings) == [(80, 130)]
    assert WallSegment("horizontal", 150, 0, 150) in walls
    assert WallSegment("horizontal", 150, 220, 300) in walls


def test_wall_drawn_beside_door_still_fills_the_gap() -> None:
    # Same door, but wall is drawn past its swing (too faint for wall detection).
    segments = _gap_between(80, 220)
    details = _swing(_blank(), (80, 150), 50, 270, 360)
    wall_pixels = _wall_pixels([*segments, WallSegment("horizontal", 150, 130, 220)])

    walls, _ = find_openings(segments, _blank(), details, thickness=10, wall_pixels=wall_pixels)

    assert WallSegment("horizontal", 150, 0, 300) in walls


def test_double_door_leaves_meeting_in_the_middle_are_one_door() -> None:
    # Two leaves hinged at the gap ends; a few pixels between their tips.
    details = _swing(_blank(), (80, 150), 66, 270, 360)
    _swing(details, (220, 150), 66, 180, 270)

    _, openings = find_openings(_gap_between(80, 220), _blank(), details, thickness=10)

    assert _door_spans(openings) == [(80, 220)]


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


def test_storefront_window_beside_entrance_in_one_gap() -> None:
    # A storefront wall stops at x=100; the next wall is at x=240. The gap holds a
    # window (x=100-160) and the entrance door (x=180-240) with no wall between.
    segments = [
        WallSegment("horizontal", 100, 0, 100),
        WallSegment("vertical", 0, 0, 300),
        WallSegment("vertical", 240, 0, 300),
    ]
    lines = _blank()
    lines[97, 100:161] = 255  # glazing
    lines[103, 100:161] = 255
    details = _swing(_blank(), (180, 100), 60, 0, 90)

    _, openings = find_openings(segments, lines, details, thickness=10)

    found = sorted((o.kind, o.span.start, o.span.end) for o in openings)
    expected = [("door", 180, 240), ("window", 100, 180)]
    assert [kind for kind, *_ in found] == [kind for kind, *_ in expected]
    assert all(
        abs(a - b) <= 2 for (_, *got), (_, *want) in zip(found, expected) for a, b in zip(got, want)
    )


def test_dashed_swing_arc_is_a_door() -> None:
    # CAD exports often draw the swing as a dashed arc: 6 px dashes, 3 px breaks.
    segments = [
        WallSegment("horizontal", 100, 0, 200),
        WallSegment("vertical", 0, 0, 300),
        WallSegment("vertical", 260, 0, 300),
    ]
    details = _blank()
    for start in range(0, 90, 9):
        _swing(details, (200, 100), 60, start, start + 6)

    _, openings = find_openings(segments, _blank(), details, thickness=10)

    assert _door_spans(openings) == [(200, 260)]


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


def test_gap_without_symbol_stays_open_floor() -> None:
    # Two wall ends face each other across a door-sized gap with nothing drawn in
    # it, e.g. an open-plan sales floor: open floor, not a doorway.
    segments = [
        WallSegment("horizontal", 100, 0, 100),
        WallSegment("vertical", 100, 0, 100),
        WallSegment("horizontal", 100, 160, 300),
        WallSegment("vertical", 160, 100, 200),
    ]

    walls, openings = find_openings(segments, _blank(), _blank(), thickness=10)

    assert openings == []
    assert sorted(walls, key=repr) == sorted(segments, key=repr)


def test_half_open_door_leaf_is_a_door() -> None:
    # A stockroom door drawn half open: its leaf (a thin double line) runs from the
    # hinge at x=180 at 40 degrees, as long as the 100 px gap, with no usable arc.
    lines = _blank()
    tip = (round(180 - 100 * np.cos(np.radians(40))), round(150 - 100 * np.sin(np.radians(40))))
    cv2.line(lines, (180, 150), tip, 255, 1)
    cv2.line(lines, (183, 150), (tip[0] + 3, tip[1]), 255, 1)

    walls, openings = find_openings(_gap_between(80, 180), lines, _blank(), thickness=10)

    assert [(o.kind, o.span) for o in openings] == [
        ("door", WallSegment("horizontal", 150, 80, 180))
    ]


def test_counter_edge_at_gap_end_is_not_a_door_leaf() -> None:
    # A counter edge leaves the wall end square to it: not a door leaf.
    lines = _blank()
    cv2.line(lines, (180, 150), (180, 60), 255, 1)

    _, openings = find_openings(_gap_between(80, 180), lines, _blank(), thickness=10)

    assert openings == []


def test_dashed_lines_across_gap_are_open_floor() -> None:
    # Two dashed lines across the gap mark an open passage, not a window.
    lines = _blank()
    for x in range(80, 180, 20):
        cv2.line(lines, (x, 147), (x + 13, 147), 255, 1)
        cv2.line(lines, (x, 153), (x + 13, 153), 255, 1)

    _, openings = find_openings(_gap_between(80, 180), lines, _blank(), thickness=10)

    assert openings == []


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


def test_window_frame_wider_than_wall_is_a_window() -> None:
    # 10 px walls; the window frame lines sit 7 px either side of the wall line,
    # just outside the wall itself.
    segments = [WallSegment("horizontal", 100, 0, 100), WallSegment("horizontal", 100, 160, 300)]
    lines = _blank(200)
    lines[93, 100:161] = 255
    lines[107, 100:161] = 255

    _, openings = find_openings(segments, lines, _blank(200), thickness=10)

    assert [o.kind for o in openings] == ["window"]


def test_glass_wall_longer_than_a_door_is_a_window() -> None:
    # 180 px of glazing on a 400 px image: wider than any door (150 px here) but a
    # plausible shopfront glass wall.
    segments = [WallSegment("horizontal", 100, 0, 100), WallSegment("horizontal", 100, 280, 400)]
    lines = _blank(200, 400)
    lines[97, 100:281] = 255
    lines[103, 100:281] = 255

    _, openings = find_openings(segments, lines, _blank(200, 400), thickness=10)

    assert [(o.kind, o.span.start, o.span.end) for o in openings] == [("window", 100, 280)]


def test_wide_gap_without_symbol_is_not_bridged() -> None:
    segments = [WallSegment("horizontal", 100, 0, 100), WallSegment("horizontal", 100, 220, 600)]

    walls, openings = find_openings(segments, _blank(200, 600), _blank(200, 600), thickness=5)

    assert openings == []
    assert walls == segments


def test_single_threshold_line_is_not_a_window() -> None:
    segments = [WallSegment("horizontal", 100, 0, 100), WallSegment("horizontal", 100, 160, 300)]
    lines = _blank(200)
    lines[100, 100:161] = 255  # one line across the gap

    _, openings = find_openings(segments, lines, _blank(200), thickness=10)

    assert openings == []  # no arc and no glazing: open floor


def test_floor_color_edges_are_not_glazing() -> None:
    # Two bands wider than glazing lines, e.g. where floor colors meet a doorway strip.
    segments = [WallSegment("horizontal", 100, 0, 100), WallSegment("horizontal", 100, 160, 300)]
    lines = _blank(200)
    lines[94:100, 100:161] = 255
    lines[101:107, 100:161] = 255

    _, openings = find_openings(segments, lines, _blank(200), thickness=10)

    assert openings == []  # no arc and no glazing: open floor


def test_filled_gap_is_not_a_window() -> None:
    segments = [WallSegment("horizontal", 100, 0, 100), WallSegment("horizontal", 100, 160, 300)]
    filled = np.full((200, 300), 255, dtype=np.uint8)  # e.g. a floor color

    _, openings = find_openings(segments, filled, filled, thickness=10)

    assert openings == []  # no arc and no glazing: open floor


def test_wide_gap_is_not_an_opening() -> None:
    segments = [WallSegment("horizontal", 100, 0, 100), WallSegment("horizontal", 100, 300, 400)]

    walls, openings = find_openings(segments, _blank(200, 400), _blank(200, 400), thickness=10)

    assert openings == []
    assert walls == segments


def test_small_glazed_gap_is_a_window() -> None:
    # A 25 px restroom window (2.5 wall thicknesses) with two glazing lines.
    lines = _blank()
    for y in (146, 154):
        cv2.line(lines, (80, y), (105, y), 255, 1)

    walls, openings = find_openings(_gap_between(80, 105), lines, _blank(), thickness=10)

    assert [(o.kind, o.span.start, o.span.end) for o in openings] == [("window", 80, 105)]
    assert WallSegment("horizontal", 150, 0, 300) in walls


def test_small_gap_without_glazing_stays_open() -> None:
    walls, openings = find_openings(_gap_between(80, 105), _blank(), _blank(), thickness=10)

    assert not openings
    assert WallSegment("horizontal", 150, 0, 80) in walls
