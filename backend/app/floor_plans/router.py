"""Floor-plan upload, image retrieval, and asynchronous recognition."""

from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from app.errors import ErrorResponse
from app.floor_plans.schemas import (
    RecognitionAccepted, RecognitionRequest, RecognitionStatus, UploadedImage,
)

router = APIRouter(prefix="/api/floor-plans", tags=["floor-plans"], responses={
    status: {"model": ErrorResponse} for status in (404, 413, 415, 422, 429, 500, 503)
})


@router.post("/uploads", status_code=201, response_model=UploadedImage)
async def upload_image(request: Request, image: UploadFile):
    try:
        contents = await image.read(request.app.state.settings.max_upload_bytes + 1)
        metadata = await run_in_threadpool(request.app.state.floor_plans.upload, contents)
    finally:
        await image.close()
    return UploadedImage(
        **metadata,
        image_url=str(request.app.url_path_for("get_image", image_id=metadata["image_id"])),
    )


@router.get("/uploads/{image_id}/image", name="get_image", response_class=FileResponse,
            responses={200: {"content": {"image/png": {}}}})
def get_image(request: Request, image_id: str):
    path = request.app.state.floor_plans.get_image(image_id)
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/recognitions", status_code=202, response_model=RecognitionAccepted)
async def submit_recognition(request: Request, payload: RecognitionRequest):
    job_id = request.app.state.jobs.submit_recognition(payload.image_id, use_llm=payload.use_llm)
    return RecognitionAccepted(
        job_id=job_id,
        status_url=str(request.app.url_path_for("recognition_status", job_id=job_id)),
    )


@router.get("/recognitions/{job_id}", name="recognition_status", response_model=RecognitionStatus)
def recognition_status(request: Request, job_id: str):
    return request.app.state.jobs.recognition_status(job_id)
