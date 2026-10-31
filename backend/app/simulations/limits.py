"""Operational limits for preparation; no physical parameters are chosen here."""

from dataclasses import dataclass

from app.simulations.errors import PreparationError

DEFAULT_CELL_SIZE_M = 0.25


@dataclass(frozen=True)
class PreparationLimits:
    max_cells: int = 100_000
    max_samples: int = 600
    max_placements: int = 16
    max_output_bytes: int = 256 * 1024 * 1024
    max_geometry_elements: int = 10_000

    def __post_init__(self):
        if any(value <= 0 for value in vars(self).values()):
            raise ValueError("Preparation limits must be positive")

    def check(self, count: int, maximum: int, label: str):
        if count > maximum:
            raise PreparationError("resource_limit", f"{label} exceeds the configured limit ({maximum}).")

    def output_bytes(self, samples: int, placements: int, rows: int, columns: int) -> int:
        # Planned float32 concentration [T,P,H,W] plus bool mask [H,W].
        # This bounds the sampled payload, not sparse-solver working memory.
        size = samples * placements * rows * columns * 4 + rows * columns
        self.check(size, self.max_output_bytes, "Estimated field payload")
        return size
