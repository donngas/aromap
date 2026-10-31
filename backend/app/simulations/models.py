"""Resolved run contracts. Preparation must detach these from editable state."""

from pydantic import BaseModel, Field

from app.diffusers.models import DiffuserDefinition
from app.floor_plans.models import Layout, PixelPoint


class DiffuserPlacement(BaseModel):
    id: str
    definition_id: str
    position: PixelPoint
    strength_override: float | None = Field(default=None, ge=0)
    enabled: bool = True


class OpeningState(BaseModel):
    """Door/window state; omitted entries resolve to closed during preparation."""

    opening_id: str
    is_open: bool


class EnvironmentalConditions(BaseModel):
    removal_rate_per_s: float = Field(ge=0)


class SimulationSettings(BaseModel):
    duration_s: float = Field(gt=0)
    sample_interval_s: float = Field(gt=0)
    grid_cell_size_m: float = Field(gt=0)
    effective_diffusivity_m2_per_s: float = Field(gt=0)


class SimulationConfiguration(BaseModel):
    """One submitted configuration, not a saved frontend scenario.

    Draft shape pending engine design: future requests will carry FE-derived
    metric geometry. Backend preparation validates geometry, ID references, and
    duplicate opening states. Open-window modeling remains undefined.
    """

    layout: Layout
    diffuser_definitions: list[DiffuserDefinition] = Field(default_factory=list)
    placements: list[DiffuserPlacement] = Field(default_factory=list)
    opening_states: list[OpeningState] = Field(default_factory=list)
    conditions: EnvironmentalConditions
    settings: SimulationSettings


class MetricPoint(BaseModel):
    """Meters: same top-left origin and axis directions as the editable layout.

    Future requests supply FE-derived metric positions; the engine never
    interprets image dimensions or screen coordinates.
    """

    x: float
    y: float


class MetricWall(BaseModel):
    start: MetricPoint
    end: MetricPoint


class MetricOpening(BaseModel):
    wall_index: int = Field(ge=0)
    start: MetricPoint
    end: MetricPoint


class SimulationGeometry(BaseModel):
    width_m: float = Field(gt=0)
    height_m: float = Field(gt=0)
    walls: list[MetricWall]
    open_doorways: list[MetricOpening]


class EmissionSource(BaseModel):
    placement_id: str
    position_m: MetricPoint
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
