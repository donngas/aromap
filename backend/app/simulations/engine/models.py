"""Numerical containers, independent of FastAPI, SQLite, and artifact encoding."""

from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from app.simulations.models import MetricPoint, SimulationInput
from app.simulations.limits import ExecutionLimits


@dataclass(frozen=True)
class SourceWeights:
    placement_id: str
    definition_id: str
    cell_indices: NDArray[np.int64]
    weights: NDArray[np.float64]


@dataclass(frozen=True)
class PreparedGrid:
    origin_m: MetricPoint
    cell_size_m: float
    rows: int
    columns: int
    active_mask: NDArray[np.bool_]
    active_index: NDArray[np.int64]  # Row-major compact indices; -1 outside.
    connections: NDArray[np.int64]  # Undirected pairs, each stored once.
    source_weights: tuple[SourceWeights, ...]  # Same channel order as input.sources.
    warnings: tuple[str, ...]

    @property
    def active_cell_count(self) -> int:
        return int(self.active_mask.sum())

    def expand(self, values: NDArray) -> NDArray:
        """Expand [..., active_cell] to [..., row, column], zero outside the mask."""
        if values.ndim < 1 or values.shape[-1] != self.active_cell_count:
            raise ValueError("Compact values must end with the active-cell dimension")
        expanded = np.zeros((*values.shape[:-1], self.rows, self.columns), dtype=values.dtype)
        expanded[..., self.active_mask] = values
        return expanded


@dataclass(frozen=True)
class PreparedSimulation:
    input: SimulationInput
    grid: PreparedGrid
    estimated_output_bytes: int
    initial_state: "ResolvedInitialState | None" = None
    estimated_working_bytes: int = 0
    execution_limits: ExecutionLimits = field(default_factory=ExecutionLimits)

    @property
    def channels(self) -> tuple["StateChannel", ...]:
        if self.initial_state is not None:
            return self.initial_state.channels
        return tuple(StateChannel(source.placement_id, source.definition_id) for source in self.grid.source_weights)


@dataclass(frozen=True)
class StateChannel:
    """Identity independent of a currently enabled emitter; residual channels survive."""

    placement_id: str
    definition_id: str


@dataclass(frozen=True)
class ResolvedInitialState:
    """Internal resolver output, not a public checkpoint/migration request.

    Values are compact concentration[channel, active_cell] in relative units/m².
    A future resolver owns channel reconciliation and geometry/grid migration.
    """

    grid_signature: str
    model_version: str
    elapsed_time_s: float
    channels: tuple[StateChannel, ...]
    concentration: NDArray[np.float64]


@dataclass(frozen=True)
class EngineOutput:
    """Future solver output: float32 concentration[T,P,H,W], no URLs/job IDs.

    Values must be finite and nonnegative, with zero outside the active mask.
    Any numerical roundoff correction belongs to the solver before publication.
    """

    grid: PreparedGrid
    sample_times_s: NDArray[np.float64]
    concentration: NDArray[np.float32]
    diagnostics: tuple[str, ...] = ()
    channels: tuple[StateChannel, ...] | None = None

    def __post_init__(self):
        if not isinstance(self.concentration, np.ndarray) or self.concentration.dtype != np.dtype(np.float32):
            raise ValueError("Sampled concentration must use float32 to respect the output budget")
        times = self.sample_times_s
        if (not isinstance(times, np.ndarray) or times.ndim != 1 or times.size == 0
                or times.dtype.kind not in "fiu" or not np.isfinite(times).all()
                or np.any(times < 0) or np.any(times[1:] <= times[:-1])):
            raise ValueError("Sample times must be nonempty, finite, nonnegative, and strictly increasing")
        channels = tuple(self.channels) if self.channels is not None else tuple(
            StateChannel(source.placement_id, source.definition_id) for source in self.grid.source_weights
        )
        identifiers = [channel.placement_id for channel in channels]
        if (not channels or len(set(identifiers)) != len(identifiers)
                or any(not channel.placement_id or not channel.definition_id for channel in channels)):
            raise ValueError("Engine output channels must be nonempty and unique")
        definitions = {channel.placement_id: channel.definition_id for channel in channels}
        if any(definitions.get(source.placement_id) != source.definition_id for source in self.grid.source_weights):
            raise ValueError("Engine output channels must include all emitting placements")
        shape = (len(self.sample_times_s), len(channels), self.grid.rows, self.grid.columns)
        if self.concentration.shape != shape:
            raise ValueError("Engine output must align with time, placement channels, and grid")
        # Validate one frame at a time to avoid payload-sized temporary masks.
        for frame in self.concentration:
            if not np.isfinite(frame).all() or np.any(frame < 0):
                raise ValueError("Sampled concentrations must be finite and nonnegative")
            if np.any(frame[:, ~self.grid.active_mask] != 0):
                raise ValueError("Sampled concentrations outside the active domain must be zero")
        object.__setattr__(self, "channels", channels)
