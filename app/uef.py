from __future__ import annotations

import gzip
import io
import re
import struct
from dataclasses import dataclass

from .checksum import sha256_bytes


class UEFError(ValueError):
    pass


@dataclass(frozen=True)
class TapeFile:
    name: str
    load: int
    execute: int
    data: bytes
    blocks: int
    complete: bool
    inferred_name: bool = False
    original_name: str | None = None


@dataclass(frozen=True)
class UEFContents:
    version: str
    files: tuple[TapeFile, ...]
    warnings: tuple[str, ...]
    chunk_counts: dict[int, int]


@dataclass(frozen=True)
class _Block:
    name: str
    load: int
    execute: int
    number: int
    data: bytes
    last: bool
    start: int = 0
    data_start: int = 0
    end: int = 0


def crc16(data: bytes) -> int:
    crc = 0
    for value in data:
        crc ^= value << 8
        for _ in range(8):
            crc <<= 1
            if crc & 0x10000:
                crc = (crc ^ 0x1021) & 0xFFFF
    return crc


def _unpack(data: bytes) -> bytes:
    maximum = 64 * 1024 * 1024
    if data.startswith(b"\x1f\x8b"):
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
                unpacked = compressed.read(maximum + 1)
        except (gzip.BadGzipFile, EOFError) as exc:
            raise UEFError("The compressed UEF data is damaged.") from exc
        if len(unpacked) > maximum:
            raise UEFError("The expanded UEF exceeds the 64 MiB safety limit.")
        return unpacked
    if len(data) > maximum:
        raise UEFError("The UEF exceeds the 64 MiB safety limit.")
    return data


def _chunks(data: bytes) -> tuple[int, int, list[tuple[int, bytes]]]:
    raw = _unpack(data)
    if len(raw) < 12 or raw[:10] != b"UEF File!\0":
        raise UEFError("This is not a valid UEF file.")
    minor, major = raw[10], raw[11]
    offset = 12
    chunks: list[tuple[int, bytes]] = []
    while offset < len(raw):
        if offset + 6 > len(raw):
            raise UEFError("The final UEF chunk header is truncated.")
        chunk_id, length = struct.unpack_from("<HI", raw, offset)
        offset += 6
        end = offset + length
        if end > len(raw):
            raise UEFError(f"UEF chunk &{chunk_id:04X} is truncated.")
        chunks.append((chunk_id, raw[offset:end]))
        offset = end
    return major, minor, chunks


def _blocks(stream: bytes) -> list[_Block]:
    blocks: list[_Block] = []
    position = 0
    while position < len(stream):
        sync = stream.find(b"\x2a", position)
        if sync < 0:
            break
        name_end = stream.find(b"\0", sync + 1, min(sync + 12, len(stream)))
        if name_end < 0 or name_end == sync + 1:
            position = sync + 1
            continue
        fixed = name_end + 1
        if fixed + 21 > len(stream):
            break
        header_tail = stream[fixed : fixed + 17]
        load, execute, number, length = struct.unpack_from("<IIHH", header_tail)
        if length > 256:
            position = sync + 1
            continue
        flags = header_tail[12]
        header_crc_at = fixed + 17
        data_at = header_crc_at + 2
        end = data_at + length + 2
        if end > len(stream):
            position = sync + 1
            continue
        header = stream[sync + 1 : fixed + 17]
        expected_header_crc = int.from_bytes(stream[header_crc_at:data_at], "big")
        payload = stream[data_at : data_at + length]
        expected_data_crc = int.from_bytes(stream[data_at + length : end], "big")
        if crc16(header) != expected_header_crc or crc16(payload) != expected_data_crc:
            position = sync + 1
            continue
        name = stream[sync + 1 : name_end].decode("latin-1", "replace")
        blocks.append(_Block(
            name, load, execute, number, payload, bool(flags & 0x80),
            sync, data_at, end,
        ))
        position = end
    return blocks


def _group_blocks(blocks: list[_Block]) -> list[dict]:
    """Group cassette blocks without discarding their physical stream spans."""
    groups: list[dict] = []
    active: dict[tuple[str, int, int], dict] = {}
    for block in blocks:
        key = (block.name.casefold(), block.load, block.execute)
        group = active.get(key)
        if block.number == 0 and group and group.get("last") is not None:
            group = None
        if group is None:
            group = {
                "name": block.name,
                "load": block.load,
                "execute": block.execute,
                "parts": {},
                "blocks": {},
                "last": None,
            }
            groups.append(group)
            active[key] = group
        existing = group["parts"].get(block.number)
        if existing is None or existing == block.data:
            group["parts"][block.number] = block.data
            group["blocks"][block.number] = block
        if block.last:
            group["last"] = block.number
    return groups


def _unique_groups(groups: list[dict]) -> list[dict]:
    unique: list[dict] = []
    fingerprints: set[tuple[str, int, int, bytes]] = set()
    for group in groups:
        last = group["last"]
        expected_last = last if last is not None else max(group["parts"], default=-1)
        payload = b"".join(
            group["parts"][number]
            for number in range(expected_last + 1)
            if number in group["parts"]
        )
        fingerprint = (group["name"].casefold(), group["load"], group["execute"], payload)
        if fingerprint in fingerprints:
            continue
        fingerprints.add(fingerprint)
        group["payload"] = payload
        group["complete"] = last is not None and all(
            number in group["parts"] for number in range(last + 1)
        )
        unique.append(group)
    return unique


def _sha256(data: bytes) -> str:
    return sha256_bytes(data)


_CHUNK_NAMES = {
    0x0000: "Origin information",
    0x0005: "Target machine",
    0x0100: "Implicit start/stop-bit data",
    0x0102: "Explicit tape data",
    0x0104: "Defined tape data",
    0x0110: "High-tone carrier",
    0x0111: "High tone with dummy byte",
    0x0112: "Integer gap",
    0x0113: "Change baud rate",
    0x0114: "Security cycles",
    0x0116: "Floating-point gap",
}


def _raw_chunks(data: bytes) -> tuple[bytes, int, int, list[tuple[int, bytes]]]:
    raw = _unpack(data)
    major, minor, chunks = _chunks(raw)
    return raw, major, minor, chunks


def uef_editability(data: bytes, file_index: int) -> dict:
    """Prove whether one logical tape file can be replaced byte-for-byte safely.

    A writable project deliberately keeps the physical duration of every data
    block unchanged. This lets the writer preserve chunk order, timing chunks,
    carrier tones, security cycles and unknown chunks exactly.
    """
    _raw, _major, _minor, chunks = _raw_chunks(data)
    standard = b"".join(body for chunk_id, body in chunks if chunk_id == 0x0100)
    groups = _unique_groups(_group_blocks(_blocks(standard)))
    if file_index < 0 or file_index >= len(groups):
        raise UEFError("That UEF member no longer exists.")
    group = groups[file_index]
    reasons: list[str] = []
    if not group["complete"]:
        reasons.append("one or more cassette blocks are missing")
    ordered = [group["blocks"].get(number) for number in range((group["last"] or 0) + 1)]
    if any(block is None for block in ordered):
        reasons.append("the physical block sequence is ambiguous")
    return {
        "editable": not reasons,
        "sameLengthRequired": True,
        "length": len(group["payload"]),
        "blocks": len(ordered),
        "reasons": reasons,
        "proof": (
            "Every UEF chunk and every cassette timing/control record will remain in its original order. "
            "Only same-length bytes inside this file's proven Acorn cassette blocks and their data CRCs may change."
        ),
    }


def uef_project(data: bytes) -> dict:
    """Describe the complete physical UEF project without interpreting bytes away."""
    raw, major, minor, chunks = _raw_chunks(data)
    contents = parse_uef(data)
    chunk_rows = [{
        "index": index,
        "id": f"&{chunk_id:04X}",
        "kind": _CHUNK_NAMES.get(chunk_id, "Unknown or private chunk"),
        "length": len(body),
        "sha256": _sha256(body),
        "preserved": True,
    } for index, (chunk_id, body) in enumerate(chunks)]
    files = []
    for index, item in enumerate(contents.files):
        proof = uef_editability(data, index)
        files.append({
            "index": index,
            "name": item.name,
            "load": item.load,
            "execute": item.execute,
            "length": len(item.data),
            "blocks": item.blocks,
            "complete": item.complete,
            "sha256": _sha256(item.data),
            "editable": proof["editable"],
            "reasons": proof["reasons"],
        })
    return {
        "schema": "acorn-file-forge/uef-project/v1",
        "version": f"{major}.{minor:02d}",
        "compressed": data.startswith(b"\x1f\x8b"),
        "storedLength": len(data),
        "rawLength": len(raw),
        "sha256": _sha256(data),
        "rawSha256": _sha256(raw),
        "chunks": chunk_rows,
        "files": files,
        "warnings": list(contents.warnings),
    }


def replace_uef_file(data: bytes, file_index: int, replacement: bytes) -> tuple[bytes, dict]:
    """Replace a proven UEF file while preserving its physical tape structure."""
    raw, major, minor, chunks = _raw_chunks(data)
    standard = bytearray(b"".join(body for chunk_id, body in chunks if chunk_id == 0x0100))
    groups = _unique_groups(_group_blocks(_blocks(bytes(standard))))
    proof = uef_editability(data, file_index)
    if not proof["editable"]:
        raise UEFError("This UEF member is not reconstructable: " + "; ".join(proof["reasons"]) + ".")
    group = groups[file_index]
    if len(replacement) != len(group["payload"]):
        raise UEFError(
            f"Safe UEF editing requires exactly {len(group['payload']):,} bytes; "
            f"the replacement contains {len(replacement):,}. Changing tape duration is not yet permitted."
        )

    cursor = 0
    changed_ranges: list[dict] = []
    for number in range(group["last"] + 1):
        block = group["blocks"][number]
        size = len(block.data)
        payload = replacement[cursor:cursor + size]
        cursor += size
        if payload == block.data:
            continue
        standard[block.data_start:block.data_start + size] = payload
        standard[block.data_start + size:block.end] = crc16(payload).to_bytes(2, "big")
        changed_ranges.append({
            "block": number,
            "offset": block.data_start,
            "length": size,
            "beforeSha256": _sha256(block.data),
            "afterSha256": _sha256(payload),
        })

    rebuilt = bytearray(b"UEF File!\0" + bytes((minor, major)))
    standard_offset = 0
    chunk_rows: list[dict] = []
    for index, (chunk_id, body) in enumerate(chunks):
        next_body = body
        if chunk_id == 0x0100:
            next_body = bytes(standard[standard_offset:standard_offset + len(body)])
            standard_offset += len(body)
        rebuilt.extend(struct.pack("<HI", chunk_id, len(next_body)))
        rebuilt.extend(next_body)
        chunk_rows.append({
            "index": index,
            "id": f"&{chunk_id:04X}",
            "length": len(body),
            "changed": body != next_body,
            "beforeSha256": _sha256(body),
            "afterSha256": _sha256(next_body),
        })
    if standard_offset != len(standard):
        raise UEFError("The rebuilt UEF did not consume its complete standard-data stream.")
    raw_rebuilt = bytes(rebuilt)
    _, _, rebuilt_chunks = _chunks(raw_rebuilt)
    output = gzip.compress(raw_rebuilt, mtime=0) if data.startswith(b"\x1f\x8b") else raw_rebuilt
    report = {
        "schema": "acorn-file-forge/uef-structural-comparison/v1",
        "version": f"{major}.{minor:02d}",
        "compressed": data.startswith(b"\x1f\x8b"),
        "originalSha256": _sha256(data),
        "rebuiltSha256": _sha256(output),
        "rawOriginalSha256": _sha256(raw),
        "rawRebuiltSha256": _sha256(raw_rebuilt),
        "sameLength": len(raw) == len(raw_rebuilt),
        "chunkOrderPreserved": (
            [row[0] for row in chunks] == [row[0] for row in rebuilt_chunks]
        ),
        "unchangedChunksPreserved": all(
            row["changed"] or row["beforeSha256"] == row["afterSha256"] for row in chunk_rows
        ),
        "changedBlocks": changed_ranges,
        "chunks": chunk_rows,
        "proof": proof["proof"],
    }
    if (
        not report["sameLength"]
        or not report["chunkOrderPreserved"]
        or not report["unchangedChunksPreserved"]
    ):
        raise UEFError("The rebuilt UEF failed its structural preservation proof.")
    return output, report


def _usable_tape_name(name: str) -> bool:
    """Return true when a cassette catalogue name can identify a disk file."""
    return bool(name.strip()) and all(32 <= ord(character) < 127 for character in name)


def _inferred_tape_name(previous: str | None, number: int) -> str:
    if previous:
        stem = re.sub(r"[^A-Za-z0-9!_-]", "", previous).upper() or "FILE"
        suffix = str(number)
        return f"{stem[: max(1, 7 - len(suffix))]}{suffix}"
    return f"FILE{number}"


def _basic_program(data: bytes) -> tuple[list[tuple[bytes, bytes]], int] | None:
    """Split a tokenised BBC BASIC program without interpreting its tokens."""
    lines: list[tuple[bytes, bytes]] = []
    position = 0
    while position + 1 < len(data) and data[position] == 0x0D:
        if data[position + 1] == 0xFF:
            return lines, position + 2
        if position + 4 > len(data):
            return None
        length = data[position + 3]
        if length < 5 or position + length > len(data):
            return None
        lines.append((data[position + 1 : position + 3], data[position + 4 : position + length]))
        position += length
    return None


def is_tokenized_basic(data: bytes) -> bool:
    program = _basic_program(data)
    return program is not None and bool(program[0])


def basic_unopened_channel_io(data: bytes) -> bool:
    """Detect BASIC that uses a file channel without opening one itself.

    Tape software can inherit an input channel from the cassette loader.  A
    generated disk !BOOT cannot recreate that implicit channel, so presenting
    such a program as directly runnable leads to BASIC error 222 (Channel).
    """
    program = _basic_program(data)
    if program is None:
        return False
    bodies = b"\r".join(body for _line, body in program[0])
    open_tokens = {0x8E, 0xAD, 0xAE}  # OPENIN, OPENUP, OPENOUT
    if any(token in bodies for token in open_tokens):
        return False
    channel_tokens = {0x9A, 0xD5, 0xD9}  # BGET#, BPUT#, CLOSE#
    if any(token in bodies for token in channel_tokens):
        return True
    # GET$, EOF, INPUT and PRINT are channel operations only when followed by #.
    return any(
        re.search(bytes((token,)) + rb"\s*#", bodies)
        for token in (0xBE, 0xC5, 0xE9, 0xF2)
    )


def rewrite_basic_loader(
    data: bytes,
    next_name: str | None,
    name_map: dict[str, str],
) -> tuple[bytes, tuple[str, ...]]:
    """Translate cassette-dependent BASIC loads to their final DFS names.

    An empty ``*/`` or ``CHAIN ""`` means "the next file on tape". That
    sequencing has no disk equivalent, so conversion must make it explicit.
    Existing explicit references are also adjusted after DFS name shortening.
    """
    program = _basic_program(data)
    if program is None:
        return data, ()
    lines, program_end = program

    mapped = {source.casefold(): destination for source, destination in name_map.items() if source}
    notes: list[str] = []
    rebuilt = bytearray()

    def destination(source: bytes) -> bytes:
        decoded = source.decode("latin-1", "replace")
        return mapped.get(decoded.casefold(), decoded).encode("latin-1", "replace")

    for line_number, original_body in lines:
        body = original_body
        stripped = body.strip()
        if stripped == b"*/" and next_name:
            replacement = b"*/" + next_name.encode("latin-1")
            body = body.replace(stripped, replacement, 1)
            notes.append(f"Rewrote cassette-next */ as */{next_name}.")
        else:
            star_match = re.fullmatch(
                rb"(?P<prefix>\s*\*(?:/|RUN\s+|LOAD\s+|EXEC\s+))(?P<name>[^\s\r\"]+)(?P<tail>\s*)",
                body,
                re.IGNORECASE,
            )
            if star_match:
                old_name = star_match.group("name")
                new_name = destination(old_name)
                if new_name != old_name:
                    body = star_match.group("prefix") + new_name + star_match.group("tail")
                    notes.append(
                        f"Updated loader reference {old_name.decode('latin-1', 'replace')} to "
                        f"{new_name.decode('latin-1', 'replace')}."
                    )

        if next_name:
            empty_chain = re.compile(rb"\xD7(?P<space>\s*)\"\"")
            body, count = empty_chain.subn(
                lambda match: b"\xD7" + match.group("space") + b'"' + next_name.encode("latin-1") + b'"',
                body,
            )
            if count:
                notes.append(f'Rewrote cassette-next CHAIN "" as CHAIN "{next_name}".')

        def remap_chain(match: re.Match[bytes]) -> bytes:
            old_name = match.group("name")
            new_name = destination(old_name)
            if old_name != new_name:
                notes.append(
                    f"Updated CHAIN reference {old_name.decode('latin-1', 'replace')} to "
                    f"{new_name.decode('latin-1', 'replace')}."
                )
            return b"\xD7" + match.group("space") + b'"' + new_name + b'"'

        body = re.sub(rb"\xD7(?P<space>\s*)\"(?P<name>[^\"]+)\"", remap_chain, body)
        length = len(body) + 4
        if length > 255:
            return data, ("A BASIC loader line was too long to rewrite safely.",)
        rebuilt.extend(b"\x0D" + line_number + bytes((length,)) + body)

    if not notes:
        return data, ()
    rebuilt.extend(b"\x0D\xFF")
    rebuilt.extend(data[program_end:])
    return bytes(rebuilt), tuple(dict.fromkeys(notes))


def parse_uef(data: bytes) -> UEFContents:
    major, minor, chunks = _chunks(data)
    counts: dict[int, int] = {}
    standard_data = bytearray()
    unsupported_data_chunks: set[int] = set()
    for chunk_id, body in chunks:
        counts[chunk_id] = counts.get(chunk_id, 0) + 1
        if chunk_id == 0x0100:
            standard_data.extend(body)
        elif chunk_id in {0x0102, 0x0104, 0x0114}:
            unsupported_data_chunks.add(chunk_id)

    warnings: list[str] = []
    if unsupported_data_chunks:
        names = ", ".join(f"&{chunk_id:04X}" for chunk_id in sorted(unsupported_data_chunks))
        warnings.append(
            f"Contains cycle-level or non-standard tape data ({names}) that cannot be converted to ordinary DFS files."
        )
    blocks = _blocks(bytes(standard_data))
    if standard_data and not blocks:
        warnings.append("No valid Acorn cassette filing-system blocks were found in the standard tape data.")

    groups = _unique_groups(_group_blocks(blocks))

    files: list[TapeFile] = []
    previous_name: str | None = None
    inferred_number = 2
    for group in groups:
        complete = group["complete"]
        payload = group["payload"]
        original_name = group["name"]
        inferred = not _usable_tape_name(original_name)
        display_name = _inferred_tape_name(previous_name, inferred_number) if inferred else original_name
        if inferred:
            warnings.append(
                f"An unnamed cassette entry was labelled {display_name}; its original tape name was not usable."
            )
            inferred_number += 1
        else:
            previous_name = display_name
            inferred_number = 2
        if not complete:
            warnings.append(f"{display_name}: one or more tape blocks are missing; only the recovered data is shown.")
        files.append(
            TapeFile(
                display_name,
                group["load"],
                group["execute"],
                payload,
                len(group["parts"]),
                complete,
                inferred,
                original_name,
            )
        )

    return UEFContents(f"{major}.{minor:02d}", tuple(files), tuple(dict.fromkeys(warnings)), counts)
