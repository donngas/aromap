"""Idealized, steady, balanced 2D airflow on the existing cell graph.

This is a projected prescribed field, not a Navier–Stokes or CFD solver.
Edge fluxes are m²/s per unit room height; positive follows the stored pair.
"""
import math
import time
from dataclasses import dataclass

import numpy as np
from scipy.sparse import coo_matrix, diags
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import LinearOperator, cg
from app.simulations.errors import PreparationError
from app.simulations.limits import ExecutionLimits

# Effective height-averaged engineering scenarios; see docs/airflow-calibration.md.
DEVICE_SPEEDS = {"fan": {"low": .08, "medium": .16, "high": .28},
                 "ac": {"low": .10, "medium": .20, "high": .35}}
DEVICE_RADII_M = {"fan": 1.0, "ac": 1.5}
OPENING_EXCHANGE_M_PER_S = {
    "window": {"calm": .004, "moderate": .012, "breezy": .025},
    "door": {"calm": .006, "moderate": .018, "breezy": .035},
}
WIND_POTENTIAL_M2_PER_S = {"calm": 0., "moderate": .06, "breezy": .15}
OPENING_RESISTANCE_LENGTH_M = {"window": 2., "door": 1.}


@dataclass(frozen=True)
class AirflowField:
    edge_flux: np.ndarray
    boundary_outflow: np.ndarray
    boundary_exchange: np.ndarray


def validate_device_positions(grid, settings, boundary, geometry=None):
    """Separate physically invalid devices from placements unresolved by a grid."""
    if geometry is not None:
        from shapely.geometry import Point
        from app.simulations.engine.grid import _barriers
        from app.simulations.geometry import polygon_for
        polygon = polygon_for(geometry.indoor_domain)
        barriers = _barriers(geometry, {item.opening_id for item in boundary})
    for device in settings.devices:
        if geometry is not None:
            point = Point(device.position_m.x, device.position_m.y)
            if not polygon.contains(point) or any(wall.distance(point) < 1e-9 for wall in barriers):
                raise PreparationError("invalid_airflow_device", f"Airflow device {device.id} is on a wall or outside the domain.")
        col = math.floor((device.position_m.x - grid.origin_m.x) / grid.cell_size_m)
        row = math.floor((device.position_m.y - grid.origin_m.y) / grid.cell_size_m)
        if not (0 <= row < grid.rows and 0 <= col < grid.columns and grid.active_mask[row, col]):
            raise PreparationError("unresolved_airflow_device", f"Airflow device {device.id} has no active containing cell; refine the grid.")


def build_airflow(grid, settings, boundary, geometry=None, *, limits=None, resident_bytes=0):
    """Project device pushes and prescribed exterior potentials onto mass balance.

    Boundary entries have cell_index, length_m, normal_x, normal_y, kind.
    """
    limits = limits or ExecutionLimits()
    started = time.monotonic()
    validate_device_positions(grid, settings, boundary, geometry)
    n = grid.active_cell_count
    edges = grid.connections
    # CSR graph/matrix, assembly temporaries, CG vectors, device rays and the
    # existing prepared data. This is a conservative estimate, not an RSS cap.
    limits.check_memory(resident_bytes + n * 640 + len(edges) * 320 + len(boundary) * 256)
    a, b = edges[:, 0], edges[:, 1]
    h = grid.cell_size_m
    rc = np.argwhere(grid.active_mask)
    xy = np.column_stack((grid.origin_m.x + (rc[:, 1] + .5) * h,
                          grid.origin_m.y + (rc[:, 0] + .5) * h))
    delta = xy[b] - xy[a]
    midpoint = (xy[a] + xy[b]) / 2
    tentative = np.zeros(len(edges))
    for device in settings.devices:
        limits.check_deadline(started)
        loc = np.array([device.position_m.x, device.position_m.y])
        angle = math.radians(device.direction_degrees)
        direction = np.array([math.cos(angle), math.sin(angle)])
        # Compact Gaussian momentum surrogate. The projection creates return flow.
        radius = DEVICE_RADII_M[device.type]
        distance2 = ((midpoint - loc) ** 2).sum(axis=1)
        influence = np.exp(-distance2 / (2 * radius ** 2))
        # Truncate before visibility filtering: otherwise unchecked Gaussian
        # tails can directly drive a disconnected room beyond the ray cutoff.
        influence[influence <= 1e-4] = 0
        if geometry is not None:
            # A fan cannot directly push air through a wall. Return flow is still
            # allowed through connected doorways during the pressure projection.
            import shapely
            from shapely import STRtree
            from app.simulations.engine.grid import _barriers
            from app.simulations.geometry import polygon_for

            barriers = _barriers(geometry, {item.opening_id for item in boundary})
            visible = np.flatnonzero(influence > 1e-4)
            if len(visible):
                rays = shapely.linestrings(np.stack((np.broadcast_to(loc, (len(visible), 2)), midpoint[visible]), axis=1))
                influence[visible[~shapely.covers(polygon_for(geometry.indoor_domain), rays)]] = 0
            if barriers and len(visible):
                hits = STRtree(barriers).query(rays, predicate="intersects")
                influence[visible[np.unique(hits[0])]] = 0
        tentative += DEVICE_SPEEDS[device.type][device.strength] * influence * (delta @ direction)

    if not len(edges) and not boundary:
        return AirflowField(tentative, np.zeros(0), np.zeros(0))
    # Potential has units m²/s. Internal face-length / center-distance = 1
    # on square cells. Boundary resistance includes the half-cell distance,
    # so refining h does not change the continuum interior conductivity.
    # This is a Darcy-like prescribed flow surrogate, not physical pressure.
    rows = np.concatenate((a, b, a, b))
    cols = np.concatenate((a, b, b, a))
    vals = np.concatenate((np.ones(len(a)), np.ones(len(a)), -np.ones(2*len(a))))
    lap = coo_matrix((vals, (rows, cols)), shape=(n, n)).tocsc()
    div = np.bincount(a, weights=tentative, minlength=n) - np.bincount(b, weights=tentative, minlength=n)
    cells = np.array([x.cell_index for x in boundary], dtype=int)
    widths = np.array([x.length_m for x in boundary], dtype=float)
    kinds = [getattr(x, "kind", "window") for x in boundary]
    conductance = widths / np.array([OPENING_RESISTANCE_LENGTH_M[k] + h / 2 for k in kinds])
    angle = math.radians(settings.wind_direction_degrees)
    wind = np.array([math.cos(angle), math.sin(angle)])
    wind_potential = WIND_POTENTIAL_M2_PER_S[settings.outdoor_conditions]
    external = np.array([-wind_potential * np.dot(wind, [x.normal_x, x.normal_y]) for x in boundary])
    if len(cells):
        lap += diags(np.bincount(cells, weights=conductance, minlength=n), format="csc")
    rhs = -div + np.bincount(cells, weights=conductance * external, minlength=n)
    graph = coo_matrix((np.ones(2*len(a)), (np.r_[a,b], np.r_[b,a])), shape=(n,n)).tocsr()
    component_count, components = connected_components(graph, directed=False)
    has_boundary = np.zeros(component_count, dtype=bool)
    has_boundary[components[cells]] = True
    _, first = np.unique(components, return_index=True)
    anchors = first[~has_boundary[components[first]]]
    if len(anchors):
        anchor_diag = np.zeros(n)
        anchor_diag[anchors] = 1.
        lap += diags(anchor_diag, format="csc")
    lap = lap.tocsr()
    diagonal = lap.diagonal()
    if np.any(diagonal <= 0):
        raise PreparationError("airflow_failed", "Airflow balance has an invalid diagonal.")
    preconditioner = LinearOperator((n, n), matvec=lambda x: x / diagonal, dtype=float)
    iterations = 0

    def check_progress(_):
        nonlocal iterations
        iterations += 1
        if iterations % 32 == 0:
            limits.check_deadline(started)

    phi, info = cg(lap, rhs, M=preconditioner, rtol=1e-10, atol=1e-14,
                   maxiter=min(10000, max(1000, 10 * n)), callback=check_progress)
    limits.check_deadline(started)
    if info != 0 or not np.isfinite(phi).all():
        raise PreparationError("airflow_failed", "Airflow balance did not converge; use a larger cell size or simplify the layout.")
    flux = tentative + (phi[a] - phi[b])
    outflow = conductance * (phi[cells] - external)
    # Separate unresolved two-way exchange; clean outdoor concentration is zero.
    exchange_speed = np.array([OPENING_EXCHANGE_M_PER_S[k][settings.outdoor_conditions] for k in kinds])
    return AirflowField(flux, outflow, widths * exchange_speed)
