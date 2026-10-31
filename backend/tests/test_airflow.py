from dataclasses import replace
from types import SimpleNamespace

import numpy as np

from app.simulations.engine.airflow import build_airflow
from app.simulations.engine.solver import simulate
from app.simulations.models import AirflowSettings
from tests.test_solver_physics import _config, _prepare


def test_fan_projection_balances_each_cell_and_conserves_scent():
    run = _prepare(_config(duration=2, sample_times=(0, 2)), {"A1": 1})
    settings = AirflowSettings.model_validate({"devices": [{"id": "f", "type": "fan", "position_m": {"x": .5, "y": .5}, "direction_degrees": 0}]})
    field = build_airflow(run.grid, settings, ())
    a, b = run.grid.connections.T
    div = np.bincount(a, weights=field.edge_flux, minlength=run.grid.active_cell_count) - np.bincount(b, weights=field.edge_flux, minlength=run.grid.active_cell_count)
    np.testing.assert_allclose(div, 0, atol=1e-12)
    assert np.max(np.abs(field.edge_flux)) > 1e-5
    output = simulate(replace(run, airflow_field=field))
    np.testing.assert_allclose(output.concentration[-1].sum() * run.grid.cell_size_m ** 2, 2, rtol=1e-6)


def test_openings_balance_net_flow_and_exchange_removes_scent():
    run = _prepare(_config(duration=2, sample_times=(0, 2)), {"A1": 1})
    openings = (SimpleNamespace(cell_index=0, length_m=.25, normal_x=-1, normal_y=0),
                SimpleNamespace(cell_index=7, length_m=.25, normal_x=1, normal_y=0))
    field = build_airflow(run.grid, AirflowSettings(outdoor_conditions="breezy"), openings)
    np.testing.assert_allclose(field.boundary_outflow.sum(), 0, atol=1e-12)
    assert np.min(field.boundary_outflow) < 0 < np.max(field.boundary_outflow)
    assert np.all(field.boundary_exchange > 0)
    output = simulate(replace(run, airflow_field=field, exterior_openings=openings))
    assert 0 < output.concentration[-1].sum() * run.grid.cell_size_m ** 2 < 2


def test_open_window_end_to_end_and_zero_wind_exchange():
    from app.simulations.models import SimulationConfiguration
    body = _config(duration=2, sample_times=(0, 2)).model_dump()
    body['geometry_m']['walls'] = [{'id': 'north', 'start': {'x': 0, 'y': 0}, 'end': {'x': 2, 'y': 0}}]
    body['geometry_m']['windows'] = [{'id': 'w', 'wall_id': 'north', 'start': {'x': .5, 'y': 0}, 'end': {'x': 1, 'y': 0}}]
    body['opening_states'] = [{'opening_id': 'w', 'is_open': True}]
    run = _prepare(SimulationConfiguration.model_validate(body), {'A1': 1})
    assert len(run.exterior_openings) >= 1
    np.testing.assert_allclose(sum(e.length_m for e in run.exterior_openings), .5)
    np.testing.assert_allclose(run.airflow_field.boundary_outflow, 0, atol=1e-12)
    assert run.airflow_field.boundary_exchange.sum() > 0
    assert simulate(run).concentration[-1].sum() * .25**2 < 2


def test_device_configuration_changes_fingerprint_and_flow():
    from app.simulations.models import SimulationConfiguration
    body = _config().model_dump()
    plain = _prepare(SimulationConfiguration.model_validate(body), {'A1': 1})
    body['airflow']['devices'] = [{'id': 'f', 'type': 'fan', 'position_m': {'x': .5, 'y': .5}, 'direction_degrees': 0}]
    fan = _prepare(SimulationConfiguration.model_validate(body), {'A1': 1})
    assert plain.input.input_fingerprint != fan.input.input_fingerprint
    assert np.max(np.abs(fan.airflow_field.edge_flux)) > 0


def test_offset_exterior_door_and_courtyard_window():
    from app.simulations.models import SimulationConfiguration
    body = _config(width=4, height=4).model_dump()
    body['geometry_m']['indoor_domain']['holes'] = [[{'x': 1.5, 'y': 1.5}, {'x': 2.5, 'y': 1.5}, {'x': 2.5, 'y': 2.5}, {'x': 1.5, 'y': 2.5}]]
    body['geometry_m']['walls'] = [
        {'id': 'outer', 'start': {'x': .1, 'y': 0}, 'end': {'x': .1, 'y': 4}},
        {'id': 'court', 'start': {'x': 1.5, 'y': 1.5}, 'end': {'x': 2.5, 'y': 1.5}},
    ]
    body['geometry_m']['doors'] = [{'id': 'door', 'wall_id': 'outer', 'boundary_kind': 'exterior', 'start': {'x': .1, 'y': 1}, 'end': {'x': .1, 'y': 2}}]
    body['geometry_m']['windows'] = [{'id': 'window', 'wall_id': 'court', 'start': {'x': 1.75, 'y': 1.5}, 'end': {'x': 2.25, 'y': 1.5}}]
    body['opening_states'] = [{'opening_id': 'door', 'is_open': True}, {'opening_id': 'window', 'is_open': True}]
    body['placements'][0]['position_m'] = {'x': 1, 'y': .5}
    run = _prepare(SimulationConfiguration.model_validate(body), {'A1': 1})
    for opening_id, length in [('door', 1), ('window', .5)]:
        edges = [e for e in run.exterior_openings if e.opening_id == opening_id]
        np.testing.assert_allclose(sum(e.length_m for e in edges), length)
    assert all(e.normal_x < -.9 for e in run.exterior_openings if e.opening_id == 'door')
    assert all(e.normal_y > .9 for e in run.exterior_openings if e.opening_id == 'window')


def test_angled_boundary_opening_maps_without_losing_width():
    from app.simulations.models import SimulationConfiguration
    body = _config(width=4, height=4).model_dump()
    body['geometry_m']['indoor_domain']['boundary'] = [{'x': 0, 'y': 0}, {'x': 4, 'y': 0}, {'x': 4, 'y': 4}]
    body['geometry_m']['walls'] = [{'id': 'diagonal', 'start': {'x': 0, 'y': 0}, 'end': {'x': 4, 'y': 4}}]
    body['geometry_m']['windows'] = [{'id': 'w', 'wall_id': 'diagonal', 'start': {'x': 1, 'y': 1}, 'end': {'x': 2, 'y': 2}}]
    body['opening_states'] = [{'opening_id': 'w', 'is_open': True}]
    body['placements'][0]['position_m'] = {'x': 3, 'y': 1}
    run = _prepare(SimulationConfiguration.model_validate(body), {'A1': 1})
    np.testing.assert_allclose(sum(e.length_m for e in run.exterior_openings), np.sqrt(2))
    assert all(e.normal_x < 0 and e.normal_y > 0 for e in run.exterior_openings)


def test_closed_fan_preserves_uniform_concentration():
    from tests.test_solver_physics import _residual_run
    run = _residual_run(_config(duration=1, sample_times=(0, 1)), lambda grid, channels: np.full((1, grid.active_cell_count), 2.0))
    settings = AirflowSettings.model_validate({'devices': [{'id': 'f', 'type': 'fan', 'position_m': {'x': .5, 'y': .5}, 'direction_degrees': 0}]})
    field = build_airflow(run.grid, settings, ())
    output = simulate(replace(run, airflow_field=field))
    np.testing.assert_allclose(output.concentration[-1, 0][run.grid.active_mask], 2, atol=1e-6)


def test_fan_does_not_directly_drive_air_through_closed_wall():
    wall = {'id': 'wall', 'start': {'x': 1, 'y': 0}, 'end': {'x': 1, 'y': 1}}
    run = _prepare(_config(walls=[wall]), {'A1': 1})
    settings = AirflowSettings.model_validate({'devices': [{'id': 'f', 'type': 'fan', 'position_m': {'x': .5, 'y': .5}, 'direction_degrees': 0}]})
    field = build_airflow(run.grid, settings, (), run.input.geometry)
    cells = np.argwhere(run.grid.active_mask)
    right_cells = cells[:, 1] >= 4
    a, b = run.grid.connections.T
    np.testing.assert_allclose(field.edge_flux[right_cells[a] & right_cells[b]], 0, atol=1e-12)


def test_interior_door_near_exterior_wall_stays_connected():
    from app.simulations.models import SimulationConfiguration
    body = _config(width=2, height=2).model_dump()
    body['geometry_m']['walls'] = [
        {'id': 'outside', 'start': {'x': 0, 'y': 0}, 'end': {'x': 0, 'y': 2}},
        {'id': 'divider', 'start': {'x': .3, 'y': 0}, 'end': {'x': .3, 'y': 2}},
    ]
    body['geometry_m']['doors'] = [{'id': 'inside', 'wall_id': 'divider', 'start': {'x': .3, 'y': .5}, 'end': {'x': .3, 'y': 1.5}}]
    body['opening_states'] = [{'opening_id': 'inside', 'is_open': True}]
    body['placements'][0]['position_m'] = {'x': 1, 'y': 1}
    run = _prepare(SimulationConfiguration.model_validate(body), {'A1': 1})
    assert not run.exterior_openings
    left = run.grid.active_index[4, 0]
    right = run.grid.active_index[4, 1]
    assert any(set(edge) == {left, right} for edge in run.grid.connections)


def test_incomplete_near_boundary_wall_is_ambiguous():
    import pytest
    from app.simulations.errors import PreparationError
    from app.simulations.models import SimulationConfiguration
    body = _config(width=2, height=2).model_dump()
    body['geometry_m']['walls'] = [{'id': 'dangling', 'start': {'x': .2, 'y': .4}, 'end': {'x': .2, 'y': 1.6}}]
    body['geometry_m']['doors'] = [{'id': 'd', 'wall_id': 'dangling', 'start': {'x': .2, 'y': .7}, 'end': {'x': .2, 'y': 1.3}}]
    body['opening_states'] = [{'opening_id': 'd', 'is_open': True}]
    body['placements'][0]['position_m'] = {'x': 1, 'y': 1}
    with pytest.raises(PreparationError, match='does not separate enclosed regions'):
        _prepare(SimulationConfiguration.model_validate(body), {'A1': 1})


def test_projection_rejects_small_memory_budget_before_solve():
    import pytest
    from app.simulations.errors import PreparationError
    from app.simulations.limits import ExecutionLimits
    run = _prepare(_config(), {'A1': 1})
    settings = AirflowSettings.model_validate({'devices': [{'id': 'f', 'type': 'fan', 'position_m': {'x': .5, 'y': .5}, 'direction_degrees': 0}]})
    with pytest.raises(PreparationError, match='memory'):
        build_airflow(run.grid, settings, (), limits=ExecutionLimits(max_working_bytes=100))


def test_fan_advection_grid_and_time_refinement():
    """A smoothness/convergence check, not validation against a real room."""
    from app.simulations.engine.solver import SolverOptions
    from app.simulations.models import SimulationConfiguration

    fields = []
    middle_run = None
    for h in (.4, .2, .1):
        body = _config(width=4, height=4, cell=h, duration=60, sample_times=(60,), diffusivity=.005,
                       placements=[{'placement_id': 'A1', 'definition_id': 'A', 'position_m': {'x': 1.02, 'y': 1.02}}]).model_dump()
        body['airflow'] = {'devices': [{'id': 'f', 'type': 'fan', 'position_m': {'x': 2, 'y': 2}, 'direction_degrees': 0}]}
        run = _prepare(SimulationConfiguration.model_validate(body), {'A1': 1})
        if h == .2:
            middle_run = run
        values = simulate(run).concentration[-1, 0]
        factor = round(h / .1)
        fields.append(np.repeat(np.repeat(values, factor, axis=0), factor, axis=1))
    reference = fields[-1]
    errors = [float(np.abs(field - reference).sum() / reference.sum()) for field in fields[:2]]
    assert errors[1] < errors[0] < .35
    assert errors[1] < .23
    default = simulate(middle_run).concentration[-1]
    fine = simulate(middle_run, SolverOptions(max_step_s=.0625)).concentration[-1]
    assert np.abs(default - fine).sum() / fine.sum() < .01


def test_projection_reports_nonconvergence(monkeypatch):
    import pytest
    import app.simulations.engine.airflow as airflow
    from app.simulations.errors import PreparationError
    run = _prepare(_config(), {'A1': 1})
    settings = AirflowSettings.model_validate({'devices': [{'id': 'f', 'type': 'fan', 'position_m': {'x': .5, 'y': .5}, 'direction_degrees': 0}]})
    monkeypatch.setattr(airflow, 'cg', lambda matrix, rhs, **kw: (np.zeros_like(rhs), 1))
    with pytest.raises(PreparationError, match='did not converge'):
        build_airflow(run.grid, settings, ())


def test_offset_closed_outer_wall_identified_from_enclosure():
    from app.simulations.models import SimulationConfiguration
    body = _config(width=4, height=4).model_dump()
    body['geometry_m']['walls'] = [
        {'id': 'top', 'start': {'x': .1, 'y': .1}, 'end': {'x': 3.9, 'y': .1}},
        {'id': 'right', 'start': {'x': 3.9, 'y': .1}, 'end': {'x': 3.9, 'y': 3.9}},
        {'id': 'bottom', 'start': {'x': 3.9, 'y': 3.9}, 'end': {'x': .1, 'y': 3.9}},
        {'id': 'left', 'start': {'x': .1, 'y': 3.9}, 'end': {'x': .1, 'y': .1}},
    ]
    body['geometry_m']['doors'] = [{'id': 'd', 'wall_id': 'top', 'start': {'x': 1, 'y': .1}, 'end': {'x': 2, 'y': .1}}]
    body['opening_states'] = [{'opening_id': 'd', 'is_open': True}]
    body['placements'][0]['position_m'] = {'x': 1, 'y': 1}
    run = _prepare(SimulationConfiguration.model_validate(body), {'A1': 1})
    assert {edge.opening_id for edge in run.exterior_openings} == {'d'}
    assert all(edge.normal_y < -.9 for edge in run.exterior_openings)


def test_offset_wall_without_enclosure_requires_explicit_classification():
    import pytest
    from app.simulations.errors import PreparationError
    from app.simulations.models import SimulationConfiguration
    body = _config(width=4, height=4).model_dump()
    body['geometry_m']['walls'] = [{'id': 'wall', 'start': {'x': .1, 'y': 0}, 'end': {'x': .1, 'y': 4}}]
    body['geometry_m']['doors'] = [{'id': 'd', 'wall_id': 'wall', 'start': {'x': .1, 'y': 1}, 'end': {'x': .1, 'y': 2}}]
    body['opening_states'] = [{'opening_id': 'd', 'is_open': True}]
    body['placements'][0]['position_m'] = {'x': 1, 'y': 1}
    with pytest.raises(PreparationError, match='specify boundary_kind'):
        _prepare(SimulationConfiguration.model_validate(body), {'A1': 1})
    body['geometry_m']['doors'][0]['boundary_kind'] = 'exterior'
    assert _prepare(SimulationConfiguration.model_validate(body), {'A1': 1}).exterior_openings


def test_default_grid_airflow_against_finer_grid():
    from app.simulations.models import SimulationConfiguration
    fields = []
    for h in (.25, .125):
        body = _config(width=4, height=4, cell=h, duration=60, sample_times=(60,), diffusivity=.005,
                       placements=[{'placement_id': 'A1', 'definition_id': 'A', 'position_m': {'x': 1.02, 'y': 1.02}}]).model_dump()
        body['airflow'] = {'devices': [{'id': 'f', 'type': 'fan', 'position_m': {'x': 2, 'y': 2}, 'direction_degrees': 0}]}
        result = simulate(_prepare(SimulationConfiguration.model_validate(body), {'A1': 1})).concentration[-1, 0]
        fields.append(np.repeat(np.repeat(result, round(h / .125), axis=0), round(h / .125), axis=1))
    assert np.abs(fields[0] - fields[1]).sum() / fields[1].sum() < .3


def test_explicit_exterior_door_far_from_boundary_fails():
    import pytest
    from app.simulations.errors import PreparationError
    from app.simulations.models import SimulationConfiguration
    body = _config(width=4, height=4).model_dump()
    body['geometry_m']['walls'] = [{'id': 'divider', 'start': {'x': 2, 'y': 0}, 'end': {'x': 2, 'y': 4}}]
    body['geometry_m']['doors'] = [{'id': 'd', 'wall_id': 'divider', 'boundary_kind': 'exterior', 'start': {'x': 2, 'y': 1}, 'end': {'x': 2, 'y': 2}}]
    body['opening_states'] = [{'opening_id': 'd', 'is_open': True}]
    body['placements'][0]['position_m'] = {'x': 1, 'y': 1}
    with pytest.raises(PreparationError, match='not near the indoor boundary'):
        _prepare(SimulationConfiguration.model_validate(body), {'A1': 1})


def test_mixing_presets_and_medium_default_are_resolved_and_recorded():
    from app.simulations.models import SimulationConfiguration
    from app.simulations.limits import MIXING_PRESETS_M2_PER_S
    for name, expected in MIXING_PRESETS_M2_PER_S.items():
        body = _config().model_dump()
        body['settings']['effective_diffusivity_m2_per_s'] = None
        body['settings']['mixing_preset'] = name
        result = _prepare(SimulationConfiguration.model_validate(body), {'A1': 1})
        assert result.input.parameters.effective_diffusivity_m2_per_s == expected
        assert any(f'Mixing preset {name}:' in item for item in result.input.assumptions)
    body['settings']['mixing_preset'] = None
    result = _prepare(SimulationConfiguration.model_validate(body), {'A1': 1})
    assert result.input.parameters.effective_diffusivity_m2_per_s == MIXING_PRESETS_M2_PER_S['medium']


def test_wind_projection_converges_under_grid_refinement_and_reverses():
    from scripts.calibrate_presets import opening_run
    flows = []
    for h in (.125, .25, .5):
        run = opening_run(6, 6, cell=h, cross=True, outdoor='moderate')
        field = run.airflow_field
        a, b = run.grid.connections.T
        div = np.bincount(a, weights=field.edge_flux, minlength=run.grid.active_cell_count) - np.bincount(b, weights=field.edge_flux, minlength=run.grid.active_cell_count)
        div += np.bincount([e.cell_index for e in run.exterior_openings], weights=field.boundary_outflow, minlength=run.grid.active_cell_count)
        np.testing.assert_allclose(div, 0, atol=1e-10)
        flows.append(np.maximum(field.boundary_outflow, 0).sum())
    assert max(flows) / min(flows) < 1.04
    forward = opening_run(cross=True, outdoor='moderate', angle=90)
    reverse = opening_run(cross=True, outdoor='moderate', angle=270)
    parallel = opening_run(cross=True, outdoor='moderate', angle=0)
    np.testing.assert_allclose(forward.airflow_field.boundary_outflow, -reverse.airflow_field.boundary_outflow, atol=1e-10)
    np.testing.assert_allclose(parallel.airflow_field.boundary_outflow, 0, atol=1e-10)


def test_exterior_door_kind_reaches_airflow_and_presets_are_ordered():
    from scripts.calibrate_airflow import prepared
    from app.simulations.models import SimulationConfiguration
    window = prepared(4, 4, window=True)
    # Build a real API configuration rather than only substituting boundary metadata.
    body = _config(width=4, height=4).model_dump()
    body['geometry_m']['walls'] = [{'id': 'north', 'start': {'x': 0, 'y': 0}, 'end': {'x': 4, 'y': 0}}]
    body['geometry_m']['doors'] = [{'id': 'd', 'wall_id': 'north', 'boundary_kind': 'exterior', 'start': {'x': 1.6, 'y': 0}, 'end': {'x': 2.4, 'y': 0}}]
    body['opening_states'] = [{'opening_id': 'd', 'is_open': True}]
    values = []
    for condition in ('calm', 'moderate', 'breezy'):
        body['airflow']['outdoor_conditions'] = condition
        run = _prepare(SimulationConfiguration.model_validate(body), {'A1': 1})
        assert {e.kind for e in run.exterior_openings} == {'door'}
        values.append(run.airflow_field.boundary_exchange.sum())
    assert window.airflow_field.boundary_exchange.sum() < values[0] < values[1] < values[2]


def test_device_strength_changes_flow_without_creating_mass():
    from app.simulations.models import SimulationConfiguration
    for kind in ('fan', 'ac'):
        speeds = []
        for strength in ('low', 'medium', 'high'):
            body = _config(width=4, height=4).model_dump()
            body['airflow']['devices'] = [{'id': 'f', 'type': kind, 'position_m': {'x': 2, 'y': 2}, 'direction_degrees': 0, 'strength': strength}]
            run = _prepare(SimulationConfiguration.model_validate(body), {'A1': 1})
            speeds.append(np.max(np.abs(run.airflow_field.edge_flux)))
        assert 0 < speeds[0] < speeds[1] < speeds[2]


def test_timestep_caps_aggregate_loss_from_multiple_opening_pieces():
    import math
    from app.simulations.engine.airflow import AirflowField
    run = _prepare(_config(duration=2, sample_times=(0,2)), {'A1':1})
    boundary = (SimpleNamespace(cell_index=0), SimpleNamespace(cell_index=0))
    field = AirflowField(np.zeros(len(run.grid.connections)), np.zeros(2), np.array([.1,.1]))
    output = simulate(replace(run, airflow_field=field, exterior_openings=boundary))
    expected_max_step = .25 / (.2 / run.grid.cell_size_m**2)
    assert f'{math.ceil(2 / expected_max_step)} uniform steps' in output.diagnostics[0]


def test_gaussian_tail_cannot_drive_a_disconnected_room_beyond_visibility_cutoff():
    wall = {'id':'wall','start':{'x':6,'y':0},'end':{'x':6,'y':4}}
    run = _prepare(_config(width=12,height=4,walls=[wall]), {'A1':1})
    settings = AirflowSettings.model_validate({'devices':[{
        'id':'f','type':'fan','position_m':{'x':1,'y':2},'direction_degrees':0,'strength':'high'}]})
    field = build_airflow(run.grid, settings, (), run.input.geometry)
    right = np.argwhere(run.grid.active_mask)[:,1] >= 24
    a,b = run.grid.connections.T
    np.testing.assert_allclose(field.edge_flux[right[a]&right[b]], 0, atol=1e-12)
