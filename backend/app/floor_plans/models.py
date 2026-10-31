"""Draft geometry contracts. Topology validation is not implemented yet."""

from typing import Literal

from pydantic import BaseModel, Field


class Point(BaseModel):
    x: float
    y: float


class ReferenceImage(BaseModel):
    media_type: Literal["image/png", "image/jpeg", "image/webp"]
    data_base64: str  # Embedded for portable JSON exports; no expiring URL.
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)


class ScaleCalibration(BaseModel):
    start: Point
    end: Point
    distance_m: float = Field(gt=0)


class Wall(BaseModel):
    id: str
    start: Point
    end: Point


class DoorOpening(BaseModel):
    id: str
    wall_id: str
    start: Point
    end: Point
    is_open: bool = True


class RoomLabel(BaseModel):
    id: str
    name: str
    position: Point


class Layout(BaseModel):
    id: str
    revision: int = Field(default=1, ge=1)
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    walls: list[Wall] = Field(default_factory=list)
    doors: list[DoorOpening] = Field(default_factory=list)
    room_labels: list[RoomLabel] = Field(default_factory=list)
    calibration: ScaleCalibration | None = None


class FloorPlan(BaseModel):
    layout: Layout
    reference_image: ReferenceImage | None = None


class RecognitionDraft(BaseModel):
    floor_plan: FloorPlan
    warnings: list[str] = Field(default_factory=list)
