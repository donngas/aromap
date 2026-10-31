"""Center-classified square grid and conservative wall-blocked neighbor graph.

No diffusion coefficients, flux calculations, or time integration live here.
"""

import math

import numpy as np
import shapely
from shapely import STRtree
from shapely.geometry import LineString, Point

from app.simulations.engine.models import PreparedGrid, SourceWeights
from app.simulations.errors import PreparationError
from app.simulations.geometry import GEOMETRY_TOLERANCE_M, polygon_for, segment_for
from app.simulations.limits import PreparationLimits
from app.simulations.models import MetricPoint, SimulationInput


def grid_extent(domain, cell_size_m: float, limits: PreparationLimits):
    limits.check_resolution(cell_size_m)
    polygon = polygon_for(domain)
    left, top, right, bottom = polygon.bounds
    width = (right - left) / cell_size_m
    height = (bottom - top) / cell_size_m
    if not math.isfinite(width) or not math.isfinite(height):
        raise PreparationError("resource_limit", "Grid dimensions exceed representable limits.")
    columns, rows = math.ceil(width), math.ceil(height)
    limits.check(rows * columns, limits.max_cells, "Bounding grid cell count")
    return polygon, MetricPoint(x=left, y=top), rows, columns


def _barriers(geometry, exterior_ids=frozenset()):
    doors_by_wall = {}
    for opening in geometry.openings:
        if opening.kind == "door" and opening.is_open and opening.id not in exterior_ids:
            doors_by_wall.setdefault(opening.wall_id, []).append(segment_for(opening))
    segments = []
    for wall in geometry.walls:
        barrier = segment_for(wall)
        doors = doors_by_wall.get(wall.id, [])
        if not doors:
            segments.append(barrier)
            continue
        # Cut by distance along the parent wall. Geometric line difference can
        # miss diagonal openings because projected floats are not exactly collinear.
        intervals = sorted(tuple(sorted((barrier.project(Point(door.coords[0])),
                                         barrier.project(Point(door.coords[-1]))))) for door in doors)
        cursor = 0.0
        for start, end in intervals:
            if start - cursor > GEOMETRY_TOLERANCE_M:
                segments.append(LineString([barrier.interpolate(cursor), barrier.interpolate(start)]))
            cursor = max(cursor, end)
        if barrier.length - cursor > GEOMETRY_TOLERANCE_M:
            segments.append(LineString([barrier.interpolate(cursor), barrier.interpolate(barrier.length)]))
    return segments


def build_grid(input: SimulationInput, limits: PreparationLimits | None = None, exterior_ids=frozenset()) -> PreparedGrid:
    limits = limits or PreparationLimits()
    cell = input.grid_cell_size_m
    polygon, origin, rows, columns = grid_extent(input.geometry.indoor_domain, cell, limits)
    limits.output_bytes(len(input.sample_times_s), len(input.sources), rows, columns)

    x = origin.x + (np.arange(columns) + 0.5) * cell
    y = origin.y + (np.arange(rows) + 0.5) * cell
    xx, yy = np.meshgrid(x, y)
    centers = np.column_stack((xx.ravel(), yy.ravel()))
    active_mask = shapely.contains(polygon, shapely.points(centers)).reshape(rows, columns)
    count = int(active_mask.sum())
    if count == 0:
        raise PreparationError("empty_grid", "No indoor cell centers; use a finer cell size.")
    active_index = np.full((rows, columns), -1, dtype=np.int64)
    active_index[active_mask] = np.arange(count)

    # Only four-neighbor adjacency. Store right/down candidates once each.
    flat = np.arange(rows * columns).reshape(rows, columns)
    pairs = np.concatenate((
        np.column_stack((flat[:, :-1].ravel(), flat[:, 1:].ravel())),
        np.column_stack((flat[:-1, :].ravel(), flat[1:, :].ravel())),
    ))
    pairs = pairs[np.all(active_mask.ravel()[pairs], axis=1)]
    segments = shapely.linestrings(centers[pairs])
    # Prevent shortcuts across concavities/holes even if both centers are inside.
    allowed = shapely.covers(polygon, segments)
    barriers = _barriers(input.geometry, exterior_ids)
    if barriers and len(segments):
        intersections = STRtree(barriers).query(segments, predicate="intersects")
        allowed[np.unique(intersections[0])] = False
    pairs = pairs[allowed]
    connection_lines = segments[allowed]
    connections = active_index.ravel()[pairs]

    warnings = []
    if not math.isclose(count * cell * cell, polygon.area, rel_tol=1e-9, abs_tol=1e-12):
        warnings.append("Indoor area is approximated by cell centers; refine the grid for boundary detail.")
    inset = polygon.buffer(-cell / 2)
    if inset.is_empty or inset.geom_type == "MultiPolygon":
        warnings.append("The footprint contains thin regions/passages that may be lost at this cell size.")
    for opening in input.geometry.openings:
        if opening.kind != "door" or not opening.is_open or opening.id in exterior_ids:
            continue
        door = segment_for(opening)
        if door.length < cell:
            warnings.append(f"Door {opening.id} is narrower than one cell; refine the grid.")
        if not len(connection_lines) or not np.any(shapely.intersects(door, connection_lines)):
            warnings.append(f"Open door {opening.id} has no represented cell connection; refine the grid.")

    source_weights = []
    barrier_tree = STRtree(barriers) if barriers else None
    for source in input.sources:
        point = Point(source.position_m.x, source.position_m.y)
        if not polygon.contains(point):
            raise PreparationError("invalid_source", f"Placement {source.placement_id} is not inside usable space.")
        if barrier_tree is not None and len(barrier_tree.query(point.buffer(GEOMETRY_TOLERANCE_M), predicate="intersects")):
            raise PreparationError("invalid_source", f"Placement {source.placement_id} lies on a closed wall.")
        column = math.floor((point.x - origin.x) / cell)
        row = math.floor((point.y - origin.y) / cell)
        if not (0 <= row < rows and 0 <= column < columns) or active_index[row, column] < 0:
            raise PreparationError("unresolved_source", f"Placement {source.placement_id} has no active containing cell; refine the grid.")
        to_center = LineString([point, Point(x[column], y[row])])
        if not polygon.covers(to_center) or (
            barrier_tree is not None and len(barrier_tree.query(to_center, predicate="intersects"))
        ):
            raise PreparationError("unresolved_source", f"Placement {source.placement_id} maps across a barrier; refine the grid.")
        # One containing cell initially; never snap across a wall/outdoor region.
        indices = np.array([active_index[row, column]], dtype=np.int64)
        weights = np.array([1.0], dtype=np.float64)
        indices.flags.writeable = weights.flags.writeable = False
        source_weights.append(SourceWeights(source.placement_id, source.definition_id, indices, weights))

    for array in (active_mask, active_index, connections):
        array.flags.writeable = False
    return PreparedGrid(origin, cell, rows, columns, active_mask, active_index,
                        connections, tuple(source_weights), tuple(warnings))
