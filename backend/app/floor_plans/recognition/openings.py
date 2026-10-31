"""Door and window detection from gaps in wall centerlines.

Walls span their openings, so each accepted gap is bridged with wall and
recorded as a door or window on that wall.
"""

from dataclasses import dataclass, replace
from typing import Literal

import numpy as np

from app.floor_plans.recognition.doors import find_door_arcs, swing_spans
from app.floor_plans.recognition.walls import TOUCH_TOLERANCE_PX, WallSegment

# Opening widths as multiples of the wall thickness: roughly 0.6-3 m for
# 0.2 m walls, covering single doors up to wide shop entrances. Only gaps with a
# door arc or window glazing are bridged (base layout format); a gap without a
# symbol is open floor, e.g. an open-plan sales floor or a passage.
MIN_OPENING_RATIO = 3
MAX_OPENING_RATIO = 15
# Plans with thin-drawn walls make real openings look too wide relative to the
# wall, so gaps up to this fraction of the image's long side are also bridged,
# but only when a door arc or window glazing confirms them.
MAX_OPENING_IMAGE_RATIO = 0.25
# Windows may be whole glass walls, so gaps up to this fraction of the image's
# long side are bridged when glazing runs along them; doors keep the limit above.
MAX_WINDOW_IMAGE_RATIO = 0.5
# A line along the gap counts as window glazing when this fraction of it is dark.
GLAZING_LINE_COVERAGE = 0.6
# Windows are drawn with at least this many separate parallel lines; a single
# line across a gap is usually a door threshold.
MIN_GLAZING_LINES = 2
# Glazing is looked for within these multiples of the wall thickness on each side
# of the wall line: first the wall itself, then a little wider for window frames
# drawn wider than the wall. The tight band comes first because on thin walls the
# wider one reaches floor-color edges.
GLAZING_BAND_RATIOS = (0.5, 0.75)
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
    segments: list[WallSegment],
    lines: np.ndarray,
    details: np.ndarray,
    thickness: int,
    wall_pixels: np.ndarray | None = None,
) -> tuple[list[WallSegment], list[Opening]]:
    """Bridge door/window-sized gaps and return the bridged walls with openings.

    Gaps are found between collinear wall pieces and between a free wall end and
    the next perpendicular wall. Every gap needs a door arc or window glazing to be
    bridged; a gap without a symbol stays open floor. Isolated segments are
    bridged only when both ends reach walls, so stray equipment or fixture
    drawings stay detached and can be dropped later.
    ``lines`` (dark lines of any shade) reveals glazing and door arcs; ``details``
    (strokes in any color) also reveals colored door arcs. ``wall_pixels`` (the
    wall mask), when given, keeps wall edges from being read as arcs.
    """
    symbols = _Symbols(lines, details, thickness, wall_pixels)
    min_gap = MIN_OPENING_RATIO * thickness
    max_gap = max(symbols.max_door_gap, MAX_WINDOW_IMAGE_RATIO * max(lines.shape))
    walls, openings = _bridge_collinear_gaps(segments, min_gap, max_gap, symbols)
    walls, end_openings = _bridge_gaps_to_walls(walls, min_gap, max_gap, symbols)
    return walls, openings + end_openings


class _Symbols:
    """Classifies gaps by the door or window symbol drawn in them."""

    def __init__(
        self,
        lines: np.ndarray,
        details: np.ndarray,
        thickness: int,
        wall_pixels: np.ndarray | None,
    ) -> None:
        self.lines = lines
        self.thickness = thickness
        self.min_gap = MIN_OPENING_RATIO * thickness
        self.max_door_gap = max(
            MAX_OPENING_RATIO * thickness, MAX_OPENING_IMAGE_RATIO * max(lines.shape)
        )
        # Dark arcs are thin in ``lines``; colored arcs only show in ``details``.
        max_radius = MAX_OPENING_IMAGE_RATIO * max(lines.shape)
        self.arcs = [
            *find_door_arcs(lines, wall_pixels, thickness, max_radius),
            *find_door_arcs(details, wall_pixels, thickness, max_radius),
        ]

    def find(self, gap: WallSegment) -> list[Opening]:
        """Openings in the gap: doors for swing arcs, windows for glazing lines.

        A door covers what its arcs swing across (two arcs for a double door). A
        leftover under one wall thickness at a gap end is a door frame and joins the
        door; a longer one is checked for glazing (e.g. a storefront window beside
        the entrance) and otherwise stays wall. Gaps too wide for a door can only
        be windows (glass walls). An empty list means no symbol.
        """
        door_sized = gap.end - gap.start <= self.max_door_gap
        spans = swing_spans(self.arcs, gap, self.thickness) if door_sized else []
        if spans:
            start = min(s for s, _ in spans)
            end = max(e for _, e in spans)
            if start - gap.start <= self.thickness:
                start = gap.start
            if gap.end - end <= self.thickness:
                end = gap.end
            found = [Opening("door", replace(gap, start=start, end=end))]
            for side in (replace(gap, end=start), replace(gap, start=end)):
                if side.end - side.start >= self.min_gap and _has_glazing(
                    self.lines, side, self.thickness
                ):
                    found.append(Opening("window", side))
            return found
        if _has_glazing(self.lines, gap, self.thickness):
            return [Opening("window", gap)]
        return []


def _bridge_collinear_gaps(
    segments: list[WallSegment],
    min_gap: float,
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
            found = symbols.find(gap) if min_gap <= width <= max_gap else []
            if found:
                openings.extend(found)
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
        bridged, segment_openings, bridged_ends = segment, [], 0
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
            found = symbols.find(gap)
            if not found:
                continue
            segment_openings.extend(found)
            bridged = replace(bridged, **{side: target})
            bridged_ends += 1
        # An isolated piece is a wall between two openings only if both ends reach
        # walls; bridging just one end would attach stray drawings such as equipment.
        isolated = not any(segment.touches(other) for other in segments if other is not segment)
        if isolated and bridged_ends < 2:
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


def _wall_band(
    lines: np.ndarray, segment: WallSegment, thickness: int, ratio: float = 0.5
) -> np.ndarray:
    """Pixels within ``ratio`` x thickness of the wall line along the segment, one
    column per step."""
    half = ratio * thickness + 1
    across = slice(max(0, round(segment.offset - half)), round(segment.offset + half) + 1)
    along = slice(int(segment.start) + 1, int(segment.end))
    if segment.orientation == "horizontal":
        return lines[across, along]
    return lines[along, across].T


def _has_glazing(lines: np.ndarray, gap: WallSegment, thickness: int) -> bool:
    return any(
        _has_glazing_in_band(_wall_band(lines, gap, thickness, ratio), thickness)
        for ratio in GLAZING_BAND_RATIOS
    )


def _has_glazing_in_band(band: np.ndarray, thickness: int) -> bool:
    # Glazing lies within the wall (or its window frame); looking further would
    # pick up edges of the floor colors on either side.
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
