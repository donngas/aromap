"""Metric configuration contracts and provisional resolved solver inputs."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.diffusers.models import ConsumerDiffuserDefinition
from app.simulations.limits import DEFAULT_DURATION_S


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class MetricPoint(ContractModel):
    """Meters, top-left origin, x rightward and y downward; FE applies scale."""

    x: float = Field(description="Horizontal distance in meters from the calibrated image origin; rightward.")
    y: float = Field(description="Vertical distance in meters from the calibrated image origin; downward.")


class IndoorDomain(ContractModel):
    """Metric simulation footprint, not the pixel-domain recognition estimate.

    Vertices are in boundary order; closing edges are implicit.
    Holes exclude outdoor/unusable areas. Preparation validates polygon topology;
    it does not infer the footprint from the rectangular image extent.
    """

    boundary: list[MetricPoint] = Field(
        min_length=3, description="Ordered outer perimeter vertices in meters, after FE calibration.",
    )
    holes: list[list[MetricPoint]] = Field(
        default_factory=list, description="Excluded interior polygons in meters; not internal rooms/walls.",
    )

    @model_validator(mode="after")
    def holes_have_vertices(self):
        if any(len(hole) < 3 for hole in self.holes):
            raise ValueError("Each hole needs at least three vertices")
        return self


class WallGeometry(ContractModel):
    id: str = Field(min_length=1)
    start: MetricPoint = Field(description="Wall start in meters, not image or display pixels.")
    end: MetricPoint = Field(description="Wall end in meters, not image or display pixels.")


class OpeningGeometry(ContractModel):
    id: str = Field(min_length=1)
    wall_id: str = Field(min_length=1)
    start: MetricPoint = Field(description="Opening start on its parent wall, in meters.")
    end: MetricPoint = Field(description="Opening end on its parent wall, in meters.")
    boundary_kind: Literal["interior", "exterior"] | None = Field(
        default=None, description="Optional classification for ambiguous wall geometry."
    )


class MetricGeometry(ContractModel):
    indoor_domain: IndoorDomain = Field(description="User-reviewed indoor footprint converted to meters by FE.")
    walls: list[WallGeometry] = Field(default_factory=list)
    doors: list[OpeningGeometry] = Field(default_factory=list)
    windows: list[OpeningGeometry] = Field(default_factory=list)


class DiffuserPlacement(ContractModel):
    placement_id: str = Field(min_length=1)
    definition_id: str = Field(min_length=1)
    position_m: MetricPoint = Field(description="Source placement in meters; not recognition pixels.")
    strength_override: float | None = Field(
        default=None, ge=0, description="Explicit dimensionless emission multiplier; defaults to 1. Zero emits nothing.",
    )
    enabled: bool = True
    operating_hours_per_day_override: float | None = Field(
        default=None, gt=0, le=24,
        description="Override lifetime-rated hours/day for estimation, not an on/off schedule. Passive reeds remain continuous.",
    )


class OpeningState(ContractModel):
    """Door/window state; omitted entries resolve to closed during preparation."""

    opening_id: str = Field(min_length=1)
    is_open: bool


class EnvironmentalConditions(ContractModel):
    """Uniform removal; preparation uses a provisional 0.5 air changes/hour default."""

    removal_rate_per_s: float | None = Field(default=None, ge=0)


class AirflowDevice(ContractModel):
    id: str = Field(min_length=1)
    type: Literal["fan", "ac"]
    position_m: MetricPoint
    direction_degrees: float = Field(description="Direction toward which air travels: 0 right, 90 down.")
    strength: Literal["low", "medium", "high"] = "medium"


class AirflowSettings(ContractModel):
    outdoor_conditions: Literal["calm", "moderate", "breezy"] = "calm"
    wind_direction_degrees: float = Field(default=0, description="Direction toward which wind travels: 0 right, 90 down.")
    devices: list[AirflowDevice] = Field(default_factory=list, max_length=8)


class SimulationSettings(ContractModel):
    duration_s: float = Field(default=DEFAULT_DURATION_S, gt=0)
    sample_interval_s: float | None = Field(
        default=None, gt=0,
        description="Explicit output interval. Omit both sampling fields for automatic sampling within the sample limit.",
    )
    sample_times_s: list[float] | None = None
    grid_cell_size_m: float | None = Field(
        default=None, gt=0, description="Cell side length in meters; omission selects a workload/geometry-aware grid starting at 0.25 m.",
    )
    effective_diffusivity_m2_per_s: float | None = Field(default=None, gt=0)
    mixing_preset: Literal["low", "medium", "high"] | None = None

    @model_validator(mode="after")
    def resolve_sampling(self):
        if self.mixing_preset is not None and self.effective_diffusivity_m2_per_s is not None:
            raise ValueError("Supply mixing_preset or effective_diffusivity_m2_per_s, not both")
        if self.sample_interval_s is not None and self.sample_times_s is not None:
            raise ValueError("Supply at most one of sample_interval_s or sample_times_s")
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

    Geometry and positions are FE-derived meters. Preparation validates geometry,
    estimates relative emissions, and resolves provisional spreading/removal defaults.
    The optional airflow configuration describes an idealized steady field.
    """

    geometry_m: MetricGeometry = Field(
        description="All geometry coordinates in meters, converted by FE; no image pixels or calibration required.",
    )
    diffuser_definitions: list[ConsumerDiffuserDefinition] = Field(default_factory=list)
    placements: list[DiffuserPlacement] = Field(
        default_factory=list, description="Current placements; empty is meaningful only with a resolved internal initial state.",
    )
    opening_states: list[OpeningState] = Field(default_factory=list)
    conditions: EnvironmentalConditions = Field(default_factory=EnvironmentalConditions)
    airflow: AirflowSettings = Field(default_factory=AirflowSettings)
    settings: SimulationSettings = Field(default_factory=SimulationSettings)

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
        unique([d.id for d in self.airflow.devices], "airflow device IDs")
        if any(p.definition_id not in definitions for p in self.placements):
            raise ValueError("Placement references an unknown definition")
        if any(o.wall_id not in walls for o in openings):
            raise ValueError("Opening references an unknown wall")
        if any(s.opening_id not in opening_ids for s in self.opening_states):
            raise ValueError("State references an unknown opening")
        return self


class ResolvedOpening(OpeningGeometry):
    kind: Literal["door", "window"]
    is_open: bool


class SimulationGeometry(ContractModel):
    """Resolved metric geometry; the grid derives its extent from the polygon."""

    indoor_domain: IndoorDomain
    walls: list[WallGeometry]
    openings: list[ResolvedOpening]


class ResolvedEmissionProfile(ContractModel):
    """Explicit rate supplied by a resolver, including all placement overrides.

    One relative unit is a surrogate for 1 mg consumed formulation, not measured
    fragrance mass or scent perception. Operating schedules remain future work.
    """

    kind: Literal["constant"] = "constant"
    rate_relative_units_per_s: float = Field(ge=0)
    assumptions: list[str] = Field(min_length=1)


class EmissionSource(ContractModel):
    placement_id: str
    definition_id: str
    position_m: MetricPoint
    profile: ResolvedEmissionProfile


class ModelParameters(ContractModel):
    effective_diffusivity_m2_per_s: float = Field(gt=0)
    removal_rate_per_s: float = Field(ge=0)


class SimulationInput(ContractModel):
    """Detached resolved snapshot. Contains no client/job IDs or image pixels."""

    input_fingerprint: str
    model_version: str
    preparation_version: str
    geometry: SimulationGeometry
    sources: list[EmissionSource] = Field(
        default_factory=list, description="Current emitters; residual-only prepared runs have no emission sources.",
    )
    duration_s: float = Field(gt=0)
    sample_times_s: list[float] = Field(min_length=1)
    grid_cell_size_m: float = Field(gt=0)
    parameters: ModelParameters
    airflow: AirflowSettings = Field(default_factory=AirflowSettings)
    assumptions: list[str]
    initial_state_fingerprint: str | None = Field(
        default=None, description="Internal resolved initial-state identity; null means zero start. Not a job ID.",
    )
