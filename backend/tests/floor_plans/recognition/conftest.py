import cv2
import numpy as np
import pytest

WALL_COLOR = (30, 30, 30)
WOOD_FLOOR = (120, 170, 210)  # BGR, grayscale ~176
TILE_FLOOR = (200, 200, 190)


@pytest.fixture
def shop_plan() -> np.ndarray:
    """A sales floor and a stockroom in a 600x400 image, mimicking a shop plan.

    Wall centerlines: outer rectangle at x=50/550 and y=50/350, and an interior
    wall at x=300 with a doorway between y=170 and y=230. Walls are 11 px thick.
    """
    image = np.full((400, 600, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (55, 55), (295, 345), WOOD_FLOOR, cv2.FILLED)
    cv2.rectangle(image, (305, 55), (545, 345), TILE_FLOOR, cv2.FILLED)

    for top_left, bottom_right in [
        ((45, 45), (555, 55)),  # top
        ((45, 345), (555, 355)),  # bottom
        ((45, 45), (55, 355)),  # left
        ((545, 45), (555, 355)),  # right
        ((295, 45), (305, 170)),  # interior, above doorway
        ((295, 230), (305, 355)),  # interior, below doorway
    ]:
        cv2.rectangle(image, top_left, bottom_right, WALL_COLOR, cv2.FILLED)

    # Thin dark details that must not become walls.
    cv2.rectangle(image, (90, 90), (220, 170), (70, 70, 70), 2)  # shelf outline
    cv2.circle(image, (420, 260), 30, (70, 70, 70), 2)  # display table
    cv2.putText(image, "SALES", (100, 260), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
    cv2.putText(image, "STORAGE", (340, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2)
    cv2.line(image, (50, 25), (550, 25), (0, 0, 0), 1)  # dimension line
    return image


def _walls(image: np.ndarray, rects, color=WALL_COLOR) -> None:
    for top_left, bottom_right in rects:
        cv2.rectangle(image, top_left, bottom_right, color, cv2.FILLED)


def _swing(image: np.ndarray, hinge, radius: int, start: int, end: int, color, width=1) -> None:
    """Quarter-circle door swing; angles in degrees, clockwise from +x."""
    cv2.ellipse(image, hinge, (radius, radius), 0, start, end, color, width)


@pytest.fixture
def cad_shop_plan() -> np.ndarray:
    """CAD-style shop in an 800x600 image: black 11 px walls on white.

    Wall centerlines: outer rectangle at x=60/740 and y=60/540, and an interior
    wall at x=400 with a plain doorway between y=260 and y=330. The top wall has
    a window (x=150-250) drawn as two gray glazing lines; the bottom wall has a
    back door (x=500-570) with a single gray threshold line and a gray swing arc.
    A stray dark stub with circles near the right wall mimics an equipment drawing.
    """
    image = np.full((600, 800, 3), 255, dtype=np.uint8)
    _walls(
        image,
        [
            ((55, 55), (150, 65)),  # top, left of window
            ((250, 55), (745, 65)),  # top, right of window
            ((55, 535), (500, 545)),  # bottom, left of back door
            ((570, 535), (745, 545)),  # bottom, right of back door
            ((55, 55), (65, 545)),  # left
            ((735, 55), (745, 545)),  # right
            ((395, 55), (405, 260)),  # interior, above doorway
            ((395, 330), (405, 545)),  # interior, below doorway
        ],
    )
    gray = (160, 160, 160)
    cv2.line(image, (150, 57), (250, 57), gray, 1)  # window glazing
    cv2.line(image, (150, 63), (250, 63), gray, 1)
    cv2.line(image, (500, 540), (570, 540), gray, 1)  # back door threshold
    _swing(image, (500, 540), 70, 270, 360, gray)
    cv2.rectangle(image, (600, 195), (650, 205), WALL_COLOR, cv2.FILLED)  # equipment
    cv2.circle(image, (620, 230), 15, (60, 60, 60), 2)
    cv2.circle(image, (660, 230), 10, (60, 60, 60), 2)
    return image


@pytest.fixture
def colored_shop_plan() -> np.ndarray:
    """Colored shop in a 650x460 image: thin 5 px walls, floor colors, pink symbols.

    Wall centerlines: outer rectangle at x=40/610 and y=40/420, an interior wall
    at x=300, and a partition at y=230 between x=300 and x=610. Doors have pink
    frame lines across the gap plus a pink swing arc: x=300, y=100-140 and y=230,
    x=450-490. Windows have pink frame lines only: top wall x=100-200, and bottom
    wall x=340-500 (32x the wall thickness).
    """
    image = np.full((460, 650, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (40, 40), (300, 420), (120, 180, 250), cv2.FILLED)  # orange
    cv2.rectangle(image, (300, 40), (610, 230), (170, 200, 215), cv2.FILLED)  # wood
    cv2.rectangle(image, (300, 230), (610, 420), (150, 200, 190), cv2.FILLED)  # olive
    _walls(
        image,
        [
            ((38, 38), (100, 42)),  # top, left of window
            ((200, 38), (612, 42)),  # top, right of window
            ((38, 418), (340, 422)),  # bottom, left of wide window
            ((500, 418), (612, 422)),  # bottom, right of wide window
            ((38, 38), (42, 422)),  # left
            ((608, 38), (612, 422)),  # right
            ((298, 38), (302, 100)),  # interior, above door
            ((298, 140), (302, 422)),  # interior, below door
            ((298, 228), (450, 232)),  # partition, left of door
            ((490, 228), (612, 232)),  # partition, right of door
        ],
    )
    pink = (155, 144, 240)
    for top_left, bottom_right in [((100, 38), (200, 42)), ((340, 418), (500, 422))]:
        cv2.rectangle(image, top_left, bottom_right, (255, 255, 255), cv2.FILLED)  # glass
    for start, end in [((100, 38), (200, 38)), ((100, 42), (200, 42)),  # window
                       ((340, 418), (500, 418)), ((340, 422), (500, 422)),  # wide window
                       ((298, 100), (298, 140)), ((302, 100), (302, 140)),  # door frames
                       ((450, 228), (490, 228)), ((450, 232), (490, 232))]:
        cv2.line(image, start, end, pink, 1)
    _swing(image, (300, 100), 40, 0, 90, pink)
    _swing(image, (450, 230), 40, 0, 90, pink)
    return image


@pytest.fixture
def hollow_line_plan() -> np.ndarray:
    """Line drawing in a 500x500 image: walls are two thin gray lines 7 px apart.

    Outer wall faces at 50/450 and 57/443; an interior wall with faces at x=247
    and x=254 has a door between y=200 and y=260, with capped wall ends and a
    swing arc.
    """
    image = np.full((500, 500, 3), 255, dtype=np.uint8)
    gray = (140, 140, 140)
    cv2.rectangle(image, (50, 50), (450, 450), gray, 1)
    cv2.rectangle(image, (57, 57), (443, 443), gray, 1)
    for x in (247, 254):
        cv2.line(image, (x, 57), (x, 200), gray, 1)
        cv2.line(image, (x, 260), (x, 443), gray, 1)
    cv2.line(image, (247, 200), (254, 200), gray, 1)  # wall end caps
    cv2.line(image, (247, 260), (254, 260), gray, 1)
    _swing(image, (254, 200), 60, 0, 90, gray)
    cv2.putText(image, "SALES", (100, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.8, gray, 1)
    return image
