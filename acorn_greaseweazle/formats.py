"""The Acorn floppy layouts a Greaseweazle can read and write.

``gw`` picks a disk definition from an image's file suffix when ``--format``
is missing, and those defaults are wrong for Acorn media: ``.adf`` means an
Amiga disk to ``gw``, and ``.ssd``/``.dsd`` mean 40 tracks. Every sector-image
command therefore names its disk definition explicitly, chosen from this
table.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class DiskFormatError(ValueError):
    """An image or request that does not describe one Acorn floppy layout."""


@dataclass(frozen=True)
class DiskFormat:
    """One physical Acorn floppy layout and the ``gw`` definition for it."""

    identifier: str
    label: str
    gw_format: str
    suffix: str
    cylinders: int
    heads: int
    sectors: int
    sector_size: int

    @property
    def size(self) -> int:
        return self.cylinders * self.heads * self.sectors * self.sector_size

    @property
    def forty_track(self) -> bool:
        """True for media an 80-track drive must double-step to read."""
        return self.cylinders == 40

    def public(self) -> dict:
        return {
            "id": self.identifier,
            "label": self.label,
            "suffix": self.suffix,
            "size": self.size,
            "fortyTrack": self.forty_track,
        }


DISK_FORMATS: dict[str, DiskFormat] = {
    item.identifier: item
    for item in (
        DiskFormat("dfs-40", "DFS 40 track, single sided", "acorn.dfs.ss", ".ssd", 40, 1, 10, 256),
        DiskFormat("dfs-80", "DFS 80 track, single sided", "acorn.dfs.ss80", ".ssd", 80, 1, 10, 256),
        DiskFormat("dfs-40-ds", "DFS 40 track, double sided", "acorn.dfs.ds", ".dsd", 40, 2, 10, 256),
        DiskFormat("dfs-80-ds", "DFS 80 track, double sided", "acorn.dfs.ds80", ".dsd", 80, 2, 10, 256),
        DiskFormat("adfs-s", "ADFS S, 160 KiB", "acorn.adfs.160", ".ads", 40, 1, 16, 256),
        DiskFormat("adfs-m", "ADFS M, 320 KiB", "acorn.adfs.320", ".adm", 80, 1, 16, 256),
        DiskFormat("adfs-l", "ADFS L, 640 KiB", "acorn.adfs.640", ".adl", 80, 2, 16, 256),
        DiskFormat("adfs-800", "ADFS D or E, 800 KiB", "acorn.adfs.800", ".adf", 80, 2, 5, 1024),
        DiskFormat("adfs-1600", "ADFS F, 1.6 MiB high density", "acorn.adfs.1600", ".adf", 80, 2, 10, 1024),
    )
}

# The short names earlier capture requests used, by image suffix.
FORMAT_ALIASES = {
    "ssd": "dfs-80",
    "dsd": "dfs-80-ds",
    "ads": "adfs-s",
    "adm": "adfs-m",
    "adl": "adfs-l",
    "adf": "adfs-800",
}

# Flux containers carry their own encoding, so gw needs no disk definition.
FLUX_SUFFIXES = frozenset({".hfe", ".scp"})

_ADFS_BY_SIZE = {
    item.size: item
    for item in DISK_FORMATS.values()
    if item.identifier.startswith("adfs-")
}


def disk_format(identifier: object) -> DiskFormat:
    """Return one layout by name, or explain the accepted names."""
    name = str(identifier or "").strip().lower()
    found = DISK_FORMATS.get(FORMAT_ALIASES.get(name, name))
    if found is None:
        raise DiskFormatError(
            "Choose a floppy format: " + ", ".join(DISK_FORMATS) + "."
        )
    return found


def dfs_sector_count(track_zero: bytes) -> int | None:
    """Read the sector count from a DFS catalogue, when one is present."""
    if len(track_zero) < 0x108:
        return None
    count = ((track_zero[0x106] & 0x03) << 8) | track_zero[0x107]
    return count or None


def adfs_old_map_sectors(track_zero: bytes) -> int | None:
    """Read the disc size, in 256-byte sectors, from an old-map ADFS disc."""
    if len(track_zero) < 0x100:
        return None
    count = int.from_bytes(track_zero[0xFC:0xFF], "little")
    return count or None


def dfs_format(sector_count: int | None, double_sided: bool) -> DiskFormat | None:
    """Return the DFS layout a catalogue's sector count describes."""
    if sector_count is None or sector_count > 800:
        return None
    tracks = 40 if sector_count <= 400 else 80
    return DISK_FORMATS[f"dfs-{tracks}{'-ds' if double_sided else ''}"]


def format_for_image(path: str | Path) -> DiskFormat | None:
    """Choose the layout a sector image must be written with.

    Returns ``None`` for flux containers, which need no disk definition. DFS
    images are frequently truncated after their last used sector, so their
    track count comes from the catalogue rather than the file size.
    """
    image = Path(path)
    suffix = image.suffix.casefold()
    if suffix in FLUX_SUFFIXES:
        return None
    size = image.stat().st_size
    if suffix in {".ssd", ".dsd"}:
        with image.open("rb") as stream:
            header = stream.read(0x108)
        found = dfs_format(dfs_sector_count(header), suffix == ".dsd")
        if found is None:
            tracks_present = size // (2560 * (2 if suffix == ".dsd" else 1))
            found = dfs_format(400 if tracks_present <= 40 else 800, suffix == ".dsd")
        assert found is not None
        if size > found.size:
            raise DiskFormatError(
                f"{image.name} is larger than a {found.label} disk and cannot be written to a floppy."
            )
        return found
    by_suffix = {".ads": "adfs-s", ".adm": "adfs-m", ".adl": "adfs-l"}
    if suffix in by_suffix:
        found = DISK_FORMATS[by_suffix[suffix]]
    elif suffix == ".adf":
        found = _ADFS_BY_SIZE.get(size)
        if found is None:
            raise DiskFormatError(
                f"{image.name} is {size:,} bytes, which is not an ADFS floppy size."
            )
    else:
        raise DiskFormatError(f"{image.name} is not an Acorn floppy image.")
    if size > found.size:
        raise DiskFormatError(f"{image.name} is larger than a {found.label} disk.")
    return found

