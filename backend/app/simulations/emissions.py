"""Bounded consumer-to-source emission estimation from usable refill data.

One relative unit is a surrogate for one milligram of consumed formulation. It is
not a measured fragrance chemical mass or a measure of perceived scent intensity.
"""

import math

from pydantic import ValidationError

from app.diffusers.models import ConsumerDiffuserDefinition
from app.simulations.errors import PreparationError
from app.simulations.models import DiffuserPlacement, ResolvedEmissionProfile

METHOD_VERSION = "consumption-v1"
REFERENCE_RATE_PER_S = 1000.0 / 86400.0
DEFAULT_DENSITY_G_PER_ML = 1.0

_SUPPORTED_TYPES = frozenset({
    "reed", "reed_diffuser", "passive", "passive_diffuser",
    "plug_in", "electric", "electric_diffuser", "liquid", "evaporative",
    "heated_oil",
})
_PASSIVE_TYPES = frozenset({"reed", "reed_diffuser", "passive", "passive_diffuser"})

_UNIT_ASSUMPTION = (
    "One relative unit is a surrogate for 1 mg of consumed formulation, not measured "
    "fragrance chemical mass or perceived scent."
)
_CONTINUOUS_ASSUMPTION = "The resolved source is a constant profile that emits continuously while enabled."
_CORRECTION_ASSUMPTION = (
    "Environmental, temperature, airflow, and reed correction multipliers are fixed at 1; "
    "no unsupported correction equation or intensity-label multiplier was applied."
)


def _invalid(message: str, cause: Exception | None = None) -> PreparationError:
    error = PreparationError("invalid_emission", message)
    if cause is not None:
        error.__cause__ = cause
    return error


def _normalized_type(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _apply_strength(baseline: float, strength: float) -> float:
    if strength == 0:
        return 0.0
    try:
        rate = math.exp(math.log(baseline) + math.log(strength))
    except (OverflowError, ValueError) as exc:
        raise _invalid("Emission rate is not representable with the supplied strength.", exc)
    if not math.isfinite(rate) or rate <= 0:
        raise _invalid("Emission rate is not representable with the supplied strength.")
    return rate


def resolve_emission(
    definition: ConsumerDiffuserDefinition, placement: DiffuserPlacement,
) -> ResolvedEmissionProfile:
    """Resolve a constant rate using only documented capacity/lifetime proxies.

    The definition and placement are revalidated first so mutations of model
    instances cannot bypass their finite/range constraints.
    """
    try:
        definition = ConsumerDiffuserDefinition.model_validate(
            definition.model_dump(include=set(ConsumerDiffuserDefinition.model_fields))
        )
        placement = DiffuserPlacement.model_validate(
            placement.model_dump(include=set(DiffuserPlacement.model_fields))
        )
    except (ValidationError, AttributeError) as exc:
        raise _invalid("Diffuser definition or placement failed revalidation.", exc)

    strength = 1.0 if placement.strength_override is None else placement.strength_override
    assumptions = [
        _UNIT_ASSUMPTION,
        _CONTINUOUS_ASSUMPTION,
        _CORRECTION_ASSUMPTION,
        (
            f"Emission method {METHOD_VERSION}: usable formulation mass divided by lifetime-rated "
            "operating seconds; this capacity/lifetime proxy is not a scientific calibration."
        ),
        f"Applied explicit dimensionless strength multiplier {strength!r}; it defaults to 1 and zero is honored.",
    ]

    diffuser_type = _normalized_type(definition.diffuser_type)
    fallback_reason = None
    if diffuser_type not in _SUPPORTED_TYPES:
        fallback_reason = f"unsupported diffuser type {definition.diffuser_type!r}"
    elif definition.capacity is None or definition.capacity_unit is None or definition.lifetime_days is None:
        fallback_reason = "missing usable refill capacity or rated lifetime"

    if fallback_reason is not None:
        baseline = REFERENCE_RATE_PER_S
        assumptions.append(
            f"Fallback reference rate 1000 mg / 86400 s (1 g/day) used because of {fallback_reason}; "
            "this is an engineering choice, not a measured product rate."
        )
        assumptions.append("Fallback capacity is not inferred from packaging, water-tank, candle, or gel total mass.")
        return ResolvedEmissionProfile(
            rate_relative_units_per_s=_apply_strength(baseline, strength), assumptions=assumptions,
        )

    rating_hours = (
        placement.operating_hours_per_day_override
        if placement.operating_hours_per_day_override is not None
        else definition.operating_hours_per_day
    )
    if diffuser_type in _PASSIVE_TYPES:
        if rating_hours is not None and not math.isclose(rating_hours, 24.0):
            assumptions.append(
                f"Passive reed diffuser assumed continuous 24 h/day; ignored supplied non-24 h/day "
                f"rating of {rating_hours!r}."
            )
        else:
            assumptions.append("Passive reed diffuser assumed continuous at 24 h/day.")
        effective_hours = 24.0
    elif rating_hours is None:
        effective_hours = 24.0
        assumptions.append("Rated operating hours defaulted to 24 h/day because none was supplied.")
    else:
        effective_hours = rating_hours
        source = "placement override" if placement.operating_hours_per_day_override is not None else "definition"
        assumptions.append(f"Rated operating hours {effective_hours!r} h/day came from the {source}.")

    assumptions.append(
        f"Rated hours are a lifetime-estimate condition for {effective_hours!r} h/day, not a runtime schedule; "
        "emission remains continuous while the source is enabled."
    )

    log_mass_g = math.log(definition.capacity)
    if definition.capacity_unit == "ml":
        density = definition.density_g_per_ml
        if density is None:
            density = DEFAULT_DENSITY_G_PER_ML
            assumptions.append(
                "Volume-to-mass conversion used the explicit engineering default density of 1 g/ml; "
                "this is not a scientific calibration."
            )
        else:
            assumptions.append(f"Volume-to-mass conversion used the supplied refill-liquid density {density!r} g/ml.")
        log_mass_g += math.log(density)
        capacity_description = f"{definition.capacity!r} ml at {density!r} g/ml"
    else:
        assumptions.append("Capacity is expressed in grams; no density conversion was applied.")
        if definition.density_g_per_ml is not None:
            assumptions.append("The supplied density_g_per_ml was ignored for a gram capacity.")
        capacity_description = f"{definition.capacity!r} g"

    log_baseline = (
        log_mass_g + math.log(1000.0) - math.log(definition.lifetime_days)
        - math.log(effective_hours) - math.log(3600.0)
    )
    try:
        baseline = math.exp(log_baseline)
    except OverflowError as exc:
        raise _invalid("Baseline emission estimate is not representable.", exc)
    if not math.isfinite(baseline) or baseline <= 0:
        raise _invalid("Baseline emission estimate is not a positive representable number.")

    assumptions.append(
        f"Baseline inputs: {capacity_description}, lifetime {definition.lifetime_days!r} days, "
        f"rated {effective_hours!r} h/day; baseline rate {baseline!r} relative units/s before strength."
    )
    return ResolvedEmissionProfile(
        rate_relative_units_per_s=_apply_strength(baseline, strength), assumptions=assumptions,
    )
