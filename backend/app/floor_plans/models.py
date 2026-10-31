"""Draft geometry contracts. Topology validation is not implemented yet."""

from math import isfinite
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator


class PixelPoint(BaseModel):
    """Image pixels: top-left origin, x rightward, y downward.

    Display zoom/pan must not change these coordinates. The frontend owns
    calibration and converts pixel geometry to meters for simulation requests.
    """

    x: float = Field(description="Horizontal position in prepared-image pixels, increasing rightward.")
    y: float = Field(description="Vertical position in prepared-image pixels, increasing downward.")


class PixelIndoorDomain(BaseModel):
    """Estimated indoor footprint in prepared-image pixels, editable by the user.

    One ordered outer polygon (possibly concave), with optional excluded holes.
    Closing edges are implicit. Internal walls and rooms are not holes. Full
    polygon topology validation and footprint extraction are not implemented here.
    """

    boundary: list[PixelPoint] = Field(
        min_length=3,
        description="Ordered outer perimeter vertices in pixels; final-to-first edge is implicit.",
    )
    holes: list[Annotated[list[PixelPoint], Field(min_length=3)]] = Field(
        default_factory=list,
        description="Excluded interior polygons in pixels, e.g. courtyards; each closes implicitly.",
    )


    @model_validator(mode="after")
    def finite_coordinates(self):
        for ring in (self.boundary, *self.holes):
            if any(not isfinite(point.x) or not isfinite(point.y) for point in ring):
                raise ValueError("Indoor domain vertices must have finite pixel coordinates")
        return self


class ReferenceImage(BaseModel):
    media_type: Literal["image/png", "image/jpeg", "image/webp"]
    data_base64: str  # Embedded for portable JSON exports; no expiring URL.
    width_px: int = Field(gt=0, description="Reference image width in pixels.")
    height_px: int = Field(gt=0, description="Reference image height in pixels.")


class ScaleCalibration(BaseModel):
    start: PixelPoint = Field(description="Calibration segment start in prepared-image pixels.")
    end: PixelPoint = Field(description="Calibration segment end in prepared-image pixels.")
    distance_m: float = Field(gt=0, description="Known physical segment length in meters, not pixels.")


class Wall(BaseModel):
    """Nonzero, zero-thickness segment; split at every crossing/T-junction.

    Connected segments share identical endpoint coordinates. No junction may
    remain in a segment's interior. Topology checks are not implemented here.
    """

    id: str
    start: PixelPoint = Field(description="Wall start in prepared-image pixels.")
    end: PixelPoint = Field(description="Wall end in prepared-image pixels.")


class DoorOpening(BaseModel):
    """Nonzero opening along one referenced wall; state belongs to a scenario.

    Both endpoints must lie on that wall after junction splitting. IDs must be
    unique across the layout's doors and windows.
    """

    id: str
    wall_id: str
    start: PixelPoint = Field(description="Door opening start on the parent wall, in pixels.")
    end: PixelPoint = Field(description="Door opening end on the parent wall, in pixels.")


class WindowOpening(BaseModel):
    """Window segment with the same geometry/ID rules as DoorOpening.

    Recognition describes location only; ventilation behavior is not inferred.
    """

    id: str
    wall_id: str
    start: PixelPoint = Field(description="Window opening start on the parent wall, in pixels.")
    end: PixelPoint = Field(description="Window opening end on the parent wall, in pixels.")


class RoomLabel(BaseModel):
    id: str
    name: str
    position: PixelPoint = Field(description="Label anchor in prepared-image pixels.")


class Layout(BaseModel):
    """Editable image-coordinate geometry, separate from the simulation grid.

    Wall IDs are unique within walls; opening IDs are unique across doors and
    windows. Parent walls span openings; do not cut holes in their geometry.
    All coordinates map to the reference image, including after preprocessing.
    """

    id: str
    revision: int = Field(default=1, ge=1)
    width_px: int = Field(gt=0, description="Prepared-image width in pixels, not physical meters.")
    height_px: int = Field(gt=0, description="Prepared-image height in pixels, not physical meters.")
    walls: list[Wall] = Field(default_factory=list)
    doors: list[DoorOpening] = Field(default_factory=list)
    windows: list[WindowOpening] = Field(default_factory=list)
    room_labels: list[RoomLabel] = Field(default_factory=list)
    indoor_domain: PixelIndoorDomain | None = Field(
        default=None,
        description="Estimated footprint in pixels for user review/correction; null when unavailable."
                    " A missing estimate is accompanied by a recognition warning.",
    )
    calibration: ScaleCalibration | None = Field(
        default=None, description="Pixel-to-meter calibration owned by FE; recognition returns null.",
    )


class FloorPlan(BaseModel):
    layout: Layout = Field(description="Editable geometry in prepared-image pixel coordinates.")
    reference_image: ReferenceImage | None = None


class RecognitionDraft(BaseModel):
    """Recognizer output: revision 1, no calibration or embedded reference image.

    The recognizer generates layout/geometry IDs. Partial or empty geometry is
    allowed with warnings; a draft does not establish simulation readiness.
    indoor_domain is a pixel-coordinate estimate or null with a warning, never a
    metric simulation domain. The user can correct or trace it before calibration.
    """

    floor_plan: FloorPlan
    warnings: list[str] = Field(default_factory=list)
