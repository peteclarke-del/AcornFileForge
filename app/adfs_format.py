"""Independent FileCore E/F probes used for precise compatibility diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


_DISC_RECORD_OFFSET = 4
_DISC_RECORD_SIZE = 60
_MIN_LOG2_SECTOR_SIZE = 8
_MAX_LOG2_SECTOR_SIZE = 12


@dataclass(frozen=True)
class NewMapADFS:
    """Description of a structurally plausible FileCore new-map image."""

    format_name: str
    disc_name: str
    size: int
    sector_size: int
    sectors_per_track: int
    heads: int
    zones: int
    map_offset: int

    @property
    def description(self) -> str:
        return (
            f"ADFS {self.format_name} new-map image "
            f"({self.size // 1024:,} KiB, {self.sector_size}-byte sectors)"
        )


def probe_new_map_adfs(path: Path) -> NewMapADFS | None:
    """Return new-map geometry when *path* contains two matching map records.

    FileCore keeps two copies of a new map.  Requiring matching disc records,
    internally consistent geometry and an exact image size keeps this probe
    deliberately narrower than a filename or size guess. It remains useful
    when a non-Docker installation has not applied the bundled Oaknut patch.
    """

    size = path.stat().st_size
    if size < 1024:
        return None
    with path.open("rb") as image:
        first = _read_record(image, _DISC_RECORD_OFFSET)
        boot = _read_record(image, 0xDC0)
    seed = next(
        (record for record in (first, boot) if _plausible_record_start(record)),
        None,
    )
    if seed is None:
        return None
    log2_sector_size = seed[0]
    if not _MIN_LOG2_SECTOR_SIZE <= log2_sector_size <= _MAX_LOG2_SECTOR_SIZE:
        return None
    sector_size = 1 << log2_sector_size
    zones = seed[9]
    zone_spare = int.from_bytes(seed[10:12], "little")
    log2_bytes_per_map_bit = seed[5]
    if not zones or not zone_spare or log2_bytes_per_map_bit > 31:
        return None
    common_zone_bits = sector_size * 8 - zone_spare
    zone_zero_bits = common_zone_bits - _DISC_RECORD_SIZE * 8
    middle_zone = zones // 2
    preceding_bits = (
        0
        if middle_zone == 0
        else zone_zero_bits + (middle_zone - 1) * common_zone_bits
    )
    map_offset = preceding_bits << log2_bytes_per_map_bit
    with path.open("rb") as image:
        first = _read_record(image, map_offset + _DISC_RECORD_OFFSET)
        second = _read_record(
            image,
            map_offset + zones * sector_size + _DISC_RECORD_OFFSET,
        )
    if first is None or second != first:
        return None

    sectors_per_track, heads, density = first[1], first[2], first[3]
    fragment_id_bits, log2_bytes_per_map_bit = first[4], first[5]
    zones = first[9]
    recorded_size = int.from_bytes(first[16:20], "little")
    if not (
        sectors_per_track
        and 1 <= heads <= 16
        and density in {0, 1, 2, 3, 4, 8}
        and 8 <= fragment_id_bits <= 15
        and log2_bytes_per_map_bit <= 31
        and zones >= 1
        and recorded_size == size
        and size % sector_size == 0
    ):
        return None

    # Bytes 4..11 of an old-map disc record must all be zero.  A live
    # fragment-id field and zone count therefore identify the new-map form.
    if not any(first[4:12]):
        return None

    format_name = _format_name(
        size=size,
        sector_size=sector_size,
        sectors_per_track=sectors_per_track,
        heads=heads,
        density=density,
    )
    if format_name is None:
        return None
    disc_name = first[22:32].decode("latin-1", errors="replace").rstrip(" \0")
    return NewMapADFS(
        format_name=format_name,
        disc_name=disc_name,
        size=size,
        sector_size=sector_size,
        sectors_per_track=sectors_per_track,
        heads=heads,
        zones=zones,
        map_offset=map_offset,
    )


def _read_record(image, offset: int) -> bytes | None:
    image.seek(offset)
    record = image.read(_DISC_RECORD_SIZE)
    return record if len(record) == _DISC_RECORD_SIZE else None


def _plausible_record_start(record: bytes | None) -> bool:
    return record is not None and _MIN_LOG2_SECTOR_SIZE <= record[0] <= _MAX_LOG2_SECTOR_SIZE


def _format_name(
    *, size: int, sector_size: int, sectors_per_track: int, heads: int, density: int
) -> str | None:
    if (size, sector_size, sectors_per_track, heads, density) == (800 * 1024, 1024, 5, 2, 2):
        return "E"
    if (size, sector_size, sectors_per_track, heads, density) == (1600 * 1024, 1024, 10, 2, 4):
        return "F"
    return None
