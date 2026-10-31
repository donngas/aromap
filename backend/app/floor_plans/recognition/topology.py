"""Junction splitting and opening assignment for recognized walls."""

from dataclasses import replace

from app.floor_plans.recognition.openings import Opening
from app.floor_plans.recognition.walls import WallSegment


def split_at_junctions(segments: list[WallSegment]) -> list[WallSegment]:
    """Split walls at every crossing and T-junction.

    Connected pieces share identical endpoint coordinates, and no perpendicular
    wall meets a returned piece in its interior.
    """
    pieces = []
    for segment in segments:
        cuts = sorted(
            {
                other.offset
                for other in segments
                if other.orientation != segment.orientation
                and segment.start < other.offset < segment.end
                and other.start <= segment.offset <= other.end
            }
        )
        bounds = [segment.start, *cuts, segment.end]
        pieces.extend(
            replace(segment, start=start, end=end)
            for start, end in zip(bounds, bounds[1:])
            if end > start
        )
    return pieces


def find_parent(opening: Opening, walls: list[WallSegment]) -> WallSegment | None:
    """Return the single wall piece containing the opening, if any."""
    span = opening.span
    return next(
        (
            wall
            for wall in walls
            if wall.orientation == span.orientation
            and wall.offset == span.offset
            and wall.start <= span.start
            and span.end <= wall.end
        ),
        None,
    )
