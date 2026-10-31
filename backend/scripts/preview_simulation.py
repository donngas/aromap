"""Export a bounded standalone HTML viewer without API/React integration.

From backend/: uv run --locked python -m scripts.preview_simulation --input ... --output ...
"""

import argparse
import base64
import json
import math
from pathlib import Path

import numpy as np

from app.simulations.engine.solver import SOLVER_VERSION, SolverOptions, simulate
from app.simulations.models import SimulationConfiguration
from app.simulations.preparation import prepare_run
from app.simulations.schemas import SimulationRequest

TEMPLATE = Path(__file__).parent / "templates" / "simulation_viewer.html"


def export_preview(
    configuration: SimulationConfiguration, destination: Path, *, title: str = "Aromap simulation",
    scale_max: float | None = None, max_preview_mib: float = 32,
    options: SolverOptions | None = None,
) -> dict:
    """Return a small summary; raw fields are embedded as little-endian float32.

    Preview encoding is internal to this tool, not a production download contract.
    The cap is checked before numerical execution and before base64 expansion.
    """
    if not math.isfinite(max_preview_mib) or max_preview_mib <= 0:
        raise ValueError("Preview size limit must be finite and positive")
    if scale_max is not None and (not math.isfinite(scale_max) or scale_max <= 0):
        raise ValueError("Color scale maximum must be finite and positive")
    if destination.suffix.lower() != ".html":
        raise ValueError("Preview output must have an .html extension")
    run = prepare_run(configuration, model_version=SOLVER_VERSION)
    if run.estimated_output_bytes + run.grid.active_mask.size * 16 > max_preview_mib * 1024 ** 2:
        raise ValueError("Preview exceeds raw-field size limit; reduce samples, placements, or resolution")
    output = simulate(run, options)
    fields = output.concentration
    # Neighbor-aware display interpolation cannot sample through closed walls.
    neighbors = np.full((run.grid.active_mask.size, 4), -1, dtype="<i4")
    active_flat = np.flatnonzero(run.grid.active_mask)
    edges = active_flat[run.grid.connections]
    for first, second in edges:
        forward = 1 if first // run.grid.columns == second // run.grid.columns else 3
        backward = 0 if forward == 1 else 2
        neighbors[first, forward] = second
        neighbors[second, backward] = first
    quantities = fields.sum(axis=(2, 3), dtype=np.float64) * run.grid.cell_size_m ** 2
    data_max = max(float(frame.sum(axis=0, dtype=np.float64).max()) for frame in fields)
    assumptions = list(dict.fromkeys([
        *run.input.assumptions,
        *(assumption for source in run.input.sources for assumption in source.profile.assumptions),
    ]))
    payload = {
        "title": title, "shape": list(fields.shape),
        "grid": {"origin": run.grid.origin_m.model_dump(), "cell": run.grid.cell_size_m,
                 "rows": run.grid.rows, "columns": run.grid.columns},
        "times": output.sample_times_s.tolist(),
        "channels": [{"placement_id": channel.placement_id, "definition_id": channel.definition_id}
                     for channel in output.channels],
        "geometry": run.input.geometry.model_dump(mode="json"),
        "sources": [source.model_dump(mode="json") for source in run.input.sources],
        "duration": run.input.duration_s, "quantities": quantities.tolist(),
        "dataMax": data_max, "scaleMax": scale_max if scale_max is not None else max(data_max, 1e-12),
        "parameters": run.input.parameters.model_dump(),
        "assumptions": assumptions, "warnings": list(run.grid.warnings),
        "diagnostics": list(output.diagnostics), "fingerprint": run.input.input_fingerprint,
        "fields": base64.b64encode(fields.astype("<f4", copy=False).tobytes()).decode("ascii"),
        "mask": base64.b64encode(run.grid.active_mask.astype(np.uint8).tobytes()).decode("ascii"),
        "neighbors": base64.b64encode(neighbors.tobytes()).decode("ascii"),
    }
    # JSON in a non-executable script element must still escape closing HTML tags.
    embedded = json.dumps(payload, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c")
    html = TEMPLATE.read_text(encoding="utf-8").replace("__AROMAP_PAYLOAD__", embedded)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html, encoding="utf-8")
    return {
        "file": str(destination.resolve()), "shape": list(fields.shape),
        "active_area_m2": run.grid.active_cell_count * run.grid.cell_size_m ** 2,
        "last_snapshot_s": float(output.sample_times_s[-1]),
        "final_snapshot_quantity": float(quantities[-1].sum()),
        "max_concentration": data_max, "file_mib": round(destination.stat().st_size / 1024 ** 2, 2),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="SimulationConfiguration or SimulationRequest JSON")
    parser.add_argument("--output", type=Path, required=True, help="Standalone .html output")
    parser.add_argument("--title", default=None)
    parser.add_argument("--scale-max", type=float, help="Fixed shared color ceiling for comparison files")
    parser.add_argument("--max-preview-mib", type=float, default=32)
    parser.add_argument("--max-step-s", type=float, default=0.25, help="Backend integration maximum, not snapshot interval")
    args = parser.parse_args()
    try:
        if args.input.stat().st_size > 2 * 1024 ** 2:
            raise ValueError("Input JSON exceeds the 2 MiB preview limit")
        raw = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Input must be a JSON configuration object")
        model = SimulationRequest if "client_request_id" in raw else SimulationConfiguration
        configuration = model.model_validate(raw)
        summary = export_preview(configuration, args.output,
                                 title=args.title or args.input.stem.replace("_", " ").title(),
                                 scale_max=args.scale_max, max_preview_mib=args.max_preview_mib,
                                 options=SolverOptions(max_step_s=args.max_step_s))
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(1, f"Preview failed: {exc}\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
