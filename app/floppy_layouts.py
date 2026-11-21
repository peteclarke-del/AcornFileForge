"""Blank images for the Acorn floppy layouts.

Formatting a disk in a drive and converting an image between filesystems
both start from an empty image of one physical layout, named by the
identifiers in ``acorn_greaseweazle.formats``. Using one table for both means
a converted image can always be written to a floppy unchanged.
"""

from __future__ import annotations

from pathlib import Path

from acorn_greaseweazle import DiskFormat, disk_format
from acorn_greaseweazle.formats import DiskFormatError

from .errors import DiskError
from .image_session import ImageSession

# The blank format ``create_blank`` makes for each physical layout.
BLANK_FORMATS = {
    "dfs-40": "ssd",
    "dfs-80": "ssd",
    "dfs-40-ds": "dsd",
    "dfs-80-ds": "dsd",
    "adfs-s": "adfs-s",
    "adfs-m": "adfs-m",
    "adfs-l": "adfs-l",
    "adfs-800": "adfs-e",
    "adfs-1600": "adfs-f",
}

# Usable sectors on one DFS side: everything after the two catalogue sectors.
DFS_CATALOGUE_SECTORS = 2
DFS_FILES_PER_SIDE = 31


def layout(identifier: object) -> DiskFormat:
    """Return a layout, or raise the user-facing error naming the choices."""
    try:
        return disk_format(identifier)
    except DiskFormatError as exc:
        raise DiskError(str(exc)) from exc


def is_dfs(item: DiskFormat) -> bool:
    return item.identifier.startswith("dfs-")


def create_blank_layout(disks, item: DiskFormat, title: str) -> ImageSession:
    """Create an empty image session of exactly one physical layout."""
    session = disks.create_blank(BLANK_FORMATS[item.identifier], title or "BLANK")
    if is_dfs(item):
        _resize_dfs(session.path, item)
    return session


def _resize_dfs(path: Path, item: DiskFormat) -> None:
    """Make a blank DFS image describe the disk it is for.

    Blank DFS images are created with 80-track sides. For a 40-track disk
    the image is cut to 40 cylinders and each side's catalogue sector count
    halved, or DFS would offer space the disk lacks. A ``.dsd`` image is
    track-interleaved, so side 1's catalogue starts one track (2560 bytes)
    in.
    """
    sectors = item.cylinders * item.sectors
    data = bytearray(path.read_bytes()[: item.size])
    for offset in range(0, item.heads * 2560, 2560):
        data[offset + 0x106] = (data[offset + 0x106] & 0xFC) | (sectors >> 8)
        data[offset + 0x107] = sectors & 0xFF
    path.write_bytes(bytes(data))
