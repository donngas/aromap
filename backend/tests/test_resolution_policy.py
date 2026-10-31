"""Quality and override contracts for automatic resolution."""
import pytest

from tests.test_simulation_preparation import configuration, OPTIONS
from app.simulations.preparation import prepare_run
from app.simulations.models import OpeningState, OpeningGeometry, WallGeometry
from app.simulations.limits import PreparationLimits
from app.simulations.resolution import automatic_cell_size


@pytest.mark.parametrize('side,expected', [(25,.25),(25.01,.3),(30,.3),(35,.35),(40,.4),(50,.5)])
def test_single_channel_hour_spatial_thresholds(side, expected):
    config = configuration(side, side)
    assert automatic_cell_size(config.geometry_m, base_cell_m=.25, channels=1,
                               duration_s=3600, samples=121, limits=PreparationLimits()) == expected


def test_three_channel_six_hour_case_gets_one_finer_increment():
    config = configuration(15, 15)
    assert automatic_cell_size(config.geometry_m, base_cell_m=.25, channels=3,
                               duration_s=21600, samples=600, limits=PreparationLimits()) == .35


def test_small_spaces_keep_baseline_large_spaces_coarsen_and_explicit_wins():
    small = configuration(4, 4)
    assert prepare_run(small, **OPTIONS).grid.cell_size_m == .25
    large = configuration(30, 30)
    coarse = prepare_run(large, **OPTIONS)
    assert .25 < coarse.grid.cell_size_m <= 1
    large.settings.grid_cell_size_m = .25
    explicit = prepare_run(large, **OPTIONS)
    assert explicit.grid.cell_size_m == .25
    assert explicit.grid.active_cell_count > coarse.grid.active_cell_count
    assert explicit.input.input_fingerprint != coarse.input.input_fingerprint


def test_workload_increases_resolution_budget_pressure():
    config = configuration(20, 20)
    first = prepare_run(config, **OPTIONS)
    config.settings.duration_s = 6 * 3600
    config.settings.sample_interval_s = None
    for i in range(3):
        config.placements.append(config.placements[0].model_copy(update={'placement_id': f'extra{i}'}))
    later = prepare_run(config, **OPTIONS)
    assert later.grid.cell_size_m > first.grid.cell_size_m


def test_open_door_limits_coarsening_and_stays_connected():
    config = configuration(30, 30)
    config.geometry_m.walls = [WallGeometry.model_validate({'id':'partition','start':{'x':15,'y':0},'end':{'x':15,'y':30}})]
    config.geometry_m.doors = [OpeningGeometry.model_validate({'id':'d','wall_id':'partition','start':{'x':15,'y':14.6},'end':{'x':15,'y':15.4}})]
    config.opening_states = [OpeningState(opening_id='d',is_open=True)]
    run = prepare_run(config, **OPTIONS)
    assert run.grid.cell_size_m <= .4
    assert not any('no represented cell connection' in warning for warning in run.grid.warnings)


def test_automatic_source_mapping_refines_instead_of_snapping_across_wall():
    config = configuration(30, 30)
    config.geometry_m.walls = [WallGeometry.model_validate({
        'id':'thin-room','start':{'x':.15,'y':0},'end':{'x':.15,'y':30}})]
    run = prepare_run(config, **OPTIONS)
    assert run.grid.cell_size_m == .25
    assert any('refined to preserve source/door mapping' in a for a in run.input.assumptions)
    assert run.estimated_output_bytes == (len(run.input.sample_times_s)*4 + 1) * run.grid.rows * run.grid.columns
    assert run.input.input_fingerprint == prepare_run(config, **OPTIONS).input.input_fingerprint


def test_exterior_door_does_not_trigger_interior_connectivity_refinement():
    config = configuration(30, 30)
    config.geometry_m.walls = [WallGeometry.model_validate({'id':'outer','start':{'x':0,'y':0},'end':{'x':30,'y':0}})]
    config.geometry_m.doors = [OpeningGeometry.model_validate({'id':'d','wall_id':'outer','boundary_kind':'exterior','start':{'x':14.6,'y':0},'end':{'x':15.4,'y':0}})]
    config.opening_states = [OpeningState(opening_id='d',is_open=True)]
    run = prepare_run(config, **OPTIONS)
    assert run.grid.cell_size_m == .3
    assert {edge.kind for edge in run.exterior_openings} == {'door'}
    assert not any('no represented cell connection' in warning for warning in run.grid.warnings)


def test_automatic_grid_refines_for_device_in_thin_footprint_extension():
    import pytest
    from app.simulations.models import MetricPoint, AirflowSettings
    from app.simulations.errors import PreparationError
    config = configuration(40, 40)
    config.placements[0].position_m = MetricPoint(x=2,y=2)
    config.geometry_m.indoor_domain.boundary = [MetricPoint(x=x,y=y) for x,y in
        [(0,0),(40,0),(40,40),(1,40),(1,.18),(0,.18)]]
    assert prepare_run(config, **OPTIONS).grid.cell_size_m == .4
    config.airflow = AirflowSettings.model_validate({'devices':[{
        'id':'fan','type':'fan','position_m':{'x':.1,'y':.1},'direction_degrees':0}]})
    run = prepare_run(config, **OPTIONS)
    assert run.grid.cell_size_m == .35
    assert run.airflow_field is not None
    config.settings.grid_cell_size_m = .4
    with pytest.raises(PreparationError) as error:
        prepare_run(config, **OPTIONS)
    assert error.value.code == 'unresolved_airflow_device'
