"""Isolated simulation process and on-disk artifact encoding."""
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app.infrastructure.storage import LocalStorage
from app.simulations.engine.solver import SOLVER_VERSION, simulate
from app.simulations.errors import PreparationError, SimulationError
from app.simulations.preparation import prepare_run
from app.simulations.schemas import SimulationRequest

logger = logging.getLogger(__name__)


def execute_simulation(root: str, job_id: str, expires_at: float):
    storage = LocalStorage(Path(root))
    try:
        request = SimulationRequest.model_validate_json(storage.path(f"results/{job_id}.request.json").read_text())
        run = prepare_run(request, model_version=SOLVER_VERSION)
        output = simulate(run)
        grid = output.grid
        # NPZ is a ZIP of standard NPY arrays and can be read without pickle.
        path = storage.path(f"results/{job_id}.npz")
        temporary = storage.path(f"results/{job_id}.npz.tmp")
        with temporary.open("wb") as file:
            np.savez_compressed(file, concentration=output.concentration, active_domain_mask=grid.active_mask)
        temporary.replace(path)
        result = {
            "run_id": job_id, "input_fingerprint": run.input.input_fingerprint,
            "model_version": run.input.model_version,
            "grid": {"origin_m": grid.origin_m.model_dump(), "cell_size_m": grid.cell_size_m,
                     "rows": grid.rows, "columns": grid.columns},
            "channels": [{"channel_id": c.placement_id, "placement_id": c.placement_id,
                          "definition_id": c.definition_id} for c in output.channels],
            "sample_times_s": output.sample_times_s.tolist(),
            "fields": {"url": f"/api/simulations/{job_id}/fields", "encoding": "npz",
                       "shape": list(output.concentration.shape),
                       "active_domain_mask": {"shape": [grid.rows, grid.columns]}},
            "resolved_assumptions": run.input.assumptions, "diagnostics": list(output.diagnostics),
            "warnings": list(grid.warnings),
            "expires_at": datetime.fromtimestamp(expires_at, timezone.utc).isoformat(),
        }
        storage.write_json(f"results/{job_id}.json", {"result": result})
    except (PreparationError, SimulationError) as exc:
        storage.write_json(f"results/{job_id}.json", {"error": {"code": exc.code, "message": str(exc)}})
    except Exception:
        logger.exception("Simulation execution failed")
        storage.write_json(f"results/{job_id}.json", {"error": {"code": "simulation_failed", "message": "Simulation could not complete."}})
