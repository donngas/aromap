"""Browser-owned editable project document; not a database schema."""

from typing import Literal

from pydantic import BaseModel, Field

from app.diffusers.models import DiffuserDefinition
from app.floor_plans.models import FloorPlan, PixelPoint


class DiffuserPlacement(BaseModel):
    id: str
    definition_id: str
    position: PixelPoint
    strength_override: float | None = Field(default=None, ge=0)
    enabled: bool = True


class EnvironmentalConditions(BaseModel):
    removal_rate_per_s: float = Field(ge=0)


class SimulationSettings(BaseModel):
    duration_s: float = Field(gt=0)
    sample_interval_s: float = Field(gt=0)
    grid_cell_size_m: float = Field(gt=0)
    effective_diffusivity_m2_per_s: float = Field(gt=0)


class OpeningState(BaseModel):
    """Scenario state referencing a door/window ID in the project's layout."""

    opening_id: str
    is_open: bool


class Scenario(BaseModel):
    """Editable conditions; omitted opening states resolve to closed.

    Preparation must reject unknown or duplicate opening references. An open
    window's physical effect is a separate, as-yet undefined simulation policy.
    """

    id: str
    name: str
    placements: list[DiffuserPlacement] = Field(default_factory=list)
    opening_states: list[OpeningState] = Field(default_factory=list)
    conditions: EnvironmentalConditions
    settings: SimulationSettings


class ProjectDocument(BaseModel):
    schema_version: Literal[1] = 1
    id: str
    name: str
    floor_plan: FloorPlan
    diffuser_definitions: list[DiffuserDefinition] = Field(default_factory=list)
    scenarios: list[Scenario] = Field(default_factory=list)
    active_scenario_id: str | None = None
