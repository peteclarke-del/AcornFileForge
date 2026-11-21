"""Reusable, UI-neutral Greaseweazle physical-floppy support."""

from .client import (
    DRIVE_CHOICES,
    IMAGE_FORMATS,
    GreaseweazleClient,
    GreaseweazleError,
    ProbeResult,
    ReadResult,
    WriteResult,
    image_format,
    stable_snapshot,
)
from .detect import Detection, classify, parse_decode, parse_sector_total
from .formats import (
    DISK_FORMATS,
    DiskFormat,
    DiskFormatError,
    disk_format,
    format_for_image,
)

__all__ = [
    "DISK_FORMATS",
    "DRIVE_CHOICES",
    "Detection",
    "DiskFormat",
    "DiskFormatError",
    "IMAGE_FORMATS",
    "GreaseweazleClient",
    "GreaseweazleError",
    "ProbeResult",
    "ReadResult",
    "WriteResult",
    "classify",
    "disk_format",
    "format_for_image",
    "image_format",
    "parse_decode",
    "parse_sector_total",
    "stable_snapshot",
]
