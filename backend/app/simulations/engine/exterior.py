"""Associate open perimeter openings with indoor cells without outdoor cells."""
from dataclasses import dataclass
import math

import numpy as np
from scipy.spatial import cKDTree
from shapely import STRtree
from shapely.geometry import LineString, Point
from shapely.ops import nearest_points, polygonize, unary_union

from app.simulations.errors import PreparationError
from app.simulations.geometry import polygon_for, segment_for


@dataclass(frozen=True)
class ExteriorEdge:
    opening_id: str
    cell_index: int
    length_m: float
    normal_x: float
    normal_y: float
    kind: str = "window"


def map_exterior_openings(geometry, grid):
    if not any(opening.is_open for opening in geometry.openings):
        return (), set()
    polygon = polygon_for(geometry.indoor_domain)
    boundary = polygon.boundary
    h = grid.cell_size_m
    tolerance = .375  # Physical recognition tolerance; independent of solver resolution.
    rc = np.argwhere(grid.active_mask)
    xy = np.column_stack((grid.origin_m.x + (rc[:, 1] + .5) * h,
                          grid.origin_m.y + (rc[:, 0] + .5) * h))
    tree = cKDTree(xy)
    walls = {w.id: segment_for(w) for w in geometry.walls}
    # Include the footprint and all walls as closed linework. Polygonized
    # faces let us distinguish a room on both sides from the outside, even
    # before any opening is made permeable.
    faces = [face for face in polygonize(unary_union([polygon.boundary, *walls.values()]))
             if polygon.covers(face.representative_point())]
    face_tree = STRtree(faces)
    # Closed wall-only regions can establish an outer wall centerline even
    # when the user-supplied footprint follows the outside wall face.
    wall_faces = ([face for face in polygonize(unary_union(list(walls.values())))
                   if polygon.covers(face.representative_point())] if walls else [])
    wall_envelope = unary_union(wall_faces) if wall_faces else None

    def face_at(point):
        indices = [int(i) for i in face_tree.query(point) if faces[int(i)].contains(point)]
        return indices[0] if len(indices) == 1 else None
    result = []
    exterior_ids = set()
    for opening in geometry.openings:
        if not opening.is_open:
            continue
        if opening.boundary_kind == 'interior':
            if opening.kind == 'window':
                raise PreparationError('invalid_opening', f'Open interior window {opening.id} is not supported.')
            continue
        line = segment_for(opening)
        mid = line.interpolate(.5, normalized=True)
        nearest = nearest_points(mid, boundary)[1]
        distance = mid.distance(nearest)
        if distance > tolerance:
            if opening.kind == 'window' or opening.boundary_kind == 'exterior':
                raise PreparationError('unresolved_exterior_opening', f'Exterior opening {opening.id} is not near the indoor boundary.')
            continue
        # If another wall encloses the near side, it is an interior opening.
        # Use intersections (not crosses): a boundary wall often meets the
        # ray exactly at its endpoint. Check the whole span, not only its center.
        blocked_samples = []
        for fraction in (.2, .5, .8):
            sample = line.interpolate(fraction, normalized=True)
            outer = nearest_points(sample, boundary)[1]
            if sample.distance(outer) <= 1e-9:
                blocked_samples.append(False)
                continue
            ray = LineString([sample, outer])
            blocked_samples.append(any(wid != opening.wall_id and ray.intersects(wall)
                                       for wid, wall in walls.items()))
        if any(blocked_samples) and not all(blocked_samples):
            raise PreparationError('ambiguous_exterior_opening', f'Opening {opening.id} has inconsistent enclosure along its span.')
        blocked = all(blocked_samples)
        if blocked:
            if opening.boundary_kind == 'exterior':
                raise PreparationError('ambiguous_exterior_opening', f'Opening {opening.id} is marked exterior but another wall encloses it.')
            if opening.kind == 'window':
                raise PreparationError('unresolved_exterior_opening', f'Window {opening.id} is behind another wall.')
            continue
        dx = opening.end.x - opening.start.x
        dy = opening.end.y - opening.start.y
        length = math.hypot(dx, dy)
        normal = np.array([-dy / length, dx / length])
        # A closed partition must separate the two nearby enclosure faces.
        # At the exact footprint boundary one side is outside, which is valid.
        # A dangling wall near the perimeter is inherently ambiguous.
        probe_distance = max(1e-7, min(h * .01, length * .01, 0.001))
        plus = Point(mid.x + probe_distance * normal[0], mid.y + probe_distance * normal[1])
        minus = Point(mid.x - probe_distance * normal[0], mid.y - probe_distance * normal[1])
        plus_face, minus_face = face_at(plus), face_at(minus)
        if polygon.contains(plus) and polygon.contains(minus):
            if (plus_face is None or minus_face is None or plus_face == minus_face) and opening.boundary_kind != 'exterior':
                raise PreparationError('ambiguous_exterior_opening', f'Opening {opening.id} lies on a wall that does not separate enclosed regions.')
        if (distance > 1e-8 and opening.boundary_kind != 'exterior'
                and (wall_envelope is None or not wall_envelope.boundary.buffer(1e-8).covers(line))):
            raise PreparationError('ambiguous_exterior_opening',
                                   f'Opening {opening.id} is near the boundary but its wall is not part of a closed exterior enclosure; specify boundary_kind.')
        if distance > 1e-8:
            toward = np.array([nearest.x - mid.x, nearest.y - mid.y])
            if abs(np.dot(normal, toward)) < .7 * distance:
                raise PreparationError('ambiguous_exterior_opening', f'Opening {opening.id} is near but not aligned with the indoor boundary.')
            if np.dot(normal, toward) < 0:
                normal = -normal
        else:
            # Distinguish inside and outside even on exact polygon boundaries.
            probe = max(1e-5, min(h * .1, .01))
            p1 = Point(mid.x + probe * normal[0], mid.y + probe * normal[1])
            p2 = Point(mid.x - probe * normal[0], mid.y - probe * normal[1])
            if polygon.covers(p1) == polygon.covers(p2):
                raise PreparationError('ambiguous_exterior_opening', f'Cannot determine the outside of opening {opening.id}.')
            if polygon.covers(p1):
                normal = -normal
        # Sample the opening at a finer resolution than the simulation grid,
        # attach each piece to a cell on the indoor side and conserve its length.
        count = max(1, math.ceil(length / (h / 4)))
        assigned = {}
        for k in range(count):
            p = line.interpolate((k + .5) / count, normalized=True)
            point = np.array([p.x, p.y])
            distances, candidates = tree.query(point - normal * (h * .5), k=min(16, len(xy)))
            found = None
            for cell_distance, idx in zip(np.atleast_1d(distances), np.atleast_1d(candidates)):
                if cell_distance > 2 * h:
                    break
                center = xy[idx]
                if np.dot(center - point, normal) >= -1e-9:
                    continue
                ray = LineString([point - normal * 1e-8, center])
                if not polygon.covers(ray):
                    continue
                if any(ray.crosses(wall) for wall in walls.values()):
                    continue
                found = int(idx)
                break
            if found is None:
                raise PreparationError('unresolved_exterior_opening', f'Opening {opening.id} cannot be mapped to an indoor cell; refine the grid.')
            assigned[found] = assigned.get(found, 0) + length / count
        exterior_ids.add(opening.id)
        result.extend(ExteriorEdge(opening.id, cell, width, float(normal[0]), float(normal[1]), opening.kind) for cell, width in assigned.items())
    return tuple(result), exterior_ids
