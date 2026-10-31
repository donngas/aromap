import math
from dataclasses import replace

import numpy as np
import pytest

from app.simulations.engine.models import ResolvedInitialState
from app.simulations.engine.solver import SolverOptions, simulate
from app.simulations.engine.state import grid_signature
from app.simulations.models import ResolvedEmissionProfile, SimulationConfiguration
from app.simulations.preparation import prepare_run
from app.simulations.errors import PreparationError, SimulationError
from app.simulations.limits import ExecutionLimits


def _placement(placement_id, definition_id, x=0.1, y=0.1):
    return {
        "placement_id": placement_id,
        "definition_id": definition_id,
        "position_m": {"x": x, "y": y},
    }


def _config(
    *, width=2.0, height=1.0, duration=2.0, sample_times=(0.0, 2.0), cell=0.25,
    diffusivity=0.02, removal=0.0, placements=None, walls=(), doors=(),
    opening_states=(), holes=(),
):
    return SimulationConfiguration.model_validate({
        "geometry_m": {
            "indoor_domain": {
                "boundary": [
                    {"x": 0.0, "y": 0.0}, {"x": width, "y": 0.0},
                    {"x": width, "y": height}, {"x": 0.0, "y": height},
                ],
                "holes": list(holes),
            },
            "walls": list(walls),
            "doors": list(doors),
        },
        "diffuser_definitions": [
            {"id": "A", "name": "A", "diffuser_type": "test"},
            {"id": "B", "name": "B", "diffuser_type": "test"},
        ],
        "placements": [_placement("A1", "A")] if placements is None else list(placements),
        "opening_states": list(opening_states),
        "conditions": {"removal_rate_per_s": removal},
        "settings": {
            "duration_s": duration,
            "sample_times_s": list(sample_times),
            "grid_cell_size_m": cell,
            "effective_diffusivity_m2_per_s": diffusivity,
        },
    })


def _prepare(configuration, rates, initial_state=None):
    def resolve_source(definition, placement):
        return ResolvedEmissionProfile(
            rate_relative_units_per_s=rates[placement.placement_id],
            assumptions=["test"],
        )

    return prepare_run(
        configuration, model_version="test", resolve_source=resolve_source,
        initial_state=initial_state,
    )


def _state(probe, concentration, channels=None):
    channels = channels or probe.channels
    return ResolvedInitialState(
        grid_signature(probe.grid), "test", 0.0, channels,
        np.asarray(concentration, dtype=np.float64),
    )


def _residual_run(configuration, concentration):
    rates = {placement.placement_id: 1.0 for placement in configuration.placements}
    probe = _prepare(configuration, rates)
    state = _state(probe, concentration(probe.grid, probe.channels))
    return _prepare(configuration.model_copy(update={"placements": []}), {}, initial_state=state)


def _active_totals(output, area):
    return output.concentration[:, 0].sum(axis=(1, 2)) * area


def test_conservation_uniform_state_and_zero_outside():
    run = _residual_run(
        _config(duration=1.5, sample_times=(0.0, 0.75, 1.5)),
        lambda grid, channels: np.full((1, grid.active_cell_count), 2.0),
    )
    output = simulate(run, SolverOptions(max_step_s=0.25))
    area = run.grid.cell_size_m ** 2
    np.testing.assert_allclose(_active_totals(output, area), 2.0 * area * run.grid.active_cell_count, rtol=1e-5)
    active = output.concentration[:, 0, run.grid.active_mask]
    np.testing.assert_allclose(active, 2.0, rtol=1e-6, atol=1e-6)
    np.testing.assert_array_equal(output.concentration[:, 0, ~run.grid.active_mask], 0.0)


def test_constant_source_total_is_rate_times_time_at_two_resolutions():
    rate = 1.5
    for cell in (0.25, 0.5):
        run = _prepare(
            _config(duration=2.0, sample_times=(0.0, 1.0, 2.0), cell=cell),
            {"A1": rate},
        )
        output = simulate(run, SolverOptions(max_step_s=0.25))
        totals = _active_totals(output, cell ** 2)
        np.testing.assert_allclose(totals, rate * output.sample_times_s, rtol=1e-6, atol=1e-6)
        assert totals[0] == 0.0


def test_uniform_residual_decay_matches_expected_and_converges():
    decay = 0.2
    initial = 4.0
    run = _residual_run(
        _config(duration=1.0, sample_times=(0.0, 1.0), removal=decay),
        lambda grid, channels: np.full((1, grid.active_cell_count), initial),
    )
    expected = initial * math.exp(-decay)
    coarse = simulate(run, SolverOptions(max_step_s=0.05))
    fine = simulate(run, SolverOptions(max_step_s=0.01))
    active = run.grid.active_mask
    coarse_error = np.max(np.abs(coarse.concentration[-1, 0, active] - expected))
    fine_error = np.max(np.abs(fine.concentration[-1, 0, active] - expected))
    assert coarse_error / expected < 0.01
    assert fine_error < coarse_error
    np.testing.assert_allclose(fine.concentration[-1, 0, active], expected, rtol=0.01)
    np.testing.assert_array_equal(fine.concentration[:, 0, ~active], 0.0)


def test_closed_divider_blocks_and_open_door_connects_without_mass_loss():
    wall = {"id": "divider", "start": {"x": 1.0, "y": 0.0}, "end": {"x": 1.0, "y": 1.0}}
    door = {
        "id": "door", "wall_id": "divider",
        "start": {"x": 1.0, "y": 0.25}, "end": {"x": 1.0, "y": 0.75},
    }
    hole = [
        {"x": 1.6, "y": 0.1}, {"x": 1.9, "y": 0.1},
        {"x": 1.9, "y": 0.4}, {"x": 1.6, "y": 0.4},
    ]

    def left_half(grid, channels):
        x = grid.origin_m.x + (np.arange(grid.columns) + 0.5) * grid.cell_size_m
        left = grid.active_mask & (x[None, :] < 1.0)
        values = np.zeros((1, grid.active_cell_count))
        values[0, grid.active_index[left]] = 1.0
        return values

    outcomes = {}
    for is_open in (False, True):
        config = _config(
            duration=2.0, sample_times=(0.0, 2.0), diffusivity=0.05,
            walls=[wall], doors=[door], holes=[hole],
            opening_states=[] if not is_open else [{"opening_id": "door", "is_open": True}],
        )
        run = _residual_run(config, left_half)
        outcomes[is_open] = (run, simulate(run, SolverOptions(max_step_s=0.25)))

    initial_total = 1.0 * outcomes[False][0].grid.active_mask[:, :4].sum() * 0.25 ** 2
    for run, output in outcomes.values():
        area = run.grid.cell_size_m ** 2
        np.testing.assert_allclose(_active_totals(output, area), initial_total, rtol=1e-4)
        np.testing.assert_array_equal(output.concentration[:, 0, ~run.grid.active_mask], 0.0)

    closed_grid, closed = outcomes[False]
    right = closed_grid.grid.active_mask[:, 4:]
    np.testing.assert_array_equal(closed.concentration[:, 0, :, 4:][:, right], 0.0)

    open_grid, opened = outcomes[True]
    right = open_grid.grid.active_mask[:, 4:]
    assert np.max(opened.concentration[-1, 0, :, 4:][right]) > 1e-4


def test_channel_mapping_order_residual_state_and_final_time():
    a = _placement("A1", "A", 0.1, 0.1)
    b = _placement("B1", "B", 1.9, 0.9)
    common = dict(duration=2.0, sample_times=(0.0, 1.0), diffusivity=0.02)
    rates = {"A1": 2.0, "B1": 3.0}

    single_a = simulate(_prepare(_config(placements=[a], **common), rates), SolverOptions(max_step_s=0.25))
    single_b = simulate(_prepare(_config(placements=[b], **common), rates), SolverOptions(max_step_s=0.25))
    for order in ([a, b], [b, a]):
        output = simulate(_prepare(_config(placements=order, **common), rates), SolverOptions(max_step_s=0.25))
        identifiers = [channel.placement_id for channel in output.channels]
        assert identifiers == [placement["placement_id"] for placement in order]
        np.testing.assert_allclose(output.concentration[:, identifiers.index("A1")], single_a.concentration[:, 0], rtol=1e-6)
        np.testing.assert_allclose(output.concentration[:, identifiers.index("B1")], single_b.concentration[:, 0], rtol=1e-6)

    probe = _prepare(_config(placements=[a, b], **common), rates)
    values = np.zeros((2, probe.grid.active_cell_count))
    values[0] = 1.0
    state = _state(probe, values)
    continued = _prepare(
        _config(placements=[b], duration=2.0, sample_times=(0.0, 1.0), diffusivity=0.02),
        {"B1": 3.0}, initial_state=state,
    )
    output = simulate(continued, SolverOptions(max_step_s=0.25))
    assert [channel.placement_id for channel in output.channels] == ["A1", "B1"]
    np.testing.assert_allclose(output.concentration[:, 1], single_b.concentration[:, 0], rtol=1e-6)

    area = probe.grid.cell_size_m ** 2
    residual_total = output.final_state.concentration[0].sum() * area
    np.testing.assert_allclose(residual_total, probe.grid.active_cell_count * area, rtol=1e-6)
    assert output.sample_times_s[-1] == 1.0
    assert output.final_state.elapsed_time_s == 2.0
    assert output.final_state.grid_signature == grid_signature(probe.grid)
    assert output.final_state.concentration.shape == (2, probe.grid.active_cell_count)
    assert np.max(output.final_state.concentration[1]) > np.max(output.concentration[-1, 1])


def test_timestep_convergence_and_output_schedule_independence():
    early = _prepare(_config(duration=1, sample_times=(1,), diffusivity=0.005), {"A1": 1})
    early_reference = simulate(early, SolverOptions(max_step_s=0.015625)).concentration
    early_default = simulate(early).concentration
    assert np.abs(early_default - early_reference).sum() / early_reference.sum() < 0.05
    run = _prepare(
        _config(duration=4.0, sample_times=(0.0, 4.0), diffusivity=0.01),
        {"A1": 1.0},
    )
    reference = simulate(run, SolverOptions(max_step_s=0.125))
    coarse = simulate(run, SolverOptions(max_step_s=1.0))
    fine = simulate(run, SolverOptions(max_step_s=0.5))
    reference_field = reference.concentration[-1, 0]
    coarse_error = np.max(np.abs(coarse.concentration[-1, 0] - reference_field))
    fine_error = np.max(np.abs(fine.concentration[-1, 0] - reference_field))
    assert fine_error < coarse_error

    sparse = _prepare(
        _config(duration=20.0, sample_times=(0.0, 10.13, 20.0), diffusivity=0.01),
        {"A1": 1.0},
    )
    dense = _prepare(
        _config(duration=20.0, sample_times=(0.0, 3.17, 10.13, 16.29, 20.0), diffusivity=0.01),
        {"A1": 1.0},
    )
    sparse_output = simulate(sparse, SolverOptions(max_step_s=0.5))
    dense_output = simulate(dense, SolverOptions(max_step_s=0.5))
    for sparse_index, time in ((1, 10.13), (2, 20.0)):
        dense_index = int(np.flatnonzero(dense_output.sample_times_s == time)[0])
        np.testing.assert_array_equal(
            sparse_output.concentration[sparse_index], dense_output.concentration[dense_index],
        )

    for prepared, output in ((sparse, sparse_output), (dense, dense_output)):
        assert output.concentration.dtype == np.float32
        assert output.concentration.shape == (
            len(output.sample_times_s), 1, prepared.grid.rows, prepared.grid.columns,
        )
        assert np.isfinite(output.concentration).all()
        assert np.all(output.concentration >= 0.0)


def test_spatial_refinement_converges_to_a_smooth_no_flux_solution():
    # A cosine profile has zero boundary gradient. Its analytic decay gives an
    # independent reference for the finite-volume geometry and diffusion scale.
    errors = []
    for cell in (0.5, 0.25, 0.125):
        config = _config(width=2, height=2, cell=cell, diffusivity=0.02,
                         duration=5, sample_times=(5,))
        def profile(grid, channels):
            x = (np.arange(grid.columns) + 0.5) * cell
            row = 1 + 0.25 * np.sinc(cell / 4) * np.cos(np.pi * x / 2)
            return np.broadcast_to(row, (grid.rows, grid.columns))[grid.active_mask][None, :].copy()
        run = _residual_run(config, profile)
        output = simulate(run, SolverOptions(max_step_s=0.01))
        x = (np.arange(run.grid.columns) + 0.5) * cell
        expected = 1 + 0.25 * np.sinc(cell / 4) * np.cos(np.pi * x / 2) * math.exp(-0.02 * (np.pi / 2) ** 2 * 5)
        errors.append(float(np.max(np.abs(output.concentration[-1, 0] - expected))))
    assert errors[2] < errors[1] < errors[0]


def test_solver_resource_guards_and_numerical_failures(monkeypatch):
    run = _prepare(_config(), {"A1": 1})
    with pytest.raises(PreparationError, match="too many internal"):
        simulate(run, SolverOptions(max_step_s=0.01, max_steps=1))
    with pytest.raises(PreparationError, match="working memory"):
        simulate(replace(run, execution_limits=ExecutionLimits(max_working_bytes=1)))
    with monkeypatch.context() as patch:
        clock = iter((0.0, 1.0))
        patch.setattr("app.simulations.engine.solver.time.monotonic", lambda: next(clock))
        with pytest.raises(PreparationError) as error:
            simulate(replace(run, execution_limits=ExecutionLimits(max_runtime_s=0.5)))
        assert error.value.code == "execution_timeout"
    with monkeypatch.context() as patch:
        def fail_factorization(matrix):
            raise RuntimeError("test failure")
        patch.setattr("app.simulations.engine.solver.splu", fail_factorization)
        with pytest.raises(SimulationError) as error:
            simulate(run)
        assert error.value.code == "solver_failure"
    huge = _prepare(_config(), {"A1": 1e40})
    with pytest.raises(SimulationError) as error:
        simulate(huge)
    assert error.value.code == "output_range"
