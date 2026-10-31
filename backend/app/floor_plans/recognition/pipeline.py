"""OpenCV recognition pipeline: shop floor-plan image to RecognitionDraft."""

import uuid
from pathlib import Path

from app.floor_plans.models import (
    DoorOpening,
    FloorPlan,
    Layout,
    PixelPoint,
    RecognitionDraft,
    Wall,
    WindowOpening,
)
from app.floor_plans.recognition.openings import Opening, find_openings
from app.floor_plans.recognition.preprocess import (
    detail_mask,
    line_mask,
    load_image,
    standardize_size,
    wall_mask,
)
from app.floor_plans.recognition.topology import (
    drop_small_groups,
    find_parent,
    split_at_junctions,
)
from app.floor_plans.recognition.walls import WallSegment, detect_walls


def recognize(image_path: Path) -> RecognitionDraft:
    """Detect walls, doors, and windows in input-image pixel coordinates.

    Raises InvalidImageError when the file cannot be read or decoded.
    """
    original = load_image(image_path)
    height, width = original.shape[:2]
    image, scale = standardize_size(original)
    segments: list[WallSegment] = []
    openings: list[Opening] = []
    warnings: list[str] = []

    mask, thickness = wall_mask(image)
    if thickness is not None:
        segments = detect_walls(mask, thickness)
        segments, openings = find_openings(
            segments, line_mask(image), detail_mask(image), thickness
        )
        kept = drop_small_groups(segments)
        if len(kept) < len(segments):
            warnings.append(
                f"Ignored {len(segments) - len(kept)} small wall-like shapes not "
                "connected to the main walls (e.g. plants or equipment)."
            )
        segments = kept
        openings = [o for o in openings if find_parent(o, segments) is not None]
        segments = split_at_junctions(segments)

    wall_ids = {segment: _new_id() for segment in segments}
    doors: list[DoorOpening] = []
    windows: list[WindowOpening] = []
    for opening in openings:
        parent = find_parent(opening, segments)
        start, end = _points(opening.span, scale)
        if parent is None:
            warnings.append(
                f"Skipped a {opening.kind} at ({start.x:.0f}, {start.y:.0f}): "
                "a wall junction lies inside it."
            )
            continue
        model = DoorOpening if opening.kind == "door" else WindowOpening
        target = doors if opening.kind == "door" else windows
        target.append(model(id=_new_id(), wall_id=wall_ids[parent], start=start, end=end))

    if not wall_ids:
        warnings.append("No walls were detected; trace the walls manually.")
    elif not doors and not windows:
        warnings.append("No doors or windows were detected; add them manually.")

    walls = []
    for segment, wall_id in wall_ids.items():
        start, end = _points(segment, scale)
        walls.append(Wall(id=wall_id, start=start, end=end))
    layout = Layout(
        id=_new_id(),
        width_px=width,
        height_px=height,
        walls=walls,
        doors=doors,
        windows=windows,
    )
    return RecognitionDraft(floor_plan=FloorPlan(layout=layout), warnings=warnings)


def _points(segment: WallSegment, scale: float) -> tuple[PixelPoint, PixelPoint]:
    """Endpoints mapped from the standardized image back to input pixels."""
    (x1, y1), (x2, y2) = segment.endpoints
    return PixelPoint(x=x1 / scale, y=y1 / scale), PixelPoint(x=x2 / scale, y=y2 / scale)


def _new_id() -> str:
    return str(uuid.uuid4())
