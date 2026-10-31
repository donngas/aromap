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
