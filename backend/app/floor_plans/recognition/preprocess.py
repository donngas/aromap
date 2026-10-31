"""Image loading and wall-mask extraction for shop floor plans.

Shop plans usually draw walls as the darkest and thickest strokes. Floors are
mid-tone fills, while shelving and fixture outlines, text, and dimension lines
are thin strokes.
"""

from pathlib import Path

import cv2
import numpy as np

# Grayscale level (0-255) at or below which a pixel may belong to a wall.
DARK_THRESHOLD = 100
# Strokes thinner than this (px) are never treated as walls.
MIN_WALL_THICKNESS_PX = 3
# Strokes thinner than this fraction of the estimated wall thickness are removed.
# Kept low because interior walls are often thinner than exterior walls.
MIN_THICKNESS_RATIO = 0.4


class InvalidImageError(ValueError):
    """The image file could not be read or decoded."""


def load_image(path: Path) -> np.ndarray:
    """Read a PNG/JPEG/WebP file into a BGR image without modifying it."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise InvalidImageError(f"Image file could not be read: {path}") from exc
    # imdecode instead of imread: imread cannot open non-ASCII paths on Windows.
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise InvalidImageError(f"Image data could not be decoded: {path}")
    return image


def dark_mask(image: np.ndarray, threshold: int = DARK_THRESHOLD) -> np.ndarray:
    """Return a binary mask (255 = dark) of pixels at or below ``threshold``."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY_INV)
    return mask


def estimate_wall_thickness(mask: np.ndarray) -> int | None:
    """Estimate the dominant thickness (px) of thick strokes in ``mask``.

    Stroke centers are distance-transform ridges whose value is about half the
    stroke width. Widths are weighted by themselves (roughly by area) so long,
    thick walls outweigh text and fixture outlines.
    """
    distance = cv2.distanceTransform(mask, cv2.DIST_L2, 3)
    ridge = (distance > 0) & (distance >= cv2.dilate(distance, np.ones((3, 3), np.uint8)))
    widths = np.rint(2 * distance[ridge] - 1).astype(int)
    widths = widths[widths >= MIN_WALL_THICKNESS_PX]
    if widths.size == 0:
        return None
    return int(np.argmax(np.bincount(widths, weights=widths)))


def wall_mask(image: np.ndarray) -> tuple[np.ndarray, int | None]:
    """Return a mask of wall-like strokes and the estimated wall thickness.

    The mask is empty and the thickness is None when no thick dark strokes exist.
    """
    mask = dark_mask(image)
    thickness = estimate_wall_thickness(mask)
    if thickness is None:
        return np.zeros_like(mask), None
    # Odd sizes keep the kernel centered; even ones shift the opened mask by 1 px.
    size = max(MIN_WALL_THICKNESS_PX, round(thickness * MIN_THICKNESS_RATIO)) | 1
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (size, size))
    walls = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    return _remove_small_components(walls, min_area=2 * thickness**2), thickness


def _remove_small_components(mask: np.ndarray, min_area: int) -> np.ndarray:
    _, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    keep = stats[:, cv2.CC_STAT_AREA] >= min_area
    keep[0] = False  # Background label.
    return np.where(keep[labels], 255, 0).astype(np.uint8)
