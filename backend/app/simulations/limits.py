"""Operational limits for preparation; no physical parameters are chosen here."""

from dataclasses import dataclass
import math
import time

from app.simulations.errors import PreparationError

DEFAULT_CELL_SIZE_M = 0.25
DEFAULT_DURATION_S = 3600.0
DEFAULT_SAMPLE_INTERVAL_S = 30.0
DEFAULT_DIFFUSIVITY_M2_PER_S = 0.005
DEFAULT_AIR_CHANGES_PER_HOUR = 0.5
DEFAULT_REMOVAL_RATE_PER_S = DEFAULT_AIR_CHANGES_PER_HOUR / 3600


@dataclass(frozen=True)
class PreparationLimits:
    max_cells: int = 100_000
    max_samples: int = 600
    max_placements: int = 16
    max_output_bytes: int = 256 * 1024 * 1024
    max_geometry_elements: int = 10_000
    max_duration_s: float = 6 * 3600
    min_cell_size_m: float = 0.10
    max_cell_size_m: float = 1.0
    output_warning_bytes: int = 64 * 1024 * 1024

    def __post_init__(self):
        if any(not math.isfinite(value) or value <= 0 for value in vars(self).values()):
            raise ValueError("Preparation limits must be finite and positive")
        if self.min_cell_size_m > self.max_cell_size_m:
            raise ValueError("Minimum cell size must not exceed maximum")

    def check_resolution(self, cell_size_m: float):
        if not math.isfinite(cell_size_m) or not self.min_cell_size_m <= cell_size_m <= self.max_cell_size_m:
            raise PreparationError("invalid_resolution", "Cell size is outside the supported resolution range.")

    def check(self, count: int, maximum: int, label: str):
        if count > maximum:
            raise PreparationError("resource_limit", f"{label} exceeds the configured limit ({maximum}).")

    def output_bytes(self, samples: int, placements: int, rows: int, columns: int) -> int:
        # Planned float32 concentration [T,P,H,W] plus bool mask [H,W].
        # This bounds the sampled payload, not sparse-solver working memory.
        size = samples * placements * rows * columns * 4 + rows * columns
        self.check(size, self.max_output_bytes, "Estimated field payload")
        return size


@dataclass(frozen=True)
class ExecutionLimits:
    """Solver guardrails; a future worker must additionally enforce a hard timeout.

    Array checks cover declared allocations, not native-library peak RSS. A solver
    must check its own working-set estimate before allocating/factorizing.
    """

    max_runtime_s: float = 120.0
    max_working_bytes: int = 512 * 1024 * 1024

    def __post_init__(self):
        if any(not math.isfinite(value) or value <= 0 for value in vars(self).values()):
            raise ValueError("Execution limits must be finite and positive")

    def check_memory(self, estimated_bytes: int):
        if (not isinstance(estimated_bytes, (int, float)) or isinstance(estimated_bytes, bool)
                or estimated_bytes < 0 or estimated_bytes > self.max_working_bytes
                or not math.isfinite(estimated_bytes)):
            raise PreparationError("resource_limit", "Estimated solver working memory exceeds the configured budget.")

    def check_deadline(self, started_at: float):
        if time.monotonic() - started_at >= self.max_runtime_s:
            raise PreparationError("execution_timeout", "Simulation execution exceeded the configured time budget.")
