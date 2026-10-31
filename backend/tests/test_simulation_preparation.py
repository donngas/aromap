"""Grid behavior and preparation boundaries; no numerical solver tests yet."""

import numpy as np
import pytest

from app.simulations.errors import PreparationError
from app.simulations.limits import PreparationLimits
from app.simulations.models import ResolvedEmissionProfile, SimulationConfiguration
from app.simulations.preparation import prepare_input, prepare_run


def configuration(width=2, height=1):
    return SimulationConfiguration.model_validate({
        "geometry_m": {"indoor_domain": {"boundary": [
            {"x": 0, "y": 0}, {"x": width, "y": 0},
            {"x": width, "y": height}, {"x": 0, "y": height},
        ]}},
        "diffuser_definitions": [{"id": "A", "name": "A", "diffuser_type": "test"}],
        "placements": [{"placement_id": "A1", "definition_id": "A", "position_m": {"x": 0.1, "y": 0.1}}],
        "settings": {"duration_s": 1, "sample_interval_s": 0.3},
    })


def resolve_source(definition, placement):
    return ResolvedEmissionProfile(
        rate_relative_units_per_s=3 * (placement.strength_override if placement.strength_override is not None else 1),
        assumptions=["Test-only explicit rate, including the placement strength override."],
    )


OPTIONS = dict(resolve_source=resolve_source, model_version="test-model",
               effective_diffusivity_m2_per_s=0.1, removal_rate_per_s=0)


def test_default_grid_snapshot_and_per_placement_mapping():
    config = configuration(1, 1)
    config.placements.append(config.placements[0].model_copy(update={"placement_id": "A2", "strength_override": 2}))
    config.placements.append(config.placements[0].model_copy(update={"placement_id": "off", "enabled": False}))
    before = config.model_dump()
    run = prepare_run(config, **OPTIONS)
    grid = run.grid
    assert grid.cell_size_m == 0.25
    assert (grid.rows, grid.columns, grid.active_cell_count) == (4, 4, 16)
    assert grid.connections.shape == (24, 2)
    np.testing.assert_array_equal(grid.active_index, np.arange(16).reshape(4, 4))
    assert [s.placement_id for s in grid.source_weights] == ["A1", "A2"]
    assert [s.profile.rate_relative_units_per_s for s in run.input.sources] == [3, 6]
    for source in grid.source_weights:
        assert source.cell_indices.tolist() == [0]
        assert source.weights.sum() == 1
    assert run.input.sample_times_s == pytest.approx([0, 0.3, 0.6, 0.9, 1])
    assert run.estimated_output_bytes == 5 * 2 * 4 * 4 * 4 + 16
    assert config.model_dump() == before
    assert prepare_input(config, **OPTIONS).input_fingerprint == run.input.input_fingerprint
    config.placements[0].position_m.x = 0.2
    assert run.input.sources[0].position_m.x == 0.1
    assert prepare_input(config, **OPTIONS).input_fingerprint != run.input.input_fingerprint


def test_metric_origin_override_and_explicit_sampling():
    body = configuration(1, 1).model_dump()
    for point in body["geometry_m"]["indoor_domain"]["boundary"]:
        point["x"] += 10
        point["y"] -= 3
    body["placements"][0]["position_m"] = {"x": 10.1, "y": -2.9}
    body["settings"].update(grid_cell_size_m=0.5, sample_interval_s=None, sample_times_s=[0.2, 0.7])
    run = prepare_run(SimulationConfiguration.model_validate(body), **OPTIONS)
    assert run.grid.origin_m.model_dump() == {"x": 10, "y": -3}
    assert (run.grid.rows, run.grid.columns) == (2, 2)
    assert run.input.sample_times_s == [0.2, 0.7]


def test_concave_domain_and_hole_mask():
    body = configuration(4, 4).model_dump()
    body["geometry_m"]["indoor_domain"] = {
        "boundary": [{"x": x, "y": y} for x, y in ((0, 0), (4, 0), (4, 2), (2, 2), (2, 4), (0, 4))],
        "holes": [[{"x": x, "y": y} for x, y in ((0.5, 0.5), (1.5, 0.5), (1.5, 1.5), (0.5, 1.5))]],
    }
    grid = prepare_run(SimulationConfiguration.model_validate(body), **OPTIONS).grid
    assert grid.active_cell_count == 176  # 11 m² at 0.25² m² per cell.
    assert not grid.active_mask[12, 12]  # Missing leg of the L.
    assert not grid.active_mask[3, 3]  # Courtyard.
    assert grid.active_index[3, 3] == -1
    expanded = grid.expand(np.ones((2, 1, grid.active_cell_count)))
    assert expanded.shape == (2, 1, 16, 16)
    assert expanded[0, 0, 3, 3] == 0
    assert expanded[0, 0, 0, 0] == 1


def test_connections_do_not_shortcut_a_subcell_hole():
    body = configuration(1, 1).model_dump()
    body["geometry_m"]["indoor_domain"]["holes"] = [[
        {"x": x, "y": y} for x, y in ((0.24, 0.01), (0.26, 0.01), (0.26, 0.99), (0.24, 0.99))
    ]]
    grid = prepare_run(SimulationConfiguration.model_validate(body), **OPTIONS).grid
    assert grid.active_mask[0, 0] and grid.active_mask[0, 1]
    assert (0, 1) not in set(map(tuple, grid.connections))


def divided_room(open_door=False, start=0.25, end=0.75):
    body = configuration().model_dump()
    body["geometry_m"].update(
        walls=[{"id": "divider", "start": {"x": 1, "y": 0}, "end": {"x": 1, "y": 1}}],
        doors=[{"id": "door", "wall_id": "divider", "start": {"x": 1, "y": start}, "end": {"x": 1, "y": end}}],
    )
    if open_door:
        body["opening_states"] = [{"opening_id": "door", "is_open": True}]
    return SimulationConfiguration.model_validate(body)


def test_wall_isolation_and_open_door_connectivity():
    closed = prepare_run(divided_room(), **OPTIONS).grid
    opened = prepare_run(divided_room(True), **OPTIONS).grid
    crossings = [(closed.active_index[r, 3], closed.active_index[r, 4]) for r in range(4)]
    closed_pairs, open_pairs = set(map(tuple, closed.connections)), set(map(tuple, opened.connections))
    assert all(pair not in closed_pairs for pair in crossings)
    assert [pair in open_pairs for pair in crossings] == [False, True, True, False]
    np.testing.assert_array_equal(closed.active_mask, opened.active_mask)


def test_unrepresented_door_is_reported():
    grid = prepare_run(divided_room(True, 0.45, 0.55), **OPTIONS).grid
    assert any("narrower than one cell" in warning for warning in grid.warnings)
    assert any("no represented cell connection" in warning for warning in grid.warnings)


def test_diagonal_door_opens_despite_floating_point_projection():
    body = configuration(2, 2).model_dump()
    body["geometry_m"].update(
        walls=[{"id": "diagonal", "start": {"x": 0, "y": 0.2}, "end": {"x": 2, "y": 1.7}}],
        doors=[{"id": "door", "wall_id": "diagonal",
                "start": {"x": 0.6, "y": 0.65}, "end": {"x": 1.4, "y": 1.25}}],
    )
    closed = prepare_run(SimulationConfiguration.model_validate(body), **OPTIONS).grid
    body["opening_states"] = [{"opening_id": "door", "is_open": True}]
    opened = prepare_run(SimulationConfiguration.model_validate(body), **OPTIONS).grid
    assert len(opened.connections) > len(closed.connections)


def test_unsafe_source_mapping_is_rejected():
    config = divided_room()
    config.placements[0].position_m.x = 1
    with pytest.raises(PreparationError, match="closed wall"):
        prepare_run(config, **OPTIONS)
    body = configuration(1, 1).model_dump()
    body["geometry_m"]["walls"] = [{"id": "near", "start": {"x": 0.13, "y": 0}, "end": {"x": 0.13, "y": 1}}]
    body["placements"][0]["position_m"]["x"] = 0.14
    with pytest.raises(PreparationError, match="across a barrier"):
        prepare_run(SimulationConfiguration.model_validate(body), **OPTIONS)


def test_invalid_polygon_and_interior_open_window_are_rejected():
    body = configuration().model_dump()
    body["geometry_m"]["indoor_domain"]["boundary"] = [
        {"x": x, "y": y} for x, y in ((0, 0), (2, 1), (0, 1), (2, 0))
    ]
    with pytest.raises(PreparationError, match="Invalid indoor polygon"):
        prepare_input(SimulationConfiguration.model_validate(body), **OPTIONS)
    body = divided_room(True).model_dump()
    body["geometry_m"]["windows"] = body["geometry_m"].pop("doors")
    with pytest.raises(PreparationError, match="not near the indoor boundary"):
        prepare_run(SimulationConfiguration.model_validate(body), **OPTIONS)


def test_resource_limits_run_before_source_resolution():
    def unexpected_resolver(*args):
        pytest.fail("Resource checks must run before source estimation")

    for limits in (PreparationLimits(max_cells=1), PreparationLimits(max_samples=1),
                   PreparationLimits(max_output_bytes=1)):
        with pytest.raises(PreparationError) as error:
            prepare_input(configuration(), **{**OPTIONS, "resolve_source": unexpected_resolver, "limits": limits})
        assert error.value.code == "resource_limit"


def test_sampled_output_dtype_matches_payload_budget():
    from app.simulations.engine.models import EngineOutput

    config = configuration(0.25, 0.25)
    config.settings.sample_interval_s = 1
    run = prepare_run(config, limits=PreparationLimits(max_output_bytes=9), **OPTIONS)
    times = np.asarray(run.input.sample_times_s)
    values = np.zeros((2, 1, 1, 1), dtype=np.float32)
    output = EngineOutput(run.grid, times, values)
    assert output.concentration.nbytes + run.grid.active_mask.nbytes == run.estimated_output_bytes == 9
    with pytest.raises(ValueError, match="float32"):
        EngineOutput(run.grid, times, values.astype(np.float64))


def test_pixel_indoor_domain_rejects_nonfinite_vertices():
    from pydantic import ValidationError
    from app.floor_plans.models import PixelIndoorDomain

    ring = [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 0, "y": 1}]
    for value in (float("nan"), float("inf"), float("-inf")):
        invalid = [*ring[:2], {"x": 0, "y": value}]
        for body in ({"boundary": invalid}, {"boundary": ring, "holes": [invalid]}):
            with pytest.raises(ValidationError, match="finite pixel coordinates"):
                PixelIndoorDomain.model_validate(body)
    domain = PixelIndoorDomain(boundary=ring, holes=[ring])
    assert PixelIndoorDomain.model_validate_json(domain.model_dump_json()) == domain
