"""Consumer product specifications used to derive bounded emission proxies."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConsumerDiffuserDefinition(BaseModel):
    """Raw product specifications; no claim of calibrated fragrance emission.

    ``capacity`` is the usable refill mass/volume consumed by the product, not
    packaging mass or an ultrasonic device's water-tank volume. ``lifetime_days``
    and ``operating_hours_per_day`` describe the rating conditions behind that
    usable capacity, not a runtime schedule. The simulation emits continuously
    while an enabled source is active.
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    diffuser_type: str = Field(min_length=1)
    capacity: float | None = Field(
        default=None, gt=0,
        description="Usable refill mass/volume, not packaging mass or ultrasonic water-tank volume.",
    )
    capacity_unit: Literal["ml", "g"] | None = Field(
        default=None, description="Physical unit of the usable refill capacity.",
    )
    density_g_per_ml: float | None = Field(
        default=None, gt=0,
        description=(
            "Refill-liquid density for converting an ml capacity to mass. "
            "A default of 1.0 g/ml is an engineering assumption, not a scientific calibration."
        ),
    )
    lifetime_days: float | None = Field(
        default=None, gt=0,
        description="Usable lifetime under the rated operating hours, not a calendar runtime schedule.",
    )
    operating_hours_per_day: float | None = Field(
        default=None, gt=0, le=24,
        description="Hours per day at which the lifetime is rated, not a runtime schedule.",
    )
    intensity: str | None = Field(
        default=None, description="Freeform label only; it is not an emission multiplier.",
    )
    provenance: Literal["user", "example"] = "user"

    @model_validator(mode="after")
    def capacity_has_units(self):
        if (self.capacity is None) != (self.capacity_unit is None):
            raise ValueError("Supply capacity and capacity_unit together")
        return self
