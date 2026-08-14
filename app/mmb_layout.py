"""MMB container layout constants and offset calculations."""

from __future__ import annotations


HEADER_SIZE = 8192
SLOT_SIZE = 204800
ENTRY_SIZE = 16
MAX_SLOTS = 511
INDEX_START = 16


def entry_offset(slot: int) -> int:
    """Return the byte offset of one 16-byte MMB index record."""
    return INDEX_START + int(slot) * ENTRY_SIZE


def slot_offset(slot: int) -> int:
    """Return the byte offset of one DFS image in an MMB container."""
    return HEADER_SIZE + int(slot) * SLOT_SIZE


def available_slots(image_size: int) -> int:
    """Return the bounded number of complete slots present in an image."""
    if image_size < HEADER_SIZE:
        return 0
    return min(MAX_SLOTS, (image_size - HEADER_SIZE) // SLOT_SIZE)


def image_size(slot_count: int = MAX_SLOTS) -> int:
    """Return the canonical container size for a number of MMB slots."""
    return HEADER_SIZE + max(0, min(MAX_SLOTS, int(slot_count))) * SLOT_SIZE
