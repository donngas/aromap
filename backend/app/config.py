"""Single-host settings. Relative data paths are resolved at startup."""

import os
import math
from dataclasses import dataclass
from pathlib import Path

DEFAULT_RECOGNITION_CALLABLE = "app.floor_plans.recognition.interface:recognize_floor_plan"


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(".data")
    max_upload_bytes: int = 10 * 1024 * 1024
    max_image_pixels: int = 20_000_000
    retention_seconds: int = 24 * 60 * 60
    cleanup_interval_seconds: int = 60
    queue_capacity: int = 4
    cors_origins: tuple[str, ...] = ("http://localhost:5173",)
    recognition_callable: str = DEFAULT_RECOGNITION_CALLABLE
    recognition_timeout_seconds: float = 60.0

    def __post_init__(self):
        for name in ("max_upload_bytes", "max_image_pixels", "retention_seconds",
                     "cleanup_interval_seconds", "queue_capacity"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if not math.isfinite(self.recognition_timeout_seconds) or self.recognition_timeout_seconds <= 0:
            raise ValueError("recognition_timeout_seconds must be finite and positive")
        if not self.recognition_callable:
            raise ValueError("recognition_callable must not be empty")

    @classmethod
    def from_env(cls):
        values = {}
        for name in ("max_upload_bytes", "max_image_pixels", "retention_seconds",
                     "cleanup_interval_seconds", "queue_capacity"):
            if (value := os.getenv(f"AROMAP_{name.upper()}")) is not None:
                values[name] = int(value)
        if (value := os.getenv("AROMAP_CORS_ORIGINS")) is not None:
            values["cors_origins"] = tuple(x.strip() for x in value.split(",") if x.strip())
        return cls(
            data_dir=Path(os.getenv("AROMAP_DATA_DIR", ".data")),
            recognition_callable=os.getenv("AROMAP_RECOGNITION_CALLABLE") or DEFAULT_RECOGNITION_CALLABLE,
            recognition_timeout_seconds=float(os.getenv("AROMAP_RECOGNITION_TIMEOUT_SECONDS", "60")),
            **values,
        )
