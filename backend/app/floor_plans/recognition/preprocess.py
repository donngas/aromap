"""Image loading and wall-mask extraction for shop floor plans.

Shop plans usually draw walls as the darkest and thickest strokes. Floors are
mid-tone fills, while shelving and fixture outlines, text, and dimension lines
are thin strokes.
"""

from pathlib import Path

import cv2
import numpy as np

# Larger images are downscaled so their long side is this many pixels.
MAX_LONG_SIDE_PX = 2000
# Grayscale level (0-255) at or below which a pixel may belong to a wall.
DARK_THRESHOLD = 100
# Levels tried for solid walls, strictest first. The first that yields a plan's
# worth of walls is used, so black walls keep the strict level while gray walls
# (light ink, pencil scans) get a looser one.
DARK_THRESHOLDS = (DARK_THRESHOLD, 120, 140, 160, 180)
# Long thick strokes must cover at least this fraction of the image to count as
# a plan's walls; less means stray marks, and the next candidate is tried.
MIN_WALL_COVERAGE = 0.005
# Strokes at least this many times the wall thickness long count toward coverage.
WALL_COVERAGE_LENGTH_RATIO = 3
# Solid walls are at least this thick (px); thinner dark strokes mean the plan
# is a line drawing and is read in that mode instead.
MIN_SOLID_WALL_THICKNESS_PX = 4
# Detail strokes (glazing lines, door arcs) are pixels at least DETAIL_CONTRAST
# gray levels darker than the mean of their DETAIL_BLOCK_PX neighborhood.
DETAIL_BLOCK_PX = 25
DETAIL_CONTRAST = 25
# Enclosed background regions narrower than this fraction of the image's long
# side (as a half-width) are the insides of hollow, line-drawn walls.
HOLLOW_WALL_HALF_WIDTH_RATIO = 0.01
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


def standardize_size(image: np.ndarray) -> tuple[np.ndarray, float]:
    """Downscale large images; return the image and its scale (output px per input px).

    Bounds processing time and keeps wall thickness in a similar pixel range.
    Smaller images are returned unchanged, since upscaling adds no detail.
    """
    scale = min(1.0, MAX_LONG_SIDE_PX / max(image.shape[:2]))
    if scale == 1.0:
        return image, scale
    return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA), scale


def dark_mask(image: np.ndarray, threshold: int = DARK_THRESHOLD) -> np.ndarray:
    """Return a binary mask (255 = dark) of pixels at or below ``threshold``."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY_INV)
    return mask


def line_mask(image: np.ndarray) -> np.ndarray:
    """Return a mask of lines darker than their surroundings, whatever their shade.

    Unlike ``dark_mask``, this keeps light gray lines of line drawings, while flat
    fills drop out because they match their surroundings. Contrast is measured on
    each pixel's darkest color channel, so colored lines count too.
    """
    darkest = image.min(axis=2)
    return cv2.adaptiveThreshold(
        darkest,
        255,
        cv2.ADAPTIVE_THRESH_MEAN_C,
        cv2.THRESH_BINARY_INV,
        DETAIL_BLOCK_PX,
        DETAIL_CONTRAST,
    )


def detail_mask(image: np.ndarray) -> np.ndarray:
    """Return a mask of thin strokes that differ from their surroundings in any color.

    Used for door arcs and window glazing, which plans may draw in light or
    colored ink, e.g. pink arcs that are lighter than an orange floor but differ
    strongly in one channel. Flat fills drop out because they match their
    surroundings.
    """
    surroundings = cv2.blur(image, (DETAIL_BLOCK_PX, DETAIL_BLOCK_PX))
    difference = cv2.absdiff(image, surroundings).max(axis=2)
    return np.where(difference >= DETAIL_CONTRAST, 255, 0).astype(np.uint8)


def fill_hollow_walls(lines: np.ndarray) -> np.ndarray:
    """Fill narrow enclosed gaps between lines, turning hollow walls solid.

    Line drawings often draw a wall as two thin lines with background between
    them. Enclosed background regions no wider than a wall are filled; rooms and
    the area around the plan are much wider and stay empty.
    """
    max_half_width = max(MIN_WALL_THICKNESS_PX, HOLLOW_WALL_HALF_WIDTH_RATIO * max(lines.shape))
    background = cv2.bitwise_not(lines)
    count, labels = cv2.connectedComponents(background, connectivity=4)
    distance = cv2.distanceTransform(background, cv2.DIST_L2, 3)
    wide = np.zeros(count, dtype=bool)
    wide[np.unique(labels[distance > max_half_width])] = True
    return np.where(wide[labels], 0, 255).astype(np.uint8)


def estimate_wall_thickness(mask: np.ndarray) -> int | None:
    """Estimate the dominant thickness (px) of thick strokes in ``mask``.

    Stroke centers are distance-transform ridges whose value is about half the
    stroke width. Each width's vote is weighted by the width squared, so a few
    long thick walls outweigh many bold thin lines (text, table and chair
    outlines), which can otherwise be far more numerous.
    """
    distance = cv2.distanceTransform(mask, cv2.DIST_L2, 3)
    ridge = (distance > 0) & (distance >= cv2.dilate(distance, np.ones((3, 3), np.uint8)))
    widths = np.rint(2 * distance[ridge] - 1).astype(int)
    widths = widths[widths >= MIN_WALL_THICKNESS_PX]
    if widths.size == 0:
        return None
    return int(np.argmax(np.bincount(widths, weights=widths.astype(float) ** 2)))


def wall_mask(image: np.ndarray) -> tuple[np.ndarray, int | None]:
    """Return a mask of wall-like strokes and the estimated wall thickness.

    Solid walls are read from dark strokes, loosening the darkness level until
    long thick strokes cover enough of the image. If none does, the plan is read
    as a line drawing: lines of any shade are kept and hollow walls are filled.
    When no candidate is convincing, the one with the most wall coverage is
    returned. The mask is empty and the thickness is None without thick strokes.
    """
    best_mask, best_thickness, best_coverage = np.zeros(image.shape[:2], np.uint8), None, 0.0
    for candidate, min_thickness in _wall_candidates(image):
        thickness = estimate_wall_thickness(candidate)
        if thickness is None or thickness < min_thickness:
            continue
        walls = _thick_strokes(candidate, thickness)
        coverage = _wall_coverage(walls, thickness)
        if coverage >= MIN_WALL_COVERAGE:
            return walls, thickness
        if best_thickness is None or coverage > best_coverage:
            best_mask, best_thickness, best_coverage = walls, thickness, coverage
    return best_mask, best_thickness


def _wall_candidates(image: np.ndarray):
    """Raw stroke masks to try with their minimum wall thickness, from black solid
    walls to hollow line drawings."""
    for level in DARK_THRESHOLDS:
        yield dark_mask(image, level), MIN_SOLID_WALL_THICKNESS_PX
    yield fill_hollow_walls(line_mask(image)), MIN_WALL_THICKNESS_PX


def _thick_strokes(mask: np.ndarray, thickness: int) -> np.ndarray:
    # Odd sizes keep the kernel centered; even ones shift the opened mask by 1 px.
    size = max(MIN_WALL_THICKNESS_PX, round(thickness * MIN_THICKNESS_RATIO)) | 1
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (size, size))
    walls = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    return _remove_small_components(walls, min_area=2 * thickness**2)


def _wall_coverage(walls: np.ndarray, thickness: int) -> float:
    """Fraction of the image covered by long horizontal or vertical thick strokes."""
    length = (WALL_COVERAGE_LENGTH_RATIO * thickness) | 1
    horizontal = cv2.morphologyEx(
        walls, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (length, 1))
    )
    vertical = cv2.morphologyEx(
        walls, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, length))
    )
    return np.count_nonzero(horizontal | vertical) / walls.size


def _remove_small_components(mask: np.ndarray, min_area: int) -> np.ndarray:
    _, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    keep = stats[:, cv2.CC_STAT_AREA] >= min_area
    keep[0] = False  # Background label.
    return np.where(keep[labels], 255, 0).astype(np.uint8)
