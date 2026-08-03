"""Streaming checksums for image files and generated archives."""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_path(path: Path) -> str:
    """Return a SHA-256 digest without loading a potentially large image into RAM."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
