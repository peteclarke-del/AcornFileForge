"""Shared image-opening workflow for browser uploads and desktop paths."""

from __future__ import annotations

from .archive_utils import open_disk_image_upload
from .formats import (
    ADFS_EXTENSIONS,
    DFS_EXTENSIONS,
    HFE_EXTENSIONS,
    MMB_EXTENSIONS,
    ROM_EXTENSIONS,
    TAPE_EXTENSIONS,
)
from .menu.analysis import best_distribution_filename


IMAGE_EXTENSIONS = (
    DFS_EXTENSIONS
    | MMB_EXTENSIONS
    | TAPE_EXTENSIONS
    | ADFS_EXTENSIONS
    | HFE_EXTENSIONS
    | ROM_EXTENSIONS
)


def open_image_upload(
    service,
    image,
    descriptor=None,
    *,
    target_hardware: str = "auto",
    rom_options: dict | None = None,
    force_kind: str | None = None,
):
    """Open one upload-like stream through the canonical archive-aware path."""
    with open_disk_image_upload(image, IMAGE_EXTENSIONS) as (
        image_item,
        archived_descriptor,
    ):
        companion = descriptor or archived_descriptor
        descriptor_stream = None
        if companion is not None and companion.filename:
            descriptor_stream = (companion.filename, companion.stream)
        session = service.create_from_stream(
            image_item.filename,
            image_item.stream,
            descriptor_stream,
            target_hardware,
            rom_options,
            force_kind,
        )
        service.set_distribution_name(
            session,
            best_distribution_filename(image_item.metadata_names),
        )
        return session


__all__ = ["IMAGE_EXTENSIONS", "open_image_upload"]
