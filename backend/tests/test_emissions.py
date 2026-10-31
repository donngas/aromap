"""Focused tests for the bounded consumption-v1 emission policy."""

import math

import pytest

from app.diffusers.models import ConsumerDiffuserDefinition
from app.simulations.emissions import resolve_emission
from app.simulations.errors import PreparationError
from app.simulations.models import DiffuserPlacement


def definition(**updates):
    values = {
        "id": "A", "name": "Reed example", "diffuser_type": "reed",
        "capacity": 100, "capacity_unit": "ml", "lifetime_days": 60,
    }
    values.update(updates)
    return ConsumerDiffuserDefinition(**values)


def placement(**updates):
    values = {"placement_id": "A1", "definition_id": "A", "position_m": {"x": 1, "y": 1}}
    values.update(updates)
    return DiffuserPlacement(**values)


def test_volume_capacity_uses_documented_default_density():
    profile = resolve_emission(definition(), placement())

    assert profile.kind == "constant"
    assert profile.rate_relative_units_per_s == pytest.approx(100 * 1000 / (60 * 24 * 3600))
    assert profile.rate_relative_units_per_s == pytest.approx(0.019290123, abs=1e-9)
    assert any("1 g/ml" in item and "engineering" in item for item in profile.assumptions)
    assert any("1 mg of consumed formulation" in item for item in profile.assumptions)


def test_gram_capacity_and_explicit_density_conversion():
    grams = resolve_emission(definition(capacity=60, capacity_unit="g"), placement())
    volume = resolve_emission(
        definition(capacity=100, capacity_unit="ml", density_g_per_ml=0.8), placement(),
    )
    ignored = resolve_emission(
        definition(capacity=60, capacity_unit="g", density_g_per_ml=2.0), placement(),
    )

    expected = 60 * 1000 / (60 * 24 * 3600)
    assert grams.rate_relative_units_per_s == pytest.approx(expected)
    assert volume.rate_relative_units_per_s == pytest.approx(100 * 0.8 * 1000 / (60 * 24 * 3600))
    assert ignored.rate_relative_units_per_s == pytest.approx(expected)
    assert not any("default density" in item for item in volume.assumptions)


def test_hours_override_and_zero_strength_without_truthiness_fallback():
    eight_hours = resolve_emission(definition(diffuser_type="electric", operating_hours_per_day=8), placement())
    overridden = resolve_emission(
        definition(diffuser_type="electric", operating_hours_per_day=8),
        placement(operating_hours_per_day_override=4),
    )
    passive = resolve_emission(definition(operating_hours_per_day=8), placement(operating_hours_per_day_override=4))
    zero = resolve_emission(definition(), placement(strength_override=0))

    assert eight_hours.rate_relative_units_per_s == pytest.approx(100 * 1000 / (60 * 8 * 3600))
    assert overridden.rate_relative_units_per_s == pytest.approx(100 * 1000 / (60 * 4 * 3600))
    # Reed is passive, so non-24 h ratings are ignored for its consumption estimate.
    assert passive.rate_relative_units_per_s == pytest.approx(100 * 1000 / (60 * 24 * 3600))
    assert any("ignored supplied non-24 h/day" in item for item in passive.assumptions)
    assert zero.rate_relative_units_per_s == 0


@pytest.mark.parametrize("kind,values,reason", [
    ("ultrasonic", {"capacity": 300, "capacity_unit": "ml"}, "unsupported diffuser type"),
    ("candle", {"capacity": 200, "capacity_unit": "g"}, "unsupported diffuser type"),
    ("nebulizer", {"capacity": 100, "capacity_unit": "ml"}, "unsupported diffuser type"),
    ("plug-in", {"capacity": None, "capacity_unit": None, "lifetime_days": None}, "missing usable refill capacity"),
])
def test_unsupported_or_missing_data_uses_reference_fallback(kind, values, reason):
    profile = resolve_emission(definition(diffuser_type=kind, **values), placement(strength_override=2))

    assert profile.rate_relative_units_per_s == pytest.approx(2 * 1000 / 86400)
    assert any(reason in item and "Fallback" in item for item in profile.assumptions)
    assert any("not inferred from packaging, water-tank, candle, or gel" in item for item in profile.assumptions)


def test_mutated_snapshots_and_nonrepresentable_estimates_are_rejected():
    mutated = definition()
    mutated.lifetime_days = math.inf
    with pytest.raises(PreparationError) as error:
        resolve_emission(mutated, placement())
    assert error.value.code == "invalid_emission"

    extreme = definition(capacity=1e308, lifetime_days=1e-300)
    with pytest.raises(PreparationError) as error:
        resolve_emission(extreme, placement())
    assert error.value.code == "invalid_emission"

    with pytest.raises(PreparationError) as error:
        resolve_emission(definition(capacity=1e9, lifetime_days=1), placement(strength_override=1e308))
    assert error.value.code == "invalid_emission"
