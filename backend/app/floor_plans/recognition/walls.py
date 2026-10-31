"""Axis-aligned wall centerline extraction from a wall mask.

Produces raw segments only. Junction splitting, IDs, and conversion to layout
models happen later in the recognition pipeline.
"""

from dataclasses import dataclass, replace
from typing import Literal

import cv2
import numpy as np

Orientation = Literal["horizontal", "vertical"]

# Shortest detectable wall, as a multiple of the wall thickness.
MIN_LENGTH_RATIO = 3
# Components thicker than this multiple of the wall thickness are filled
# regions (e.g. solid counters or shelving), not walls.
MAX_THICKNESS_RATIO = 2


@dataclass(frozen=True)
class WallSegment:
    """Wall centerline in pixels; ``offset`` is y when horizontal, x when vertical."""

    orientation: Orientation
    offset: float
    start: float
    end: float

    @property
    def endpoints(self) -> tuple[tuple[float, float], tuple[float, float]]:
        if self.orientation == "horizontal":
            return (self.start, self.offset), (self.end, self.offset)
        return (self.offset, self.start), (self.offset, self.end)


def detect_walls(mask: np.ndarray, thickness: int) -> list[WallSegment]:
    """Find horizontal and vertical wall centerlines in a wall mask."""
    length = (MIN_LENGTH_RATIO * thickness) | 1  # Odd keeps the kernel centered.
    segments = [
        *_directional_segments(mask, "horizontal", length, thickness),
        *_directional_segments(mask, "vertical", length, thickness),
    ]
    segments = _merge_collinear(segments, tolerance=thickness)
    return _snap_endpoints(segments, tolerance=thickness)


def _directional_segments(
    mask: np.ndarray, orientation: Orientation, length: int, thickness: int
) -> list[WallSegment]:
    horizontal = orientation == "horizontal"
    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (length, 1) if horizontal else (1, length)
    )
    runs = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    _, _, stats, _ = cv2.connectedComponentsWithStats(runs, connectivity=8)
    segments = []
    for x, y, width, height, _ in stats[1:]:
        along_pos, along, across_pos, across = (
            (x, width, y, height) if horizontal else (y, height, x, width)
        )
        if across > MAX_THICKNESS_RATIO * thickness:
            continue
        segments.append(
            WallSegment(
                orientation=orientation,
                offset=float(across_pos + (across - 1) / 2),
                start=float(along_pos),
                end=float(along_pos + along - 1),
            )
        )
    return segments


def _merge_collinear(segments: list[WallSegment], tolerance: float) -> list[WallSegment]:
    """Align near-collinear segments and join pieces separated by small breaks.

    Gaps wider than ``tolerance`` (e.g. doorways) are kept.
    """
    merged = []
    for orientation in ("horizontal", "vertical"):
        group: list[WallSegment] = []
        for segment in sorted(
            (s for s in segments if s.orientation == orientation), key=lambda s: s.offset
        ):
            if group and segment.offset - group[-1].offset > tolerance / 2:
                merged.extend(_merge_group(group, tolerance))
                group = []
            group.append(segment)
        if group:
            merged.extend(_merge_group(group, tolerance))
    return merged


def _merge_group(group: list[WallSegment], tolerance: float) -> list[WallSegment]:
    total_length = sum(s.end - s.start for s in group)
    offset = sum(s.offset * (s.end - s.start) for s in group) / total_length
    runs: list[WallSegment] = []
    for segment in sorted(group, key=lambda s: s.start):
        if runs and segment.start - runs[-1].end <= tolerance:
            runs[-1] = replace(runs[-1], end=max(runs[-1].end, segment.end))
        else:
            runs.append(replace(segment, offset=offset))
    return runs


def _snap_endpoints(segments: list[WallSegment], tolerance: float) -> list[WallSegment]:
    """Move endpoints onto nearby perpendicular centerlines so corners meet."""
    return [
        _snap(segment, [s for s in segments if s.orientation != segment.orientation], tolerance)
        for segment in segments
    ]


def _snap(
    segment: WallSegment, perpendicular: list[WallSegment], tolerance: float
) -> WallSegment:
    def nearest(value: float) -> float:
        candidates = [
            other.offset
            for other in perpendicular
            if abs(other.offset - value) <= tolerance
            and other.start - tolerance <= segment.offset <= other.end + tolerance
        ]
        return min(candidates, key=lambda c: abs(c - value), default=value)

    return replace(segment, start=nearest(segment.start), end=nearest(segment.end))
