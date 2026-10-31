"""Metric configuration contracts and provisional resolved solver inputs."""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.diffusers.models import ConsumerDiffuserDefinition


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class MetricPoint(ContractModel):
    """Meters, top-left origin, x rightward and y downward; FE applies scale."""

    x: float
    y: float


class IndoorDomain(ContractModel):
    """Draft footprint polygon; vertices in boundary order, closing edge implied.

    Holes exclude outdoor/unusable areas. Polygon topology is checked by future
    preparation, not inferred from the image rectangle by this contract.
    """

    boundary: list[MetricPoint] = Field(min_length=3)
    holes: list[list[MetricPoint]] = Field(default_factory=list)

    @model_validator(mode="after")
    def holes_have_vertices(self):
        if any(len(hole) < 3 for hole in self.holes):
            raise ValueError("Each hole needs at least three vertices")
        return self


class WallGeometry(ContractModel):
    id: str = Field(min_length=1)
    start: MetricPoint
    end: MetricPoint


class OpeningGeometry(ContractModel):
    id: str = Field(min_length=1)
    wall_id: str = Field(min_length=1)
    start: MetricPoint
    end: MetricPoint


class MetricGeometry(ContractModel):
    indoor_domain: IndoorDomain
    walls: list[WallGeometry] = Field(default_factory=list)
    doors: list[OpeningGeometry] = Field(default_factory=list)
    windows: list[OpeningGeometry] = Field(default_factory=list)


class DiffuserPlacement(ContractModel):
    placement_id: str = Field(min_length=1)
    definition_id: str = Field(min_length=1)
    position_m: MetricPoint
    strength_override: float | None = Field(default=None, ge=0)
    enabled: bool = True
    operating_hours_per_day_override: float | None = Field(default=None, gt=0, le=24)


class OpeningState(ContractModel):
    """Door/window state; omitted entries resolve to closed during preparation."""

    opening_id: str = Field(min_length=1)
    is_open: bool


class EnvironmentalConditions(ContractModel):
    """Omitted values await engine defaults; no scientific defaults chosen here."""

    removal_rate_per_s: float | None = Field(default=None, ge=0)


class SimulationSettings(ContractModel):
    duration_s: float = Field(gt=0)
    sample_interval_s: float | None = Field(default=None, gt=0)
    sample_times_s: list[float] | None = None
    grid_cell_size_m: float | None = Field(default=None, gt=0)
    effective_diffusivity_m2_per_s: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def sampling_is_explicit(self):
        if (self.sample_interval_s is None) == (self.sample_times_s is None):
            raise ValueError("Supply exactly one of sample_interval_s or sample_times_s")
        if self.sample_interval_s is not None and self.sample_interval_s > self.duration_s:
            raise ValueError("Sampling interval must not exceed duration")
        if self.sample_times_s is not None:
            if not self.sample_times_s or any(t < 0 or t > self.duration_s for t in self.sample_times_s):
                raise ValueError("Sample times must be nonempty and within duration")
            if any(b <= a for a, b in zip(self.sample_times_s, self.sample_times_s[1:])):
                raise ValueError("Sample times must be strictly increasing")
        return self


class SimulationConfiguration(ContractModel):
    """One submitted configuration, not a saved frontend scenario.

    Geometry and positions are FE-derived meters. Full geometry validation,
    source estimation, open-window behavior, and engine limits remain future work.
    """

    geometry_m: MetricGeometry
    diffuser_definitions: list[ConsumerDiffuserDefinition] = Field(default_factory=list)
    placements: list[DiffuserPlacement] = Field(min_length=1)
    opening_states: list[OpeningState] = Field(default_factory=list)
    conditions: EnvironmentalConditions = Field(default_factory=EnvironmentalConditions)
    settings: SimulationSettings

    @model_validator(mode="after")
    def references_are_consistent(self):
        def unique(values, label):
            if len(values) != len(set(values)):
                raise ValueError(f"Duplicate {label}")
            return set(values)

        definitions = unique([d.id for d in self.diffuser_definitions], "definition IDs")
        unique([p.placement_id for p in self.placements], "placement IDs")
        walls = unique([w.id for w in self.geometry_m.walls], "wall IDs")
        openings = self.geometry_m.doors + self.geometry_m.windows
        opening_ids = unique([o.id for o in openings], "door/window IDs")
        unique([s.opening_id for s in self.opening_states], "opening states")
        if any(p.definition_id not in definitions for p in self.placements):
            raise ValueError("Placement references an unknown definition")
        if any(o.wall_id not in walls for o in openings):
            raise ValueError("Opening references an unknown wall")
        if any(s.opening_id not in opening_ids for s in self.opening_states):
            raise ValueError("State references an unknown opening")
        return self


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
