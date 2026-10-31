"""Door and window detection from gaps in wall centerlines.

Walls span their openings, so each accepted gap is bridged with wall and
recorded as a door or window on that wall.
"""

from dataclasses import dataclass, replace
from typing import Literal

import numpy as np

from app.floor_plans.recognition.walls import WallSegment

# Opening widths as multiples of the wall thickness: roughly 0.6-3 m for
# 0.2 m walls, covering single doors up to wide shop entrances.
MIN_OPENING_RATIO = 3
MAX_OPENING_RATIO = 15
# A line along the gap counts as window glazing when this fraction of it is dark.
GLAZING_LINE_COVERAGE = 0.6
# Endpoints closer than this (px) to a perpendicular wall are attached to it.
TOUCH_TOLERANCE_PX = 0.5

OpeningKind = Literal["door", "window"]


@dataclass(frozen=True)
class Opening:
    kind: OpeningKind
    span: WallSegment


def find_openings(
    segments: list[WallSegment], dark: np.ndarray, thickness: int
) -> tuple[list[WallSegment], list[Opening]]:
    """Bridge door/window-sized gaps and return the bridged walls with openings.

    Gaps are found between collinear wall pieces and between a free wall end and
    the next perpendicular wall. ``dark`` is the unfiltered dark-pixel mask, used
    to spot thin glazing lines that mark windows.
    """
    min_gap, max_gap = MIN_OPENING_RATIO * thickness, MAX_OPENING_RATIO * thickness
    walls, gaps = _bridge_collinear_gaps(segments, min_gap, max_gap)
    walls, end_gaps = _bridge_gaps_to_walls(walls, min_gap, max_gap)
    return walls, [Opening(_classify(dark, gap, thickness), gap) for gap in gaps + end_gaps]


def _bridge_collinear_gaps(
    segments: list[WallSegment], min_gap: float, max_gap: float
) -> tuple[list[WallSegment], list[WallSegment]]:
    lines: dict[tuple[str, float], list[WallSegment]] = {}
    for segment in segments:
        lines.setdefault((segment.orientation, segment.offset), []).append(segment)

    walls, gaps = [], []
    for line in lines.values():
        line.sort(key=lambda s: s.start)
        current = line[0]
        for segment in line[1:]:
            if min_gap <= segment.start - current.end <= max_gap:
                gaps.append(replace(current, start=current.end, end=segment.start))
                current = replace(current, end=segment.end)
            else:
                walls.append(current)
                current = segment
        walls.append(current)
    return walls, gaps


def _bridge_gaps_to_walls(
    segments: list[WallSegment], min_gap: float, max_gap: float
) -> tuple[list[WallSegment], list[WallSegment]]:
    walls, gaps = [], []
    for segment in segments:
        perpendicular = [s for s in segments if s.orientation != segment.orientation]
        collinear = [
            s for s in segments if s is not segment and s.orientation == segment.orientation
        ]
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
            gaps.append(gap)
            segment = replace(segment, **{side: target})
        walls.append(segment)
    return walls, gaps


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


def _classify(dark: np.ndarray, gap: WallSegment, thickness: int) -> OpeningKind:
    """Windows show thin glazing lines running along the gap; doors are empty."""
    across = slice(max(0, round(gap.offset - thickness)), round(gap.offset + thickness) + 1)
    along = slice(int(gap.start) + 1, int(gap.end))
    if gap.orientation == "horizontal":
        band = dark[across, along]
    else:
        band = dark[along, across].T
    if band.size == 0:
        return "door"
    coverage = (band > 0).mean(axis=1)
    return "window" if (coverage >= GLAZING_LINE_COVERAGE).any() else "door"
