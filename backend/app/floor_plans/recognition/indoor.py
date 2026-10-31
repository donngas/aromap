"""Indoor footprint estimate: one outline around everything the walls enclose.

Walls are drawn as barriers with doors and windows closed, then the outdoors is
filled in from the image edge. Everything the fill cannot reach (sales floor,
stockroom, restrooms, and the walls between them) is one indoor space, traced as
a single outline polygon. The outline follows the outer face of the outer walls.
"""

import cv2
import numpy as np

from app.floor_plans.recognition.walls import WallSegment

# The indoor space must cover at least this fraction of the box around the walls;
# less means the outer walls are not closed (a missed opening lets the outdoors in)
# or the walls belong to scattered fragments rather than one shop.
MIN_FOOTPRINT_RATIO = 0.4
# Outline corners are simplified to within this fraction of the wall thickness,
# so wall-edge noise does not add points but real corners (e.g. an L-shape) stay.
OUTLINE_TOLERANCE_RATIO = 0.5
# Barriers are drawn at least this thick (px) so thin-wall plans still seal.
MIN_BARRIER_PX = 3


def estimate_footprint(
    barriers: list[WallSegment], shape: tuple[int, int], thickness: int
) -> list[tuple[float, float]] | None:
    """Outline of the indoor space in image pixels, or None if it is not enclosed.

    ``barriers`` are the walls plus the door and window spans (treated as closed).
    """
    if not barriers:
        return None
    height, width = shape
    walls = np.zeros((height, width), np.uint8)
    line_width = max(MIN_BARRIER_PX, thickness)
    for segment in barriers:
        (x1, y1), (x2, y2) = segment.endpoints
        cv2.line(walls, (round(x1), round(y1)), (round(x2), round(y2)), 255, line_width)

    space = (~_outdoors(walls)).astype(np.uint8) * 255
    contours, _ = cv2.findContours(space, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    outline = max(contours, key=cv2.contourArea)
    x, y, box_width, box_height = cv2.boundingRect(outline)
    if cv2.contourArea(outline) < MIN_FOOTPRINT_RATIO * box_width * box_height:
        return None
    polygon = cv2.approxPolyDP(outline, OUTLINE_TOLERANCE_RATIO * line_width, closed=True)
    if len(polygon) < 3:
        return None
    return [(float(px), float(py)) for px, py in polygon[:, 0]]


def _outdoors(walls: np.ndarray) -> np.ndarray:
    """Open pixels connected to the image edge."""
    _, labels = cv2.connectedComponents((walls == 0).astype(np.uint8), connectivity=4)
    edge = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    return np.isin(labels, edge[edge > 0])
