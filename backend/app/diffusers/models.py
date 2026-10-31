"""Relative emission profiles, independent of product concentration claims."""

from typing import Literal

from pydantic import BaseModel, Field


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
