"""Pure BeebSCSI and old-format ADFS geometry helpers."""

from __future__ import annotations

from pathlib import Path


SECTOR_SIZE = 256
SECTORS_PER_TRACK = 33
MAX_SECTORS = 0x1FFFFF
MAX_SIZE = MAX_SECTORS * SECTOR_SIZE
OLD_ROOT_OFFSET = 2 * SECTOR_SIZE
OLD_DIRECTORY_TAIL = 0x4CB
OLD_DIRECTORY_SIZE = 5 * SECTOR_SIZE
OLD_DIRECTORY_ENTRY_OFFSET = 5
OLD_DIRECTORY_ENTRY_SIZE = 26
OLD_DIRECTORY_MAX_ENTRIES = 47


def descriptor_size(descriptor_path: Path) -> int | None:
    """Return the device capacity declared by a BeebSCSI mode descriptor."""
    try:
        descriptor = descriptor_path.read_bytes()
    except OSError:
        return None
    if len(descriptor) < 16:
        return None
    cylinders = (descriptor[13] << 8) | descriptor[14]
    heads = descriptor[15]
    if not cylinders or not heads:
        return None
    return cylinders * heads * SECTORS_PER_TRACK * SECTOR_SIZE


def old_map_size(image_path: Path) -> int | None:
    """Return the filesystem extent stored in an old-format ADFS map."""
    try:
        with image_path.open("rb") as image:
            map_sector = image.read(SECTOR_SIZE)
    except OSError:
        return None
    if len(map_sector) != SECTOR_SIZE:
        return None
    sectors = int.from_bytes(map_sector[0xFC:0xFF], "little")
    if not sectors or sectors > MAX_SECTORS:
        return None
    return sectors * SECTOR_SIZE


def range_is_zero(
    path: Path,
    start: int,
    buffer_size: int = 8 * 1024 * 1024,
) -> bool:
    """Check a prospective compatibility tail without loading it into memory."""
    with path.open("rb") as image:
        image.seek(start)
        while chunk := image.read(buffer_size):
            if chunk.strip(b"\0"):
                return False
    return True


def old_map_checksum(block: bytes | bytearray) -> int:
    """Return the order-sensitive Acorn checksum for one old-map sector."""
    checksum = 0
    carry = 0
    for value in reversed(block[: SECTOR_SIZE - 1]):
        total = checksum + value + carry
        checksum = total & 0xFF
        carry = 1 if total > 0xFF else 0
    return checksum
