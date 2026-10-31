"""Conservative automatic spatial policy; explicit request resolution always wins."""
import math

from app.simulations.geometry import polygon_for


def automatic_cell_size(geometry, *, base_cell_m, channels, duration_s, samples, limits):
    polygon = polygon_for(geometry.indoor_domain)
    left, top, right, bottom = polygon.bounds
    # Bound solve work as channels/duration grow, and bound dense output too.
    target = 6000 / math.sqrt(max(1, channels)) * min(1., math.sqrt(3600 / duration_s))
    target = min(target, limits.max_cells, limits.max_output_bytes / (4 * max(1, channels) * samples + 1))
    desired = math.sqrt((right - left) * (bottom - top) / max(1., target))
    # Small increments avoid large jumps in quality at area thresholds.
    cell = min(limits.max_cell_size_m, max(base_cell_m, math.ceil(desired / .05) * .05))
    return round(cell, 10)


def protect_features(geometry, opening_states, cell, base_cell):
    # Keep two cells across open apertures where the baseline permits it.
    opened = {s.opening_id for s in opening_states if s.is_open}
    for opening in [*geometry.doors, *geometry.windows]:
        if opening.id in opened:
            width = math.hypot(opening.end.x - opening.start.x, opening.end.y - opening.start.y)
            cell = min(cell, max(base_cell, math.floor((width / 2 + 1e-9) / .05) * .05))
    polygon = polygon_for(geometry.indoor_domain)
    # Avoid introducing a new loss of footprint connectivity relative to the
    # baseline's erosion. Fine internal door connectivity is checked on the grid.
    def components(h):
        inset = polygon.buffer(-h / 2)
        return 0 if inset.is_empty else len(getattr(inset, 'geoms', [inset]))
    baseline = components(base_cell)
    while cell > base_cell + 1e-9 and components(cell) != baseline:
        cell = max(base_cell, round(cell - .05, 10))
    return round(cell, 10)
