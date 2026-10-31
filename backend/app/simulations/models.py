"""Resolved run contracts. Preparation must detach these from editable state."""

from pydantic import BaseModel, Field

from app.floor_plans.models import Point


class MetricWall(BaseModel):
    start: Point
    end: Point


class MetricOpening(BaseModel):
    wall_index: int = Field(ge=0)
    start: Point
    end: Point


class SimulationGeometry(BaseModel):
    width_m: float = Field(gt=0)
    height_m: float = Field(gt=0)
    walls: list[MetricWall]
    open_doorways: list[MetricOpening]


class EmissionSource(BaseModel):
    placement_id: str
    position_m: Point
    rate_relative_units_per_s: float = Field(ge=0)


class SimulationInput(BaseModel):
    input_fingerprint: str
    solver_version: str
    geometry: SimulationGeometry
    sources: list[EmissionSource]
    duration_s: float = Field(gt=0)
    sample_interval_s: float = Field(gt=0)
    grid_cell_size_m: float = Field(gt=0)
    effective_diffusivity_m2_per_s: float = Field(gt=0)
    removal_rate_per_s: float = Field(ge=0)
    assumptions: list[str]


class SimulationResult(BaseModel):
    run_id: str
    input_snapshot: SimulationInput
    sample_times_s: list[float]
    concentration_unit: str = "relative_units_per_m2"
    field_artifact_id: str
    diagnostics: list[str] = Field(default_factory=list)
