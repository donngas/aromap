from pathlib import Path

import cv2
import numpy as np
import pytest

from app.floor_plans.recognition.preprocess import (
    InvalidImageError,
    dark_mask,
    estimate_wall_thickness,
    load_image,
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
