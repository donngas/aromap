"""Draft geometry contracts. Topology validation is not implemented yet."""

from typing import Literal

from pydantic import BaseModel, Field


class PixelPoint(BaseModel):
    """Image pixels: top-left origin, x rightward, y downward.

    Display zoom/pan must not change these coordinates. Simulation preparation
    converts them to metric coordinates using the layout's scale calibration.
    """

    x: float
    y: float


class ReferenceImage(BaseModel):
    media_type: Literal["image/png", "image/jpeg", "image/webp"]
    data_base64: str  # Embedded for portable JSON exports; no expiring URL.
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)


class ScaleCalibration(BaseModel):
    start: PixelPoint
    end: PixelPoint
    distance_m: float = Field(gt=0)


class Wall(BaseModel):
    """Nonzero, zero-thickness segment; split at every crossing/T-junction.

    Connected segments share identical endpoint coordinates. No junction may
    remain in a segment's interior. Topology checks are not implemented here.
    """

    id: str
    start: PixelPoint
    end: PixelPoint


class DoorOpening(BaseModel):
    """Nonzero opening along one referenced wall; state belongs to a scenario.

    Both endpoints must lie on that wall after junction splitting. IDs must be
    unique across the layout's doors and windows.
    """

    id: str
    wall_id: str
    start: PixelPoint
    end: PixelPoint


class WindowOpening(BaseModel):
    """Window segment with the same geometry/ID rules as DoorOpening.

    Recognition describes location only; ventilation behavior is not inferred.
    """

    id: str
    wall_id: str
    start: PixelPoint
    end: PixelPoint


class RoomLabel(BaseModel):
    id: str
    name: str
    position: PixelPoint


class Layout(BaseModel):
    """Editable image-coordinate geometry, separate from the simulation grid.

    Wall IDs are unique within walls; opening IDs are unique across doors and
    windows. Parent walls span openings; do not cut holes in their geometry.
    All coordinates map to the reference image, including after preprocessing.
    """

    id: str
    revision: int = Field(default=1, ge=1)
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    walls: list[Wall] = Field(default_factory=list)
    doors: list[DoorOpening] = Field(default_factory=list)
    windows: list[WindowOpening] = Field(default_factory=list)
    room_labels: list[RoomLabel] = Field(default_factory=list)
    calibration: ScaleCalibration | None = None


class FloorPlan(BaseModel):
    layout: Layout
    reference_image: ReferenceImage | None = None


class RecognitionDraft(BaseModel):
    """Recognizer output: revision 1, no calibration or embedded reference image.

    The recognizer generates layout/geometry IDs. Partial or empty geometry is
    allowed with warnings; a draft does not establish simulation readiness.
    """

    floor_plan: FloorPlan
    warnings: list[str] = Field(default_factory=list)
