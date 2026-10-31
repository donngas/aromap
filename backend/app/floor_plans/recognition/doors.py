"""Door swing detection: find quarter-circle arcs, then read each door from its arc.

The supported door symbol is a swing arc: a quarter circle centered on the hinge,
with the door width as its radius (see backend README). Arcs are found once per
image, independent of wall gaps, so a hinge on a short wall stub or an arc that
stops at a door frame needs no special handling.
"""

from dataclasses import dataclass

import cv2
import numpy as np

from app.floor_plans.recognition.walls import WallSegment

# A swing arc covers about a quarter turn; full circles (round tables, stools)
# and short curves (chair backs, text) fall outside this range.
MIN_ARC_SPAN_DEG = 45
MAX_ARC_SPAN_DEG = 120
# Arc points stay within this fraction of the radius from the fitted circle.
MAX_ARC_FIT_ERROR = 0.06
# Door widths, as multiples of the wall thickness; the upper bound is a fraction
# of the image's long side, matching the widest openings bridged elsewhere.
MIN_DOOR_RATIO = 2
# Straight runs at least this long (px, and at least the wall thickness) are
# door leaves, thresholds, or furniture edges, removed before fitting arcs.
MIN_STRAIGHT_RUN_PX = 9
# An arc belongs to a gap when its hinge lies within one wall thickness of the
# gap's wall line and at least this fraction of its swing lies inside the gap.
MIN_SWING_IN_GAP = 0.6


@dataclass(frozen=True)
class DoorArc:
    """A swing arc: hinge (circle center) in pixels, radius, and the quadrant the
    arc lies in (sign of x and y relative to the hinge)."""

    hinge_x: float
    hinge_y: float
    radius: float
    sign_x: int
    sign_y: int


def find_door_arcs(
    strokes: np.ndarray, wall_pixels: np.ndarray | None, thickness: int, max_radius: float
) -> list[DoorArc]:
    """Quarter-circle arcs of door size among thin strokes, away from the walls."""
    curves = (strokes > 0).astype(np.uint8) * 255
    if wall_pixels is not None:
        curves[cv2.dilate(wall_pixels, np.ones((5, 5), np.uint8)) > 0] = 0
    straight = cv2.dilate(_straight_runs(curves, thickness), np.ones((3, 3), np.uint8))
    curves = cv2.subtract(curves, straight)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(curves, connectivity=8)
    min_radius = MIN_DOOR_RATIO * thickness
    arcs = []
    for label in range(1, count):
        x, y, width, height, _ = stats[label]
        if max(width, height) < min_radius / 2:
            continue
        ys, xs = np.nonzero(labels[y : y + height, x : x + width] == label)
        arc = _fit_arc(xs + x, ys + y)
        if arc is not None and min_radius <= arc.radius <= max_radius:
            arcs.append(arc)
    return arcs


def swing_spans(
    arcs: list[DoorArc], gap: WallSegment, thickness: int
) -> list[tuple[float, float]]:
    """Spans along the gap's wall line swept by arcs hinged on that line."""
    spans = []
    for arc in arcs:
        if gap.orientation == "horizontal":
            offset, hinge, direction = arc.hinge_y, arc.hinge_x, arc.sign_x
        else:
            offset, hinge, direction = arc.hinge_x, arc.hinge_y, arc.sign_y
        if abs(offset - gap.offset) > thickness or direction == 0:
            continue
        start, end = sorted((hinge, hinge + direction * arc.radius))
        if min(end, gap.end) - max(start, gap.start) >= MIN_SWING_IN_GAP * (end - start):
            spans.append((max(start, gap.start), min(end, gap.end)))
    return spans


def _straight_runs(mask: np.ndarray, thickness: int) -> np.ndarray:
    length = max(MIN_STRAIGHT_RUN_PX, thickness) | 1
    runs = [
        cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, size))
        for size in ((length, 1), (1, length))
    ]
    return cv2.bitwise_or(*runs)


def _fit_arc(xs: np.ndarray, ys: np.ndarray) -> DoorArc | None:
    """Least-squares circle through the points, if they form a quarter arc."""
    if len(xs) < 8:
        return None
    # x^2 + y^2 = 2ax + 2by + c, linear in (a, b, c); radius^2 = c + a^2 + b^2.
    design = np.column_stack([2 * xs, 2 * ys, np.ones(len(xs))])
    (cx, cy, c), *_ = np.linalg.lstsq(design, xs**2 + ys**2, rcond=None)
    radius_sq = c + cx**2 + cy**2
    if radius_sq <= 0:
        return None
    radius = float(np.sqrt(radius_sq))
    distances = np.hypot(xs - cx, ys - cy)
    if np.sqrt(np.mean((distances - radius) ** 2)) > MAX_ARC_FIT_ERROR * radius:
        return None
    if not MIN_ARC_SPAN_DEG <= _angular_span(np.arctan2(ys - cy, xs - cx)) <= MAX_ARC_SPAN_DEG:
        return None
    sign_x = int(np.sign(np.mean(xs - cx)))
    sign_y = int(np.sign(np.mean(ys - cy)))
    return DoorArc(float(cx), float(cy), radius, sign_x, sign_y)


def _angular_span(angles: np.ndarray) -> float:
    """Degrees covered by the angles: a full turn minus the widest empty gap."""
    ordered = np.sort(np.degrees(angles) % 360)
    gaps = np.diff(np.concatenate([ordered, [ordered[0] + 360]]))
    return float(360 - gaps.max())
