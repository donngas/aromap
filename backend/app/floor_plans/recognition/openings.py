"""Door and window detection from gaps in wall centerlines.

Walls span their openings, so each accepted gap is bridged with wall and
recorded as a door or window on that wall.
"""

from dataclasses import dataclass, replace
from typing import Literal

import cv2
import numpy as np

from app.floor_plans.recognition.walls import TOUCH_TOLERANCE_PX, WallSegment

# Opening widths as multiples of the wall thickness: roughly 0.6-3 m for
# 0.2 m walls, covering single doors up to wide shop entrances. A gap of this
# size between two aligned wall pieces is bridged even without a door or window
# symbol.
MIN_OPENING_RATIO = 3
MAX_OPENING_RATIO = 15
# Plans with thin-drawn walls make real openings look too wide relative to the
# wall, so gaps up to this fraction of the image's long side are also bridged,
# but only when a door arc or window glazing confirms them.
MAX_OPENING_IMAGE_RATIO = 0.25
# A door swing arc is a quarter circle centered on a hinge, reaching the far end
# of the gap (single door) or the middle of it (double door). The hinge may sit
# up to this fraction of the gap inside its end, e.g. on a short wall stub.
MAX_HINGE_INSET_RATIO = 0.3
# The arc is found when this fraction of points sampled along it are strokes...
ARC_COVERAGE = 0.7
# ...while smaller rings inside it, where the door swings, are at most this
# covered. Cluttered areas and textured floors therefore do not count as arcs.
MAX_SWING_AREA_COVERAGE = 0.15
ARC_INNER_RATIOS = (0.45, 0.7)
# Sampled arc angles (degrees from the wall), avoiding the wall line itself and
# the door leaf drawn perpendicular to it.
ARC_ANGLES = np.radians(np.linspace(20, 80, 16))
# A line along the gap counts as window glazing when this fraction of it is dark.
GLAZING_LINE_COVERAGE = 0.6
# Windows are drawn with at least this many separate parallel lines; a single
# line across a gap is usually a door threshold.
MIN_GLAZING_LINES = 2
# Glazing is a few thin lines; if more of the band than this is covered, it is a
# filled area (e.g. a floor color) rather than a window.
MAX_GLAZING_LINE_FRACTION = 0.7
# Each glazing line (or tight group of lines) is at most this fraction of the wall
# thickness (minimum 3 px); wider bands are edges between floor colors, not glass.
MAX_GLAZING_LINE_WIDTH_RATIO = 1 / 2

OpeningKind = Literal["door", "window"]


@dataclass(frozen=True)
class Opening:
    kind: OpeningKind
    span: WallSegment


def find_openings(
    segments: list[WallSegment], lines: np.ndarray, details: np.ndarray, thickness: int
) -> tuple[list[WallSegment], list[Opening]]:
    """Bridge door/window-sized gaps and return the bridged walls with openings.

    Gaps are found between collinear wall pieces and between a free wall end and
    the next perpendicular wall. A wall end often just stops in an open room, so
    those gaps, like unusually wide ones, need a door arc or window glazing to be
    bridged. Isolated segments are bridged only when both ends reach walls, so
    stray equipment or fixture drawings stay detached and can be dropped later.
    ``lines`` (dark lines of any shade) reveals glazing; ``details`` (strokes in
    any color) reveals door arcs.
    """
    symbols = _Symbols(lines, details, thickness)
    min_gap = MIN_OPENING_RATIO * thickness
    plain_gap = MAX_OPENING_RATIO * thickness
    max_gap = max(plain_gap, MAX_OPENING_IMAGE_RATIO * max(lines.shape))
    walls, openings = _bridge_collinear_gaps(segments, min_gap, plain_gap, max_gap, symbols)
    walls, end_openings = _bridge_gaps_to_walls(walls, min_gap, max_gap, symbols)
    return walls, openings + end_openings


class _Symbols:
    """Classifies gaps by the door or window symbol drawn in them."""

    def __init__(self, lines: np.ndarray, details: np.ndarray, thickness: int) -> None:
        self.lines = lines
        # Slightly thickened strokes tolerate arcs drawn a pixel off their path.
        self.strokes = cv2.dilate(details, np.ones((3, 3), np.uint8))
        self.thickness = thickness

    def find(self, gap: WallSegment) -> OpeningKind | None:
        """Door for a swing arc, window for glazing lines, None for no symbol."""
        if _has_swing_arc(self.strokes, gap):
            return "door"
        if _has_glazing(self.lines, gap, self.thickness):
            return "window"
        return None


def _bridge_collinear_gaps(
    segments: list[WallSegment],
    min_gap: float,
    plain_gap: float,
    max_gap: float,
    symbols: _Symbols,
) -> tuple[list[WallSegment], list[Opening]]:
    lines: dict[tuple[str, float], list[WallSegment]] = {}
    for segment in segments:
        lines.setdefault((segment.orientation, segment.offset), []).append(segment)

    walls, openings = [], []
    for line in lines.values():
        line.sort(key=lambda s: s.start)
        current = line[0]
        for segment in line[1:]:
            width = segment.start - current.end
            gap = replace(current, start=current.end, end=segment.start)
            kind = symbols.find(gap) if min_gap <= width <= max_gap else None
            if kind is None and min_gap <= width <= plain_gap:
                kind = "door"  # A plain gap between aligned walls is a doorway.
            if kind is not None:
                openings.append(Opening(kind, gap))
                current = replace(current, end=segment.end)
            else:
                walls.append(current)
                current = segment
        walls.append(current)
    return walls, openings


def _bridge_gaps_to_walls(
    segments: list[WallSegment], min_gap: float, max_gap: float, symbols: _Symbols
) -> tuple[list[WallSegment], list[Opening]]:
    walls, openings = [], []
    for segment in segments:
        perpendicular = [s for s in segments if s.orientation != segment.orientation]
        collinear = [
            s for s in segments if s is not segment and s.orientation == segment.orientation
        ]
        bridged, segment_openings = segment, []
        for side, direction in (("start", -1), ("end", 1)):
            value = getattr(segment, side)
            if _touches(value, segment.offset, perpendicular):
                continue
            target = _nearest_crossing(value, direction, segment.offset, perpendicular)
            if target is None or not min_gap <= abs(target - value) <= max_gap:
                continue
            gap = replace(segment, start=min(value, target), end=max(value, target))
            if any(_overlaps(gap, other) for other in collinear):
                continue
            kind = symbols.find(gap)
            if kind is None:
                continue
            segment_openings.append(Opening(kind, gap))
            bridged = replace(bridged, **{side: target})
        # An isolated piece is a wall between two openings only if both ends reach
        # walls; bridging just one end would attach stray drawings such as equipment.
        isolated = not any(segment.touches(other) for other in segments if other is not segment)
        if isolated and len(segment_openings) < 2:
            walls.append(segment)
            continue
        walls.append(bridged)
        openings.extend(segment_openings)
    return walls, openings


def _touches(value: float, offset: float, perpendicular: list[WallSegment]) -> bool:
    return any(
        abs(other.offset - value) <= TOUCH_TOLERANCE_PX and other.start <= offset <= other.end
        for other in perpendicular
    )


def _nearest_crossing(
    value: float, direction: int, offset: float, perpendicular: list[WallSegment]
) -> float | None:
    ahead = [
        other.offset
        for other in perpendicular
        if other.start <= offset <= other.end and direction * (other.offset - value) > 0
    ]
    return min(ahead, key=lambda c: abs(c - value), default=None)


def _overlaps(gap: WallSegment, other: WallSegment) -> bool:
    return (
        abs(other.offset - gap.offset) <= TOUCH_TOLERANCE_PX
        and other.start < gap.end
        and gap.start < other.end
    )


def _has_swing_arc(strokes: np.ndarray, gap: WallSegment) -> bool:
    width = gap.end - gap.start
    single = max(
        _arc_score(strokes, gap, end + direction * inset, direction, width - inset)
        for end, direction in ((gap.start, 1), (gap.end, -1))
        for inset in np.linspace(0, MAX_HINGE_INSET_RATIO * width, 7)
    )
    double = min(
        _arc_score(strokes, gap, gap.start, 1, width / 2),
        _arc_score(strokes, gap, gap.end, -1, width / 2),
    )
    return max(single, double) >= ARC_COVERAGE


def _arc_score(
    strokes: np.ndarray, gap: WallSegment, hinge: float, toward_gap: int, radius: float
) -> float:
    """Best arc coverage over both wall sides, or 0 where the swing area is not empty."""
    best = 0.0
    for side in (1, -1):
        swing_area = max(
            _coverage(strokes, gap, hinge, toward_gap, side, radius * ratio)
            for ratio in ARC_INNER_RATIOS
        )
        if swing_area <= MAX_SWING_AREA_COVERAGE:
            best = max(best, _coverage(strokes, gap, hinge, toward_gap, side, radius))
    return best


def _coverage(
    strokes: np.ndarray,
    gap: WallSegment,
    hinge: float,
    toward_gap: int,
    side: int,
    radius: float,
) -> float:
    along = np.rint(hinge + toward_gap * radius * np.cos(ARC_ANGLES)).astype(int)
    across = np.rint(gap.offset + side * radius * np.sin(ARC_ANGLES)).astype(int)
    xs, ys = (along, across) if gap.orientation == "horizontal" else (across, along)
    height, width = strokes.shape
    inside = (xs >= 0) & (xs < width) & (ys >= 0) & (ys < height)
    hits = np.zeros(len(xs), dtype=bool)
    hits[inside] = strokes[ys[inside], xs[inside]] > 0
    return float(hits.mean())


def _has_glazing(lines: np.ndarray, gap: WallSegment, thickness: int) -> bool:
    # Glazing lies within the wall's own thickness; looking further would pick up
    # edges of the floor colors on either side.
    half = thickness / 2 + 1
    across = slice(max(0, round(gap.offset - half)), round(gap.offset + half) + 1)
    along = slice(int(gap.start) + 1, int(gap.end))
    if gap.orientation == "horizontal":
        band = lines[across, along]
    else:
        band = lines[along, across].T
    if band.size == 0:
        return False
    covered = (band > 0).mean(axis=1) >= GLAZING_LINE_COVERAGE
    if covered.mean() > MAX_GLAZING_LINE_FRACTION:
        return False
    # Separate lines are runs of consecutive covered rows.
    edges = np.flatnonzero(np.diff(np.concatenate(([0], covered.astype(int), [0]))))
    widths = edges[1::2] - edges[::2]
    max_width = max(3, thickness * MAX_GLAZING_LINE_WIDTH_RATIO)
    return len(widths) >= MIN_GLAZING_LINES and bool((widths <= max_width).all())
