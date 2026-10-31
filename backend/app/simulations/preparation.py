"""Resolve metric configurations, proxy emissions, and internal solver boundaries."""

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import replace

from pydantic import ValidationError

from app.diffusers.models import ConsumerDiffuserDefinition
from app.simulations.engine.grid import build_grid, grid_extent
from app.simulations.engine.exterior import map_exterior_openings
from app.simulations.engine.airflow import build_airflow
from app.simulations.engine.models import PreparedSimulation, ResolvedInitialState
from app.simulations.engine.state import initial_state_fingerprint, validate_initial_state
from app.simulations.emissions import resolve_emission
from app.simulations.errors import PreparationError
from app.simulations.geometry import resolve_geometry
from app.simulations.limits import (
    DEFAULT_CELL_SIZE_M, DEFAULT_DIFFUSIVITY_M2_PER_S, DEFAULT_REMOVAL_RATE_PER_S, DEFAULT_SAMPLE_INTERVAL_S,
    ExecutionLimits, PreparationLimits,
)
from app.simulations.models import (
    DiffuserPlacement, EmissionSource, ModelParameters, ResolvedEmissionProfile,
    SimulationConfiguration, SimulationInput,
)

PREPARATION_VERSION = "square-center-grid-v2"
SourceResolver = Callable[[ConsumerDiffuserDefinition, DiffuserPlacement], ResolvedEmissionProfile]


def _sample_times(settings, limits: PreparationLimits) -> list[float]:
    if settings.sample_times_s is not None:
        limits.check(len(settings.sample_times_s), limits.max_samples, "Sample count")
        return list(settings.sample_times_s)
    interval = settings.sample_interval_s
    if interval is None:
        # Keep omission distinct from an explicit interval through JSON round trips.
        # Automatic sampling includes both endpoints and can become less frequent.
        if limits.max_samples < 2:
            raise PreparationError("resource_limit", "Automatic sampling needs room for zero and the final time.")
        interval = min(DEFAULT_SAMPLE_INTERVAL_S, settings.duration_s)
        if math.ceil(settings.duration_s / interval) + 1 > limits.max_samples:
            return [(i / (limits.max_samples - 1)) * settings.duration_s for i in range(limits.max_samples)]
    ratio = settings.duration_s / interval
    if not math.isfinite(ratio):
        raise PreparationError("resource_limit", "Sample count exceeds representable limits.")
    steps = math.floor(ratio)
    last_is_end = math.isclose(steps * interval, settings.duration_s, rel_tol=1e-12)
    limits.check(steps + 1 + (not last_is_end), limits.max_samples, "Sample count")
    times = [i * interval for i in range(steps + 1)]
    if last_is_end:
        times[-1] = settings.duration_s
    else:
        times.append(settings.duration_s)
    return times


def prepare_input(
    configuration: SimulationConfiguration,
    *,
    resolve_source: SourceResolver = resolve_emission,
    model_version: str,
    effective_diffusivity_m2_per_s: float = DEFAULT_DIFFUSIVITY_M2_PER_S,
    removal_rate_per_s: float = DEFAULT_REMOVAL_RATE_PER_S,
    default_cell_size_m: float = DEFAULT_CELL_SIZE_M,
    limits: PreparationLimits | None = None,
) -> SimulationInput:
    """Resolve a zero-start input; no sources requires prepare_run with initial state."""
    return _prepare_input(
        configuration, resolve_source=resolve_source, model_version=model_version,
        effective_diffusivity_m2_per_s=effective_diffusivity_m2_per_s,
        removal_rate_per_s=removal_rate_per_s, default_cell_size_m=default_cell_size_m,
        limits=limits,
    )


def _prepare_input(
    configuration: SimulationConfiguration, *, resolve_source: SourceResolver = resolve_emission,
    model_version: str, effective_diffusivity_m2_per_s: float = DEFAULT_DIFFUSIVITY_M2_PER_S,
    removal_rate_per_s: float = DEFAULT_REMOVAL_RATE_PER_S,
    default_cell_size_m: float = DEFAULT_CELL_SIZE_M, limits: PreparationLimits | None = None,
    allow_residual_only: bool = False,
) -> SimulationInput:
    """Produce a detached snapshot with explicit proxy assumptions, not measured rates.

    resolve_source receives a copy of the definition and placement. It must resolve
    ALL strength/operating overrides and record its assumptions; preparation does
    not apply them a second time or infer a schedule from daily operating hours.
    Request-specified model parameters take precedence over explicit caller defaults.
    """
    limits = limits or PreparationLimits()
    # Revalidate even model instances: callers may have mutated lists/fields.
    configuration = SimulationConfiguration.model_validate(
        configuration.model_dump(include=set(SimulationConfiguration.model_fields))
    )
    geometry = configuration.geometry_m
    element_count = len(geometry.indoor_domain.boundary) + sum(map(len, geometry.indoor_domain.holes))
    element_count += 2 * (len(geometry.walls) + len(geometry.doors) + len(geometry.windows))
    limits.check(element_count, limits.max_geometry_elements, "Geometry element count")
    limits.check(configuration.settings.duration_s, limits.max_duration_s, "Simulation duration")
    enabled = [placement for placement in configuration.placements if placement.enabled]
    if not enabled and not allow_residual_only:
        raise PreparationError("no_sources", "At least one placement must be enabled.")
    limits.check(len(enabled), limits.max_placements, "Enabled placement count")
    times = _sample_times(configuration.settings, limits)
    cell_size = configuration.settings.grid_cell_size_m
    if cell_size is None:
        cell_size = default_cell_size_m
    limits.check_resolution(cell_size)
    _, _, rows, columns = grid_extent(geometry.indoor_domain, cell_size, limits)
    limits.output_bytes(len(times), len(enabled), rows, columns)

    diffusion = configuration.settings.effective_diffusivity_m2_per_s
    if configuration.settings.mixing_preset is not None:
        diffusion = {"low": 0.001, "medium": 0.005, "high": 0.013}[configuration.settings.mixing_preset]
    removal = configuration.conditions.removal_rate_per_s
    diffusion = diffusion if diffusion is not None else effective_diffusivity_m2_per_s
    removal = removal if removal is not None else removal_rate_per_s
    if not model_version.strip():
        raise PreparationError("invalid_model_version", "A model version is required for reproducibility.")
    try:
        parameters = ModelParameters(effective_diffusivity_m2_per_s=diffusion, removal_rate_per_s=removal)
    except ValidationError as exc:
        raise PreparationError("invalid_parameters", "Model parameters must be finite and within their allowed ranges.") from exc
    resolved_geometry = resolve_geometry(configuration)
    definitions = {definition.id: definition for definition in configuration.diffuser_definitions}
    sources = []
    for placement in enabled:
        resolved = resolve_source(definitions[placement.definition_id].model_copy(deep=True),
                                  placement.model_copy(deep=True))
        profile = ResolvedEmissionProfile.model_validate(resolved.model_dump()).model_copy(deep=True)
        sources.append(EmissionSource(
            placement_id=placement.placement_id, definition_id=placement.definition_id,
            position_m=placement.position_m.model_copy(deep=True), profile=profile,
        ))
    payload = {
        "model_version": model_version, "preparation_version": PREPARATION_VERSION,
        "geometry": resolved_geometry.model_dump(mode="json"),
        "sources": [source.model_dump(mode="json") for source in sources],
        "duration_s": configuration.settings.duration_s, "sample_times_s": times,
        "grid_cell_size_m": cell_size, "parameters": parameters.model_dump(mode="json"),
        "airflow": configuration.airflow.model_dump(mode="json"),
        "assumptions": [
            "Coordinates and lengths are supplied in meters; no image scaling is performed.",
            "Unspecified door/window states are closed.",
            "Source resolver supplied explicit rates and handled placement overrides.",
            "One relative unit is a surrogate for 1 mg consumed formulation; fields are relative units/m², not perceived intensity.",
            "Background mixing and removal are uniform; airflow is an idealized steady 2D approximation, not measured CFD.",
        ],
        "initial_state_fingerprint": None,
    }
    if configuration.settings.effective_diffusivity_m2_per_s is None:
        payload["assumptions"].append(f"Caller/default effective spreading: {diffusion} m²/s; provisional mixing parameter, not molecular diffusivity.")
    if configuration.conditions.removal_rate_per_s is None:
        payload["assumptions"].append(f"Caller/default uniform removal: {removal} /s ({removal * 3600} air changes/hour equivalent).")
    payload["assumptions"].append(
        f"Airflow: outdoor conditions {configuration.airflow.outdoor_conditions}, "
        f"wind direction {configuration.airflow.wind_direction_degrees} degrees toward; "
        f"{len(configuration.airflow.devices)} recirculating devices. "
        "Opening exchange and fan strength use uncalibrated engineering presets; background removal excludes modeled openings."
    )
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return SimulationInput(input_fingerprint=fingerprint, **payload)


def prepare_run(
    configuration: SimulationConfiguration, *, initial_state: ResolvedInitialState | None = None,
    execution_limits: ExecutionLimits | None = None, **resolution_options,
) -> PreparedSimulation:
    """Compile for the numerical solver; optional state must already be reconciled.

    No state migration, time stepping, hard worker timeout, or job execution here.
    """
    limits = resolution_options.get("limits") or PreparationLimits()
    execution_limits = execution_limits or ExecutionLimits()
    input = _prepare_input(configuration, allow_residual_only=initial_state is not None, **resolution_options)
    channels = len(initial_state.channels) if initial_state is not None else len(input.sources)
    limits.check(channels, limits.max_placements, "Channel count including residual sources")
    _, _, rows, columns = grid_extent(input.geometry.indoor_domain, input.grid_cell_size_m, limits)
    size = limits.output_bytes(len(input.sample_times_s), channels, rows, columns)
    # Conservative array/preparation allowance, not a bound on native solver RSS.
    estimated_working_bytes = size + rows * columns * (128 + channels * 8 * 3)
    execution_limits.check_memory(estimated_working_bytes)
    grid = build_grid(input, limits)
    boundary, exterior_ids = map_exterior_openings(input.geometry, grid)
    if exterior_ids:
        grid = build_grid(input, limits, exterior_ids)
        boundary, exterior_ids = map_exterior_openings(input.geometry, grid)
        grid = replace(grid, warnings=(*grid.warnings,
            "Exterior openings are inferred from proximity to the indoor boundary; review results when interior walls lie close to the perimeter."))
    airflow = None
    if input.airflow.devices or boundary:
        # Output snapshots and scent-solver factorization are allocated later,
        # after projection has returned. Count only arrays resident now.
        resident_bytes = (grid.active_mask.nbytes + grid.active_index.nbytes + grid.connections.nbytes
                          + sum(s.cell_indices.nbytes + s.weights.nbytes for s in grid.source_weights))
        airflow = build_airflow(grid, input.airflow, boundary, input.geometry,
                                limits=execution_limits, resident_bytes=resident_bytes)
    if initial_state is not None:
        initial_state = validate_initial_state(initial_state, grid, input.model_version)
        payload = input.model_dump(exclude={"input_fingerprint"})
        payload["initial_state_fingerprint"] = initial_state_fingerprint(initial_state)
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        input = SimulationInput(input_fingerprint=fingerprint, **payload)
    if size > limits.output_warning_bytes:
        grid = replace(grid, warnings=(*grid.warnings, "Large sampled payload; reduce samples, channels, or grid resolution for browser playback."))
    return PreparedSimulation(input, grid, size, initial_state, estimated_working_bytes, execution_limits, airflow, boundary)
