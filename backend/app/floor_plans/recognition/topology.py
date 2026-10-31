"""Wall grouping, junction splitting, and opening assignment."""

from dataclasses import replace

from app.floor_plans.recognition.openings import Opening
from app.floor_plans.recognition.walls import WallSegment

# Connected wall groups shorter in total than this fraction of the largest group
# are discarded. A shop's walls form one large network once openings are bridged;
# small separate clusters are usually plants, equipment, or fixtures.
MIN_GROUP_LENGTH_RATIO = 0.2


def drop_small_groups(segments: list[WallSegment]) -> list[WallSegment]:
    """Keep connected wall groups with substantial total length."""
    parents = list(range(len(segments)))

    def root(i: int) -> int:
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    for i, segment in enumerate(segments):
        for j in range(i):
            if segment.touches(segments[j]):
                parents[root(i)] = root(j)

    lengths: dict[int, float] = {}
    for i, segment in enumerate(segments):
        lengths[root(i)] = lengths.get(root(i), 0.0) + segment.end - segment.start
    if not lengths:
        return []
    min_length = MIN_GROUP_LENGTH_RATIO * max(lengths.values())
    return [s for i, s in enumerate(segments) if lengths[root(i)] >= min_length]


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
