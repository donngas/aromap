"""Standalone reproducible solver smoke benchmark; run from backend with uv.

uv run --locked python -m scripts.benchmark_simulation --case apartment
Peak RSS includes Python/native libraries and is process-wide, not just solver arrays.
"""

import argparse
import json
import resource
import time

from app.simulations.engine.solver import SOLVER_VERSION, SolverOptions, simulate
from app.simulations.models import SimulationConfiguration
from app.simulations.preparation import prepare_run

CASES = {
    "apartment": (20, 15, 3600, 4),
    "comparison": (25, 25, 600, 16),
    "large": (79, 79, 60, 1),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=CASES, default="apartment")
    parser.add_argument("--cell-size", type=float, default=None, help="Explicit grid override; omitted uses automatic policy")
    parser.add_argument("--max-step", type=float, default=2., help="Maximum internal timestep in seconds")
    args = parser.parse_args()
    width, height, duration, channel_count = CASES[args.case]
    configuration = SimulationConfiguration.model_validate({
        "geometry_m": {"indoor_domain": {"boundary": [
            {"x": 0, "y": 0}, {"x": width, "y": 0},
            {"x": width, "y": height}, {"x": 0, "y": height},
        ]}},
        "diffuser_definitions": [{"id": "A", "name": "Benchmark refill", "diffuser_type": "reed",
                                  "capacity": 100, "capacity_unit": "ml", "lifetime_days": 60}],
        "placements": [{"placement_id": f"A{i}", "definition_id": "A",
                        "position_m": {"x": 0.1 + i * 0.5, "y": 0.1}} for i in range(channel_count)],
        "settings": {"duration_s": duration, "grid_cell_size_m": args.cell_size},
    })
    started = time.perf_counter()
    prepared = prepare_run(configuration, model_version=SOLVER_VERSION)
    preparation_s = time.perf_counter() - started
    started = time.perf_counter()
    result = simulate(prepared, SolverOptions(max_step_s=args.max_step))
    print(json.dumps({
        "case": args.case, "cell_size_m": prepared.grid.cell_size_m, "active_cells": prepared.grid.active_cell_count,
        "channels": channel_count, "duration_s": duration, "samples": len(result.sample_times_s),
        "preparation_s": round(preparation_s, 3), "solver_s": round(time.perf_counter() - started, 3),
        "field_mib": round(result.concentration.nbytes / 1024 ** 2, 2),
        "process_peak_mib_linux": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
        "diagnostics": result.diagnostics,
    }, indent=2))


if __name__ == "__main__":
    main()
