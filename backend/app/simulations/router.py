"""Contract endpoints; the standalone solver is not wired to jobs/downloads yet."""

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
    200: {"description": "Concentration and active-domain mask bundle; see result.fields.encoding.",
          "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}},
    404: {"model": ErrorResponse},
})
def simulation_fields(job_id: str):
    """Future single download: concentration [T,P,H,W] and active_domain_mask [H,W]."""
    raise api_error(404, "result_not_found", "Simulation fields are unknown or expired.")
