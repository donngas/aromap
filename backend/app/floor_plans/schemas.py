"""Frontend-facing upload and recognition DTOs; no project persistence."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.errors import ErrorDetail
from app.floor_plans.models import RecognitionDraft


class UploadedImage(BaseModel):
    image_id: str
    image_url: str
    width_px: int
    height_px: int
    media_type: Literal["image/png"] = "image/png"
    expires_at: datetime


class RecognitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_id: str


class RecognitionAccepted(BaseModel):
    job_id: str
    status_url: str


class RecognitionStatus(BaseModel):
    job_id: str
    state: Literal["queued", "running", "succeeded", "failed"]
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    result: RecognitionDraft | None = None
    error: ErrorDetail | None = None
