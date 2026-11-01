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
# Shorter pieces down to this multiple are kept only when they meet a longer
# perpendicular wall: corner returns beside windows and jambs beside doors.
# Free-standing short blocks (display stands, counters) are still ignored.
MIN_STUB_LENGTH_RATIO = 1
# Short pieces on a longer wall's line, within this many wall thicknesses of its
# end, are also kept: wall between two openings (e.g. between a window and a
# door). So are short pieces with a wall across their line this close on both
# sides (e.g. between two windows of a bay). They only join the walls if the
# openings between them are found.
MAX_STUB_GAP_RATIO = 15
# A piece whose ends would both snap onto one crossing wall is that wall's own
# width and is dropped, unless it is at least this many thicknesses long: then it
# is a short wall crossing it (e.g. where a partition meets the outer wall between
# two windows) and keeps its drawn ends.
MIN_CROSSING_PIECE_RATIO = 1.5
# After corners are snapped, pieces shorter than this multiple of the thickness
# are leftovers of a wall's own width (e.g. anti-aliased edges), not walls.
MIN_PIECE_RATIO = 0.5
# Components thicker than this multiple of the wall thickness are filled
# regions (e.g. solid counters or shelving), not walls.
MAX_THICKNESS_RATIO = 2
# Segments closer than this (px) are considered connected.
TOUCH_TOLERANCE_PX = 0.5


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

    def touches(self, other: "WallSegment") -> bool:
        """Whether the segments meet, overlap, or cross (within TOUCH_TOLERANCE_PX)."""
        eps = TOUCH_TOLERANCE_PX
        if self.orientation == other.orientation:
            return (
                abs(self.offset - other.offset) <= eps
                and self.start <= other.end + eps
                and other.start <= self.end + eps
            )
        return (
            self.start - eps <= other.offset <= self.end + eps
            and other.start - eps <= self.offset <= other.end + eps
        )


def detect_walls(mask: np.ndarray, thickness: int) -> list[WallSegment]:
    """Find horizontal and vertical wall centerlines in a wall mask."""
    walls = _merge_collinear(
        _segments(mask, MIN_LENGTH_RATIO * thickness, thickness), tolerance=thickness
    )
    # Just longer than the thickness, so a wall's usual width never reads as a stub.
    stub_length = MIN_STUB_LENGTH_RATIO * thickness + 1
    stubs = [
        stub
        for stub in _stub_segments(mask, stub_length, thickness)
        if (_meets_perpendicular(stub, walls, thickness) or _on_wall_line(stub, walls, thickness))
        and not _is_covered(stub, walls, thickness)
    ]
    segments = _merge_collinear(walls + stubs, tolerance=thickness)
    return snap_corners(segments, thickness)


def snap_corners(segments: list[WallSegment], thickness: int) -> list[WallSegment]:
    """Move wall ends onto nearby perpendicular walls so corners meet, then drop
    pieces that collapse to (almost) nothing.

    Run again after openings are bridged: walls completed by bridging (e.g. a
    storefront with windows near both corners) only then reach their corners.
    """
    snapped = _snap_endpoints(segments, tolerance=thickness)
    return [s for s in snapped if s.end - s.start >= MIN_PIECE_RATIO * thickness]


def _segments(mask: np.ndarray, length: int, thickness: int) -> list[WallSegment]:
    length |= 1  # Odd keeps the kernel centered.
    return [
        *_directional_segments(mask, "horizontal", length, thickness),
        *_directional_segments(mask, "vertical", length, thickness),
    ]


def _stub_segments(mask: np.ndarray, length: int, thickness: int) -> list[WallSegment]:
    """Short pieces, also looked for with the long walls across them removed.

    A wall thicker than the short kernel (e.g. a 12 px outer wall with a 10 px
    estimate) passes the kernel too and joins a corner piece into one tall blob,
    which is dropped as too thick; without the crossing wall the piece is found.
    """
    length |= 1
    long_length = (MIN_LENGTH_RATIO * thickness) | 1
    segments = _segments(mask, length, thickness)
    for orientation, across in (("horizontal", (1, long_length)), ("vertical", (long_length, 1))):
        crossing = cv2.morphologyEx(
            mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, across)
        )
        segments += _directional_segments(
            cv2.subtract(mask, crossing), orientation, length, thickness
        )
    return segments


def _meets_perpendicular(
    stub: WallSegment, walls: list[WallSegment], tolerance: float
) -> bool:
    return any(
        wall.orientation != stub.orientation
        and wall.start - tolerance <= stub.offset <= wall.end + tolerance
        and stub.start - tolerance <= wall.offset <= stub.end + tolerance
        for wall in walls
    )


def _on_wall_line(stub: WallSegment, walls: list[WallSegment], thickness: float) -> bool:
    """Whether a longer wall lies on the stub's line, or walls cross its line on
    both sides, within MAX_STUB_GAP_RATIO thicknesses."""
    reach = MAX_STUB_GAP_RATIO * thickness
    if any(
        wall.orientation == stub.orientation
        and abs(wall.offset - stub.offset) <= thickness / 2
        and wall.start - reach <= stub.end
        and stub.start <= wall.end + reach
        for wall in walls
    ):
        return True
    crossing = [
        wall.offset
        for wall in walls
        if wall.orientation != stub.orientation
        and wall.start - thickness <= stub.offset <= wall.end + thickness
    ]
    return any(0 <= stub.start - c <= reach for c in crossing) and any(
        0 <= c - stub.end <= reach for c in crossing
    )


def _is_covered(stub: WallSegment, walls: list[WallSegment], tolerance: float) -> bool:
    """Whether a longer collinear wall already spans the stub."""
    return any(
        wall.orientation == stub.orientation
        and abs(wall.offset - stub.offset) <= tolerance / 2
        and wall.start - tolerance <= stub.start
        and stub.end <= wall.end + tolerance
        for wall in walls
    )


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

    start, end = nearest(segment.start), nearest(segment.end)
    if start == end and segment.end - segment.start >= MIN_CROSSING_PIECE_RATIO * tolerance:
        return segment
    return replace(segment, start=start, end=end)
