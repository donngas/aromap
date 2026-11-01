"""Door and window detection from gaps in wall centerlines.

Walls span their openings, so each accepted gap is bridged with wall and
recorded as a door or window on that wall.
"""

from dataclasses import dataclass, replace
from typing import Literal

import cv2
import numpy as np

from app.floor_plans.recognition.doors import (
    MAX_HINGE_OFFSET_RADIUS_RATIO,
    MAX_HINGE_OFFSET_RATIO,
    MIN_SWING_IN_GAP,
    DoorArc,
    find_door_arcs,
    swing_spans,
)
from app.floor_plans.recognition.walls import TOUCH_TOLERANCE_PX, WallSegment

# Opening widths as multiples of the wall thickness: roughly 0.6-3 m for
# 0.2 m walls, covering single doors up to wide shop entrances. Only gaps with a
# door arc or window glazing are bridged (base layout format); a gap without a
# symbol is open floor, e.g. an open-plan sales floor or a passage.
MIN_OPENING_RATIO = 3
# Small windows (e.g. a bathroom window) may be narrower, down to this multiple,
# when glazing is drawn in the gap; doors keep the limit above.
MIN_WINDOW_RATIO = 2
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
# Each glazing line also has one unbroken piece at least this fraction of the
# gap long; dashed lines across a gap mark an open passage (e.g. into a
# stockroom), not glass.
MIN_GLAZING_SOLID_RATIO = 0.35
# Windows are drawn with at least this many separate parallel lines; a single
# line across a gap is usually a door threshold.
MIN_GLAZING_LINES = 2
# Glazing is looked for within these multiples of the wall thickness on each side
# of the wall line: first the wall itself, then a little wider for window frames
# drawn wider than the wall. The tight band comes first because on thin walls the
# wider one reaches floor-color edges.
GLAZING_BAND_RATIOS = (0.5, 0.75)
# Glazing is a few thin lines; if more of the band than this is covered, it is a
# filled area (e.g. a floor color) rather than a window. On thin walls the band is
# only a few pixels, so two frame lines alone already cover most of it.
MAX_GLAZING_LINE_FRACTION = 0.8
# Each glazing line (or tight group of lines) is at most this fraction of the wall
# thickness; wider bands are edges between floor colors, not glass.
MAX_GLAZING_LINE_WIDTH_RATIO = 1 / 2
# Minimum allowed glazing line width (px), so on thin walls a frame line that
# touches a fixture edge (e.g. a stockroom shelf against the window) still counts.
MIN_GLAZING_LINE_WIDTH_PX = 4

# A door drawn half open (CAD style) may have only a short arc, too short to fit,
# but its leaf is a straight line from the hinge at one gap end, about as long as
# the gap, at an angle to the wall. Leaves are checked between these angles off
# the wall line: flatter lines are thresholds or glazing, and lines near square
# to the wall are door frames, counters, or other walls (a door opened square is
# drawn with a full arc anyway).
LEAF_ANGLES_DEG = range(15, 76, 3)
# The leaf must be drawn along this fraction of its length, measured from one
# wall thickness out from the hinge (the jamb) to this fraction of the gap width.
LEAF_COVERAGE = 0.7
LEAF_REACH_RATIO = 0.8
# Beyond this many gap widths from the hinge the line must stop: longer lines are
# furniture or fixture edges that happen to start at the wall.
LEAF_END_RATIO = 1.3
# A piece of a gap left beside a door, at least an opening wide and with less
# than this fraction of it drawn as wall, is open floor (e.g. the open side of a
# stair or a passage next to a stockroom door), so it is not filled with wall.
MAX_OPEN_FLOOR_WALL_FRACTION = 0.5

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
    glazing: np.ndarray | None = None,
) -> tuple[list[WallSegment], list[Opening]]:
    """Bridge door/window-sized gaps and return the bridged walls with openings.

    Gaps are found between collinear wall pieces and between a free wall end and
    the next perpendicular wall. Every gap needs a door arc or window glazing to be
    bridged; a gap without a symbol stays open floor. Isolated segments are
    bridged only when both ends reach walls, so stray equipment or fixture
    drawings stay detached and can be dropped later.
    ``lines`` (dark lines of any shade) reveals glazing and door arcs; ``details``
    (strokes in any color) also reveals colored door arcs. ``wall_pixels`` (the
    wall mask), when given, keeps wall edges from being read as arcs. ``glazing``,
    when given, is used instead of ``lines`` to look for glazing (see
    preprocess.glazing_mask).
    """
    symbols = _Symbols(lines, details, thickness, wall_pixels, segments, glazing)
    min_gap = MIN_WINDOW_RATIO * thickness
    max_gap = max(symbols.max_door_gap, MAX_WINDOW_IMAGE_RATIO * max(lines.shape))
    walls, openings = _bridge_collinear_gaps(segments, min_gap, max_gap, symbols)
    walls, end_openings = _bridge_gaps_to_walls(walls, min_gap, max_gap, symbols)
    openings += end_openings
    arc_walls, arc_doors = _place_arc_doors(walls, openings, symbols)
    return walls + arc_walls, openings + arc_doors


class _Symbols:
    """Classifies gaps by the door or window symbol drawn in them."""

    def __init__(
        self,
        lines: np.ndarray,
        details: np.ndarray,
        thickness: int,
        wall_pixels: np.ndarray | None,
        walls: list[WallSegment] | None = None,
        glazing: np.ndarray | None = None,
    ) -> None:
        self.lines = lines
        self.glazing = lines if glazing is None else glazing
        self.thickness = thickness
        self.wall_pixels = wall_pixels
        self.walls = walls or []
        # Door leaves are thin lines away from the walls (a wall meeting the gap
        # end would otherwise look like a leaf opened square to the wall).
        self.leaf_lines = (lines > 0).astype(np.uint8)
        if wall_pixels is not None:
            self.leaf_lines[cv2.dilate(wall_pixels, np.ones((5, 5), np.uint8)) > 0] = 0
        self.leaf_lines = cv2.dilate(self.leaf_lines, np.ones((3, 3), np.uint8))
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
        # Which edge of each arc is the doorway, where it can be told (see _closing_axis).
        self.axis = {arc: _closing_axis(arc, walls or [], thickness) for arc in self.arcs}
        self.axis.update(_double_door_axes(self.arcs, thickness))

    def arcs_along(self, orientation: str) -> list[DoorArc]:
        """Arcs whose doorway may lie along a wall line of this orientation."""
        return [arc for arc in self.arcs if self.axis[arc] in (None, orientation)]

    def find(self, gap: WallSegment) -> list[Opening]:
        """Openings in the gap: doors for swing arcs, windows for glazing lines.

        A door covers what its arcs swing across (two touching arcs for a double
        door). Arcs with wall between them are separate doors, e.g. a restroom door
        and a stockroom door either side of the wall between those rooms; the piece
        between them stays wall. A leftover under one wall thickness at a gap end is
        a door frame and joins the door; a longer one is checked for glazing (e.g. a
        storefront window beside the entrance) and otherwise stays wall. Gaps too
        wide for a door can only be windows (glass walls). A door-sized gap with
        neither arcs nor glazing is still a door when a straight door leaf runs
        from one of its ends (a door drawn half open). An empty list means no
        symbol.
        """
        if gap.end - gap.start < self.min_gap:  # Only a small window fits.
            if _has_glazing(self.glazing, gap, self.thickness):
                return [Opening("window", gap)]
            return []
        door_sized = gap.end - gap.start <= self.max_door_gap
        arcs = self.arcs_along(gap.orientation) if door_sized else []
        spans = _merge_spans(swing_spans(arcs, gap, self.thickness), self.thickness)
        if spans:
            if spans[0][0] - gap.start <= self.thickness:
                spans[0] = (gap.start, spans[0][1])
            if gap.end - spans[-1][1] <= self.thickness:
                spans[-1] = (spans[-1][0], gap.end)
            found = [Opening("door", replace(gap, start=s, end=e)) for s, e in spans]
            start, end = spans[0][0], spans[-1][1]
            for side in (replace(gap, end=start), replace(gap, start=end)):
                if side.end - side.start >= self.min_gap and _has_glazing(
                    self.glazing, side, self.thickness
                ):
                    found.append(Opening("window", side))
            return found
        if _has_glazing(self.glazing, gap, self.thickness):
            return [Opening("window", gap)]
        if self.min_gap <= gap.end - gap.start <= MAX_OPENING_RATIO * self.thickness:
            if _has_leaf(self.leaf_lines, gap, self.thickness):
                return [Opening("door", gap)]
        return []

    def extent(self, gap: WallSegment, found: list[Opening]) -> tuple[float, float]:
        """Part of the gap to fill with wall around the openings found in it.

        Normally the whole gap. When a door leaves an opening-wide piece with no
        wall drawn at one end, that piece is open floor and is left out. If both
        ends are like that the whole gap is kept, so the door stays on a wall.
        A wall reaching the line in that piece (e.g. at a stair post) still gets
        the short wall from the door to it; only the rest is open floor.
        """
        if self.wall_pixels is None or not any(o.kind == "door" for o in found):
            return gap.start, gap.end
        start = min(o.span.start for o in found)
        end = max(o.span.end for o in found)
        open_start = self._is_open_floor(replace(gap, end=start))
        open_end = self._is_open_floor(replace(gap, start=end))
        if open_start and not open_end:
            return self._wall_before_open_floor(gap, start, -1), gap.end
        if open_end and not open_start:
            return gap.start, self._wall_before_open_floor(gap, end, 1)
        return gap.start, gap.end

    def _wall_before_open_floor(self, gap: WallSegment, door_end: float, direction: int) -> float:
        """Where the wall from a door ends, going ``direction`` into open floor: at
        the nearest wall reaching the line, if enough open floor is left after it."""
        far_end = gap.end if direction > 0 else gap.start
        reach = [
            wall.offset
            for wall in self.walls
            if wall.orientation != gap.orientation
            and wall.start - self.thickness <= gap.offset <= wall.end + self.thickness
            and 0 < (wall.offset - door_end) * direction
            and (far_end - wall.offset) * direction >= self.min_gap
        ]
        return min(reach, key=lambda x: abs(x - door_end), default=door_end)

    def _is_open_floor(self, piece: WallSegment) -> bool:
        if piece.end - piece.start < self.min_gap:
            return False
        band = _wall_band(self.wall_pixels, piece, self.thickness)
        return band.size > 0 and (band > 0).mean() < MAX_OPEN_FLOOR_WALL_FRACTION


def _has_leaf(lines: np.ndarray, gap: WallSegment, thickness: int) -> bool:
    """Whether a straight door leaf runs from either end of the gap, on either side."""
    # The hinge sits at the gap end, or up to one wall thickness in from it when
    # the gap ends at the middle of a wall the door closes against.
    for end, toward in ((gap.start, 1), (gap.end, -1)):
        for inset in (0, thickness / 2, thickness):
            hinge = end + toward * inset
            width = gap.end - gap.start - inset
            radii = np.arange(thickness, LEAF_REACH_RATIO * width)
            beyond = np.arange(LEAF_END_RATIO * width, (LEAF_END_RATIO + 0.2) * width)
            if len(radii) == 0:
                continue
            for side in (-1, 1):
                for angle in np.radians(LEAF_ANGLES_DEG):
                    along, across = toward * np.cos(angle), side * np.sin(angle)
                    if _drawn(lines, gap, hinge, along, across, radii) < LEAF_COVERAGE:
                        continue
                    if _drawn(lines, gap, hinge, along, across, beyond) < 1 - LEAF_COVERAGE:
                        return True
    return False


def _drawn(
    lines: np.ndarray,
    gap: WallSegment,
    hinge: float,
    along: float,
    across: float,
    radii: np.ndarray,
) -> float:
    """Fraction of points on a ray from the hinge that lie on a drawn line."""
    a = hinge + along * radii
    b = gap.offset + across * radii
    xs, ys = (a, b) if gap.orientation == "horizontal" else (b, a)
    xs, ys = np.rint(xs).astype(int), np.rint(ys).astype(int)
    height, width = lines.shape
    inside = (xs >= 0) & (xs < width) & (ys >= 0) & (ys < height)
    if not inside.any():
        return 0.0
    hits = np.zeros(len(xs), bool)
    hits[inside] = lines[ys[inside], xs[inside]] > 0
    return float(hits.mean())


def _merge_spans(
    spans: list[tuple[float, float]], tolerance: float
) -> list[tuple[float, float]]:
    """Sorted spans with those touching within ``tolerance`` merged into one."""
    merged: list[tuple[float, float]] = []
    for start, end in sorted(spans):
        if merged and start - merged[-1][1] <= tolerance:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


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
                start, end = symbols.extent(gap, found)
                if end < gap.end:  # Open floor after the door.
                    walls.append(replace(current, end=end))
                    current = segment
                elif start > gap.start:  # Open floor before the door.
                    walls.append(current)
                    current = replace(segment, start=start)
                else:
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
            start, end = symbols.extent(gap, found)
            # Open floor between the door and the far wall: the door only extends
            # this wall, which then doesn't reach that wall (open floor on this
            # side keeps the whole gap as before).
            reached = target
            if side == "start" and start > gap.start:
                reached = start
            elif side == "end" and end < gap.end:
                reached = end
            segment_openings.extend(found)
            bridged = replace(bridged, **{side: reached})
            bridged_ends += reached == target
        # An isolated piece is a wall between two openings only if both ends reach
        # walls; bridging just one end would attach stray drawings such as equipment.
        isolated = not any(segment.touches(other) for other in segments if other is not segment)
        if isolated and bridged_ends < 2:
            walls.append(segment)
            continue
        walls.append(bridged)
        openings.extend(segment_openings)
    return walls, openings


def _place_arc_doors(
    walls: list[WallSegment], openings: list[Opening], symbols: _Symbols
) -> tuple[list[WallSegment], list[Opening]]:
    """Doors for swing arcs that no wall gap lined up with, plus the walls holding them.

    Such a door has no wall pieces on its own line, e.g. a door across a hallway
    between its two side walls, or a doorway between a room corner and a wall.
    The door is placed on the arc's line, between the two walls its swing spans.
    """
    thickness = symbols.thickness
    doors = [o.span for o in openings if o.kind == "door"]
    new_walls: list[WallSegment] = []
    new_doors: list[Opening] = []
    for arc in symbols.arcs:
        if any(_arc_on(arc, door, thickness) for door in doors):
            continue
        for orientation in ("vertical", "horizontal"):
            if symbols.axis[arc] not in (None, orientation):
                continue
            placed = _arc_door(arc, orientation, walls + new_walls, symbols)
            if placed is not None:
                wall, door = placed
                new_walls.append(wall)
                new_doors.append(door)
                doors.append(door.span)
                break
    return new_walls, new_doors


def _arc_door(
    arc: DoorArc, orientation: str, walls: list[WallSegment], symbols: _Symbols
) -> tuple[WallSegment, Opening] | None:
    thickness = symbols.thickness
    if orientation == "vertical":
        line, hinge, direction = arc.hinge_x, arc.hinge_y, arc.sign_y
    else:
        line, hinge, direction = arc.hinge_y, arc.hinge_x, arc.sign_x
    if direction == 0:
        return None
    swing_start, swing_end = sorted((hinge, hinge + direction * arc.radius))
    # The walls bounding the doorway cross the door's line at either end.
    crossing = [
        w.offset
        for w in walls
        if w.orientation != orientation and w.start - thickness <= line <= w.end + thickness
    ]
    before = [c for c in crossing if c <= swing_start + thickness]
    after = [c for c in crossing if c >= swing_end - thickness]
    if not before or not after:
        return None
    start, end = max(before), min(after)
    if not symbols.min_gap <= end - start <= symbols.max_door_gap:
        return None
    if swing_end - swing_start < MIN_SWING_IN_GAP * (end - start):
        return None
    # Join a wall already on this line (e.g. a room's side wall) if there is one.
    collinear = [
        w for w in walls if w.orientation == orientation and abs(w.offset - line) <= thickness
    ]
    offset = min(collinear, key=lambda w: abs(w.offset - line)).offset if collinear else line
    wall = WallSegment(orientation, offset, start, end)
    if any(w.start < end - thickness and start + thickness < w.end for w in collinear):
        return None  # a wall already runs here: the gap passes handle it
    door_start = start if swing_start - start <= thickness else swing_start
    door_end = end if end - swing_end <= thickness else swing_end
    return wall, Opening("door", replace(wall, start=door_start, end=door_end))


def _closing_axis(arc: DoorArc, walls: list[WallSegment], thickness: int) -> str | None:
    """The axis of the arc's edge that closes against a wall, i.e. the doorway.

    A quarter arc has two straight edges from its hinge: the door closed (across
    the doorway, its far end meeting the opposite jamb) and the door open (its far
    end in the room). Only the closed edge's far end touches a wall. None when both
    or neither do, e.g. without nearby wall pieces.
    """
    near = MAX_HINGE_OFFSET_RATIO * thickness
    ends = {
        "horizontal": (arc.hinge_x + arc.sign_x * arc.radius, arc.hinge_y),
        "vertical": (arc.hinge_x, arc.hinge_y + arc.sign_y * arc.radius),
    }
    touching = [axis for axis, point in ends.items() if _near_wall(point, walls, near)]
    return touching[0] if len(touching) == 1 else None


def _double_door_axes(arcs: list[DoorArc], thickness: int) -> dict[DoorArc, str]:
    """Doorway axis of the two arcs of a double door.

    Their closed edges meet each other in the middle, not a wall, so
    _closing_axis can't tell (and an open leaf beside a wall misleads it). Two
    arcs hinged on one line that swing toward each other with tips meeting
    (within one wall thickness) close along that line.
    """
    axes = {}
    for i, a in enumerate(arcs):
        for b in arcs[i + 1 :]:
            for axis, along, across, sign in (
                ("horizontal", "hinge_x", "hinge_y", "sign_x"),
                ("vertical", "hinge_y", "hinge_x", "sign_y"),
            ):
                tip_a = getattr(a, along) + getattr(a, sign) * a.radius
                tip_b = getattr(b, along) + getattr(b, sign) * b.radius
                if (
                    abs(getattr(a, across) - getattr(b, across)) <= thickness
                    and getattr(a, sign) == -getattr(b, sign) != 0
                    and abs(tip_a - tip_b) <= thickness
                ):
                    axes[a] = axes[b] = axis
    return axes


def _near_wall(point: tuple[float, float], walls: list[WallSegment], distance: float) -> bool:
    x, y = point
    for wall in walls:
        along, across = (x, y) if wall.orientation == "horizontal" else (y, x)
        dx = max(wall.start - along, 0.0, along - wall.end)
        if (dx**2 + (across - wall.offset) ** 2) ** 0.5 <= distance:
            return True
    return False


def _arc_on(arc: DoorArc, door: WallSegment, thickness: int) -> bool:
    """Whether a door already uses this arc: its hinge lies on the door's span."""
    if door.orientation == "horizontal":
        along, across = arc.hinge_x, arc.hinge_y
    else:
        along, across = arc.hinge_y, arc.hinge_x
    near = max(MAX_HINGE_OFFSET_RATIO * thickness, MAX_HINGE_OFFSET_RADIUS_RATIO * arc.radius)
    return abs(across - door.offset) <= near and door.start - near <= along <= door.end + near


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
    max_width = max(MIN_GLAZING_LINE_WIDTH_PX, thickness * MAX_GLAZING_LINE_WIDTH_RATIO)
    if len(widths) < MIN_GLAZING_LINES or not (widths <= max_width).all():
        return False
    return all(
        _longest_run(band[start:end].any(axis=0)) >= MIN_GLAZING_SOLID_RATIO * band.shape[1]
        for start, end in zip(edges[::2], edges[1::2])
    )


def _longest_run(drawn: np.ndarray) -> int:
    """Length of the longest unbroken run of drawn pixels."""
    edges = np.flatnonzero(np.diff(np.concatenate(([0], drawn.astype(int), [0]))))
    return int((edges[1::2] - edges[::2]).max(initial=0))
