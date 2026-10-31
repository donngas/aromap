"""Metric topology validation and opening resolution; no image processing."""

import math

from shapely import STRtree
from shapely.geometry import LineString, Point, Polygon
from shapely.validation import explain_validity

from app.simulations.errors import PreparationError
from app.simulations.models import (
    MetricPoint, ResolvedOpening, SimulationConfiguration, SimulationGeometry,
)

GEOMETRY_TOLERANCE_M = 1e-9


def polygon_for(domain) -> Polygon:
    polygon = Polygon(
        [(p.x, p.y) for p in domain.boundary],
        [[(p.x, p.y) for p in hole] for hole in domain.holes],
    )
    if polygon.is_empty or not polygon.is_valid or not math.isfinite(polygon.area) or polygon.area <= 0:
        raise PreparationError("invalid_domain", f"Invalid indoor polygon: {explain_validity(polygon)}")
    return polygon


def segment_for(segment) -> LineString:
    return LineString([(segment.start.x, segment.start.y), (segment.end.x, segment.end.y)])


def resolve_geometry(configuration: SimulationConfiguration) -> SimulationGeometry:
    geometry = configuration.geometry_m
    polygon = polygon_for(geometry.indoor_domain)
    walls = {wall.id: segment_for(wall) for wall in geometry.walls}
    for wall_id, wall in walls.items():
        if wall.length <= GEOMETRY_TOLERANCE_M or not polygon.covers(wall):
            raise PreparationError("invalid_wall", f"Wall {wall_id} is zero-length or outside the indoor domain.")

    # Junctions must already have been split; overlapping walls are ambiguous.
    lines = list(walls.values())
    if lines:
        tree = STRtree(lines)
        for first, line in enumerate(lines):
            for second in tree.query(line, predicate="intersects"):
                if first >= second:
                    continue
                intersection = line.intersection(lines[second])
                if intersection.geom_type != "Point" or any(
                    min(Point(candidate.coords[0]).distance(intersection),
                        Point(candidate.coords[-1]).distance(intersection)) > GEOMETRY_TOLERANCE_M
                    for candidate in (line, lines[second])
                ):
                    raise PreparationError("invalid_wall_junction", "Split walls at crossings and junctions; remove overlaps.")

    states = {state.opening_id: state.is_open for state in configuration.opening_states}
    openings = []
    opening_lines = []
    for kind, collection in (("door", geometry.doors), ("window", geometry.windows)):
        for opening in collection:
            wall = walls[opening.wall_id]
            line = segment_for(opening)
            if line.length <= GEOMETRY_TOLERANCE_M or not wall.buffer(GEOMETRY_TOLERANCE_M).covers(line):
                raise PreparationError("invalid_opening", f"Opening {opening.id} must lie on its parent wall.")
            # Snap only floating-point roundoff to the parent segment so subtraction
            # opens the wall reliably; do not perform geometry recognition/correction.
            start = wall.interpolate(wall.project(Point(line.coords[0])))
            end = wall.interpolate(wall.project(Point(line.coords[-1])))
            snapped = LineString([start, end])
            if snapped.length <= GEOMETRY_TOLERANCE_M:
                raise PreparationError("invalid_opening", f"Opening {opening.id} has no usable length.")
            is_open = states.get(opening.id, False)
            if kind == "window" and is_open:
                raise PreparationError("unsupported_open_window", "Open-window behavior has not been defined yet.")
            openings.append(ResolvedOpening(
                **opening.model_dump(exclude={"start", "end"}),
                start=MetricPoint(x=start.x, y=start.y), end=MetricPoint(x=end.x, y=end.y),
                kind=kind, is_open=is_open,
            ))
            opening_lines.append(snapped)
    if opening_lines:
        tree = STRtree(opening_lines)
        for first, line in enumerate(opening_lines):
            for second in tree.query(line, predicate="intersects"):
                if first < second and line.intersection(opening_lines[second]).length > GEOMETRY_TOLERANCE_M:
                    raise PreparationError("overlapping_openings", "Door/window segments must not overlap.")
    return SimulationGeometry(
        indoor_domain=geometry.indoor_domain.model_copy(deep=True),
        walls=[wall.model_copy(deep=True) for wall in geometry.walls], openings=openings,
    )
