"""Bounded, arbitrary-angle centerline proposals for clean digital drawings.

Distance ridges retain local stroke widths. Hough proposals are merged only across
source-supported gaps, then share exact intersection vertices. These are geometric
proposals, not semantic wall detections; the adaptive caller gates their use.
"""

import math

import cv2
import numpy as np
from shapely.geometry import LineString, Point

MAX_PROPOSALS = 256


def _cross(a, b):
    return float(a[0] * b[1] - a[1] * b[0])


def _supported(mask, start, end):
    length = np.linalg.norm(end - start)
    points = np.linspace(start, end, max(3, int(length)))
    x = np.clip(np.rint(points[:, 0]).astype(int), 0, mask.shape[1] - 1)
    y = np.clip(np.rint(points[:, 1]).astype(int), 0, mask.shape[0] - 1)
    return np.mean(mask[y, x] > 0) >= .95


def _merge(lines, mask):
    groups = []
    for start, end, width in sorted(lines, key=lambda line: -np.linalg.norm(line[1] - line[0])):
        direction = (end - start) / np.linalg.norm(end - start)
        for group in groups:
            origin, other = group[0]
            axis = (other - origin) / np.linalg.norm(other - origin)
            angle = math.degrees(math.acos(min(1, abs(float(direction @ axis)))))
            offset = max(abs(_cross(axis, start - origin)), abs(_cross(axis, end - origin)))
            if angle >= 2 or offset > max(1.5, min(width, 5) * .3):
                continue
            low, high = sorted([float((start - origin) @ axis), float((end - origin) @ axis)])
            extent = [float((p - origin) @ axis) for pair in group for p in pair]
            gap = max(min(extent) - high, low - max(extent), 0)
            if gap >= max(mask.shape) * .12:
                continue
            left, right = (max(extent), low) if low > max(extent) else (high, min(extent))
            if gap == 0 or _supported(mask, origin + left * axis, origin + right * axis):
                group.append((start, end))
                break
        else:
            groups.append([(start, end)])
    merged = []
    for group in groups:
        points = np.array([p for pair in group for p in pair])
        center = points.mean(axis=0)
        _, _, vectors = np.linalg.svd(points - center, full_matrices=False)
        axis = vectors[0]
        positions = (points - center) @ axis
        start, end = center + positions.min() * axis, center + positions.max() * axis
        if abs(axis[1]) < .003:
            start[1] = end[1] = float(np.median(points[:, 1]))
        if abs(axis[0]) < .003:
            start[0] = end[0] = float(np.median(points[:, 0]))
        merged.append((start, end))
    return merged


def _junctions(lines, distance):
    endpoints = [[a.copy(), b.copy()] for a, b in lines]
    events = [[] for _ in lines]
    height, width = distance.shape
    for i, (start, end) in enumerate(lines):
        vector = end - start
        for j in range(i + 1, len(lines)):
            origin, other = lines[j]
            axis = other - origin
            matrix = np.column_stack([vector, -axis])
            if abs(np.linalg.det(matrix)) < .1 * np.linalg.norm(vector) * np.linalg.norm(axis):
                continue
            position, other_position = np.linalg.solve(matrix, origin - start)
            intersection = start + position * vector
            if not (0 <= intersection[0] < width and 0 <= intersection[1] < height):
                continue
            x, y = np.rint(intersection).astype(int)
            x, y = min(width - 1, x), min(height - 1, y)
            # Bounded by measured ink width at the proposed junction.
            limit = min(35, max(8, float(distance[y, x]) * 3))
            if not (-limit / np.linalg.norm(vector) <= position <= 1 + limit / np.linalg.norm(vector)
                    and -limit / np.linalg.norm(axis) <= other_position <= 1 + limit / np.linalg.norm(axis)):
                continue
            shared = np.round(intersection, 4)
            for index, t, a, b in ((i, position, start, end), (j, other_position, origin, other)):
                events[index].append((t, shared))
                for k, p in enumerate((a, b)):
                    current = endpoints[index][k]
                    if (np.linalg.norm(shared - p) <= limit
                            and (np.array_equal(current, p) or np.linalg.norm(shared - p) < np.linalg.norm(current - p))):
                        endpoints[index][k] = shared
    result = []
    canonical = []
    for i, (start, end) in enumerate(lines):
        vector = end - start
        norm = float(vector @ vector)
        first, last = endpoints[i]
        low, high = sorted([float((first - start) @ vector / norm), float((last - start) @ vector / norm)])
        vertices = [(low, tuple(np.round(first, 4))), (high, tuple(np.round(last, 4)))]
        vertices.extend((t, tuple(p)) for t, p in events[i] if low - 1e-5 <= t <= high + 1e-5)
        ordered = []
        for _, point in sorted(vertices):
            match = next((q for q in canonical if Point(point).distance(Point(q)) <= 1.5), None)
            if match is None:
                match = point
                canonical.append(point)
            if not ordered or Point(match).distance(Point(ordered[-1])) > 1e-3:
                ordered.append(match)
        result.extend(LineString([a, b]) for a, b in zip(ordered, ordered[1:])
                      if Point(a).distance(Point(b)) > 1e-3)
    return result


def extract_centerlines(image):
    """Propose centerlines from dark, locally thick ink at any orientation.

    Caller supplies an image bounded by standardize_size. Thin text, light scans
    and semantic interpretation remain outside this conservative proposal path.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    mask = (gray < 100).astype(np.uint8) * 255
    distance = cv2.distanceTransform(mask, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    ridge = ((distance > 0) & (distance >= cv2.dilate(distance, np.ones((3, 3), np.uint8)) - .01)).astype(np.uint8) * 255
    found = cv2.HoughLinesP(ridge, 1, np.pi / 720, threshold=25,
                            minLineLength=max(30, int(max(image.shape[:2]) * .025)), maxLineGap=12)
    if found is None:
        return []
    lines = []
    # Inspect longest proposals first and bound the quadratic graph work.
    proposals = sorted(found.reshape(-1, 4), key=lambda p: -math.hypot(p[2] - p[0], p[3] - p[1]))[:MAX_PROPOSALS]
    for x1, y1, x2, y2 in proposals:
        start, end = np.array([x1, y1], float), np.array([x2, y2], float)
        positions = np.linspace(start, end, max(5, int(np.linalg.norm(end - start))))
        x = np.clip(np.rint(positions[:, 0]).astype(int), 0, mask.shape[1] - 1)
        y = np.clip(np.rint(positions[:, 1]).astype(int), 0, mask.shape[0] - 1)
        thickness = float(np.median(2 * distance[y, x] - 1))
        if np.mean(mask[y, x] > 0) >= .95 and thickness >= 2:
            lines.append((start, end, thickness))
    return _junctions(_merge(lines, mask), distance)
