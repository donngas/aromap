"""Relative emission profiles, independent of product concentration claims."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConsumerDiffuserDefinition(BaseModel):
    """Raw product specifications; no claim of calibrated fragrance emission."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    diffuser_type: str = Field(min_length=1)
    capacity: float | None = Field(default=None, gt=0)
    capacity_unit: Literal["ml", "g"] | None = None
    lifetime_days: float | None = Field(default=None, gt=0)
    operating_hours_per_day: float | None = Field(default=None, gt=0, le=24)
    intensity: str | None = None
    provenance: Literal["user", "example"] = "user"

    @model_validator(mode="after")
    def capacity_has_units(self):
        if (self.capacity is None) != (self.capacity_unit is None):
            raise ValueError("Supply capacity and capacity_unit together")
        return self


class RelativeEmissionProfile(BaseModel):
    kind: Literal["constant"] = "constant"
    rate_relative_units_per_s: float = Field(ge=0)


class DiffuserDefinition(BaseModel):
    id: str
    name: str
    diffuser_type: str | None = None
    emission: RelativeEmissionProfile
    default_strength: float = Field(default=1.0, ge=0)
    provenance: Literal["example", "user", "calibrated"] = "user"
    assumptions: list[str] = Field(default_factory=list)
