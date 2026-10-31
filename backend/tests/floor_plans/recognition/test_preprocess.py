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


def test_wall_mask_removes_thin_details(shop_plan: np.ndarray) -> None:
    mask, _ = wall_mask(shop_plan)

    assert mask[90, 150] == 0  # shelf outline
    assert mask[260, 450] == 0  # display table outline
    assert mask[25, 300] == 0  # dimension line
    assert not mask[230:265, 100:220].any()  # "SALES" text
    assert mask[50, 300] == 255
    assert mask[200, 550] == 255


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
