"""Test-only providers; never used as production fallback recognition."""

import os
import time
from pathlib import Path

from PIL import Image

from app.floor_plans.models import FloorPlan, Layout, RecognitionDraft
from app.floor_plans.recognition.interface import RecognitionError


def recognize(image_path: Path) -> RecognitionDraft:
    assert image_path.is_absolute()
    with Image.open(image_path) as image:
        width, height = image.size
    return RecognitionDraft(
        floor_plan=FloorPlan(layout=Layout(id="fixture", width_px=width, height_px=height)),
        warnings=[f"Test fixture executed in process {os.getpid()}; no geometry detected."],
    )


def fail(image_path: Path) -> RecognitionDraft:
    raise RecognitionError(f"Private provider details: {image_path}")


def wait_for_release(image_path: Path) -> RecognitionDraft:
    image_path.with_name("started").touch()
    deadline = time.monotonic() + 10
    while not image_path.with_name("release").exists():
        if time.monotonic() > deadline:
            raise RecognitionError("Test provider timed out")
        time.sleep(0.01)
    image_path.with_name("started").unlink(missing_ok=True)
    image_path.with_name("release").unlink(missing_ok=True)
    return recognize(image_path)
