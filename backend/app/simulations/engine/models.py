"""Numerical containers, independent of FastAPI, SQLite, and artifact encoding."""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from app.simulations.models import MetricPoint, SimulationInput


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


@dataclass(frozen=True)
class EngineOutput:
    """Future solver output: float concentration[T,P,H,W], no URLs/job IDs.

    Entries outside the active mask are zero. Output values and encoding remain
    the solver/artifact writer's responsibility; this is not a time-stepper.
    """

    grid: PreparedGrid
    sample_times_s: NDArray[np.float64]
    concentration: NDArray[np.floating]
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self):
        shape = (len(self.sample_times_s), len(self.grid.source_weights), self.grid.rows, self.grid.columns)
        if self.sample_times_s.ndim != 1 or self.concentration.shape != shape:
            raise ValueError("Engine output must align with time, placement channels, and grid")
