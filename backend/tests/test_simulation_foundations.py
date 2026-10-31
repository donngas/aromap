"""Integrated policy defaults, resource guards, and resolved-state handoff."""

from dataclasses import replace

import numpy as np
import pytest

from app.simulations.engine.models import EngineOutput, ResolvedInitialState, StateChannel
from app.simulations.engine.state import grid_signature, initial_concentrations
from app.simulations.errors import PreparationError
from app.simulations.limits import ExecutionLimits, PreparationLimits
from app.simulations.models import SimulationConfiguration
from app.simulations.preparation import prepare_input, prepare_run


def configuration():
    return SimulationConfiguration.model_validate({
        "geometry_m": {"indoor_domain": {"boundary": [
            {"x": 0, "y": 0}, {"x": 2, "y": 0}, {"x": 2, "y": 2}, {"x": 0, "y": 2},
        ]}},
        "diffuser_definitions": [{"id": "A", "name": "Reed", "diffuser_type": "reed",
                                  "capacity": 100, "capacity_unit": "ml", "lifetime_days": 60}],
        "placements": [{"placement_id": "A1", "definition_id": "A", "position_m": {"x": 0.1, "y": 0.1}}],
    })


def test_default_policy_and_explicit_overrides_are_reproducible():
    config = configuration()
    run = prepare_run(config, model_version="test")
    assert run.input.duration_s == 3600
    assert len(run.input.sample_times_s) == 121
    assert run.input.parameters.effective_diffusivity_m2_per_s == 0.005
    assert run.input.parameters.removal_rate_per_s == pytest.approx(0.5 / 3600)
    assert run.input.sources[0].profile.rate_relative_units_per_s == pytest.approx(100000 / (60 * 86400))
    assert run.input.input_fingerprint == prepare_input(config, model_version="test").input_fingerprint
    initial = initial_concentrations(run)
    assert initial.shape == (1, 64) and not initial.any()
    initial[0, 0] = 1
    assert not initial_concentrations(run).any()
    config.settings.effective_diffusivity_m2_per_s = 0.01
    config.conditions.removal_rate_per_s = 0
    overridden = prepare_input(config, model_version="test", effective_diffusivity_m2_per_s=0.02,
                               removal_rate_per_s=1)
    assert overridden.parameters.effective_diffusivity_m2_per_s == 0.01
    assert overridden.parameters.removal_rate_per_s == 0
    assert overridden.input_fingerprint != run.input.input_fingerprint


def test_duration_resolution_output_and_execution_budgets(monkeypatch):
    config = configuration()
    config.settings.duration_s = 21601
    with pytest.raises(PreparationError, match="duration"):
        prepare_run(config, model_version="test")
    config.settings.duration_s = 3600
    config.settings.grid_cell_size_m = 0.05
    with pytest.raises(PreparationError, match="resolution"):
        prepare_run(config, model_version="test")
    # The server can deliberately allow a finer resolution for future experiments.
    run = prepare_run(config, model_version="test", limits=PreparationLimits(min_cell_size_m=0.05,
                                                                           output_warning_bytes=1))
    assert any("Large sampled payload" in warning for warning in run.grid.warnings)
    with pytest.raises(PreparationError, match="working memory"):
        prepare_run(config, model_version="test", limits=PreparationLimits(min_cell_size_m=0.05),
                    execution_limits=ExecutionLimits(max_working_bytes=1))
    monkeypatch.setattr("app.simulations.limits.time.monotonic", lambda: 130.0)
    with pytest.raises(PreparationError) as error:
        ExecutionLimits(max_runtime_s=120).check_deadline(10.0)
    assert error.value.code == "execution_timeout"
    for invalid in (float("nan"), float("inf"), float("-inf"), -1, 10 ** 1000):
        with pytest.raises(PreparationError):
            ExecutionLimits().check_memory(invalid)
    ExecutionLimits().check_memory(0)
    ExecutionLimits().check_memory(512 * 1024 * 1024)


def test_resolved_state_preserves_residuals_and_new_channels_without_implicit_migration():
    config = configuration()
    config.settings.duration_s = 60
    config.placements.append(config.placements[0].model_copy(update={"placement_id": "new"}))
    zero = prepare_run(config, model_version="test")
    channels = (StateChannel("old", "removed-definition"), StateChannel("A1", "A"), StateChannel("new", "A"))
    values = np.zeros((3, zero.grid.active_cell_count), dtype=np.float64)
    values[0] = 2  # Residual from a removed emitter.
    values[1] = 1
    state = ResolvedInitialState(grid_signature(zero.grid), "test", 600, channels, values)
    continued = prepare_run(config, model_version="test", initial_state=state)
    assert continued.channels == channels
    assert continued.estimated_output_bytes == 3 * 3 * 8 * 8 * 4 + 64
    assert continued.input.initial_state_fingerprint
    assert continued.input.input_fingerprint != zero.input.input_fingerprint
    assert not continued.initial_state.concentration.flags.writeable
    values[0] = 99
    np.testing.assert_array_equal(initial_concentrations(continued)[0], 2)
    assert not initial_concentrations(continued)[2].any()
    EngineOutput(continued.grid, np.asarray(continued.input.sample_times_s),
                 np.zeros((3, 3, 8, 8), dtype=np.float32), channels=continued.channels)
    for bad in (replace(state, grid_signature="wrong"), replace(state, model_version="other"),
                replace(state, channels=channels[:2], concentration=values[:2]),
                replace(state, concentration=np.full_like(values, np.nan))):
        with pytest.raises(PreparationError):
            prepare_run(config, model_version="test", initial_state=bad)


def test_automatic_sampling_adapts_but_explicit_requests_are_not_changed():
    config = configuration()
    config.settings.duration_s = 21600
    # Preserve automatic mode across the same JSON persistence path used by FE.
    config = SimulationConfiguration.model_validate_json(config.model_dump_json())
    run = prepare_run(config, model_version="test")
    times = run.input.sample_times_s
    assert len(times) == 600 and times[0] == 0 and times[-1] == 21600
    assert all(b > a for a, b in zip(times, times[1:]))
    limited = prepare_run(config, model_version="test", limits=PreparationLimits(max_samples=2))
    assert limited.input.sample_times_s == [0, 21600]
    config.settings.sample_interval_s = 30
    with pytest.raises(PreparationError, match="Sample count"):
        prepare_run(config, model_version="test")
    config.settings.sample_interval_s = None
    config.settings.sample_times_s = [0, 100, 21600]
    assert prepare_run(config, model_version="test").input.sample_times_s == [0, 100, 21600]


def test_engine_output_rejects_invalid_fields_and_timestamps():
    run = prepare_run(configuration(), model_version="test")
    values = np.zeros((2, 1, run.grid.rows, run.grid.columns), dtype=np.float32)
    times = np.array([0.0, 1.0])
    assert EngineOutput(run.grid, times, values).channels == run.channels
    for bad_times in (np.array([]), np.array(0.0), np.array([0, np.nan]),
                      np.array([0, np.inf]), np.array([-1, 0]), np.array([1, 1]), np.array([1, 0])):
        with pytest.raises(ValueError, match="Sample times"):
            EngineOutput(run.grid, bad_times, values)
    for bad_value in (np.nan, np.inf, -np.inf, -0.01):
        bad = values.copy()
        bad[0, 0, 0, 0] = bad_value
        with pytest.raises(ValueError, match="finite and nonnegative"):
            EngineOutput(run.grid, times, bad)
    mask = run.grid.active_mask.copy()
    mask[0, 0] = False
    outside = values.copy()
    outside[0, 0, 0, 0] = 1
    with pytest.raises(ValueError, match="outside the active domain"):
        EngineOutput(replace(run.grid, active_mask=mask), times, outside)


def test_residual_only_runs_need_valid_state_and_preserve_its_channels():
    config = configuration()
    zero = prepare_run(config, model_version="test")
    state = ResolvedInitialState(grid_signature(zero.grid), "test", 600, zero.channels,
                                 np.ones((1, zero.grid.active_cell_count)))
    config.placements[0].enabled = False
    for placements in (list(config.placements), []):
        config.placements = placements
        continued = prepare_run(config, model_version="test", initial_state=state)
        assert continued.input.sources == [] and continued.grid.source_weights == ()
        assert continued.channels == zero.channels
        np.testing.assert_array_equal(initial_concentrations(continued), state.concentration)
        assert continued.estimated_output_bytes == zero.estimated_output_bytes
        EngineOutput(continued.grid, np.asarray(continued.input.sample_times_s),
                     np.zeros((121, 1, 8, 8), dtype=np.float32), channels=continued.channels)
        with pytest.raises(PreparationError, match="At least one placement"):
            prepare_run(config, model_version="test")
        with pytest.raises(PreparationError, match="matching grid"):
            prepare_run(config, model_version="test", initial_state=replace(state, grid_signature="wrong"))
