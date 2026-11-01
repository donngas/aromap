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
# Kept low because interior walls are often thinner than exterior walls (e.g. a
# stockroom drawn at half the outer wall's width).
MIN_THICKNESS_RATIO = 0.35
# Inner walls drawn thinner still (e.g. stockroom partitions at under half the
# outer wall's width) are kept when they are the same color as the thick walls,
# within this many gray levels, at least MIN_WALL_THICKNESS_PX wide, and joined
# to the thick walls. Text is thinner and fixtures are lighter, so both drop out.
# Only for solid dark walls; line drawings have no wall color to match.
WALL_COLOR_TOLERANCE = 30
# Such a stroke must be one unbroken run across at this fraction of its length
# (a solid bar; an outline has two edges across it), have a wall along its line within this many wall thicknesses past
# each end (touching, or across a door gap), and not run within HUG_DISTANCE_RATIO
# thicknesses of a parallel wall along HUG_FRACTION of its length.
THIN_WALL_MIN_SOLID = 0.8
MAX_DOOR_GAP_RATIO = 15
HUG_DISTANCE_RATIO = 2
HUG_FRACTION = 0.5
# A stroke at least this many wall thicknesses long may have one free end, e.g. a
# partition ending between two doors (longer than most furniture).
THIN_WALL_FREE_END_RATIO = 10
# Wall blobs smaller than 2 x thickness^2 are dropped as marks, unless they are at
# least thickness^2 and wall lies on their line on both sides within this many
# thicknesses: a short wall between two windows.
MAX_SMALL_WALL_GAP_RATIO = 15
# Light glazing beside black walls is looked for again with the walls (and this
# many px around them) painted white: dark walls make a light line look no darker
# than its surroundings.
GLAZING_WALL_MARGIN_PX = 2


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


def glazing_mask(image: np.ndarray, walls: np.ndarray) -> np.ndarray:
    """Return ``line_mask`` plus light lines found with the walls painted white.

    Next to black walls the neighborhood mean is dark, so light gray glazing
    (e.g. a small window between two wall ends) is missed by ``line_mask``. Only
    used to look for glazing; door arcs and leaves keep ``line_mask``.
    """
    lines = line_mask(image)
    size = 2 * GLAZING_WALL_MARGIN_PX + 1
    near_walls = cv2.dilate(walls, np.ones((size, size), np.uint8)) > 0
    clean = image.copy()
    clean[near_walls] = 255
    extra = line_mask(clean)
    extra[near_walls] = 0
    return lines | extra


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
            return _with_thin_walls(image, walls, thickness), thickness
        if best_thickness is None or coverage > best_coverage:
            best_mask, best_thickness, best_coverage = walls, thickness, coverage
    if best_thickness is None:
        return best_mask, best_thickness
    return _with_thin_walls(image, best_mask, best_thickness), best_thickness


def _with_thin_walls(image: np.ndarray, walls: np.ndarray, thickness: int) -> np.ndarray:
    """Add thin strokes of the thick walls' color that join the thick walls.

    Each stroke must be at least one wall thickness long, so the anti-aliased
    edges of thick walls (e.g. at a window's ends) are not added. It must also
    look like a wall rather than furniture drawn in the same ink (see
    _is_thin_wall).
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    core = cv2.erode(walls, np.ones((3, 3), np.uint8)) > 0
    if not core.any():
        return walls
    level = int(np.median(gray[core]))
    if level > DARK_THRESHOLD:
        return walls
    same = (np.abs(gray.astype(np.int16) - level) <= WALL_COLOR_TOLERANCE).astype(np.uint8)
    size = MIN_WALL_THICKNESS_PX
    thin = cv2.morphologyEx(same * 255, cv2.MORPH_OPEN, np.ones((size, size), np.uint8))
    thin[walls > 0] = 0
    count, pieces, stats, _ = cv2.connectedComponentsWithStats(thin, connectivity=8)
    candidates = walls | thin
    keep_piece = np.zeros(count, dtype=bool)
    for i in range(1, count):
        x, y, width, height, area = stats[i]
        piece = pieces[y : y + height, x : x + width] == i
        keep_piece[i] = _is_thin_wall(candidates, piece, (x, y, width, height, area), thickness)
    thin = np.where(keep_piece[pieces], 255, 0).astype(np.uint8)
    if not thin.any():
        return walls
    combined = walls | thin
    _, labels = cv2.connectedComponents(combined, connectivity=8)
    joined = np.unique(labels[walls > 0])
    keep = np.isin(labels, joined[joined > 0]) & (thin > 0)
    return np.where(keep, 255, walls).astype(np.uint8)


def _is_thin_wall(
    walls: np.ndarray, piece: np.ndarray, box: tuple[int, int, int, int, int], thickness: int
) -> bool:
    """Whether a thin wall-colored stroke is a wall, not furniture in the same ink.

    A wall is a solid straight bar (furniture is mostly outlines: sinks, tables,
    sofas). Each end reaches a wall along its line, touching it or across a door
    gap (furniture sticking out from a wall ends in open floor); a long stroke may
    have one free end (see THIN_WALL_FREE_END_RATIO). It doesn't run
    alongside another wall (counter fronts and shelving stand just off a wall).
    ``walls`` holds the thick walls and all thin candidates.
    """
    x, y, width, height, _ = box
    if max(width, height) < thickness:
        return False
    horizontal = width >= height
    sections = piece.T if horizontal else piece  # one row per step along the stroke
    starts = np.diff(sections.astype(np.int8), axis=1, prepend=0) == 1
    if (starts.sum(axis=1) == 1).mean() < THIN_WALL_MIN_SOLID:
        return False
    # Work along the stroke: rows across it, columns along it.
    lines = walls if horizontal else walls.T
    along, across, length, span = (x, y, width, height) if horizontal else (y, x, height, width)
    band = lines[across : across + span]
    reach = int(MAX_DOOR_GAP_RATIO * thickness)
    before = band[:, max(0, along - reach) : along]
    after = band[:, along + length : along + length + reach]
    ends = int((before > 0).any()) + int((after > 0).any())
    if ends < (1 if length >= THIN_WALL_FREE_END_RATIO * thickness else 2):
        return False
    margin, side = 2, int(HUG_DISTANCE_RATIO * thickness)
    above = lines[max(0, across - side) : max(0, across - margin), along : along + length]
    below = lines[across + span + margin : across + span + side, along : along + length]
    return all(
        part.size == 0 or (part > 0).any(axis=0).mean() < HUG_FRACTION for part in (above, below)
    )


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
    opened = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    walls = _remove_small_components(opened, min_area=2 * thickness**2)
    return _with_small_walls_on_line(opened, walls, thickness)


def _with_small_walls_on_line(
    opened: np.ndarray, walls: np.ndarray, thickness: int
) -> np.ndarray:
    """Add small blobs with wall on their line on both sides (MAX_SMALL_WALL_GAP_RATIO)."""
    count, labels, stats, _ = cv2.connectedComponentsWithStats(opened, connectivity=8)
    reach = MAX_SMALL_WALL_GAP_RATIO * thickness
    result = walls.copy()
    for i in range(1, count):
        x, y, width, height, area = stats[i]
        if not thickness**2 <= area < 2 * thickness**2:
            continue
        if width >= height:
            band = walls[y : y + height]
            before, after = band[:, max(0, x - reach) : x], band[:, x + width : x + width + reach]
        else:
            band = walls[:, x : x + width]
            before, after = band[max(0, y - reach) : y], band[y + height : y + height + reach]
        if before.any() and after.any():
            result[labels == i] = 255
    return result


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
