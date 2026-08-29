from __future__ import annotations

import re
import struct


_INF_FIELDS = re.compile(r'"[^"]*"|\S+')


def _hex_field(value: str) -> int:
    return int(re.sub(r"^(?:&|0x)", "", value, flags=re.IGNORECASE), 16)


def parse_address(value: object) -> int:
    """Parse the hex notation used by Acorn catalogues and sidecars.

    Acorn writes addresses in hexadecimal, so a bare value such as ``1900``
    means &1900 here, exactly as it does when typed into the catalogue metadata
    editor. ``&`` and ``0x`` prefixes are both accepted because Acorn
    documentation and host tooling each use one of them.
    """
    text = str(value or "").strip()
    if not re.fullmatch(r"(?:&|0x)?[0-9a-f]{1,8}", text, flags=re.IGNORECASE):
        raise ValueError("an Acorn address contains one to eight hexadecimal digits")
    return _hex_field(text)


def engine_address(value: object) -> str:
    """Render an address unambiguously for the Oaknut command line.

    The engine reads a bare number as decimal, so handing it the user's text
    verbatim would silently turn &1900 into 1900 decimal. Everything the user
    types is parsed with :func:`parse_address` first and re-emitted with an
    explicit ``0x`` prefix, so one written address means one number on every
    path through the application.
    """
    return f"0x{parse_address(value):X}"


def canonical_dfs_address(value: object) -> int:
    """Expand DFS's packed/sign-extended address representation to 32 bits."""
    address = (
        parse_address(value) if isinstance(value, str) and value.strip() else int(value or 0)
    ) & 0xFFFFFFFF
    if address <= 0x3FFFF and address & 0x30000 == 0x30000:
        return address | 0xFFFC0000
    if address <= 0xFFFFFF and address & 0xFF0000 == 0xFF0000:
        return address | 0xFF000000
    return address


def parse_inf(data: bytes | str) -> dict | None:
    """Parse the portable Acorn ``.inf`` fields used beside a host file."""
    text = data.decode("latin-1", "replace") if isinstance(data, bytes) else str(data)
    fields = _INF_FIELDS.findall(text.strip())
    if len(fields) < 3:
        return None
    try:
        load = parse_address(fields[1])
        execute = parse_address(fields[2])
    except ValueError:
        return None
    length = None
    attribute_start = 3
    if len(fields) > 3:
        try:
            length = _hex_field(fields[3])
            attribute_start = 4
        except ValueError:
            pass
    if any(not 0 <= value <= 0xFFFFFFFF for value in (load, execute)):
        return None
    return {
        "name": fields[0].strip('"'),
        "load": canonical_dfs_address(load),
        "execute": canonical_dfs_address(execute),
        "length": length,
        "locked": any(field.casefold() in {"l", "locked"} for field in fields[attribute_start:]),
    }


def format_inf(path: str, metadata: dict) -> str:
    """Create one deterministic sidecar record from catalogue metadata."""
    catalogue_path = str(path or "FILE").strip() or "FILE"
    if "." not in catalogue_path:
        catalogue_path = f"$.{catalogue_path}"
    if any(character.isspace() for character in catalogue_path):
        catalogue_path = f'"{catalogue_path}"'
    load = int(metadata.get("load") or 0) & 0xFFFFFFFF
    execute = int(metadata.get("execute") or 0) & 0xFFFFFFFF
    length = int(metadata.get("length") or 0) & 0xFFFFFFFF
    locked = " Locked" if int(metadata.get("access") or 0) & 0x08 else ""
    return f"{catalogue_path} {load:08X} {execute:08X} {length:08X}{locked}\n"


def spark_metadata(extra: bytes) -> dict | None:
    """Decode the Acorn/SparkFS ZIP extra field without interpreting file bytes."""
    cursor = 0
    while cursor + 4 <= len(extra):
        field_id, length = struct.unpack_from("<HH", extra, cursor)
        cursor += 4
        field = extra[cursor:cursor + length]
        cursor += length
        if field_id == 0x4341 and len(field) >= 16 and field[:4] == b"ARC0":
            load, execute, access = struct.unpack_from("<III", field, 4)
            filetype = (load >> 8) & 0xFFF if load & 0xFFF00000 == 0xFFF00000 else None
            return {"load": load, "execute": execute, "access": access, "filetype": filetype}
    return None
