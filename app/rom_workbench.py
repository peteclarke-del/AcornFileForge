"""Higher-level ROM maintenance tools built on the conservative ROM decoder.

The functions in this module never execute bytes from an uploaded image.  They
return bounded, serialisable reports and require source fingerprints before a
patch can alter an image.
"""

from __future__ import annotations

import base64
import json
import io
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path

from .checksum import sha256_bytes
from .rom import inspect_bank, parse_risc_os_extension_header, parse_sideways_header

try:
    from capstone import (
        Cs, CS_ARCH_ARM, CS_ARCH_M68K, CS_ARCH_MOS65XX, CS_MODE_ARM,
        CS_MODE_BIG_ENDIAN, CS_MODE_LITTLE_ENDIAN, CS_MODE_M68K_000,
        CS_MODE_MOS65XX_65C02, CS_MODE_MOS65XX_65816_LONG_MX,
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


def _symbol_labels(symbols: dict | None) -> dict[int, str]:
    """Accept decimal or conventional hexadecimal addresses from project files."""
    labels = {}
    for key, value in (symbols or {}).items():
        try:
            address = int(str(key).strip().replace("&", "0x", 1), 0)
        except ValueError:
            continue
        labels[address] = str(value)
    return labels


MOS_PURPOSES = {
    0xFFB9: "Read a byte from sideways ROM",
    0xFFBC: "Send a byte through the VDU system",
    0xFFBF: "Generate an event",
    0xFFC2: "Start parsing the command-line string",
    0xFFC5: "Read the next command-line item",
    0xFFC8: "Read from the currently selected input stream",
    0xFFCB: "Write to the currently selected output stream",
    0xFFCE: "Open or close a file",
    0xFFD1: "Transfer a block through the filing system",
    0xFFD4: "Write one byte to an open file",
    0xFFD7: "Read one byte from an open file",
    0xFFDA: "Read or change filing-system information for an open file",
    0xFFDD: "Perform a whole-file filing-system operation",
    0xFFE0: "Read a character from the current input stream",
    0xFFE3: "Write a character, expanding carriage return to a newline",
    0xFFE7: "Write a newline",
    0xFFEE: "Write a character or VDU control byte",
    0xFFF1: "Perform an OSWORD parameter-block operation",
    0xFFF4: "Perform an OSBYTE operation",
    0xFFF7: "Execute a MOS command string",
}

OSBYTE_REASONS = {
    0x00: "identify the operating-system version",
    0x7C: "clear the Escape condition",
    0x7D: "set the Escape condition",
    0x7E: "acknowledge the Escape condition",
    0x7F: "check for end of file",
    0x80: "read ADC or buffer status",
    0x81: "read a key with a time limit",
    0x82: "read the machine's high-order address",
    0x83: "read the bottom of user memory (OSHWM)",
    0x84: "read the top of user memory",
    0x86: "read the text cursor position",
    0x87: "read the character at the text cursor",
    0x8F: "issue a sideways-ROM service call",
}

OSWORD_REASONS = {
    0x00: "read an edited line",
    0x01: "read the system clock",
    0x02: "write the system clock",
    0x03: "read the interval timer",
    0x04: "write the interval timer",
    0x05: "read a byte from I/O memory",
    0x06: "write a byte to I/O memory",
    0x07: "perform a SOUND command",
    0x08: "define an ENVELOPE",
    0x09: "read a pixel colour",
    0x0A: "read a character definition",
}

OSFILE_ACTIONS = {
    0x00: "save a complete file", 0x01: "write catalogue information",
    0x02: "write the load address", 0x03: "write the execution address",
    0x04: "write file attributes", 0x05: "read catalogue information",
    0x06: "delete a file", 0x07: "create a file", 0xFF: "load a complete file",
}

OSFIND_ACTIONS = {
    0x00: "close a file", 0x40: "open a file for input",
    0x80: "open a file for output", 0xC0: "open a file for update",
}

BRANCH_MEANINGS = {
    "BPL": "Branch if the result is positive", "BMI": "Branch if the result is negative",
    "BVC": "Branch if overflow is clear", "BVS": "Branch if overflow is set",
    "BCC": "Branch if carry is clear", "BCS": "Branch if carry is set",
    "BNE": "Branch if the comparison was not equal", "BEQ": "Branch if the comparison was equal",
}

HARDWARE_REGIONS = (
    (0xFC00, 0xFCFF, "FRED expansion I/O"), (0xFD00, 0xFDFF, "JIM expansion I/O"),
    (0xFE00, 0xFE07, "6845 display controller"), (0xFE08, 0xFE0F, "serial ACIA"),
    (0xFE10, 0xFE17, "serial ULA"), (0xFE20, 0xFE2F, "video ULA"),
    (0xFE30, 0xFE3F, "ROM and memory paging latch"), (0xFE40, 0xFE5F, "system VIA"),
    (0xFE60, 0xFE7F, "user VIA"), (0xFE80, 0xFE9F, "filing-system hardware area"),
    (0xFEA0, 0xFEBF, "Econet hardware area"), (0xFEC0, 0xFEDF, "analogue converter"),
    (0xFEE0, 0xFEFF, "Tube interface"),
)

MOS_VECTORS = {
    0x0200: "USERV", 0x0202: "BRKV", 0x0204: "IRQ1V", 0x0206: "IRQ2V",
    0x0208: "CLIV", 0x020A: "BYTEV", 0x020C: "WORDV", 0x020E: "WRCHV",
    0x0210: "RDCHV", 0x0212: "FILEV", 0x0214: "ARGSV", 0x0216: "BGETV",
    0x0218: "BPUTV", 0x021A: "GBPBV", 0x021C: "FINDV", 0x021E: "FSCV",
    0x0220: "EVNTV", 0x0222: "UPTV", 0x0224: "NETV", 0x0226: "VDUV",
    0x0228: "KEYV", 0x022A: "INSV", 0x022C: "REMV", 0x022E: "CNPV",
    0x0230: "IND1V", 0x0232: "IND2V", 0x0234: "IND3V",
}

VDU_CONTROLS = {
    0: "no operation", 1: "send next byte to printer", 2: "enable printer output",
    3: "disable printer output", 4: "write text at the text cursor",
    5: "write text at the graphics cursor", 6: "enable VDU drivers", 7: "bell",
    8: "cursor left", 9: "cursor right", 10: "cursor down", 11: "cursor up",
    12: "clear the text area", 13: "carriage return", 14: "enable paged mode",
    15: "disable paged mode", 16: "clear the graphics area", 17: "set text colour",
    18: "set graphics colour and action", 19: "define a logical colour",
    20: "restore default colours", 21: "disable VDU output", 22: "select screen mode",
    23: "program a VDU character or system variable", 24: "define graphics window",
    25: "plot graphics", 26: "restore default windows", 27: "send escape",
    28: "define text window", 29: "set graphics origin", 30: "home text cursor",
    31: "position text cursor",
}


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


def _hex_value(operand: str) -> int | None:
    text = str(operand or "").strip()
    if text.startswith("#&"):
        text = text[2:]
    elif text.startswith("&"):
        text = text[1:].split(",", 1)[0]
    else:
        return None
    try:
        return int(text, 16)
    except ValueError:
        return None


def _character(value: int | None) -> str:
    if value is None:
        return ""
    names = {7: "bell", 8: "backspace", 9: "tab", 10: "line feed", 12: "clear screen", 13: "carriage return", 27: "escape", 127: "delete"}
    if value in names:
        return names[value]
    if 32 <= value < 127:
        return repr(chr(value))
    return ""


def _vdu_value(value: int | None) -> str:
    display = _character(value)
    if value in VDU_CONTROLS:
        return f"VDU {value}: {VDU_CONTROLS[value]}"
    return display


def _cstring(data: bytes, origin: int, address: int | None) -> str:
    if address is None or not origin <= address < origin + len(data):
        return ""
    offset = address - origin
    end = offset
    while end < len(data) and 32 <= data[end] < 127 and end - offset < 80:
        end += 1
    if end - offset < 3:
        return ""
    text = data[offset:end].decode("ascii", "replace")
    return text if any(character.isalpha() for character in text) else ""


def _hardware_region(address: int | None) -> str:
    if address is None:
        return ""
    return next((name for start, end, name in HARDWARE_REGIONS if start <= address <= end), "")


def _semantic_6502_labels(report: dict) -> None:
    """Assign stable labels from proved control flow and routine behaviour."""
    rows = report["rows"]
    by_address = {int(row["address"]): row for row in rows}
    index_by_address = {int(row["address"]): index for index, row in enumerate(rows)}
    call_targets = {
        int(row["target"])
        for row in rows
        if row.get("mnemonic") == "JSR" and isinstance(row.get("target"), int)
        and int(row["target"]) in by_address
    }

    def routine_rows(target: int) -> list[dict]:
        start = index_by_address.get(target)
        if start is None:
            return []
        block = []
        for row in rows[start:start + 96]:
            if block and int(row["address"]) in call_targets:
                break
            block.append(row)
            if str(row.get("mnemonic") or "").upper() in {"RTS", "RTI", "BRK", "JMP"}:
                break
        return block

    purpose_names = {
        0xFFF7: "execute_command", 0xFFDD: "file_operation",
        0xFFCE: "open_close_file", 0xFFD1: "transfer_file_block",
        0xFFD7: "read_file_byte", 0xFFD4: "write_file_byte",
        0xFFF1: "osword_operation", 0xFFF4: "osbyte_operation",
        0xFFE0: "read_character", 0xFFE7: "write_newline",
        0xFFC2: "start_command_parser", 0xFFC5: "read_command_item",
        0xFFC8: "read_input_stream", 0xFFCB: "write_output_stream",
        0xFFBF: "generate_event", 0xFFB9: "read_sideways_rom",
    }
    character_calls = {0xFFBC, 0xFFE3, 0xFFEE}
    for target in sorted(call_targets):
        target_row = by_address[target]
        existing = str(target_row.get("label") or "")
        if existing and not existing.startswith(("sub_", "loc_", "subroutine_")):
            continue
        block = routine_rows(target)
        calls = [
            int(row["target"]) for row in block
            if row.get("mnemonic") == "JSR" and isinstance(row.get("target"), int)
        ]
        endings = {str(row.get("mnemonic") or "").upper() for row in block}
        backwards_branch = any(
            isinstance(row.get("target"), int) and int(row["target"]) <= int(row["address"])
            for row in block if str(row.get("mnemonic") or "").upper() in BRANCH_MEANINGS
        )
        if "RTI" in endings:
            purpose = "interrupt_handler"
        elif "BRK" in endings:
            purpose = "raise_error"
        elif any(call in character_calls for call in calls):
            purpose = "write_text" if backwards_branch or sum(call in character_calls for call in calls) > 1 else "write_character"
        else:
            purpose = next((purpose_names[call] for call in calls if call in purpose_names), "")
        if not purpose:
            hardware = next((
                _hardware_region(int(row["target"]))
                for row in block if isinstance(row.get("target"), int) and _hardware_region(int(row["target"]))
            ), "")
            purpose = "access_hardware" if hardware else "subroutine"
        target_row["label"] = f"{purpose}_{target:04X}"

    branch_names = {
        "BEQ": "equal", "BNE": "not_equal", "BCC": "carry_clear",
        "BCS": "carry_set", "BMI": "negative", "BPL": "positive",
        "BVC": "overflow_clear", "BVS": "overflow_set",
    }
    flow_references: dict[int, list[dict]] = {}
    for source in rows:
        target = source.get("target")
        if source.get("mnemonic") in {*BRANCH_MEANINGS, "JMP"} and isinstance(target, int):
            flow_references.setdefault(target, []).append(source)
    for target, references in flow_references.items():
        target_row = by_address.get(target)
        if target_row is None or target in call_targets or target_row.get("label"):
            continue
        if any(target <= int(source["address"]) for source in references):
            purpose = "loop"
        else:
            mnemonics = {str(source.get("mnemonic") or "").upper() for source in references}
            if len(mnemonics) == 1:
                mnemonic = next(iter(mnemonics))
                purpose = branch_names.get(mnemonic, "dispatch" if mnemonic == "JMP" else "continue")
            else:
                purpose = "continue"
        target_row["label"] = f"{purpose}_{target:04X}"


def _mos_comment(target: int, registers: dict[str, int | None], data: bytes, origin: int) -> str:
    name = MOS_CALLS[target]
    base = MOS_PURPOSES[target]
    a, x, y = registers["A"], registers["X"], registers["Y"]
    xy = f"&{(y << 8 | x):04X}" if x is not None and y is not None else "unknown"
    if target in {0xFFBC, 0xFFE3, 0xFFEE} and a is not None:
        display = _vdu_value(a)
        action = display or f"byte &{a:02X}"
        verb = "write" if target != 0xFFBC else "send"
        suffix = ", expanding carriage return to a newline" if target == 0xFFE3 else ""
        return f"{name}: {verb} {action} through the VDU system{suffix}"
    if target == 0xFFF4 and a is not None:
        action = OSBYTE_REASONS.get(a, "use an undocumented or machine-specific reason code")
        return f"OSBYTE &{a:02X}: {action}; X={f'&{x:02X}' if x is not None else 'unknown'}; Y={f'&{y:02X}' if y is not None else 'unknown'}"
    if target == 0xFFF1 and a is not None:
        action = OSWORD_REASONS.get(a, "use a filing-system or machine-specific reason code")
        return f"OSWORD &{a:02X}: {action}; parameter block at XY={xy}"
    if target == 0xFFDD and a is not None:
        action = OSFILE_ACTIONS.get(a, "perform a filing-system-specific whole-file action")
        return f"OSFILE &{a:02X}: {action}; control block at XY={xy}"
    if target == 0xFFCE and a is not None:
        argument = (
            f"file handle Y=&{y:02X}" if a == 0 and y is not None
            else f"filename at XY={xy}"
        )
        action = OSFIND_ACTIONS.get(a, "perform a filing-system-specific open or close action")
        return f"OSFIND &{a:02X}: {action}; {argument}"
    if target == 0xFFF7 and x is not None and y is not None:
        pointer = y << 8 | x
        command = _cstring(data, origin, pointer)
        return f"OSCLI: execute {command!r} from XY=&{pointer:04X}" if command else f"OSCLI: execute the command string at XY=&{pointer:04X}"
    if target == 0xFFD4 and y is not None:
        return f"OSBPUT: write A to file handle Y=&{y:02X}"
    if target == 0xFFD7 and y is not None:
        return f"OSBGET: read the next byte from file handle Y=&{y:02X}"
    if target == 0xFFD1 and a is not None:
        return f"OSGBPB &{a:02X}: transfer a filing-system block; control block at XY={xy}"
    if target == 0xFFF4:
        return "OSBYTE: the reason code in A could not be proved on this code path"
    if target == 0xFFF1:
        return "OSWORD: the reason code in A could not be proved on this code path"
    return f"{name}: {base}"


def _annotate_6502(report: dict, data: bytes) -> dict:
    rows = report["rows"]
    by_address = {int(row["address"]): row for row in rows}
    _semantic_6502_labels(report)
    call_targets = {int(row["target"]) for row in rows if row.get("mnemonic") == "JSR" and isinstance(row.get("target"), int)}
    flow_targets = {int(row["target"]) for row in rows if str(row.get("mnemonic") or "") in set(BRANCH_MEANINGS) | {"JMP"} and isinstance(row.get("target"), int)}
    for target in call_targets | flow_targets:
        target_row = by_address.get(target)
        if target_row is not None and not target_row.get("label"):
            target_row["label"] = f"{'sub' if target in call_targets else 'loc'}_{target:04X}"
    for row in rows:
        target = row.get("target")
        if isinstance(target, int) and target in by_address and row.get("mnemonic") in {"JSR", "JMP", *BRANCH_MEANINGS}:
            row["operand"] = by_address[target].get("label") or row["operand"]

    registers: dict[str, int | None] = {"A": None, "X": None, "Y": None}
    previous_address = None
    for row in rows:
        address = int(row["address"])
        size = max(1, len(str(row.get("bytes") or "").split()))
        if previous_address is not None and any(source != previous_address for source in row.get("references", [])):
            registers = {"A": None, "X": None, "Y": None}
        mnemonic = str(row.get("mnemonic") or "").upper()
        operand = str(row.get("operand") or "")
        target = row.get("target")
        comment = ""
        value = _hex_value(operand)
        if mnemonic in {"LDA", "LDX", "LDY"} and operand.startswith("#"):
            register = mnemonic[-1]
            registers[register] = value
            display = _character(value)
            comment = f"{register} = &{value:02X}{f' ({display})' if display else ''}" if value is not None else ""
        elif mnemonic in {"LDA", "LDX", "LDY"}:
            registers[mnemonic[-1]] = None
        elif mnemonic == "TAX": registers["X"], comment = registers["A"], "Copy A to X"
        elif mnemonic == "TAY": registers["Y"], comment = registers["A"], "Copy A to Y"
        elif mnemonic == "TXA": registers["A"], comment = registers["X"], "Copy X to A"
        elif mnemonic == "TYA": registers["A"], comment = registers["Y"], "Copy Y to A"
        elif mnemonic in {"CMP", "CPX", "CPY"} and operand.startswith("#") and value is not None:
            register = {"CMP": "A", "CPX": "X", "CPY": "Y"}[mnemonic]
            display = _character(value)
            comment = f"Compare {register} with &{value:02X}{f' ({display})' if display else ''}"
        elif mnemonic in BRANCH_MEANINGS:
            comment = f"{BRANCH_MEANINGS[mnemonic]} to {operand}"
        elif mnemonic == "JSR" and isinstance(target, int):
            comment = _mos_comment(target, registers, data, int(report["origin"])) if target in MOS_CALLS else f"Call subroutine {operand}"
            registers = {"A": None, "X": None, "Y": None}
        elif mnemonic == "JMP":
            comment = (
                f"Dispatch through MOS {MOS_VECTORS[target]} vector"
                if isinstance(target, int) and target in MOS_VECTORS and operand.startswith("(")
                else f"Continue execution at {operand}"
            )
        elif mnemonic == "RTS": comment = "Return from subroutine"
        elif mnemonic == "RTI": comment = "Return from interrupt"
        elif mnemonic == "BRK":
            offset = int(row["offset"])
            if offset + 2 < len(data):
                message = _cstring(data, int(report["origin"]), int(report["origin"]) + offset + 2)
                comment = f"Raise error {data[offset + 1]}{f': {message!r}' if message else ''}"
            else: comment = "Raise a software error"
        elif mnemonic in {"PHA", "PHP"}: comment = f"Push {'A' if mnemonic == 'PHA' else 'processor flags'} onto the stack"
        elif mnemonic in {"PLA", "PLP"}:
            comment = f"Pull {'A' if mnemonic == 'PLA' else 'processor flags'} from the stack"
            if mnemonic == "PLA": registers["A"] = None
        elif mnemonic in {"STA", "STX", "STY", "LDA", "LDX", "LDY", "BIT"}:
            vector = MOS_VECTORS.get(target) if isinstance(target, int) else None
            hardware = _hardware_region(target)
            if vector:
                action = "Write" if mnemonic.startswith("ST") else "Read or test"
                comment = f"{action} MOS {vector} vector at &{int(target):04X}"
            elif hardware:
                action = "Write to" if mnemonic.startswith("ST") else "Read or test"
                comment = f"{action} {hardware} register &{int(target):04X}"
        elif mnemonic == "CLC": comment = "Clear carry before arithmetic or to signal success"
        elif mnemonic == "SEC": comment = "Set carry before subtraction or to signal a condition"
        elif mnemonic == "CLI": comment = "Enable maskable interrupts"
        elif mnemonic == "SEI": comment = "Disable maskable interrupts"
        elif mnemonic == "CLD": comment = "Use binary arithmetic"
        elif mnemonic == "SED": comment = "Use binary-coded decimal arithmetic"
        elif mnemonic == "CLV": comment = "Clear the overflow flag"
        elif mnemonic in {"INX", "DEX"}:
            registers["X"] = None
        elif mnemonic in {"INY", "DEY"}:
            registers["Y"] = None
        elif mnemonic in {"ADC", "SBC", "AND", "ORA", "EOR", "ASL", "LSR", "ROL", "ROR"}:
            registers["A"] = None
        row["comment"] = comment or str(row.get("comment") or "")
        previous_address = address + size
        if mnemonic in {"JMP", "RTS", "RTI", "BRK"} or mnemonic in BRANCH_MEANINGS:
            registers = {"A": None, "X": None, "Y": None}
    return report


def disassemble_6502(data: bytes, *, origin: int = 0x8000, start: int = 0,
                     length: int | None = None, symbols: dict | None = None) -> dict:
    if start < 0 or start >= len(data):
        raise RomWorkbenchError("The disassembly start is outside this ROM bank.")
    requested = len(data) - start if length is None else max(1, int(length))
    end = min(len(data), start + requested, start + MAX_DISASSEMBLY_BYTES)
    labels = _symbol_labels(symbols)
    rows, offset = [], start
    while offset < end:
        value = data[offset]
        opcode = OPCODES[value]
        address = origin + offset
        if value == 0x00 and offset + 3 < end:
            message_end = offset + 2
            while message_end < end and 32 <= data[message_end] < 127 and message_end - offset <= 82:
                message_end += 1
            if message_end > offset + 4 and message_end < end and data[message_end] == 0:
                message = data[offset + 2:message_end].decode("ascii")
                rows.extend([
                    {"offset": offset, "address": address, "bytes": "00", "mnemonic": "BRK", "operand": "", "target": None, "label": "", "comment": ""},
                    {"offset": offset + 1, "address": address + 1, "bytes": f"{data[offset + 1]:02X}", "mnemonic": "EQUB", "operand": f"&{data[offset + 1]:02X}", "target": None, "label": "", "comment": f"Error number {data[offset + 1]}"},
                    {"offset": offset + 2, "address": address + 2, "bytes": " ".join(f"{byte:02X}" for byte in data[offset + 2:message_end]), "mnemonic": "EQUS", "operand": json.dumps(message), "target": None, "label": "", "comment": "Error message"},
                    {"offset": message_end, "address": origin + message_end, "bytes": "00", "mnemonic": "EQUB", "operand": "&00", "target": None, "label": "", "comment": "End of error message"},
                ])
                offset = message_end + 1
                continue
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
    report = _with_control_flow({"architecture": "6502", "origin": origin, "start": start,
            "end": offset, "truncated": offset < start + requested, "rows": rows}, [])
    return _annotate_6502(report, data)


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
        if isinstance(target, int) and (mnemonic.startswith("B") or mnemonic in {"JSR", "JSL", "JMP", "JML", "BL", "BLX", "BSR", "BRA", "BRL"}):
            pending.append(target)
        if mnemonic not in {"JMP", "JML", "BRA", "BRL", "RTS", "RTL", "RTI", "BRK", "RTE"} and not mnemonic.startswith("B."):
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


def _annotate_generic_control_flow(report: dict) -> dict:
    rows = report["rows"]
    by_address = {int(row["address"]): row for row in rows}
    call_names = {"BL", "BLX", "BSR", "JSR", "JSL"}
    jump_names = {"B", "BRA", "BRL", "JMP", "JML"}
    for row in rows:
        target = row.get("target")
        mnemonic = str(row.get("mnemonic") or "").upper()
        target_row = by_address.get(target) if isinstance(target, int) else None
        if target_row is not None and not target_row.get("label"):
            if mnemonic in call_names:
                purpose = "subroutine"
            elif int(target) <= int(row["address"]):
                purpose = "loop"
            elif mnemonic in jump_names:
                purpose = "dispatch"
            else:
                purpose = "continue"
            target_row["label"] = f"{purpose}_{int(target):X}"
    for row in rows:
        mnemonic = str(row.get("mnemonic") or "").upper()
        operand = str(row.get("operand") or "")
        target = row.get("target")
        target_row = by_address.get(target) if isinstance(target, int) else None
        if target_row is not None:
            operand = row["operand"] = target_row.get("label") or operand
        if row.get("comment"):
            continue
        if mnemonic in call_names:
            row["comment"] = f"Call subroutine {operand}"
        elif mnemonic in jump_names:
            row["comment"] = f"Continue execution at {operand}"
        elif mnemonic.startswith("B") and isinstance(target, int):
            row["comment"] = f"Conditional branch to {operand}"
        elif mnemonic in {"RTS", "RTL", "RTI", "RTE"} or (mnemonic == "BX" and operand.upper() == "LR"):
            row["comment"] = "Return from subroutine"
    return report


def disassemble_capstone(data: bytes, *, architecture: str, origin: int = 0,
                         start: int = 0, length: int | None = None,
                         symbols: dict | None = None,
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
    elif architecture == "65c02":
        engine = Cs(CS_ARCH_MOS65XX, CS_MODE_MOS65XX_65C02)
    elif architecture == "65816":
        # Static bytes do not reveal the processor's runtime M/X flags. Start
        # with both accumulator and index registers in their 16-bit form; the
        # explicit profile is more honest than guessing from operand lengths.
        engine = Cs(CS_ARCH_MOS65XX, CS_MODE_MOS65XX_65816_LONG_MX)
    else:
        raise RomWorkbenchError("Choose 6502, 65C02, 65816, ARM or 68000 disassembly.")
    engine.skipdata = True
    rows = []
    labels = _symbol_labels(symbols)
    branch_names = {
        "b", "bl", "blx", "bx", "bra", "brl", "bsr", "jmp", "jml",
        "jsr", "jsl", "bcc", "bcs", "beq", "bmi", "bne", "bpl", "bvc", "bvs",
    }
    for instruction in engine.disasm(data[start:end], origin + start):
        mnemonic = instruction.mnemonic.upper()
        operand = instruction.op_str
        target = None
        if instruction.mnemonic.lower() in branch_names:
            token = operand.split(",", 1)[0].strip().lstrip("#")
            try:
                target = int(token[1:], 16) if token.startswith("$") else int(token, 0)
            except ValueError:
                target = None
        rows.append({"offset": instruction.address - origin, "address": instruction.address,
                     "bytes": instruction.bytes.hex(" ").upper(), "mnemonic": mnemonic,
                     "operand": operand, "target": target,
                     "label": labels.get(instruction.address, ""), "comment": ""})
    report = {"architecture": architecture, "origin": origin, "start": start,
              "end": end, "truncated": end < start + requested, "rows": rows}
    return _annotate_generic_control_flow(_with_control_flow(report, entry_points or []))


def disassemble(data: bytes, *, architecture: str, origin: int, start: int = 0,
                length: int | None = None, symbols: dict | None = None,
                entry_points: list[int] | None = None) -> dict:
    if architecture == "6502":
        report = disassemble_6502(data, origin=origin, start=start, length=length, symbols=symbols)
        return _annotate_6502(_with_control_flow(report, entry_points or []), data)
    return disassemble_capstone(data, architecture=architecture, origin=origin, start=start,
                                length=length, symbols=symbols, entry_points=entry_points)


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
    return {"leftSize": len(left), "rightSize": len(right), "leftSha256": sha256_bytes(left),
            "rightSha256": sha256_bytes(right), "changedBytes": changed_bytes,
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
    if document.get("format") != PATCH_FORMAT or sha256_bytes(source) != document.get("sourceSha256"):
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
    if len(result) != int(document.get("targetSize", -1)) or sha256_bytes(result) != document.get("targetSha256"):
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
            "sha256": sha256_bytes(data), "crc32": f"{zlib.crc32(data) & 0xFFFFFFFF:08X}",
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
    digest, crc = sha256_bytes(data), f"{zlib.crc32(data) & 0xFFFFFFFF:08X}"
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
            "addressSwaps": [list(pair) for pair in swaps], "sha256": sha256_bytes(prepared),
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
