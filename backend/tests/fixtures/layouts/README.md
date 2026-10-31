Metric configurations for standalone previews, independent of image recognition:

- `closed_door.json`: two 5 × 6 m rooms, closed 1 m doorway, one source on the left.
- `open_door.json`: same layout and source with the doorway open.
- `split_placement.json`: open doorway, two half-strength sources, one in each room.
- `courtyard.json`: L-shaped footprint with an excluded courtyard and connected rooms.

All use 25 cm cells, 1 hour, 30-second output snapshots, default spreading/removal,
and the same total emission proxy (one 200 mL / 60 day reed refill, or two at half
strength). They are illustrative scenarios, not calibrated measurements.
Use a shared `--scale-max 8` for density comparisons. The viewer's optional log density
transform must also match across files; it never changes numerical concentrations.

Physics conservation, decay, and boundary assertions live in `test_solver_physics.py`.
