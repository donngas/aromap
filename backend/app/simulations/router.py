"""Contract endpoints; no solver, fake jobs, or fabricated fields are installed."""

from fastapi import APIRouter
from fastapi.responses import Response

from app.errors import ErrorResponse, api_error
from app.simulations.schemas import SimulationAccepted, SimulationRequest, SimulationStatus

router = APIRouter(prefix="/api/simulations", tags=["simulations"])


@router.post("", status_code=202, response_model=SimulationAccepted, responses={
    422: {"model": ErrorResponse}, 503: {"model": ErrorResponse},
})
def submit_simulation(payload: SimulationRequest):
    """Validate one metric configuration; execution is not implemented yet.

    Returns 503 simulation_unavailable without creating a job. The 202 response
    describes the future acceptance contract, not current runtime behavior.
    """
    raise api_error(503, "simulation_unavailable", "The simulation engine is not integrated yet.")


@router.get("/{job_id}", response_model=SimulationStatus, responses={404: {"model": ErrorResponse}})
def simulation_status(job_id: str):
    """Future status/result metadata. No simulation jobs exist yet, so returns 404."""
    raise api_error(404, "job_not_found", "Simulation job is unknown or expired.")


@router.get("/{job_id}/fields", response_class=Response, responses={
    200: {"description": "Concentration artifact; encoding is specified in result.fields.encoding.",
          "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}},
    404: {"model": ErrorResponse},
})
def simulation_fields(job_id: str):
    """Future array download with logical axes [time, channel, row, column]."""
    raise api_error(404, "result_not_found", "Simulation fields are unknown or expired.")


@router.get("/{job_id}/mask", response_class=Response, responses={
    200: {"description": "Active-domain mask artifact; encoding is specified in result metadata.",
          "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}},
    404: {"model": ErrorResponse},
})
def simulation_mask(job_id: str):
    """Future shared mask download; true means usable indoor space."""
    raise api_error(404, "result_not_found", "Simulation mask is unknown or expired.")
