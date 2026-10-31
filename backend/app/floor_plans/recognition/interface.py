"""Recognition handoff contract, delegating to the OpenCV pipeline."""

from pathlib import Path

from app.floor_plans.models import RecognitionDraft
from app.floor_plans.recognition import pipeline
from app.floor_plans.recognition.preprocess import InvalidImageError


class RecognitionError(Exception):
    """The input image could not be read or recognition could not complete."""


def recognize_floor_plan(image_path: Path) -> RecognitionDraft:
    """Read a prepared image and return editable walls, doors, and windows.

    Input:
        Caller supplies an absolute path to a readable PNG/JPEG/WebP image with
        EXIF orientation already applied to its pixels. Caller owns storage and
        keeps the file available until this synchronous call finishes; execution
        outside the HTTP event loop and cleanup are caller responsibilities.

    Ownership:
        Read the original without modifying/deleting it. Private intermediates
        may be created and must be cleaned up by the implementation. Never
        construct upload paths, look up upload IDs, or return HTTP responses.

    Output:
        Return RecognitionDraft with generated layout/geometry IDs, revision 1,
        matching image dimensions, reference_image=None, and calibration=None.
        Map any internal resizing/rotation back to the input pixel coordinates.
        Follow the geometry rules in floor_plans.models, including splitting
        walls at crossings and T-junctions and assigning openings to final walls.
        Do not infer scenario states, airflow, or a computational grid.

    Failures:
        Incomplete/no detection returns partial/empty geometry with warnings.
        Unreadable input or processing failure raises RecognitionError, chaining
        the underlying exception when appropriate. Never return None.

    The implementation lives in ``pipeline``; this entry point maps its errors.
    """
    try:
        return pipeline.recognize(image_path)
    except InvalidImageError as exc:
        raise RecognitionError(str(exc)) from exc
    except Exception as exc:
        raise RecognitionError("Floor-plan recognition failed") from exc
