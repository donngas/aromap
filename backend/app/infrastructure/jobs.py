"""Shared job status contract; execution and persistence are not implemented."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class JobStatus(BaseModel):
    id: str
    kind: Literal["recognition", "simulation"]
    state: Literal["queued", "running", "succeeded", "failed"]
    input_fingerprint: str
    expires_at: datetime
    result_artifact_id: str | None = None
    error_message: str | None = None
