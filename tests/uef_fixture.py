from __future__ import annotations

import struct

from app.uef import crc16


def minimal_uef(name: str = "THRUST", payload: bytes = b"10 PRINT \"THRUST\"\r") -> bytes:
    """Build one valid, complete cassette block for parser-facing tests."""
    header = (
        name.encode("latin-1") + b"\0"
        + struct.pack("<IIHH", 0x1900, 0x1900, 0, len(payload))
        + b"\x80\0\0\0\0"
    )
    tape_block = (
        b"*" + header + crc16(header).to_bytes(2, "big")
        + payload + crc16(payload).to_bytes(2, "big")
    )
    chunk = struct.pack("<HI", 0x0100, len(tape_block)) + tape_block
    return b"UEF File!\0\x00\x00" + chunk
