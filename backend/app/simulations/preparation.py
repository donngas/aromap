"""Resolve a metric configuration without HTTP, persistence, or emission formulas."""

import hashlib
import json
import math
from collections.abc import Callable

from pydantic import ValidationError

from app.diffusers.models import ConsumerDiffuserDefinition
from app.simulations.engine.grid import build_grid, grid_extent
from app.simulations.engine.models import PreparedSimulation
from app.simulations.errors import PreparationError
from app.simulations.geometry import resolve_geometry
from app.simulations.limits import DEFAULT_CELL_SIZE_M, PreparationLimits
from app.simulations.models import (
    DiffuserPlacement, EmissionSource, ModelParameters, ResolvedEmissionProfile,
    SimulationConfiguration, SimulationInput,
)

PREPARATION_VERSION = "square-center-grid-v1"
SourceResolver = Callable[[ConsumerDiffuserDefinition, DiffuserPlacement], ResolvedEmissionProfile]


def _sample_times(settings, limits: PreparationLimits) -> list[float]:
    if settings.sample_times_s is not None:
        limits.check(len(settings.sample_times_s), limits.max_samples, "Sample count")
        return list(settings.sample_times_s)
    interval = settings.sample_interval_s
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
    resolve_source: SourceResolver,
    model_version: str,
    effective_diffusivity_m2_per_s: float | None = None,
    removal_rate_per_s: float | None = None,
    default_cell_size_m: float = DEFAULT_CELL_SIZE_M,
    limits: PreparationLimits | None = None,
) -> SimulationInput:
    """Produce a detached, serializable snapshot, never a fabricated physical rate.

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
    enabled = [placement for placement in configuration.placements if placement.enabled]
    if not enabled:
        raise PreparationError("no_sources", "At least one placement must be enabled.")
    limits.check(len(enabled), limits.max_placements, "Enabled placement count")
    times = _sample_times(configuration.settings, limits)
    cell_size = configuration.settings.grid_cell_size_m
    if cell_size is None:
        cell_size = default_cell_size_m
    if not math.isfinite(cell_size) or cell_size <= 0:
        raise PreparationError("invalid_resolution", "Cell size must be finite and positive.")
    _, _, rows, columns = grid_extent(geometry.indoor_domain, cell_size, limits)
    limits.output_bytes(len(times), len(enabled), rows, columns)

    diffusion = configuration.settings.effective_diffusivity_m2_per_s
    removal = configuration.conditions.removal_rate_per_s
    diffusion = diffusion if diffusion is not None else effective_diffusivity_m2_per_s
    removal = removal if removal is not None else removal_rate_per_s
    if diffusion is None or removal is None:
        raise PreparationError("unresolved_parameters", "Supply explicit spreading and removal parameters; no physics defaults exist yet.")
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
        profile = ResolvedEmissionProfile.model_validate(resolve_source(
            definitions[placement.definition_id].model_copy(deep=True), placement.model_copy(deep=True),
        )).model_copy(deep=True)
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
        "assumptions": [
            "Coordinates and lengths are supplied in meters; no image scaling is performed.",
            "Unspecified door/window states are closed; open-window behavior is unsupported.",
            "Source resolver supplied explicit rates and handled placement overrides.",
        ],
    }
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return SimulationInput(input_fingerprint=fingerprint, **payload)


def prepare_run(configuration: SimulationConfiguration, **resolution_options) -> PreparedSimulation:
    """Compile a configuration for a future solver; no time stepping or jobs."""
    limits = resolution_options.get("limits") or PreparationLimits()
    input = prepare_input(configuration, **resolution_options)
    grid = build_grid(input, limits)
    size = limits.output_bytes(len(input.sample_times_s), len(input.sources), grid.rows, grid.columns)
    return PreparedSimulation(input, grid, size)
