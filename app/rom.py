"""Inspection and safe editing helpers for Acorn ROM images.

ROM files are byte images, not filing systems.  The workbench therefore exposes
fixed-size banks as its objects and keeps layout choices in session metadata.
"""

from __future__ import annotations

import hashlib
import math
import zlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


DEFAULT_BANK_SIZE = 16 * 1024
MIN_BANK_SIZE = 256
MAX_ROM_SIZE = 64 * 1024 * 1024
ROM_LAYOUTS = {"linear", "byte-interleaved-2", "byte-interleaved-4"}
ROM_PLATFORMS = {"bbc-master-electron", "archimedes", "custom"}


class RomError(ValueError):
    pass


@dataclass(frozen=True)
class RomHeader:
    title: str
    version: str
    copyright: str
    version_byte: int
    type_byte: int
    language_entry: int | None
    service_entry: int | None
    title_capacity: int
    metadata_end: int

    @property
    def roles(self) -> str:
        roles = []
        if self.type_byte & 0x40:
            roles.append("language")
        if self.type_byte & 0x80:
            roles.append("service")
        return " + ".join(roles) or "data"

    @property
    def processor(self) -> str:
        return {
            0x0: "6502 BASIC",
            0x2: "6502 machine code",
            0x3: "68000 machine code",
            0x8: "Z80 machine code",
            0x9: "32016 machine code",
            0xB: "80186 machine code",
            0xC: "80286 machine code",
            0xD: "ARM machine code",
        }.get(self.type_byte & 0x0F, "unspecified processor")

    @property
    def features(self) -> list[str]:
        features = []
        if self.type_byte & 0x20:
            features.append("second-processor relocation information")
        if self.type_byte & 0x10:
            features.append("Electron function-key information")
        return features


@dataclass(frozen=True)
class RiscOsExtensionHeader:
    declared_size: int
    checksum: int
    calculated_checksum: int

    @property
    def checksum_valid(self) -> bool:
        return self.checksum == self.calculated_checksum


def _cstring(data: bytes, start: int, limit: int = 255) -> tuple[str, int] | None:
    if start < 0 or start >= len(data):
        return None
    end = data.find(b"\0", start, min(len(data), start + limit + 1))
    if end < 0:
        return None
    raw = data[start:end]
    if not raw or any(byte < 32 or byte > 126 for byte in raw):
        return None
    return raw.decode("latin-1"), end


def _jmp_target(data: bytes, offset: int) -> int | None:
    if len(data) < offset + 3 or data[offset] != 0x4C:
        return None
    target = int.from_bytes(data[offset + 1 : offset + 3], "little")
    return target if 0x8000 <= target <= 0xBFFF else None


def parse_sideways_header(data: bytes) -> RomHeader | None:
    """Return a BBC-family sideways-ROM header when one is structurally sound."""
    if len(data) < 16:
        return None
    language = _jmp_target(data, 0)
    service = _jmp_target(data, 3)
    if language is None and service is None:
        return None
    title = _cstring(data, 9, 96)
    if title is None:
        return None
    title_text, title_end = title
    version = _cstring(data, title_end + 1, 96)
    version_text = version[0] if version else ""
    marker = int(data[7])
    # The header offset identifies the NUL immediately before the copyright.
    if marker >= len(data) or data[marker] != 0:
        return None
    copyright_value = _cstring(data, marker + 1, 160)
    if copyright_value is None or not copyright_value[0].upper().startswith("(C)"):
        return None
    copyright_text = copyright_value[0]
    return RomHeader(
        title=title_text,
        version=version_text,
        copyright=copyright_text,
        version_byte=int(data[8]),
        type_byte=int(data[6]),
        language_entry=language,
        service_entry=service,
        title_capacity=title_end - 9,
        metadata_end=copyright_value[1] + 1,
    )


def parse_risc_os_extension_header(data: bytes) -> RiscOsExtensionHeader | None:
    """Return the standard 16-byte RISC OS extension-ROM trailer, if present."""
    if len(data) < 16 or data[-8:] != b"ExtnROM0" or len(data) % 4:
        return None
    declared_size = int.from_bytes(data[-16:-12], "little")
    if declared_size != len(data):
        return None
    checksum = int.from_bytes(data[-12:-8], "little")
    calculated = sum(
        int.from_bytes(data[offset : offset + 4], "little")
        for offset in range(0, len(data) - 12, 4)
    ) & 0xFFFFFFFF
    return RiscOsExtensionHeader(declared_size, checksum, calculated)


def is_erased(data: bytes, erase_byte: int = 0xFF) -> bool:
    return not data or not data.strip(bytes((erase_byte & 0xFF,)))


def validate_bank_size(value: int) -> int:
    size = int(value)
    if size < MIN_BANK_SIZE or size > MAX_ROM_SIZE or size % 256:
        raise RomError("ROM bank size must be a multiple of 256 bytes between 256 bytes and 64 MiB.")
    return size


def validate_layout(value: str) -> str:
    layout = str(value or "linear")
    if layout not in ROM_LAYOUTS:
        raise RomError("Choose a linear, two-chip or four-chip ROM byte layout.")
    return layout


def validate_platform(value: str) -> str:
    platform = str(value or "bbc-master-electron")
    if platform not in ROM_PLATFORMS:
        raise RomError("Choose a BBC-family, Archimedes or custom ROM target.")
    return platform


def bank_count(size: int, bank_size: int) -> int:
    return (max(0, int(size)) + bank_size - 1) // bank_size


def printable_strings(data: bytes, minimum: int = 4, limit: int = 513) -> list[dict]:
    """Return bounded printable ASCII runs as useful evidence, never as guessed files."""
    found = []
    start = None
    for offset, value in enumerate(data + b"\0"):
        if 32 <= value <= 126:
            if start is None:
                start = offset
            continue
        if start is not None and offset - start >= minimum:
            text = data[start:offset].decode("latin-1")
            found.append({
                "offset": start,
                "address": 0x8000 + start,
                "length": offset - start,
                "text": text[:160] + ("…" if len(text) > 160 else ""),
            })
            if len(found) >= limit:
                break
        start = None
    return found


def byte_diagnostics(data: bytes, erase_byte: int, deep: bool = True) -> dict:
    fingerprints = {
        "sha256": hashlib.sha256(data).hexdigest(),
        "crc32": f"{zlib.crc32(data) & 0xFFFFFFFF:08X}",
    }
    if not deep:
        return fingerprints
    counts = Counter(data)
    length = len(data)
    entropy = -sum(
        (count / length) * math.log2(count / length)
        for count in counts.values()
    ) if length else 0.0
    erased = erase_byte & 0xFF
    used_start = next((offset for offset, value in enumerate(data) if value != erased), None)
    used_end = next(
        (offset for offset in range(length - 1, -1, -1) if data[offset] != erased),
        None,
    )
    return {
        **fingerprints,
        "entropy": round(entropy, 3),
        "uniqueByteValues": len(counts),
        "zeroBytes": counts.get(0, 0),
        "ffBytes": counts.get(0xFF, 0),
        "printableBytes": sum(counts.get(value, 0) for value in range(32, 127)),
        "erasedBytes": counts.get(erased, 0),
        "usedStart": used_start,
        "usedEnd": used_end,
    }


def risc_os_module_candidates(data: bytes, limit: int = 64) -> list[dict]:
    """Find structurally plausible RISC OS module headers without naming random data."""
    modules = []
    for base in range(0, max(0, len(data) - 44), 4):
        words = [int.from_bytes(data[base + offset : base + offset + 4], "little") for offset in range(0, 44, 4)]
        title_offset = words[4]
        if not title_offset or title_offset > len(data) - base - 2:
            continue
        title = _cstring(data, base + title_offset, 31)
        if title is None or not title[0].replace("_", "").isalnum():
            continue
        pointer_fields = words[:7]
        if any(value and (value >= len(data) - base or value % 4) for value in pointer_fields[:4]):
            continue
        if any(value and value >= len(data) - base for value in pointer_fields[4:]):
            continue
        if sum(bool(value) for value in pointer_fields) < 2:
            continue
        help_text = _cstring(data, base + words[5], 160) if words[5] else None
        modules.append({
            "offset": base,
            "title": title[0],
            "help": help_text[0] if help_text else "",
            "start": words[0] or None,
            "initialise": words[1] or None,
            "finalise": words[2] or None,
            "service": words[3] or None,
            "commands": words[6] or None,
            "commandKeywords": _risc_os_command_keywords(data, base, words[6]) if words[6] else [],
            "swiChunk": words[7] or None,
            "swiHandler": words[8] or None,
            "swiDecodeTable": words[9] or None,
            "swiDecodeCode": words[10] or None,
        })
        if len(modules) >= limit:
            break
    return modules


def _risc_os_command_keywords(data: bytes, module_base: int, table_offset: int, limit: int = 128) -> list[dict]:
    """Decode a standard RISC OS module help and command keyword table.

    Each entry is a NUL-terminated keyword, word alignment, then the documented
    code offset, information word, invalid-syntax offset and help offset.  Tight
    bounds and pointer checks are intentional: random ROM data must not become a
    confident command inventory.
    """
    cursor = module_base + table_offset
    module_length = len(data) - module_base
    if table_offset <= 0 or cursor >= len(data):
        return []
    commands = []
    for _ in range(limit):
        if cursor >= len(data) or data[cursor] == 0:
            break
        keyword = _cstring(data, cursor, 32)
        if keyword is None:
            return []
        name, end = keyword
        if not name or any(not (char.isalnum() or char == "_") for char in name):
            return []
        entry_offset = cursor - module_base
        cursor = (end + 1 + 3) & ~3
        if cursor + 16 > len(data):
            return []
        code, information, syntax, help_offset = (
            int.from_bytes(data[cursor + offset : cursor + offset + 4], "little")
            for offset in range(0, 16, 4)
        )
        offsets = (code, syntax, help_offset)
        if any(value and value >= module_length for value in offsets) or (code and code % 4):
            return []
        flags = (information >> 24) & 0xFF
        display = (
            f"*Configure {name} / *Status {name}"
            if flags & 0x40
            else f"*{name}"
        )
        syntax_value = _cstring(data, module_base + syntax, 160) if syntax else None
        help_value = _cstring(data, module_base + help_offset, 320) if help_offset else None
        syntax_text = syntax_value[0] if syntax_value else ""
        help_text = help_value[0] if help_value else ""
        commands.append({
            "name": name,
            "display": display,
            "offset": module_base + entry_offset,
            "address": None,
            "source": "RISC OS module command table",
            "confidence": "declared",
            "entryOffset": code or None,
            "minimumParameters": information & 0xFF,
            "maximumParameters": (information >> 16) & 0xFF,
            "filingSystemCommand": bool(flags & 0x80),
            "configureKeyword": bool(flags & 0x40),
            "helpOnly": code == 0,
            "syntax": syntax_text,
            "helpText": help_text or syntax_text,
            "helpSource": "Declared RISC OS command help" if help_text else ("Declared RISC OS syntax message" if syntax_text else ""),
            "syntaxOffset": module_base + syntax if syntax else None,
            "helpOffset": module_base + help_offset if help_offset else None,
        })
        cursor += 16
    return commands


def _indexed_6502_table_addresses(data: bytes) -> set[int]:
    """Return sideways-ROM addresses read through common absolute indexed opcodes."""
    indexed_table_opcodes = {0xB9, 0xBD, 0xD9, 0xDD}
    return {
        int.from_bytes(data[offset + 1 : offset + 3], "little")
        for offset in range(max(0, len(data) - 2))
        if data[offset] in indexed_table_opcodes
        and 0x8000 <= int.from_bytes(data[offset + 1 : offset + 3], "little") < 0xC000
    }


def _bbc_token_command_tables(data: bytes, limit: int = 256) -> list[dict]:
    """Find the compact high-bit-terminated keyword tables used by many MOS ROMs."""
    best: list[dict] = []
    best_end: int | None = None
    referenced_tables = _indexed_6502_table_addresses(data)
    for table_start in range(len(data)):
        mapped_start = 0x8000 + table_start
        if not any(0 <= mapped_start - referenced <= 256 for referenced in referenced_tables):
            continue
        cursor = table_start
        entries = []
        while cursor < len(data) and len(entries) < limit:
            # &80 is used as an in-table group divider by some ROMs. &FF is
            # deliberately not skipped: in RH Plus it separates help-only
            # keywords from the actual OSCLI command set and terminates it.
            if data[cursor] == 0x80:
                cursor += 1
            start = cursor
            while cursor < len(data) and (
                65 <= data[cursor] <= 90 or 48 <= data[cursor] <= 57 or data[cursor] == 95
            ) and cursor - start < 17:
                cursor += 1
            if cursor - start < 2 or cursor - start > 16 or cursor >= len(data) or data[cursor] < 0x80:
                break
            name = data[start:cursor].decode("ascii")
            if not name[0].isalpha():
                break
            entries.append({
                "name": name,
                "display": f"*{name}",
                "offset": start,
                "address": 0x8000 + start,
                "source": "BBC MOS tokenised command table",
                "confidence": "strong candidate",
                "token": data[cursor],
            })
            cursor += 1
        if len(entries) > len(best):
            best = entries
            best_end = cursor
    if len(best) < 4:
        return []
    # Several MOS ROMs put one CR-delimited syntax row after the terminating
    # &FF for each distinct dispatch token, in first-use order. Aliases share
    # the same token and therefore the same reconstructed signature.
    token_order = list(dict.fromkeys(entry["token"] for entry in best))
    if best_end is not None and best_end < len(data) and data[best_end] == 0xFF:
        cursor = best_end + 1
        rows: list[str] = []
        for _ in token_order:
            end = data.find(b"\r", cursor, min(len(data), cursor + 96))
            if end < 0:
                rows = []
                break
            raw = data[cursor:end]
            if any(byte < 32 or byte > 126 for byte in raw):
                rows = []
                break
            rows.append(raw.decode("latin-1").strip())
            cursor = end + 1
        if len(rows) == len(token_order) and any(rows):
            syntax_by_token = dict(zip(token_order, rows))
            for entry in best:
                syntax = syntax_by_token[entry["token"]]
                entry["syntax"] = syntax
                entry["helpText"] = f'{entry["display"]} {syntax}'.strip()
                entry["helpSource"] = "Reconstructed ROM command syntax table"
    return best


def _address_table_help_fragments(data: bytes, commands: list[dict]) -> None:
    """Attach syntax assembled from a nearby nibble-indexed fragment table.

    Some MOS help handlers store two syntax-fragment indexes in the metadata
    byte beside every command. This recognises the data layout rather than
    pretending to execute the service ROM.
    """
    metadata = [entry.get("metadataByte") for entry in commands]
    if not metadata or any(value is None for value in metadata):
        return
    used_indexes = {nibble for value in metadata for nibble in (value >> 4, value & 0x0F)}
    highest = max(used_indexes)
    if highest > 15:
        return
    command_start = min(entry["offset"] for entry in commands)
    command_end = max(entry["offset"] + len(entry["name"]) + 3 for entry in commands)
    referenced_tables = _indexed_6502_table_addresses(data)
    best: tuple[int, list[str], int] | None = None
    for pointer_start in range(max(0, command_start - 768), command_start):
        if 0x8000 + pointer_start not in referenced_tables:
            continue
        lows = data[pointer_start : pointer_start + highest + 1]
        if len(lows) != highest + 1:
            continue
        for page in range(0x80, 0xC0):
            fragments: list[str] = []
            valid = True
            for index, low in enumerate(lows):
                offset = ((page - 0x80) << 8) | low
                value = _cstring(data, offset, 32)
                if value is None:
                    # Index zero conventionally means no suffix and may point
                    # at a NUL immediately before executable code.
                    if index == 0 and offset < len(data) and data[offset] == 0:
                        fragments.append("")
                        continue
                    valid = False
                    break
                fragments.append(value[0].strip())
            if not valid or not all(fragments[index] or index == 0 for index in used_indexes):
                continue
            meaningful = sum(bool(value) and any(char in value for char in "<(") for value in fragments)
            if meaningful < 2:
                continue
            distance = abs(pointer_start - command_start) + abs(min((((page - 0x80) << 8) | low) for low in lows) - command_end)
            candidate = (distance, fragments, pointer_start)
            if best is None or candidate[0] < best[0]:
                best = candidate
    if best is None:
        return
    _, fragments, pointer_start = best
    for entry in commands:
        metadata_byte = entry["metadataByte"]
        syntax = " ".join(
            fragment for fragment in (fragments[metadata_byte >> 4], fragments[metadata_byte & 0x0F]) if fragment
        )
        entry["syntax"] = syntax
        entry["helpText"] = f'{entry["display"]} {syntax}'.strip()
        entry["helpSource"] = "Reconstructed shared *HELP syntax fragments"
        entry["helpTableOffset"] = pointer_start


def _bbc_address_command_tables(data: bytes, limit: int = 256) -> list[dict]:
    """Find MOS command tables whose names are followed by an RTS dispatch address.

    Several service ROMs push the two bytes after a matched keyword and execute
    RTS. The stored address is therefore the real handler address minus one.
    Validating every handler against the sideways-ROM window makes this much
    stronger evidence than merely finding command-looking text.
    """
    best: list[dict] = []
    referenced_tables = _indexed_6502_table_addresses(data)
    for stride in (2, 3):
        for table_start in range(len(data)):
            mapped_start = 0x8000 + table_start
            if mapped_start not in referenced_tables:
                continue
            cursor = table_start
            entries = []
            while cursor < len(data) and len(entries) < limit:
                start = cursor
                while cursor < len(data) and (
                    65 <= data[cursor] <= 90 or 48 <= data[cursor] <= 57 or data[cursor] == 95
                ) and cursor - start < 17:
                    cursor += 1
                if cursor - start < 2 or cursor - start > 16 or cursor + stride > len(data):
                    break
                name = data[start:cursor].decode("ascii")
                if not name[0].isalpha():
                    break
                stored_address = (data[cursor] << 8) | data[cursor + 1]
                handler_address = stored_address + 1
                if not 0x8000 <= handler_address < 0xC000:
                    break
                entry = {
                    "name": name,
                    "display": f"*{name}",
                    "offset": start,
                    "address": 0x8000 + start,
                    "source": "BBC MOS address-dispatch command table",
                "confidence": "strong candidate",
                "handlerAddress": handler_address,
                "handlerOffset": handler_address - 0x8000,
                }
                if stride == 3:
                    entry["metadataByte"] = data[cursor + 2]
                entries.append(entry)
                cursor += stride
            if len(entries) > len(best):
                best = entries
    if len(best) < 3:
        return []
    _address_table_help_fragments(data, best)
    return best


def _attach_shared_help_lines(data: bytes, commands: list[dict]) -> None:
    """Attach literal *HELP lines only to commands already proven by a table."""
    upper_data = data.upper()
    for entry in commands:
        if entry.get("helpText"):
            continue
        needle = f'*{entry["name"]}'.encode("ascii")
        cursor = 0
        while (start := upper_data.find(needle, cursor)) >= 0:
            after_name = start + len(needle)
            cursor = after_name
            if after_name < len(data) and data[after_name] not in b" \t\r\n\0":
                continue
            ends = [position for delimiter in (b"\r", b"\n", b"\0") if (position := data.find(delimiter, after_name, min(len(data), start + 121))) >= 0]
            if not ends:
                continue
            raw_line = data[start:min(ends)].strip()
            if any(byte < 32 or byte > 126 for byte in raw_line):
                continue
            entry["helpText"] = " ".join(raw_line.decode("latin-1").split())
            entry["helpSource"] = "Literal line from shared ROM *HELP output"
            break


def star_command_inventory(data: bytes, modules: list[dict] | None = None) -> list[dict]:
    """List declared commands and carefully labelled BBC-family candidates."""
    commands = []
    for module in modules or []:
        for command in module.get("commandKeywords", []):
            if not command.get("helpOnly"):
                commands.append({
                    **command,
                    "module": module["title"],
                    "handlerOffset": (
                        module["offset"] + command["entryOffset"]
                        if command.get("entryOffset") is not None
                        else None
                    ),
                })
    commands.extend(_bbc_address_command_tables(data))
    commands.extend(_bbc_token_command_tables(data))
    _attach_shared_help_lines(data, commands)
    confidence_rank = {"declared": 3, "strong candidate": 2}
    unique = {}
    for command in commands:
        key = command["name"].casefold()
        current = unique.get(key)
        if (
            current is None
            or confidence_rank[command["confidence"]] > confidence_rank[current["confidence"]]
            or (
                confidence_rank[command["confidence"]] == confidence_rank[current["confidence"]]
                and command.get("helpText")
                and not current.get("helpText")
            )
        ):
            unique[key] = command
    return sorted(unique.values(), key=lambda item: (item["name"].casefold(), item["offset"]))


def inspect_bank(
    data: bytes,
    number: int,
    erase_byte: int = 0xFF,
    extension_header: RiscOsExtensionHeader | None = None,
    include_contents: bool = False,
    include_risc_os_modules: bool = False,
) -> dict:
    header = parse_sideways_header(data)
    blank = is_erased(data, erase_byte)
    title = header.title if header else ("Empty bank" if blank else f"Bank {number:03d}")
    structures = []
    if header:
        structures.append({
            "kind": "header",
            "name": "BBC sideways-ROM header and identification strings",
            "offset": 0,
            "address": 0x8000,
            "length": header.metadata_end,
        })
        for role, entry in (("Language entry point", header.language_entry), ("Service entry point", header.service_entry)):
            if entry is not None:
                structures.append({
                    "kind": "entry",
                    "name": role,
                    "offset": entry - 0x8000,
                    "address": entry,
                    "length": None,
                })
        structures.append({
            "kind": "payload",
            "name": "Program code and embedded data",
            "offset": header.metadata_end,
            "address": 0x8000 + header.metadata_end,
            "length": max(0, len(data) - header.metadata_end),
        })
    elif not blank:
        structures.append({
            "kind": "payload",
            "name": "Raw code and data (no standard BBC header recognised)",
            "offset": 0,
            "address": 0x8000,
            "length": len(data),
        })
    if extension_header:
        structures.append({
            "kind": "extension-header",
            "name": "RISC OS ExtnROM0 size, checksum and identity trailer",
            "offset": max(0, len(data) - 16),
            "address": None,
            "length": 16,
        })
    strings = printable_strings(data) if include_contents and not blank else []
    modules = (
        risc_os_module_candidates(data)
        if include_contents and include_risc_os_modules and not blank
        else []
    )
    diagnostics = byte_diagnostics(data, erase_byte, deep=include_contents)
    programmed_bytes = len(data) - data.count(bytes((erase_byte & 0xFF,)))
    warnings = []
    if header:
        if bool(header.type_byte & 0x40) != (header.language_entry is not None):
            warnings.append("The language-ROM flag and language entry vector disagree.")
        if bool(header.type_byte & 0x80) != (header.service_entry is not None):
            warnings.append("The service-ROM flag and service entry vector disagree.")
    return {
        "slot": number,
        "bank": number,
        "name": title,
        "type": "rom-bank",
        "length": len(data),
        "attr": "EMPTY" if blank else "ROM",
        "empty": blank,
        "fileOffset": number * len(data),
        "programmedBytes": programmed_bytes,
        "programmedPercent": round(programmed_bytes * 100 / len(data), 1) if data else 0,
        "filetype": (
            f"RISC OS extension ROM ({'valid' if extension_header.checksum_valid else 'bad'} checksum)"
            if extension_header
            else f"{header.roles} · {header.processor}" if header
            else "erased" if blank
            else "raw data"
        ),
        "header": ({
            "title": header.title,
            "version": header.version,
            "copyright": header.copyright,
            "versionByte": header.version_byte,
            "typeByte": header.type_byte,
            "typeHex": f"{header.type_byte:02X}",
            "roles": header.roles,
            "processor": header.processor,
            "features": header.features,
            "languageEntry": header.language_entry,
            "serviceEntry": header.service_entry,
            "titleCapacity": header.title_capacity,
            "metadataEnd": header.metadata_end,
        } if header else None),
        "extensionHeader": ({
            "declaredSize": extension_header.declared_size,
            "checksum": extension_header.checksum,
            "calculatedChecksum": extension_header.calculated_checksum,
            "checksumValid": extension_header.checksum_valid,
        } if extension_header else None),
        "structures": structures,
        "strings": strings[:512],
        "stringsTruncated": len(strings) > 512,
        "diagnostics": diagnostics,
        "warnings": warnings,
        "modules": modules,
        "starCommands": star_command_inventory(data, modules) if include_contents and not blank else [],
    }


def inspect_image(path: Path, bank_size: int, erase_byte: int = 0xFF) -> list[dict]:
    size = path.stat().st_size
    rows = []
    with path.open("rb") as image:
        for number in range(bank_count(size, bank_size)):
            row = inspect_bank(image.read(bank_size), number, erase_byte)
            row["fileOffset"] = number * bank_size
            rows.append(row)
        if rows and size >= 16 and size % 4 == 0:
            image.seek(size - 16)
            trailer = image.read(16)
            if trailer[-8:] == b"ExtnROM0":
                declared_size = int.from_bytes(trailer[:4], "little")
                if declared_size == size:
                    image.seek(0)
                    remaining = size - 12
                    checksum = 0
                    while remaining:
                        chunk = image.read(min(1024 * 1024, remaining))
                        if not chunk:
                            break
                        checksum = (
                            checksum
                            + sum(
                                int.from_bytes(chunk[offset : offset + 4], "little")
                                for offset in range(0, len(chunk), 4)
                            )
                        ) & 0xFFFFFFFF
                        remaining -= len(chunk)
                    extension_header = RiscOsExtensionHeader(
                        declared_size,
                        int.from_bytes(trailer[4:8], "little"),
                        checksum,
                    )
                    final_data = read_bank(path, len(rows) - 1, bank_size)
                    rows[-1] = inspect_bank(
                        final_data,
                        len(rows) - 1,
                        erase_byte,
                        extension_header,
                    )
    matches = {}
    for row in rows:
        matches.setdefault(row["diagnostics"]["sha256"], []).append(row["bank"])
    for row in rows:
        row["matchingBanks"] = [
            bank for bank in matches[row["diagnostics"]["sha256"]]
            if bank != row["bank"]
        ]
    return rows


def read_bank(path: Path, number: int, bank_size: int) -> bytes:
    count = bank_count(path.stat().st_size, bank_size)
    if number < 0 or number >= count:
        raise RomError(f"ROM bank {number} does not exist.")
    with path.open("rb") as image:
        image.seek(number * bank_size)
        return image.read(bank_size)


def bank_number(path: str) -> int:
    value = str(path or "").strip().lower()
    if value.startswith("$."):
        value = value[2:]
    if value.startswith("bank:"):
        value = value[5:]
    elif value.startswith("bank-"):
        value = value[5:]
    try:
        number = int(value, 10)
    except ValueError as exc:
        raise RomError("Choose a ROM bank.") from exc
    if number < 0:
        raise RomError("Choose a ROM bank.")
    return number


def make_sideways_template(size: int, title: str, erase_byte: int = 0xFF) -> bytes:
    size = validate_bank_size(size)
    if size < 256:
        raise RomError("A sideways-ROM template needs at least 256 bytes.")
    clean_title = "".join(char for char in str(title or "NEW ROM") if 32 <= ord(char) <= 126)[:24] or "NEW ROM"
    version = "0.01"
    copyright_text = "(C) Custom"
    data = bytearray(bytes((erase_byte & 0xFF,)) * size)
    entry = 0x8080
    data[0:6] = bytes((0x4C, entry & 0xFF, entry >> 8, 0x4C, entry & 0xFF, entry >> 8))
    data[6] = 0xC0
    data[8] = 1
    cursor = 9
    for value in (clean_title, version):
        encoded = value.encode("latin-1")
        data[cursor : cursor + len(encoded)] = encoded
        cursor += len(encoded)
        data[cursor] = 0
        cursor += 1
    data[7] = cursor - 1
    encoded = copyright_text.encode("latin-1")
    data[cursor : cursor + len(encoded)] = encoded
    data[cursor + len(encoded)] = 0
    data[0x80] = 0x60  # RTS: deliberately inert until edited by the ROM author.
    return bytes(data)
