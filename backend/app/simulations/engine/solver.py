"""Conservative square-cell balance, solved by sparse backward Euler.

NIST finite-volume discretization: https://pages.nist.gov/fipy/en/stable/numerical/discret.html
No HTTP, persistence, airflow-field generation, or product estimation lives here.
"""

import math
import time
from dataclasses import dataclass

import numpy as np
from scipy.sparse import csc_matrix, eye
from scipy.sparse.linalg import splu

from app.simulations.engine.models import EngineOutput, PreparedSimulation, ResolvedInitialState
from app.simulations.engine.state import grid_signature, initial_concentrations
from app.simulations.errors import PreparationError, SimulationError

SOLVER_VERSION = "square-balance-airflow-v2"


@dataclass(frozen=True)
class SolverOptions:
    """Backend accuracy/work policy; output sampling never selects integration steps.

    The diffusion/removal caps are provisional accuracy choices, not stability
    requirements or scientific constants. Smaller max_step_s enables convergence tests.
    """

    max_step_s: float = 0.25
    max_steps: int = 200_000

    def __post_init__(self):
        if not math.isfinite(self.max_step_s) or self.max_step_s <= 0:
            raise ValueError("Maximum solver step must be finite and positive")
        if isinstance(self.max_steps, bool) or not isinstance(self.max_steps, int) or self.max_steps <= 0:
            raise ValueError("Maximum solver step count must be a positive integer")


def transport_matrix(run: PreparedSimulation) -> csc_matrix:
    """Positive loss operator K: each connection contributes equal/opposite exchange.

    K @ C is subtracted from concentration. Missing edges are no-flux boundaries;
    no outside zero-concentration cells are added. A future directed transport
    operator can be assembled separately; the LU solver permits asymmetry.
    """
    grid = run.grid
    count = grid.active_cell_count
    edges = grid.connections
    coupling = run.input.parameters.effective_diffusivity_m2_per_s / grid.cell_size_m ** 2
    if not math.isfinite(coupling):
        raise SimulationError("numerical_range", "Spreading coefficient is outside representable numerical limits.")
    degree = np.bincount(edges.ravel(), minlength=count)
    rows = np.concatenate((edges[:, 0], edges[:, 1], np.arange(count)))
    columns = np.concatenate((edges[:, 1], edges[:, 0], np.arange(count)))
    values = np.concatenate((np.full(2 * len(edges), -coupling), degree * coupling))
    operator = csc_matrix((values, (rows, columns)), shape=(count, count))
    if run.airflow_field is not None:
        field = run.airflow_field
        # Conservative first-order upwind transfers between adjacent cells.
        flux = field.edge_flux / grid.cell_size_m ** 2
        upstream = np.where(flux >= 0, edges[:, 0], edges[:, 1])
        downstream = np.where(flux >= 0, edges[:, 1], edges[:, 0])
        rate = np.abs(flux)
        operator += csc_matrix((np.r_[rate, -rate],
                                (np.r_[upstream, downstream], np.r_[upstream, upstream])),
                               shape=(count, count))
        # Net outflow and additional balanced two-way exchange remove scent locally.
        cells = np.array([opening.cell_index for opening in run.exterior_openings], dtype=int)
        loss = (np.maximum(field.boundary_outflow, 0) + field.boundary_exchange) / grid.cell_size_m ** 2
        operator += csc_matrix((loss, (cells, cells)), shape=(count, count))
    return operator


def source_rates(run: PreparedSimulation) -> np.ndarray:
    """Concentration gain per second [active_cell, channel], including zero residuals."""
    rates = np.zeros((run.grid.active_cell_count, len(run.channels)), dtype=np.float64, order="F")
    channels = {channel.placement_id: (index, channel.definition_id) for index, channel in enumerate(run.channels)}
    weights = {source.placement_id: source for source in run.grid.source_weights}
    if set(weights) != {source.placement_id for source in run.input.sources}:
        raise SimulationError("invalid_prepared_run", "Source mappings do not match prepared emission sources.")
    for source in run.input.sources:
        index, definition = channels[source.placement_id]
        mapped = weights[source.placement_id]
        if (definition != source.definition_id or mapped.definition_id != definition
                or mapped.weights.ndim != 1 or mapped.cell_indices.shape != mapped.weights.shape
                or not np.isfinite(mapped.weights).all() or np.any(mapped.weights < 0)
                or not np.isclose(mapped.weights.sum(), 1, rtol=0, atol=1e-12)
                or np.any(mapped.cell_indices < 0) or np.any(mapped.cell_indices >= len(rates))):
            raise SimulationError("invalid_prepared_run", "Source weights must conserve each placement's emission.")
        with np.errstate(over="ignore", invalid="ignore"):
            contribution = source.profile.rate_relative_units_per_s * mapped.weights / run.grid.cell_size_m ** 2
        if not np.isfinite(contribution).all() or np.any(contribution < 0):
            raise SimulationError("numerical_range", "Source concentration rate is not finite and nonnegative.")
        np.add.at(rates[:, index], mapped.cell_indices, contribution)
    return rates


def _check_state(values: np.ndarray) -> float:
    if not np.isfinite(values).all():
        raise SimulationError("numerical_failure", "The numerical state contains non-finite concentrations.")
    tolerance = 1e-12 * max(1.0, float(values.max()))
    if values.min() < -tolerance:
        raise SimulationError("numerical_failure", "The numerical state contains materially negative concentrations.")
    negative = values < 0
    correction = float(np.abs(values[negative]).sum())
    values[negative] = 0
    return correction


def simulate(prepared: PreparedSimulation, options: SolverOptions | None = None) -> EngineOutput:
    """Advance the entire run, exporting snapshots without changing the solver clock.

    All channels share one sparse factorization. Internal time is relative to this
    run; the returned compact final state also carries elapsed continuation time.
    Native factorization/solve calls cannot be hard-interrupted here: job execution
    must enforce a process timeout when this engine is connected to the API.
    """
    started = time.monotonic()
    options = options or SolverOptions()
    run = prepared
    grid, data, budget = run.grid, run.input, run.execution_limits
    budget.check_deadline(started)
    count, channels = grid.active_cell_count, len(run.channels)
    samples = np.asarray(data.sample_times_s, dtype=np.float64)
    if (count == 0 or channels == 0 or samples.ndim != 1 or samples.size == 0
            or not np.isfinite(samples).all() or np.any(samples < 0)
            or np.any(samples > data.duration_s) or np.any(samples[1:] <= samples[:-1])):
        raise SimulationError("invalid_prepared_run", "Prepared cells, channels, and sample times must be valid.")
    spreading = data.parameters.effective_diffusivity_m2_per_s / grid.cell_size_m ** 2
    removal = data.parameters.removal_rate_per_s
    if not math.isfinite(spreading) or spreading <= 0 or not math.isfinite(removal) or removal < 0:
        raise SimulationError("numerical_range", "Transport parameters are outside numerical limits.")
    target_step = min(options.max_step_s, 0.25 / spreading, 0.05 / removal if removal else math.inf)
    if run.airflow_field is not None and len(run.airflow_field.edge_flux):
        speed = np.max(np.abs(run.airflow_field.edge_flux)) / grid.cell_size_m
        if speed > 0:
            target_step = min(target_step, 0.5 * grid.cell_size_m / speed)
    ratio = data.duration_s / target_step if target_step > 0 else math.inf
    if not math.isfinite(ratio) or ratio > options.max_steps:
        raise PreparationError("resource_limit", "Requested duration/parameters require too many internal solver steps.")
    steps = max(1, math.ceil(ratio))
    step_s = data.duration_s / steps

    output_bytes = len(samples) * channels * grid.rows * grid.columns * 4
    grid_bytes = grid.active_mask.nbytes + grid.active_index.nbytes + grid.connections.nbytes
    if run.airflow_field is not None:
        grid_bytes += (run.airflow_field.edge_flux.nbytes + run.airflow_field.boundary_outflow.nbytes
                       + run.airflow_field.boundary_exchange.nbytes)
    # Reserve space for sparse assembly, native LU fill, copies, output, and state.
    # Grid-like sparse LU fill varies; this is a guard estimate, not a peak-RSS cap.
    base_bytes = output_bytes + grid_bytes + 8 * count * channels * 8 + 256 * count
    fill_reserve = 128 * count * max(1, math.ceil(math.log2(count + 1)))
    budget.check_memory(base_bytes + fill_reserve)
    state = np.asfortranarray(initial_concentrations(run).T)
    if state.shape != (count, channels):
        raise SimulationError("invalid_prepared_run", "Initial state dimensions do not match the prepared channels.")
    clipped = _check_state(state)
    rates = source_rates(run)
    operator = transport_matrix(run)
    matrix = step_s * operator + (1 + step_s * removal) * eye(count, format="csc")
    if not np.isfinite(matrix.data).all():
        raise SimulationError("numerical_range", "The numerical transport matrix is not finite.")
    budget.check_deadline(started)
    try:
        factor = splu(matrix)
    except (RuntimeError, ValueError) as exc:
        raise SimulationError("solver_failure", "Sparse transport factorization failed.") from exc
    budget.check_deadline(started)
    factors = (factor.L, factor.U)
    factor_bytes = sum(part.data.nbytes + part.indices.nbytes + part.indptr.nbytes for part in factors)
    # Native factors and Python sparse factor views may both occupy memory.
    budget.check_memory(base_bytes + 2 * factor_bytes + factor.perm_r.nbytes + factor.perm_c.nbytes)
    fields = np.zeros((len(samples), channels, grid.rows, grid.columns), dtype=np.float32)
    snapshot_index = 0
    for step in range(1, steps + 1):
        budget.check_deadline(started)
        left = (step - 1) * step_s
        right = data.duration_s if step == steps else step * step_s
        with np.errstate(over="ignore", invalid="ignore"):
            rhs = state + step_s * rates
        if not np.isfinite(rhs).all():
            raise SimulationError("numerical_range", "Source accumulation exceeded numerical limits.")
        try:
            following = factor.solve(rhs)
        except (RuntimeError, ValueError) as exc:
            raise SimulationError("solver_failure", "Sparse transport solve failed.") from exc
        clipped += _check_state(following)
        while snapshot_index < len(samples) and samples[snapshot_index] <= right:
            budget.check_deadline(started)
            fraction = min(1.0, max(0.0, (samples[snapshot_index] - left) / (right - left)))
            snapshot = (1 - fraction) * state + fraction * following
            if snapshot.max() > np.finfo(np.float32).max:
                raise SimulationError("output_range", "Concentrations exceed float32 output range.")
            fields[snapshot_index][:, grid.active_mask] = snapshot.T
            snapshot_index += 1
        state = following
    if snapshot_index != len(samples):
        raise SimulationError("numerical_failure", "The solver did not produce every requested snapshot.")
    elapsed = (run.initial_state.elapsed_time_s if run.initial_state is not None else 0) + data.duration_s
    final_values = np.array(state.T, dtype=np.float64, order="C", copy=True)
    final_values.flags.writeable = False
    final = ResolvedInitialState(grid_signature(grid), data.model_version, elapsed, run.channels, final_values)
    result = EngineOutput(
        grid, samples.copy(), fields,
        diagnostics=(f"Solver {SOLVER_VERSION}: backward Euler, {steps} uniform steps of {step_s:.12g} s.",
                     "Output times select linearly interpolated snapshots; they do not alter integration steps.",
                     f"Roundoff clipping added {clipped * grid.cell_size_m ** 2:.12g} relative units."),
        channels=run.channels, final_state=final,
    )
    budget.check_deadline(started)
    return result
