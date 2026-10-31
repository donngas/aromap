"""Prepare uploaded images without changing the recognizer's path contract."""

import time
import warnings
from io import BytesIO
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import Settings
from app.errors import api_error
from app.infrastructure.database import Database
from app.infrastructure.storage import LocalStorage


class FloorPlanService:
    def __init__(self, settings: Settings, database: Database, storage: LocalStorage):
        self.settings = settings
        self.database = database
        self.storage = storage

    def upload(self, contents: bytes):
        if len(contents) > self.settings.max_upload_bytes:
            raise api_error(413, "image_too_large", "Image exceeds the upload size limit.")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(contents)) as image:
                    if image.format not in {"PNG", "JPEG", "WEBP"}:
                        raise api_error(415, "unsupported_image", "Use PNG, JPEG, or WebP.")
                    if image.width * image.height > self.settings.max_image_pixels:
                        raise api_error(413, "image_too_large", "Image exceeds the pixel limit.")
                    if getattr(image, "is_animated", False):
                        raise api_error(415, "animated_image", "Animated images are unsupported.")
                    image.load()
                    with ImageOps.exif_transpose(image) as oriented:
                        mode = "RGBA" if "A" in oriented.getbands() or "transparency" in oriented.info else "RGB"
                        prepared = oriented.convert(mode)
                        # Export only pixels: do not preserve original EXIF/metadata.
                        prepared.info.clear()
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise api_error(413, "image_too_large", "Image exceeds safe decoding limits.") from exc
        except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
            raise api_error(422, "invalid_image", "The image could not be decoded or prepared.") from exc

        image_id = uuid4().hex
        relative_path = f"uploads/{image_id}/image.png"
        destination = self.storage.path(relative_path)
        now = time.time()
        expires_at = now + self.settings.retention_seconds
        try:
            with prepared:
                width, height = prepared.size
                destination.parent.mkdir(parents=True, exist_ok=True)
                prepared.save(destination, format="PNG")
            with self.database.connect() as db:
                db.execute(
                    "INSERT INTO uploads VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (image_id, relative_path, width, height, "image/png", now, expires_at),
                )
        except Exception:
            if destination.parent.exists():
                self.storage.remove(relative_path)
            raise
        return {"image_id": image_id, "width_px": width, "height_px": height,
                "expires_at": expires_at}

    def get_image(self, image_id: str):
        with self.database.connect() as db:
            row = db.execute(
                "SELECT * FROM uploads WHERE id = ? AND expires_at > ?", (image_id, time.time())
            ).fetchone()
        if row is None or not self.storage.path(row["relative_path"]).is_file():
            raise api_error(404, "image_not_found", "Image is unknown or expired.")
        return self.storage.path(row["relative_path"])
