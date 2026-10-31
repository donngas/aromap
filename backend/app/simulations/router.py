"""Asynchronous simulation submission, status, and field downloads."""
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from app.errors import ErrorResponse
from app.simulations.schemas import SimulationAccepted, SimulationRequest, SimulationStatus

router = APIRouter(prefix="/api/simulations", tags=["simulations"])


@router.post("", status_code=202, response_model=SimulationAccepted, responses={
    422: {"model": ErrorResponse}, 429: {"model": ErrorResponse},
})
async def submit_simulation(request: Request, payload: SimulationRequest):
    job_id = request.app.state.jobs.submit_simulation(payload)
    return SimulationAccepted(job_id=job_id, client_request_id=payload.client_request_id,
                              status_url=str(request.app.url_path_for("simulation_status", job_id=job_id)))


@router.get("/{job_id}", name="simulation_status", response_model=SimulationStatus, responses={404: {"model": ErrorResponse}})
def simulation_status(request: Request, job_id: str):
    return request.app.state.jobs.simulation_status(job_id)


@router.get("/{job_id}/fields", response_class=FileResponse, responses={
    200: {"description": "NPZ bundle containing concentration and active_domain_mask arrays",
          "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}},
    404: {"model": ErrorResponse},
})
def simulation_fields(request: Request, job_id: str):
    return FileResponse(request.app.state.jobs.simulation_fields(job_id), media_type="application/octet-stream",
                        headers={"Cache-Control": "no-store"})
