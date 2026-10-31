"""Idealized, steady, balanced 2D airflow on the existing cell graph.

This is a projected prescribed field, not a Navier–Stokes or CFD solver.
Edge fluxes are m²/s per unit room height; positive follows the stored pair.
"""
import math
from dataclasses import dataclass

import numpy as np
from scipy.sparse import coo_matrix, diags
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import LinearOperator, cg
from app.simulations.errors import PreparationError
from app.simulations.limits import ExecutionLimits
import time


@dataclass(frozen=True)
class AirflowField:
    edge_flux: np.ndarray
    boundary_outflow: np.ndarray
    boundary_exchange: np.ndarray


def build_airflow(grid, settings, boundary, geometry=None, *, limits=None, resident_bytes=0):
    """Project device pushes and prescribed exterior potentials onto mass balance.

    boundary entries have cell_index, length_m, normal_x, normal_y.
    """
    limits = limits or ExecutionLimits()
    started = time.monotonic()
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
    speeds = {"low": .025, "medium": .05, "high": .1}
    for device in settings.devices:
        limits.check_deadline(started)
        loc = np.array([device.position_m.x, device.position_m.y])
        col = math.floor((loc[0] - grid.origin_m.x) / h)
        row = math.floor((loc[1] - grid.origin_m.y) / h)
        if not (0 <= row < grid.rows and 0 <= col < grid.columns and grid.active_mask[row, col]):
            raise PreparationError("invalid_airflow_device", f"Airflow device {device.id} must be inside the active domain.")
        angle = math.radians(device.direction_degrees)
        direction = np.array([math.cos(angle), math.sin(angle)])
        # Compact Gaussian momentum surrogate. The projection creates return flow.
        radius = 1.0 if device.type == "fan" else 1.5
        distance2 = ((midpoint - loc) ** 2).sum(axis=1)
        influence = np.exp(-distance2 / (2 * radius ** 2))
        if geometry is not None:
            # A fan cannot directly push air through a wall. Return flow is still
            # allowed through connected doorways during the pressure projection.
            import shapely
            from shapely import STRtree
            from app.simulations.engine.grid import _barriers
            from app.simulations.geometry import polygon_for

            barriers = _barriers(geometry, {item.opening_id for item in boundary})
            from shapely.geometry import Point
            if not polygon_for(geometry.indoor_domain).contains(Point(*loc)) or any(
                wall.distance(Point(*loc)) < 1e-9 for wall in barriers
            ):
                raise PreparationError("invalid_airflow_device", f"Airflow device {device.id} is on a wall or outside the domain.")
            visible = np.flatnonzero(influence > 1e-4)
            if len(visible):
                rays = shapely.linestrings(np.stack((np.broadcast_to(loc, (len(visible), 2)), midpoint[visible]), axis=1))
                influence[visible[~shapely.covers(polygon_for(geometry.indoor_domain), rays)]] = 0
            if barriers and len(visible):
                hits = STRtree(barriers).query(rays, predicate="intersects")
                influence[visible[np.unique(hits[0])]] = 0
        tentative += speeds[device.strength] * influence * (delta @ direction)

    if not len(edges) and not boundary:
        return AirflowField(tentative, np.zeros(0), np.zeros(0))
    # q_ij = q*_ij + h*(phi_i-phi_j); q_out = width*(phi_i-phi_out).
    # The correction is velocity-like, not calibrated physical pressure.
    rows = np.concatenate((a, b, a, b))
    cols = np.concatenate((a, b, b, a))
    vals = np.concatenate((np.full(len(a), h), np.full(len(a), h), np.full(2*len(a), -h)))
    lap = coo_matrix((vals, (rows, cols)), shape=(n, n)).tocsc()
    div = np.bincount(a, weights=tentative, minlength=n) - np.bincount(b, weights=tentative, minlength=n)
    cells = np.array([x.cell_index for x in boundary], dtype=int)
    widths = np.array([x.length_m for x in boundary], dtype=float)
    angle = math.radians(settings.wind_direction_degrees)
    wind = np.array([math.cos(angle), math.sin(angle)])
    wind_speed = {"calm": 0., "moderate": .02, "breezy": .05}[settings.outdoor_conditions]
    external = np.array([-wind_speed * np.dot(wind, [x.normal_x, x.normal_y]) for x in boundary])
    if len(cells):
        lap += diags(np.bincount(cells, weights=widths, minlength=n), format="csc")
    rhs = -div + np.bincount(cells, weights=widths * external, minlength=n)
    graph = coo_matrix((np.ones(2*len(a)), (np.r_[a,b], np.r_[b,a])), shape=(n,n)).tocsr()
    component_count, components = connected_components(graph, directed=False)
    has_boundary = np.zeros(component_count, dtype=bool)
    has_boundary[components[cells]] = True
    _, first = np.unique(components, return_index=True)
    anchors = first[~has_boundary[components[first]]]
    if len(anchors):
        anchor_diag = np.zeros(n)
        anchor_diag[anchors] = h
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
    flux = tentative + h * (phi[a] - phi[b])
    outflow = widths * (phi[cells] - external)
    # Per-height exchange m²/s; fixed effective velocity, not a measured window rate.
    exchange_speed = {"calm": .001, "moderate": .003, "breezy": .006}[settings.outdoor_conditions]
    return AirflowField(flux, outflow, widths * exchange_speed)
