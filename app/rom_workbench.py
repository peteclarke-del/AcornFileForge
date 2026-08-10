"""Higher-level ROM maintenance tools built on the conservative ROM decoder.

The functions in this module never execute bytes from an uploaded image.  They
return bounded, serialisable reports and require source fingerprints before a
patch can alter an image.
"""

from __future__ import annotations

import base64
import hashlib
import json
import io
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path

from .rom import inspect_bank, parse_risc_os_extension_header, parse_sideways_header

try:
    from capstone import (
        Cs, CS_ARCH_ARM, CS_ARCH_M68K, CS_MODE_ARM, CS_MODE_BIG_ENDIAN,
        CS_MODE_LITTLE_ENDIAN, CS_MODE_M68K_000,
    )
except ImportError:  # Host-side lightweight tests may not install production dependencies.
    Cs = None


PATCH_FORMAT = "acorn-file-forge-rom-patch-1"
PROJECT_FORMAT = "acorn-file-forge-rom-project-1"
MAX_DISASSEMBLY_BYTES = 256 * 1024
MAX_PATCH_BYTES = 16 * 1024 * 1024


class RomWorkbenchError(ValueError):
    pass


@dataclass(frozen=True)
class Opcode:
    mnemonic: str
    mode: str
    size: int


# Official NMOS 6502 opcodes. Unknown and undocumented instructions remain
# byte directives so the analyser never invents control flow.
_MODE_SIZE = {"imp": 1, "acc": 1, "imm": 2, "zp": 2, "zpx": 2, "zpy": 2,
              "indx": 2, "indy": 2, "rel": 2, "abs": 3, "absx": 3, "absy": 3, "ind": 3}
_OPCODE_SPEC = """
00 BRK imp 01 ORA indx 05 ORA zp 06 ASL zp 08 PHP imp 09 ORA imm 0A ASL acc 0D ORA abs 0E ASL abs
10 BPL rel 11 ORA indy 15 ORA zpx 16 ASL zpx 18 CLC imp 19 ORA absy 1D ORA absx 1E ASL absx
20 JSR abs 21 AND indx 24 BIT zp 25 AND zp 26 ROL zp 28 PLP imp 29 AND imm 2A ROL acc 2C BIT abs 2D AND abs 2E ROL abs
30 BMI rel 31 AND indy 35 AND zpx 36 ROL zpx 38 SEC imp 39 AND absy 3D AND absx 3E ROL absx
40 RTI imp 41 EOR indx 45 EOR zp 46 LSR zp 48 PHA imp 49 EOR imm 4A LSR acc 4C JMP abs 4D EOR abs 4E LSR abs
50 BVC rel 51 EOR indy 55 EOR zpx 56 LSR zpx 58 CLI imp 59 EOR absy 5D EOR absx 5E LSR absx
60 RTS imp 61 ADC indx 65 ADC zp 66 ROR zp 68 PLA imp 69 ADC imm 6A ROR acc 6C JMP ind 6D ADC abs 6E ROR abs
70 BVS rel 71 ADC indy 75 ADC zpx 76 ROR zpx 78 SEI imp 79 ADC absy 7D ADC absx 7E ROR absx
81 STA indx 84 STY zp 85 STA zp 86 STX zp 88 DEY imp 8A TXA imp 8C STY abs 8D STA abs 8E STX abs
90 BCC rel 91 STA indy 94 STY zpx 95 STA zpx 96 STX zpy 98 TYA imp 99 STA absy 9A TXS imp 9D STA absx
A0 LDY imm A1 LDA indx A2 LDX imm A4 LDY zp A5 LDA zp A6 LDX zp A8 TAY imp A9 LDA imm AA TAX imp AC LDY abs AD LDA abs AE LDX abs
B0 BCS rel B1 LDA indy B4 LDY zpx B5 LDA zpx B6 LDX zpy B8 CLV imp B9 LDA absy BA TSX imp BC LDY absx BD LDA absx BE LDX absy
C0 CPY imm C1 CMP indx C4 CPY zp C5 CMP zp C6 DEC zp C8 INY imp C9 CMP imm CA DEX imp CC CPY abs CD CMP abs CE DEC abs
D0 BNE rel D1 CMP indy D5 CMP zpx D6 DEC zpx D8 CLD imp D9 CMP absy DD CMP absx DE DEC absx
E0 CPX imm E1 SBC indx E4 CPX zp E5 SBC zp E6 INC zp E8 INX imp E9 SBC imm EA NOP imp EC CPX abs ED SBC abs EE INC abs
F0 BEQ rel F1 SBC indy F5 SBC zpx F6 INC zpx F8 SED imp F9 SBC absy FD SBC absx FE INC absx
""".split()
_opcode_rows = [Opcode("???", "imp", 1) for _ in range(256)]
for _index in range(0, len(_OPCODE_SPEC), 3):
    _code, _mnemonic, _mode = _OPCODE_SPEC[_index:_index + 3]
    _opcode_rows[int(_code, 16)] = Opcode(_mnemonic, _mode, _MODE_SIZE[_mode])
OPCODES = tuple(_opcode_rows)

MOS_CALLS = {
    0xFFB9: "OSRDRM", 0xFFBC: "VDUCHR", 0xFFBF: "OSEVEN", 0xFFC2: "GSINIT",
    0xFFC5: "GSREAD", 0xFFC8: "NVRDCH", 0xFFCB: "NVWRCH", 0xFFCE: "OSFIND",
    0xFFD1: "OSGBPB", 0xFFD4: "OSBPUT", 0xFFD7: "OSBGET", 0xFFDA: "OSARGS",
    0xFFDD: "OSFILE", 0xFFE0: "OSRDCH", 0xFFE3: "OSASCI", 0xFFE7: "OSNEWL",
    0xFFEE: "OSWRCH", 0xFFF1: "OSWORD", 0xFFF4: "OSBYTE", 0xFFF7: "OSCLI",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _operand(data: bytes, offset: int, opcode: Opcode, address: int) -> tuple[str, int | None]:
    raw = data[offset + 1:offset + opcode.size]
    if len(raw) != opcode.size - 1:
        return "", None
    value = int.from_bytes(raw, "little") if raw else None
    mode = opcode.mode
    if mode == "imp": return "", None
    if mode == "acc": return "A", None
    if mode == "imm": return f"#&{value:02X}", None
    if mode == "zp": return f"&{value:02X}", None
    if mode == "zpx": return f"&{value:02X},X", None
    if mode == "zpy": return f"&{value:02X},Y", None
    if mode == "indx": return f"(&{value:02X},X)", None
    if mode == "indy": return f"(&{value:02X}),Y", None
    if mode == "abs": return f"&{value:04X}", value
    if mode == "absx": return f"&{value:04X},X", value
    if mode == "absy": return f"&{value:04X},Y", value
    if mode == "ind": return f"(&{value:04X})", value
    if mode == "rel":
        displacement = value if value < 0x80 else value - 0x100
        target = (address + 2 + displacement) & 0xFFFF
        return f"&{target:04X}", target
    return "", None


def disassemble_6502(data: bytes, *, origin: int = 0x8000, start: int = 0,
                     length: int | None = None, symbols: dict | None = None) -> dict:
    if start < 0 or start >= len(data):
        raise RomWorkbenchError("The disassembly start is outside this ROM bank.")
    requested = len(data) - start if length is None else max(1, int(length))
    end = min(len(data), start + requested, start + MAX_DISASSEMBLY_BYTES)
    labels = {int(key): str(value) for key, value in (symbols or {}).items() if str(key).isdigit()}
    rows, offset = [], start
    while offset < end:
        value = data[offset]
        opcode = OPCODES[value]
        address = origin + offset
        if opcode.mnemonic == "???" or offset + opcode.size > end:
            rows.append({"offset": offset, "address": address, "bytes": f"{value:02X}",
                         "mnemonic": "EQUB", "operand": f"&{value:02X}", "comment": ""})
            offset += 1
            continue
        operand, target = _operand(data, offset, opcode, address)
        comment = MOS_CALLS.get(target, "") if opcode.mnemonic in {"JSR", "JMP"} else ""
        rows.append({
            "offset": offset, "address": address,
            "bytes": " ".join(f"{byte:02X}" for byte in data[offset:offset + opcode.size]),
            "mnemonic": opcode.mnemonic, "operand": labels.get(target, operand),
            "target": target, "label": labels.get(address, ""), "comment": comment,
        })
        offset += opcode.size
    return _with_control_flow({"architecture": "6502", "origin": origin, "start": start,
            "end": offset, "truncated": offset < start + requested, "rows": rows}, [])


def _with_control_flow(report: dict, entry_points: list[int]) -> dict:
    rows = report["rows"]
    by_address = {int(row["address"]): row for row in rows}
    xrefs: dict[int, list[int]] = {}
    for row in rows:
        target = row.get("target")
        if isinstance(target, int):
            xrefs.setdefault(target, []).append(int(row["address"]))
    starts = [point for point in entry_points if point in by_address]
    if not starts and rows:
        starts = [int(rows[0]["address"])]
    reachable, pending = set(), list(starts)
    while pending:
        address = pending.pop()
        row = by_address.get(address)
        if row is None or address in reachable:
            continue
        reachable.add(address)
        mnemonic = str(row.get("mnemonic") or "").upper()
        target = row.get("target")
        size = max(1, len(str(row.get("bytes") or "").split()))
        fallthrough = address + size
        if isinstance(target, int) and (mnemonic.startswith("B") or mnemonic in {"JSR", "JMP", "BL", "BLX", "BSR", "BRA"}):
            pending.append(target)
        if mnemonic not in {"JMP", "BRA", "RTS", "RTI", "BRK", "RTE"} and not mnemonic.startswith("B."):
            pending.append(fallthrough)
    for row in rows:
        row["reachable"] = int(row["address"]) in reachable
        row["references"] = xrefs.get(int(row["address"]), [])
    report["entryPoints"] = starts
    report["crossReferences"] = [
        {"target": target, "sources": sources}
        for target, sources in sorted(xrefs.items())
    ]
    report["reachableInstructions"] = len(reachable)
    return report


def disassemble_capstone(data: bytes, *, architecture: str, origin: int = 0,
                         start: int = 0, length: int | None = None,
                         entry_points: list[int] | None = None) -> dict:
    if Cs is None:
        raise RomWorkbenchError("The production disassembly engine is not installed.")
    if start < 0 or start >= len(data):
        raise RomWorkbenchError("The disassembly start is outside this ROM bank.")
    requested = len(data) - start if length is None else max(1, int(length))
    end = min(len(data), start + requested, start + MAX_DISASSEMBLY_BYTES)
    if architecture == "arm":
        engine = Cs(CS_ARCH_ARM, CS_MODE_ARM | CS_MODE_LITTLE_ENDIAN)
    elif architecture == "m68k":
        engine = Cs(CS_ARCH_M68K, CS_MODE_M68K_000 | CS_MODE_BIG_ENDIAN)
    else:
        raise RomWorkbenchError("Choose 6502, ARM or 68000 disassembly.")
    engine.skipdata = True
    rows = []
    branch_names = {"b", "bl", "blx", "bx", "bra", "bsr", "jmp", "jsr"}
    for instruction in engine.disasm(data[start:end], origin + start):
        mnemonic = instruction.mnemonic.upper()
        operand = instruction.op_str
        target = None
        if instruction.mnemonic.lower() in branch_names:
            token = operand.split(",", 1)[0].strip().lstrip("#")
            try:
                target = int(token, 0)
            except ValueError:
                target = None
        rows.append({"offset": instruction.address - origin, "address": instruction.address,
                     "bytes": instruction.bytes.hex(" ").upper(), "mnemonic": mnemonic,
                     "operand": operand, "target": target, "label": "", "comment": ""})
    report = {"architecture": architecture, "origin": origin, "start": start,
              "end": end, "truncated": end < start + requested, "rows": rows}
    return _with_control_flow(report, entry_points or [])


def disassemble(data: bytes, *, architecture: str, origin: int, start: int = 0,
                length: int | None = None, symbols: dict | None = None,
                entry_points: list[int] | None = None) -> dict:
    if architecture == "6502":
        report = disassemble_6502(data, origin=origin, start=start, length=length, symbols=symbols)
        return _with_control_flow(report, entry_points or [])
    return disassemble_capstone(data, architecture=architecture, origin=origin, start=start,
                                length=length, entry_points=entry_points)


def bank_map(data: bytes, bank_size: int, erase_byte: int = 0xFF) -> dict:
    rows, hashes = [], {}
    for bank, offset in enumerate(range(0, len(data), bank_size)):
        block = data[offset:offset + bank_size]
        decoded = inspect_bank(block, bank, erase_byte)
        digest = decoded["diagnostics"]["sha256"]
        hashes.setdefault(digest, []).append(bank)
        rows.append({"bank": bank, "fileOffset": offset, "cpuWindow": "&8000-&BFFF",
                     "length": len(block), "title": decoded["name"], "type": decoded["filetype"],
                     "empty": decoded["empty"], "sha256": digest})
    for row in rows:
        row["duplicates"] = [number for number in hashes[row["sha256"]] if number != row["bank"]]
    return {"bankSize": bank_size, "bankCount": len(rows), "banks": rows}


def compare_roms(left: bytes, right: bytes, *, max_ranges: int = 10000) -> dict:
    maximum = max(len(left), len(right))
    ranges, start, changed_bytes, captured_hex, omitted_bytes = [], None, 0, 0, False
    for offset in range(maximum + 1):
        different = offset < maximum and (
            offset >= len(left) or offset >= len(right) or left[offset] != right[offset]
        )
        if different and start is None:
            start = offset
        elif not different and start is not None:
            length = offset - start
            changed_bytes += length
            if len(ranges) < max_ranges:
                left_bytes, right_bytes = left[start:offset], right[start:offset]
                keep_bytes = captured_hex + 2 * (len(left_bytes) + len(right_bytes)) <= MAX_PATCH_BYTES * 4
                left_hex = left_bytes.hex().upper() if keep_bytes else ""
                right_hex = right_bytes.hex().upper() if keep_bytes else ""
                ranges.append({"start": start, "end": offset, "length": length,
                               "left": left_hex, "right": right_hex})
                captured_hex += len(left_hex) + len(right_hex)
                omitted_bytes = omitted_bytes or not keep_bytes
            start = None
    return {"leftSize": len(left), "rightSize": len(right), "leftSha256": sha256(left),
            "rightSha256": sha256(right), "changedBytes": changed_bytes,
            "ranges": ranges, "rangesTruncated": changed_bytes > sum(row["length"] for row in ranges),
            "bytesOmitted": omitted_bytes}


def make_patch(left: bytes, right: bytes) -> dict:
    report = compare_roms(left, right)
    if report["changedBytes"] > MAX_PATCH_BYTES or report["rangesTruncated"] or report["bytesOmitted"]:
        raise RomWorkbenchError("That patch exceeds the 16 MiB safety limit.")
    return {"format": PATCH_FORMAT, "sourceSha256": report["leftSha256"],
            "targetSha256": report["rightSha256"], "sourceSize": len(left), "targetSize": len(right),
            "ranges": [{"offset": row["start"], "remove": len(bytes.fromhex(row["left"])),
                        "data": base64.b64encode(bytes.fromhex(row["right"])).decode("ascii")}
                       for row in report["ranges"]]}


def make_selective_patch(left: bytes, right: bytes, indexes: list[int]) -> dict:
    report = compare_roms(left, right)
    selected = sorted(set(int(index) for index in indexes))
    if not selected or any(index < 0 or index >= len(report["ranges"]) for index in selected):
        raise RomWorkbenchError("Choose one or more valid changed ranges.")
    result = bytearray(left)
    adjustment = 0
    for index in selected:
        row = report["ranges"][index]
        if not row.get("right"):
            raise RomWorkbenchError("That changed range is too large for a selective patch.")
        offset = row["start"] + adjustment
        remove = len(bytes.fromhex(row["left"]))
        replacement = bytes.fromhex(row["right"])
        result[offset:offset + remove] = replacement
        adjustment += len(replacement) - remove
    return make_patch(left, bytes(result))


def apply_patch(source: bytes, document: dict) -> bytes:
    if document.get("format") != PATCH_FORMAT or sha256(source) != document.get("sourceSha256"):
        raise RomWorkbenchError("This patch does not match the selected source ROM checksum.")
    result = bytearray(source)
    adjustment = 0
    for row in document.get("ranges", []):
        offset, remove = int(row["offset"]) + adjustment, int(row["remove"])
        replacement = base64.b64decode(row["data"], validate=True)
        if offset < 0 or remove < 0 or offset + remove > len(result):
            raise RomWorkbenchError("The patch contains an invalid byte range.")
        result[offset:offset + remove] = replacement
        adjustment += len(replacement) - remove
    if len(result) != int(document.get("targetSize", -1)) or sha256(result) != document.get("targetSha256"):
        raise RomWorkbenchError("The patched bytes did not produce the expected target ROM.")
    return bytes(result)


def audit_rom(data: bytes, bank_size: int, erase_byte: int = 0xFF) -> dict:
    findings, repairable = [], []
    mapping = bank_map(data, bank_size, erase_byte)
    if len(data) % bank_size:
        findings.append({"level": "warning", "code": "partial-bank", "message":
                         f"The final bank contains {len(data) % bank_size:,} bytes."})
    for row in mapping["banks"]:
        block = data[row["fileOffset"]:row["fileOffset"] + bank_size]
        decoded = inspect_bank(block, row["bank"], erase_byte)
        for warning in decoded["warnings"]:
            findings.append({"level": "error", "code": "header-role", "bank": row["bank"], "message": warning})
            if "header-role-flags" not in repairable:
                repairable.append("header-role-flags")
        if row["duplicates"] and row["bank"] < min(row["duplicates"]):
            findings.append({"level": "info", "code": "duplicate-bank", "bank": row["bank"],
                             "message": f"Bank {row['bank']} is identical to bank(s) {', '.join(map(str, row['duplicates']))}."})
    extension = parse_risc_os_extension_header(data)
    if extension and not extension.checksum_valid:
        findings.append({"level": "error", "code": "extension-checksum", "message":
                         "The RISC OS extension-ROM checksum is invalid."})
        repairable.append("extension-checksum")
    return {"healthy": not any(row["level"] == "error" for row in findings),
            "sha256": sha256(data), "crc32": f"{zlib.crc32(data) & 0xFFFFFFFF:08X}",
            "findings": findings, "repairable": repairable, "map": mapping}


def repair_extension_checksum(data: bytes) -> bytes:
    extension = parse_risc_os_extension_header(data)
    if extension is None:
        raise RomWorkbenchError("No standard RISC OS extension-ROM trailer was found.")
    result = bytearray(data)
    result[-12:-8] = extension.calculated_checksum.to_bytes(4, "little")
    return bytes(result)


def repair_header_role_flags(data: bytes, bank_size: int) -> bytes:
    result = bytearray(data)
    repaired = 0
    for offset in range(0, len(result), bank_size):
        block = bytes(result[offset:offset + bank_size])
        header = parse_sideways_header(block)
        if header is None:
            continue
        roles = (0x40 if header.language_entry is not None else 0) | (0x80 if header.service_entry is not None else 0)
        new_type = (header.type_byte & 0x3F) | roles
        if new_type != header.type_byte:
            result[offset + 6] = new_type
            repaired += 1
    if not repaired:
        raise RomWorkbenchError("No contradictory sideways-ROM role flags were found.")
    return bytes(result)


def normalise_project(document: dict | None) -> dict:
    source = document if isinstance(document, dict) else {}
    identity_source = source.get("identity") if isinstance(source.get("identity"), dict) else {}
    identity = {
        key: str(identity_source.get(key) or "")[:limit]
        for key, limit in {"title": 160, "version": 80, "publisher": 160,
                           "platform": 120, "notes": 2000}.items()
    }
    return {"format": PROJECT_FORMAT, "notes": str(source.get("notes") or "")[:20000],
            "hardware": str(source.get("hardware") or "")[:200],
            "symbols": {str(key): str(value)[:80] for key, value in dict(source.get("symbols") or {}).items()},
            "regions": [row for row in source.get("regions", []) if isinstance(row, dict)][:2048],
            "tests": [row for row in source.get("tests", []) if isinstance(row, dict)][:512],
            "identity": identity}


def project_json(document: dict) -> bytes:
    return json.dumps(normalise_project(document), indent=2, sort_keys=True).encode("utf-8") + b"\n"


def identify_rom(data: bytes, catalogue_path: Path | None = None) -> dict:
    """Identify exact and common transformed dumps without guessing a title."""
    digest, crc = sha256(data), f"{zlib.crc32(data) & 0xFFFFFFFF:08X}"
    records = []
    if catalogue_path and catalogue_path.is_file():
        try:
            document = json.loads(catalogue_path.read_text(encoding="utf-8"))
            records = document.get("roms", []) if isinstance(document, dict) else []
        except (OSError, ValueError, json.JSONDecodeError):
            records = []
    exact = next((row for row in records if str(row.get("sha256", "")).lower() == digest), None)
    transformations = []
    if len(data) % 2 == 0 and data[:len(data)//2] == data[len(data)//2:]:
        transformations.append("The image contains two identical mirrored halves.")
    if len(data) in {8192, 16384, 32768, 65536, 131072, 262144}:
        transformations.append(f"The size is a conventional {len(data) // 1024} KiB ROM or bank set.")
    return {"matched": exact is not None, "record": exact, "sha256": digest, "crc32": crc,
            "transformations": transformations}


def build_sideways_rom(title: str, commands: list[dict] | None = None,
                       size: int = 16 * 1024, erase_byte: int = 0xFF) -> bytes:
    """Build an inert, valid service-ROM development scaffold.

    The generated command table is deliberately descriptive. Handlers initially
    return immediately, so a scaffold cannot perform an unexpected operation.
    """
    if size not in {8192, 16384, 32768}:
        raise RomWorkbenchError("A BBC-family ROM scaffold must be 8K, 16K or 32K.")
    clean = "".join(char for char in str(title or "NEW ROM") if 32 <= ord(char) <= 126)[:24] or "NEW ROM"
    data = bytearray(bytes((erase_byte & 0xFF,)) * size)
    service = 0x8080
    data[0:6] = b"\x60\x00\x00\x4c" + service.to_bytes(2, "little")
    data[6] = 0x82
    data[8] = 0x01
    cursor = 9
    for raw in (clean.encode("ascii"), b"1.00"):
        data[cursor:cursor + len(raw)] = raw; cursor += len(raw); data[cursor] = 0; cursor += 1
    data[7] = cursor - 1
    copyright_text = b"(C) Acorn File Forge"
    data[cursor:cursor + len(copyright_text)] = copyright_text
    data[cursor + len(copyright_text)] = 0
    data[0x80] = 0x60
    table = bytearray(b"AFFCOMMANDS\0")
    for row in commands or []:
        name = "".join(char for char in str(row.get("name") or "").upper().lstrip("*") if char.isalnum())[:12]
        if name:
            syntax = str(row.get("syntax") or "")[:80]
            table.extend(name.encode("ascii") + b"\0" + syntax.encode("ascii", "replace") + b"\0")
    end = min(len(data), 0x100 + len(table))
    data[0x100:end] = table[:end - 0x100]
    return bytes(data)


def build_data_archive(title: str, files: list[tuple[str, bytes]], *,
                       size: int = 16 * 1024, erase_byte: int = 0xFF) -> bytes:
    """Build a documented AFFROMFS data ROM.

    This is a deterministic storage layout for a companion service ROM. It is
    not presented as a filing system understood by an unmodified MOS.
    """
    data = bytearray(build_sideways_rom(title, [{"name": "ROMLIST"}, {"name": "ROMLOAD"}], size, erase_byte))
    directory = bytearray(b"AFFROMFS1")
    payload = bytearray()
    for name, content in files:
        encoded = str(name).encode("ascii", "replace")[:31]
        directory.extend(bytes((len(encoded),)) + encoded + len(payload).to_bytes(4, "little") + len(content).to_bytes(4, "little"))
        payload.extend(content)
    directory.append(0)
    start = 0x200
    if start + len(directory) + len(payload) > size:
        raise RomWorkbenchError("Those files do not fit in the selected ROM size.")
    data[start:start + len(directory)] = directory
    data[start + len(directory):start + len(directory) + len(payload)] = payload
    return bytes(data)


def hardware_export(data: bytes, *, device_size: int, erase_byte: int = 0xFF,
                    mirror: bool = False, lanes: int = 1, byte_swap: bool = False,
                    word_swap: bool = False,
                    address_swaps: list[tuple[int, int]] | None = None) -> dict:
    if device_size < len(data) or device_size > 64 * 1024 * 1024 or device_size & (device_size - 1):
        raise RomWorkbenchError("Choose a power-of-two device size large enough for the ROM.")
    if lanes not in {1, 2, 4} or device_size % lanes:
        raise RomWorkbenchError("Choose one, two or four equal byte lanes.")
    if mirror and data:
        repeats = (device_size + len(data) - 1) // len(data)
        prepared = (data * repeats)[:device_size]
    else:
        prepared = data.ljust(device_size, bytes((erase_byte & 0xFF,)))
    if byte_swap:
        swapped = bytearray(prepared)
        for offset in range(0, len(swapped) - 1, 2):
            swapped[offset], swapped[offset + 1] = swapped[offset + 1], swapped[offset]
        prepared = bytes(swapped)
    if word_swap:
        swapped = bytearray(prepared)
        for offset in range(0, len(swapped) - 3, 4):
            swapped[offset:offset + 4] = swapped[offset + 2:offset + 4] + swapped[offset:offset + 2]
        prepared = bytes(swapped)
    swaps = []
    maximum_bit = device_size.bit_length() - 1
    for left, right in address_swaps or []:
        left, right = int(left), int(right)
        if left == right or min(left, right) < 0 or max(left, right) >= maximum_bit:
            raise RomWorkbenchError("Address-line swaps must name two different address bits used by the device.")
        swaps.append((left, right))
    if swaps:
        rewired = bytearray(len(prepared))
        for source, value in enumerate(prepared):
            target = source
            for left, right in swaps:
                left_value, right_value = (target >> left) & 1, (target >> right) & 1
                if left_value != right_value:
                    target ^= (1 << left) | (1 << right)
            rewired[target] = value
        prepared = bytes(rewired)
    components = [prepared[index::lanes] for index in range(lanes)]
    return {"deviceSize": device_size, "lanes": lanes, "eraseByte": erase_byte & 0xFF,
            "mirrored": mirror, "byteSwapped": byte_swap, "wordSwapped": word_swap,
            "addressSwaps": [list(pair) for pair in swaps], "sha256": sha256(prepared),
            "components": components}


def hardware_export_zip(result: dict, stem: str = "rom") -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for index, content in enumerate(result["components"], 1):
            name = f"{stem}.rom" if len(result["components"]) == 1 else f"{stem}-lane-{index}.rom"
            archive.writestr(name, content)
        report = {key: value for key, value in result.items() if key != "components"}
        archive.writestr("PROGRAMMING.md", "# ROM programming export\n\n```json\n" + json.dumps(report, indent=2) + "\n```\n")
    return output.getvalue()
