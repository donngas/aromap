"""Validate already-resolved initial states; no migration or checkpoint storage."""

import hashlib
import json
import math

import numpy as np

from app.simulations.engine.models import PreparedGrid, PreparedSimulation, ResolvedInitialState
from app.simulations.errors import PreparationError


def grid_signature(grid: PreparedGrid) -> str:
    """Topology identity, independent of source position, duration, and emission."""
    digest = hashlib.sha256(json.dumps({
        "origin": grid.origin_m.model_dump(), "cell": grid.cell_size_m,
        "rows": grid.rows, "columns": grid.columns,
    }, sort_keys=True).encode())
    digest.update(grid.active_mask.tobytes(order="C"))
    digest.update(grid.connections.astype("<i8", copy=False).tobytes(order="C"))
    return digest.hexdigest()


def validate_initial_state(state: ResolvedInitialState, grid: PreparedGrid, model_version: str) -> ResolvedInitialState:
    """Accept only matching, resolved state. Never silently snap/resample/drop channels."""
    if state.grid_signature != grid_signature(grid) or state.model_version != model_version:
        raise PreparationError("incompatible_initial_state", "Initial state requires matching grid topology and model version.")
    if not math.isfinite(state.elapsed_time_s) or state.elapsed_time_s < 0:
        raise PreparationError("invalid_initial_state", "Elapsed simulation time must be finite and nonnegative.")
    identities = [channel.placement_id for channel in state.channels]
    if not identities or len(identities) != len(set(identities)) or any(
        not channel.placement_id or not channel.definition_id for channel in state.channels
    ):
        raise PreparationError("invalid_initial_state", "Initial state channel identities must be nonempty and unique.")
    definitions = {channel.placement_id: channel.definition_id for channel in state.channels}
    if any(definitions.get(source.placement_id) != source.definition_id for source in grid.source_weights):
        raise PreparationError("unresolved_initial_state", "Resolve every emitting placement into an initial-state channel first.")
    values = state.concentration
    if (not isinstance(values, np.ndarray) or values.dtype not in (np.dtype("float32"), np.dtype("float64"))
            or values.shape != (len(state.channels), grid.active_cell_count)
            or not np.isfinite(values).all() or np.any(values < 0)):
        raise PreparationError("invalid_initial_state", "Initial concentrations must be finite, nonnegative float values matching channels and active cells.")
    values = np.array(values, dtype=np.float64, copy=True, order="C")
    values.flags.writeable = False
    return ResolvedInitialState(state.grid_signature, state.model_version, state.elapsed_time_s,
                                tuple(state.channels), values)


def initial_state_fingerprint(state: ResolvedInitialState) -> str:
    digest = hashlib.sha256(json.dumps({
        "grid": state.grid_signature, "model": state.model_version, "elapsed": state.elapsed_time_s,
        "channels": [(channel.placement_id, channel.definition_id) for channel in state.channels],
        "units": "relative_units_per_m2",
    }, sort_keys=True).encode())
    digest.update(state.concentration.astype("<f8", copy=False).tobytes(order="C"))
    return digest.hexdigest()


def initial_concentrations(run: PreparedSimulation) -> np.ndarray:
    """Fresh writable solver array; time-zero fields are independent of output sampling."""
    if run.initial_state is not None:
        return run.initial_state.concentration.copy()
    return np.zeros((len(run.channels), run.grid.active_cell_count), dtype=np.float64)
