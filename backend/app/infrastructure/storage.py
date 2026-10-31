"""Files and atomic artifact publication on a local Docker volume."""

import errno
import json
import logging
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)

class LocalStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()
        for directory in ("uploads", "results"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)

    def path(self, relative_path: str) -> Path:
        path = (self.root / relative_path).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Artifact path escapes storage root")
        return path

    def write_json(self, relative_path: str, value: dict):
        destination = self.path(relative_path)
        temporary = destination.with_name(f".{uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(value), encoding="utf-8")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)

    def remove(self, relative_path: str):
        path = self.path(relative_path)
        path.unlink(missing_ok=True)
        if path.parent.parent == self.root / "uploads":
            try:
                path.parent.rmdir()
            except OSError as exc:
                if exc.errno not in (errno.ENOENT, errno.ENOTEMPTY):
                    raise

    def prune_orphans(self, referenced: set[str], older_than: float):
        """Age grace protects uploads being written before their registry insert."""
        candidates = list((self.root / "uploads").glob("*/*"))
        candidates.extend((self.root / "results").glob("*"))
        for path in candidates:
            relative = path.relative_to(self.root).as_posix()
            if relative in referenced or path.is_symlink() or not path.is_file():
                continue
            try:
                if path.stat().st_mtime <= older_than:
                    self.remove(relative)
            except FileNotFoundError:
                pass
            except OSError:
                logger.exception("Could not remove orphan artifact %s; retrying later", relative)
