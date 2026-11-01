"""Conservative geometry improvements around the existing orthogonal recognizer."""

import math
from uuid import uuid4

import cv2
import numpy as np
from shapely.affinity import scale as scale_geometry
from shapely.geometry import LineString, Point
from shapely.ops import nearest_points, polygonize, unary_union

from app.floor_plans.models import PixelIndoorDomain, PixelPoint, Wall
from app.floor_plans.recognition.preprocess import standardize_size
from app.floor_plans.recognition.vector_geometry import extract_centerlines


def _line(wall):
    return LineString([(wall.start.x, wall.start.y), (wall.end.x, wall.end.y)])


def _point(p):
    return PixelPoint(x=float(p[0]), y=float(p[1]))


def _domain_area(draft):
    domain = draft.floor_plan.layout.indoor_domain
    if domain is None:
        return 0
    from shapely.geometry import Polygon
    return Polygon([(p.x, p.y) for p in domain.boundary]).area


def _publish(base, lines, domain, warning):
    graph = unary_union(lines)
    pieces = [graph] if graph.geom_type == "LineString" else list(graph.geoms)
    result = base.model_copy(deep=True)
    layout = result.floor_plan.layout
    previous = list(layout.walls)
    walls = []
    for piece in pieces:
        for start, end in zip(piece.coords, list(piece.coords)[1:]):
            segment = LineString([start, end])
            if segment.length < 1e-5:
                continue
            old = next((w for w in previous if _line(w).equals(segment)), None)
            walls.append(Wall(id=old.id if old else uuid4().hex, start=_point(start), end=_point(end)))
    for opening in [*layout.doors, *layout.windows]:
        candidates = [w for w in walls if all(_line(w).distance(Point(p)) <= 3 for p in _line(opening).coords)]
        if len(candidates) != 1:
            return base  # Never trade a valid opening for extra wall coverage.
        parent = _line(candidates[0])
        projected = [parent.interpolate(parent.project(Point(p))).coords[0] for p in _line(opening).coords]
        if Point(projected[0]).distance(Point(projected[1])) < 1e-5:
            return base
        opening.wall_id = candidates[0].id
        opening.start, opening.end = map(_point, projected)
    openings = [*layout.doors, *layout.windows]
    for index, opening in enumerate(openings):
        for other in openings[index + 1:]:
            if opening.wall_id == other.wall_id and _line(opening).intersection(_line(other)).length > 1e-5:
                return base
    layout.walls = walls
    if domain is not None:
        layout.indoor_domain = PixelIndoorDomain(
            boundary=[_point(p) for p in list(domain.exterior.coords)[:-1]],
            holes=[[_point(p) for p in list(ring.coords)[:-1]] for ring in domain.interiors],
        )
        result.warnings = [w for w in result.warnings if "Indoor domain estimate is unavailable" not in w
                           and "No walls were detected" not in w]
    result.warnings.append(warning)
    return result


def _refine_apertures(image, draft):
    """Bound deskew interpolation drift using dense wall ink at each jamb."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    ink = (gray < 100).astype(np.uint8)
    distance = cv2.distanceTransform(ink, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    layout = draft.floor_plan.layout
    parents = {wall.id: wall for wall in layout.walls}
    for opening in [*layout.doors, *layout.windows]:
        wall = _line(parents[opening.wall_id])
        origin = np.array(wall.coords[0])
        direction = (np.array(wall.coords[-1]) - origin) / wall.length
        normal = np.array([-direction[1], direction[0]])
        samples = origin + np.linspace(0, wall.length, max(2, int(wall.length)))[:, None] * direction
        pixels = np.rint(samples).astype(int)
        pixels[:, 0] = pixels[:, 0].clip(0, gray.shape[1] - 1)
        pixels[:, 1] = pixels[:, 1].clip(0, gray.shape[0] - 1)
        half_width = float(np.percentile(distance[pixels[:, 1], pixels[:, 0]], 75))
        if half_width < 2:
            continue
        endpoints = [wall.project(Point(p)) for p in _line(opening).coords]
        lo, hi = sorted(endpoints)
        margin = min(half_width * 2, (hi - lo) * .2)
        positions = np.arange(max(0, lo - margin), min(wall.length, hi + margin), .5)
        offsets = np.arange(-half_width * .6, half_width * .6 + .5, .5)
        coords = origin + positions[:, None, None] * direction + offsets[None, :, None] * normal
        coords = np.rint(coords).astype(int)
        x = coords[:, :, 0].clip(0, gray.shape[1] - 1)
        y = coords[:, :, 1].clip(0, gray.shape[0] - 1)
        opaque = ink[y, x].mean(axis=1) >= .6
        midpoint = int(np.argmin(abs(positions - (lo + hi) / 2)))
        if opaque[midpoint]:
            continue
        left = midpoint
        right = midpoint
        while left > 0 and not opaque[left - 1]:
            left -= 1
        while right + 1 < len(positions) and not opaque[right + 1]:
            right += 1
        if left == 0 or right == len(positions) - 1:
            continue
        refined = [positions[left] - .25, positions[right] + .25]
        if max(abs(refined[0] - lo), abs(refined[1] - hi)) > margin:
            continue
        overlap = False
        for other in [*layout.doors, *layout.windows]:
            if other is opening or other.wall_id != opening.wall_id:
                continue
            other_lo, other_hi = sorted(wall.project(Point(p)) for p in _line(other).coords)
            if min(refined[1], other_hi) - max(refined[0], other_lo) > 1e-5:
                overlap = True
                break
        if overlap:
            continue
        if endpoints[0] > endpoints[1]:
            refined.reverse()
        opening.start, opening.end = [_point(origin + t * direction) for t in refined]


def _deskew(original, base, proposals, recognize_orthogonal):
    if not proposals:
        return None
    angles = np.array([math.atan2(line.coords[-1][1] - line.coords[0][1],
                                  line.coords[-1][0] - line.coords[0][0]) for line in proposals])
    weights = np.array([line.length for line in proposals])
    # Orthogonal directions share the same phase after multiplication by four.
    direction = np.sum(weights * np.exp(4j * angles))
    if abs(direction) / weights.sum() < .85:
        return None
    angle = math.degrees(np.angle(direction) / 4)
    if abs(angle) < .75:
        return None
    height, width = original.shape[:2]
    source, factor = standardize_size(original)
    source_height, source_width = source.shape[:2]
    matrix = cv2.getRotationMatrix2D((source_width / 2, source_height / 2), angle, 1)
    cosine, sine = abs(matrix[0, 0]), abs(matrix[0, 1])
    target_width = math.ceil(source_height * sine + source_width * cosine)
    target_height = math.ceil(source_height * cosine + source_width * sine)
    matrix[0, 2] += target_width / 2 - source_width / 2
    matrix[1, 2] += target_height / 2 - source_height / 2
    enlargement = min(2.0, 2000 / max(target_width, target_height))
    matrix *= enlargement
    rotated = cv2.warpAffine(source, matrix, (math.ceil(target_width * enlargement), math.ceil(target_height * enlargement)),
                             flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))
    draft = recognize_orthogonal(rotated)
    if _domain_area(draft) / (factor * enlargement) ** 2 < max(width * height * .1, _domain_area(base) * 1.2):
        return None
    _refine_apertures(rotated, draft)
    inverse = cv2.invertAffineTransform(matrix)
    layout = draft.floor_plan.layout
    points = [p for wall in [*layout.walls, *layout.doors, *layout.windows] for p in (wall.start, wall.end)]
    points.extend(label.position for label in layout.room_labels)
    if layout.indoor_domain:
        points.extend(p for ring in (layout.indoor_domain.boundary, *layout.indoor_domain.holes) for p in ring)
    mapped = [(inverse @ np.array([p.x, p.y, 1])) / factor for p in points]
    if any(not (0 <= p[0] <= width and 0 <= p[1] <= height) for p in mapped):
        return None
    for point, mapped_point in zip(points, mapped):
        point.x, point.y = map(float, mapped_point)
    layout.width_px, layout.height_px = width, height
    draft.warnings.append(f"Deskewed a clean orthogonal plan by {angle:.2f} degrees; geometry maps to original pixels.")
    return draft


def improve_geometry(original, base, recognize_orthogonal):
    """Improve clear unsupported geometry, retaining conservative classic results."""
    prepared, factor = standardize_size(original)
    proposals = extract_centerlines(prepared)
    if not proposals:
        return base
    if factor != 1:
        proposals = [scale_geometry(line, xfact=1 / factor, yfact=1 / factor, origin=(0, 0)) for line in proposals]
    height, width = original.shape[:2]
    if _domain_area(base) < width * height * .1:
        rectified = _deskew(original, base, proposals, recognize_orthogonal)
        if rectified is not None:
            return rectified
        # A fallback must provide a substantial closed envelope, not isolated
        # furniture/text rectangles. Keep the connected network of that envelope.
        graph = unary_union(proposals)
        polygons = list(polygonize(graph))
        if not polygons:
            return base
        envelope = unary_union(polygons)
        if envelope.geom_type != "Polygon" or envelope.area < width * height * .1:
            return base
        network = [line for line in proposals if envelope.buffer(1).covers(line)]
        return _publish(base, network, envelope,
                        "Recovered a closed wall graph using local stroke widths and arbitrary angles; verify openings manually.")

    # Only add a missing partition when BOTH ends meet existing walls and it
    # creates substantial enclosed regions inside the established footprint.
    lines = [_line(w) for w in base.floor_plan.layout.walls]
    graph = unary_union(lines)
    added = 0
    from shapely.geometry import Polygon
    domain = base.floor_plan.layout.indoor_domain
    footprint = Polygon([(p.x, p.y) for p in domain.boundary],
                        [[(p.x, p.y) for p in ring] for ring in domain.holes])
    min_length = max(30, max(width, height) * .05)
    ink = (cv2.cvtColor(prepared, cv2.COLOR_BGR2GRAY) < 100).astype(np.uint8) * 255
    local_distance = cv2.distanceTransform(ink, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    protected = {o.wall_id for o in [*base.floor_plan.layout.doors, *base.floor_plan.layout.windows]}
    for proposal in proposals:
        if proposal.length < min_length or not footprint.buffer(1).covers(proposal):
            continue
        if proposal.difference(graph.buffer(2)).length < proposal.length * .7:
            continue
        endpoints = [Point(p) for p in (proposal.coords[0], proposal.coords[-1])]
        if any(graph.distance(p) > 3 for p in endpoints):
            continue
        candidate = LineString([nearest_points(graph, p)[0].coords[0] for p in endpoints])
        samples = np.array([proposal.interpolate(t, normalized=True).coords[0] for t in np.linspace(.1, .9, 9)]) * factor
        x = np.clip(np.rint(samples[:, 0]).astype(int), 0, prepared.shape[1] - 1)
        y = np.clip(np.rint(samples[:, 1]).astype(int), 0, prepared.shape[0] - 1)
        ink_width = min(15 / factor, max(3 / factor, float(np.median(local_distance[y, x])) * 2 / factor))
        # The orthogonal extractor can turn a diagonal wall's ends into short
        # perpendicular bounding-box stubs. Remove only nearby unprotected stubs
        # as part of an accepted angular correction, never opening parents.
        trimmed = []
        for line in lines:
            old = next((w for w in base.floor_plan.layout.walls if _line(w).equals(line)), None)
            artifact = (line.length < 3 * ink_width
                        and all(proposal.distance(Point(p)) <= ink_width for p in line.coords)
                        and (old is None or old.id not in protected))
            if not artifact:
                trimmed.append(line)
        cleaned = unary_union(trimmed)
        before = list(polygonize(cleaned))
        combined = unary_union([cleaned, candidate])
        after = list(polygonize(combined))
        new_faces = [p for p in after if not any(p.equals(old) for old in before)]
        if len(after) <= len(before) or not new_faces or min(p.area for p in new_faces) < footprint.area * .06:
            continue
        lines = [*trimmed, candidate]
        graph = combined
        added += 1
    if not added:
        return base
    return _publish(base, lines, None,
                    f"Recovered {added} source-supported partition segments using local stroke widths; verify the draft.")
