"""Simulation HTTP metadata; numerical fields are a separate artifact download."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.errors import ErrorDetail
from app.simulations.models import ContractModel, MetricPoint, SimulationConfiguration

PositiveInt = Annotated[int, Field(gt=0)]


class SimulationRequest(SimulationConfiguration):
    client_request_id: str = Field(min_length=1)


class SimulationAccepted(ContractModel):
    job_id: str
    client_request_id: str
    status_url: str


class GridMetadata(ContractModel):
    origin_m: MetricPoint = Field(description="Top-left grid corner in meters, in the calibrated layout frame.")
    cell_size_m: float = Field(gt=0, description="Cell side length in meters, not image pixels.")
    rows: PositiveInt = Field(description="Number of grid rows; an array count, not a physical distance.")
    columns: PositiveInt = Field(description="Number of grid columns; an array count, not a physical distance.")
    x_direction: Literal["right"] = "right"
    y_direction: Literal["down"] = "down"
    cell_position: Literal["center"] = Field(
        default="center", description="Values are at cell centers: origin_m + (index + 0.5) * cell_size_m.",
    )


class PlacementChannel(ContractModel):
    """List index maps to array channel index; one channel per simulated placement."""

    channel_id: str = Field(min_length=1)
    placement_id: str = Field(min_length=1)
    definition_id: str = Field(min_length=1)


class ActiveDomainMask(ContractModel):
    """Mask inside the fields bundle; true means usable indoor space."""

    axes: tuple[Literal["row"], Literal["column"]] = ("row", "column")
    shape: tuple[PositiveInt, PositiveInt]


class ConcentrationFields(ContractModel):
    """One download containing concentration and active_domain_mask arrays."""

    url: str = Field(min_length=1)
    encoding: str = Field(min_length=1, description="Bundle encoding, to be selected with the engine")
    axes: tuple[Literal["time"], Literal["channel"], Literal["row"], Literal["column"]] = (
        "time", "channel", "row", "column",
    )
    shape: tuple[PositiveInt, PositiveInt, PositiveInt, PositiveInt]
    units: Literal["relative_units_per_m2"] = Field(
        default="relative_units_per_m2",
        description="One relative unit is a surrogate for 1 mg consumed formulation, not measured fragrance mass or perceived intensity.",
    )
    active_domain_mask: ActiveDomainMask


class SimulationResult(ContractModel):
    run_id: str
    input_fingerprint: str
    model_version: str
    grid: GridMetadata
    channels: list[PlacementChannel] = Field(min_length=1)
    sample_times_s: list[float] = Field(min_length=1)
    fields: ConcentrationFields
    resolved_assumptions: list[str]
    diagnostics: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    expires_at: datetime

    @model_validator(mode="after")
    def dimensions_match_metadata(self):
        expected = (len(self.sample_times_s), len(self.channels), self.grid.rows, self.grid.columns)
        if self.fields.shape != expected:
            raise ValueError("Field shape must match times, channels, and grid")
        if self.fields.active_domain_mask.shape != (self.grid.rows, self.grid.columns):
            raise ValueError("Mask shape must match grid")
        if any(t < 0 for t in self.sample_times_s) or any(
            b <= a for a, b in zip(self.sample_times_s, self.sample_times_s[1:])
        ):
            raise ValueError("Sample times must be nonnegative and strictly increasing")
        for attribute in ("channel_id", "placement_id"):
            values = [getattr(c, attribute) for c in self.channels]
            if len(set(values)) != len(values):
                raise ValueError(f"Duplicate {attribute}")
        return self


class SimulationStatus(ContractModel):
    job_id: str
    client_request_id: str
    state: Literal["queued", "running", "succeeded", "failed"]
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    result: SimulationResult | None = None
    error: ErrorDetail | None = None

    @model_validator(mode="after")
    def payload_matches_state(self):
        if (self.state == "succeeded") != (self.result is not None):
            raise ValueError("Only a succeeded job has a result")
        if (self.state == "failed") != (self.error is not None):
            raise ValueError("Only a failed job has an error")
        return self
