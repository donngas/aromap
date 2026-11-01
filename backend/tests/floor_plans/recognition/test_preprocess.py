from pathlib import Path

import cv2
import numpy as np
import pytest

from app.floor_plans.recognition.preprocess import (
    InvalidImageError,
    dark_mask,
    detail_mask,
    estimate_wall_thickness,
    fill_hollow_walls,
    glazing_mask,
    line_mask,
    load_image,
    standardize_size,
    wall_mask,
)


def test_load_image_reads_png(tmp_path: Path, shop_plan: np.ndarray) -> None:
    path = tmp_path / "plan.png"
    path.write_bytes(cv2.imencode(".png", shop_plan)[1].tobytes())

    image = load_image(path)

    assert image.shape == shop_plan.shape
    assert np.array_equal(image, shop_plan)


def test_load_image_rejects_non_image(tmp_path: Path) -> None:
    path = tmp_path / "plan.png"
    path.write_bytes(b"not an image")

    with pytest.raises(InvalidImageError):
        load_image(path)


def test_load_image_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(InvalidImageError):
        load_image(tmp_path / "missing.png")


def test_dark_mask_ignores_colored_floors(shop_plan: np.ndarray) -> None:
    mask = dark_mask(shop_plan)

    assert mask[200, 150] == 0  # wood floor
    assert mask[200, 450] == 0  # tile floor
    assert mask[50, 300] == 255  # wall


def test_estimates_wall_thickness(shop_plan: np.ndarray) -> None:
    thickness = estimate_wall_thickness(dark_mask(shop_plan))

    assert thickness is not None
    assert 9 <= thickness <= 13  # drawn at 11 px


def test_wall_thickness_ignores_many_bold_thin_lines() -> None:
    # A 15 px shop outline, plus far more bold 3 px lines (tables, chairs, labels)
    # than wall: the walls still set the thickness.
    mask = np.zeros((600, 600), dtype=np.uint8)
    cv2.rectangle(mask, (50, 50), (550, 550), 255, 15)
    for y in range(80, 530, 12):
        cv2.line(mask, (80, y), (520, y), 255, 3)

    thickness = estimate_wall_thickness(mask)

    assert thickness is not None
    assert 13 <= thickness <= 17


def test_wall_mask_removes_thin_details(shop_plan: np.ndarray) -> None:
    mask, _ = wall_mask(shop_plan)

    assert mask[90, 150] == 0  # shelf outline
    assert mask[260, 450] == 0  # display table outline
    assert mask[25, 300] == 0  # dimension line
    assert not mask[230:265, 100:220].any()  # "SALES" text
    assert mask[50, 300] == 255
    assert mask[200, 550] == 255


def test_wall_mask_keeps_inner_walls_half_as_thick() -> None:
    # 9 px outer walls with a stockroom partition drawn 4 px thick.
    image = np.full((400, 600, 3), 255, dtype=np.uint8)
    gray = (60, 60, 60)
    for top_left, bottom_right in [((40, 40), (560, 48)), ((40, 352), (560, 360)),
                                   ((40, 40), (48, 360)), ((552, 40), (560, 360))]:
        cv2.rectangle(image, top_left, bottom_right, gray, cv2.FILLED)
    cv2.rectangle(image, (400, 40), (403, 200), gray, cv2.FILLED)

    mask, thickness = wall_mask(image)

    assert thickness == 9
    assert mask[120, 398:407].any()  # the partition survives


def test_wall_mask_is_empty_without_dark_strokes() -> None:
    blank = np.full((100, 100, 3), 255, dtype=np.uint8)

    mask, thickness = wall_mask(blank)

    assert thickness is None
    assert not mask.any()


def test_standardize_size_downscales_large_images() -> None:
    large = np.zeros((1000, 4000, 3), dtype=np.uint8)

    image, scale = standardize_size(large)

    assert image.shape[:2] == (500, 2000)
    assert scale == 0.5


def test_standardize_size_keeps_small_images(shop_plan: np.ndarray) -> None:
    image, scale = standardize_size(shop_plan)

    assert image is shop_plan
    assert scale == 1.0


def test_detail_mask_keeps_light_colored_lines_but_not_flat_fills() -> None:
    image = np.full((100, 100, 3), (120, 180, 250), dtype=np.uint8)  # orange floor
    cv2.line(image, (10, 50), (90, 50), (240, 144, 155), 1)  # pink arc-like line

    mask = detail_mask(image)

    assert mask[50, 50] == 255
    assert mask[20, 50] == 0


def test_line_mask_keeps_light_gray_lines() -> None:
    image = np.full((100, 100, 3), 255, dtype=np.uint8)
    cv2.line(image, (10, 50), (90, 50), (150, 150, 150), 1)

    assert line_mask(image)[50, 50] == 255
    assert dark_mask(image)[50, 50] == 0


def test_fill_hollow_walls_fills_space_between_parallel_lines() -> None:
    lines = np.zeros((300, 300), dtype=np.uint8)
    cv2.rectangle(lines, (50, 50), (250, 250), 255, 1)  # outer face of the wall
    cv2.rectangle(lines, (56, 56), (244, 244), 255, 1)  # inner face

    filled = fill_hollow_walls(lines)

    assert filled[53, 150] == 255  # inside the wall
    assert filled[150, 150] == 0  # the room
    assert filled[20, 20] == 0  # outside the plan


def test_wall_mask_reads_hollow_line_drawings() -> None:
    image = np.full((600, 600, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (100, 100), (500, 500), (140, 140, 140), 1)
    cv2.rectangle(image, (107, 107), (493, 493), (140, 140, 140), 1)

    mask, thickness = wall_mask(image)

    assert thickness is not None and 6 <= thickness <= 10
    assert mask[103, 300] == 255


def test_wall_mask_reads_gray_solid_walls() -> None:
    image = np.full((400, 400, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (50, 50), (350, 350), (130, 130, 130), 8)  # gray, not dark

    mask, thickness = wall_mask(image)

    assert thickness is not None and 6 <= thickness <= 10
    assert mask[50, 200] == 255


def test_wall_mask_ignores_stray_dark_marks_in_line_drawings(
    hollow_line_plan: np.ndarray,
) -> None:
    for x in (120, 200, 300):  # a few small dark blobs, e.g. scan specks or symbols
        cv2.circle(hollow_line_plan, (x, 380), 3, (0, 0, 0), cv2.FILLED)

    mask, thickness = wall_mask(hollow_line_plan)

    assert thickness is not None and thickness >= 6  # hollow walls, not the specks
    assert mask[53, 250] == 255


def _shop_with_thick_walls(width: int = 12) -> np.ndarray:
    image = np.full((400, 600, 3), 255, dtype=np.uint8)
    for top_left, bottom_right in [
        ((40, 40), (560, 40 + width - 1)),
        ((40, 361 - width), (560, 360)),
        ((40, 40), (40 + width - 1, 360)),
        ((561 - width, 40), (560, 360)),
    ]:
        cv2.rectangle(image, top_left, bottom_right, (0, 0, 0), cv2.FILLED)
    return image


def test_wall_mask_keeps_thin_partitions_in_wall_color() -> None:
    # 12 px black outer walls; a black stockroom partition only 4 px thick runs
    # from the top wall to the bottom wall.
    image = _shop_with_thick_walls()
    cv2.rectangle(image, (400, 52), (403, 348), (0, 0, 0), cv2.FILLED)

    mask, _ = wall_mask(image)

    assert mask[200, 400:404].all()


def test_wall_mask_skips_thin_strokes_that_are_not_walls() -> None:
    image = _shop_with_thick_walls()
    # 4 px strokes, each failing one wall check:
    cv2.rectangle(image, (400, 52), (403, 348), (150, 150, 150), cv2.FILLED)  # gray shelf
    cv2.rectangle(image, (200, 150), (300, 153), (0, 0, 0), cv2.FILLED)  # loose counter edge
    cv2.rectangle(image, (52, 200), (100, 203), (0, 0, 0), cv2.FILLED)  # shelf, free end
    cv2.rectangle(image, (100, 58), (300, 61), (0, 0, 0), cv2.FILLED)  # counter along wall
    for edge in [((52, 280), (120, 283)), ((52, 327), (120, 330)), ((117, 280), (120, 330))]:
        cv2.rectangle(image, *edge, (0, 0, 0), cv2.FILLED)  # outlined table at the wall

    mask, _ = wall_mask(image)

    assert not mask[200, 400:404].any()
    assert not mask[150:154, 200:301].any()
    assert not mask[200:204, 60:101].any()
    assert not mask[58:62, 100:301].any()
    assert not mask[300, 64:120].any()


def test_wall_mask_keeps_small_wall_between_two_windows() -> None:
    # 10 px outer wall with two windows (gaps) and 12 px of wall between them.
    image = np.full((300, 400, 3), 255, dtype=np.uint8)
    for x0, x1 in [(20, 120), (180, 191), (250, 380)]:
        cv2.rectangle(image, (x0, 150), (x1, 159), (0, 0, 0), cv2.FILLED)
    cv2.rectangle(image, (20, 20), (29, 280), (0, 0, 0), cv2.FILLED)
    cv2.rectangle(image, (371, 20), (380, 280), (0, 0, 0), cv2.FILLED)

    mask, _ = wall_mask(image)

    assert mask[155, 180:192].all()


def test_glazing_mask_finds_light_lines_beside_black_walls() -> None:
    # A small window: two light gray lines in a 24 px gap between black wall ends.
    image = np.full((100, 200, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (0, 40), (88, 51), (0, 0, 0), cv2.FILLED)
    cv2.rectangle(image, (112, 40), (199, 51), (0, 0, 0), cv2.FILLED)
    for y in (41, 50):
        cv2.line(image, (89, y), (111, y), (205, 205, 205), 1)
    walls, _ = wall_mask(image)

    glazing = glazing_mask(image, walls)

    for y in (41, 50):
        assert glazing[y, 92:109].mean() / 255 >= 0.9
        assert line_mask(image)[y, 92:109].mean() / 255 < 0.6  # missed without it
