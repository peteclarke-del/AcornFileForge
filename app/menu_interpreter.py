from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


BBC_COLOURS = (
    "#000000",
    "#ff0000",
    "#00ff00",
    "#ffff00",
    "#0000ff",
    "#ff00ff",
    "#00ffff",
    "#ffffff",
)

# BBC BASIC II tokens. The interpreter only executes the declarative display
# setup, but decoding the complete token range makes detection deterministic
# and lets unsupported programs be described honestly.
_TOKENS = {
    code: token
    for code, token in enumerate(
        (
            "AND", "DIV", "EOR", "MOD", "OR", "ERROR", "LINE", "OFF", "STEP", "SPC", "TAB(",
            "ELSE", "THEN", "<LINE>", "OPENIN", "PTR", "PAGE", "TIME", "LOMEM", "HIMEM", "ABS",
            "ACS", "ADVAL", "ASC", "ASN", "ATN", "BGET", "COS", "COUNT", "DEG", "ERL", "ERR",
            "EVAL", "EXP", "EXT", "FALSE", "FN", "GET", "INKEY", "INSTR(", "INT", "LEN", "LN",
            "LOG", "NOT", "OPENUP", "OPENOUT", "PI", "POINT(", "POS", "RAD", "RND", "SGN", "SIN",
            "SQR", "TAN", "TO", "TRUE", "USR", "VAL", "VPOS", "CHR$", "GET$", "INKEY$", "LEFT$(",
            "MID$(", "RIGHT$(", "STR$", "STRING$(", "EOF", "AUTO", "DELETE", "LOAD", "LIST", "NEW",
            "OLD", "RENUMBER", "SAVE", "EDIT", "PTR", "PAGE", "TIME", "LOMEM", "HIMEM", "SOUND",
            "BPUT", "CALL", "CHAIN", "CLEAR", "CLOSE", "CLG", "CLS", "DATA", "DEF", "DIM", "DRAW", "END",
            "ENDPROC", "ENVELOPE", "FOR", "GOSUB", "GOTO", "GCOL", "IF", "INPUT", "LET", "LOCAL", "MODE",
            "MOVE", "NEXT", "ON", "VDU", "PLOT", "PRINT", "PROC", "READ", "REM", "REPEAT", "REPORT",
            "RESTORE", "RETURN", "RUN", "STOP", "COLOUR", "TRACE", "UNTIL", "WIDTH", "*",
        ),
        0x80,
    )
}


@dataclass(frozen=True)
class BasicLine:
    number: int
    body: bytes
    text: str


def _decode_body(body: bytes) -> str:
    output: list[str] = []
    quoted = False
    remark = False
    index = 0
    while index < len(body):
        value = body[index]
        if value == 34:
            quoted = not quoted
            output.append('"')
        elif value == 0x8D and not quoted and not remark and index + 3 < len(body):
            output.append("<LINE>")
            index += 3
        elif value >= 0x80 and not quoted and not remark:
            token = _TOKENS.get(value, f"<{value:02X}>")
            output.append(token)
            if token == "REM":
                remark = True
        else:
            output.append(chr(value) if value in (9,) or 32 <= value < 127 else f"<{value:02X}>")
        index += 1
    return "".join(output)


def decode_basic(program: bytes) -> list[BasicLine] | None:
    lines: list[BasicLine] = []
    position = 0
    while position + 2 <= len(program) and program[position] == 0x0D:
        if program[position + 1] == 0xFF:
            return lines if lines else None
        if position + 4 > len(program):
            return None
        length = program[position + 3]
        if length < 4 or position + length > len(program):
            return None
        body = program[position + 4 : position + length]
        lines.append(
            BasicLine(
                int.from_bytes(program[position + 1 : position + 3], "big"),
                body,
                _decode_body(body),
            )
        )
        position += length
    return None


def _numbers(text: str, command: str) -> list[list[int]]:
    matches = []
    for body in re.findall(rf"\b{command}([0-9, ]+)", text, re.IGNORECASE):
        values = [int(value) for value in re.findall(r"\d+", body)]
        if values:
            matches.append(values)
    return matches


def _memory_string(
    address: int,
    support_files: dict[str, tuple[int, bytes]],
) -> str | None:
    for _name, (load, data) in support_files.items():
        offset = address - int(load)
        if 0 <= offset < len(data):
            end = offset
            while end < len(data) and data[end] not in (0, 13):
                end += 1
            if end == offset:
                return ""
            return data[offset:end].decode("latin-1", "replace")
    return None


def interpret_menu_program(
    program_name: str,
    program: bytes,
    support_files: dict[str, tuple[int, bytes]],
) -> dict:
    """Interpret the declarative display path of a BBC BASIC menu.

    This is intentionally not a pretend full-machine emulator. It decodes the
    installed program and follows the setup statements that determine the
    screen, palette, text window, headings, database fields and page size. A
    program outside the recognised Universal Menu family is returned as
    unsupported rather than rendered using invented styling.
    """
    digest = hashlib.sha256(program).hexdigest()
    lines = decode_basic(program)
    if not lines:
        return {
            "supported": False,
            "program": program_name,
            "programSha256": digest,
            "reason": "The installed menu program is not tokenised BBC BASIC.",
        }
    text = "\n".join(line.text for line in lines)
    mode_match = re.search(r"\bMODE\s*(\d+)", text, re.IGNORECASE)
    databases = re.findall(
        r'"((?:E)?(?:GAM|PUB)(?:DATA|DAT|INDX|IDX))"',
        text,
        re.IGNORECASE,
    )
    loaded_helpers = re.findall(r"\*\s*LOAD\s+([!A-Za-z0-9_-]+)", text, re.IGNORECASE)
    universal = (
        mode_match is not None
        and {name.upper() for name in databases}.issuperset({"GAMDATA", "GAMINDX"})
        and any(name.upper() == "TXT2SCN" for name in loaded_helpers)
    )
    spi_game_menu = (
        mode_match is not None
        and program_name.upper() in {"GAMECOL", "GAMEMNU"}
        and {name.upper() for name in databases}.issuperset({"GAMDATA", "GAMINDX"})
        and "PROCOSGBPB" in text.upper()
        and "DIN 0" in text.upper()
    )
    if not universal and not spi_game_menu:
        return {
            "supported": False,
            "program": program_name,
            "programSha256": digest,
            "reason": "This menu program uses display behaviour the interpreter does not yet support.",
            "decodedLines": len(lines),
        }

    mode = int(mode_match.group(1))
    dimensions = {0: (80, 32), 1: (40, 32), 2: (20, 32), 3: (80, 25), 4: (40, 32), 5: (20, 32), 6: (40, 25), 7: (40, 25)}
    columns, rows = dimensions.get(mode, (40, 32))
    logical_palette = list(BBC_COLOURS)
    palettes = []
    windows = []
    for values in _numbers(text, "VDU"):
        if len(values) >= 3 and values[0] == 19:
            logical, physical = values[1], values[2]
            if 0 <= logical < len(logical_palette) and 0 <= physical < len(BBC_COLOURS):
                logical_palette[logical] = BBC_COLOURS[physical]
                palettes.append({"logical": logical, "physical": physical})
        if len(values) >= 5 and values[0] == 28:
            windows.append({
                "left": values[1],
                "bottom": values[2],
                "right": values[3],
                "top": values[4],
            })
    text_window = next(
        (window for window in windows if window["right"] >= columns - 1 and window["top"] > 0),
        {"left": 0, "bottom": rows - 1, "right": columns - 1, "top": 3},
    )

    if spi_game_menu:
        title_match = re.search(
            r'PRINT\s*TAB\((\d+)\)\s*"([^"]+)"',
            text,
            re.IGNORECASE,
        )
        banner_match = re.search(r'FUNK\$\s*=\s*"([^"]+)"', text, re.IGNORECASE)
        title = title_match.group(2).rstrip() if title_match else "ELECTRON SPI GAME MENU"
        title_x = int(title_match.group(1)) if title_match else max(0, (columns - len(title)) // 2)
        banner = banner_match.group(1) if banner_match else "f0=EXIT,f3=Game,f5=Publisher,f7=A-Z Jump"
        return {
            "supported": True,
            "kind": "bbc-basic-spi-game-menu",
            "program": program_name,
            "programSha256": digest,
            "decodedLines": len(lines),
            "mode": mode,
            "columns": columns,
            "rows": rows,
            "palette": logical_palette,
            "paletteCommands": palettes,
            "textWindow": text_window,
            "title": {"text": title, "x": title_x, "y": 0, "colour": 2},
            "banner": {"text": banner, "x": 0, "y": 1, "colour": 1},
            "status": {"visible": False, "text": ""},
            "entries": {
                "x": text_window["left"],
                "y": text_window["top"],
                "pageSize": 26,
                "labelStart": "A",
                "labelColour": 1,
                "titleColour": 2,
                "publisherColour": 3,
                "separator": ",",
            },
            "databases": [name.upper() for name in databases],
            "helpers": ["DOEXEC"],
            "launch": {
                "diskCommand": "*DIN 0 {diskTitle}",
                "command": "*EXEC !BOOT",
            },
            "limitations": [
                "The preview interprets the installed SPI Game Menu display and databases; it does not execute selected software.",
            ],
        }

    address_references = [
        (line.number, int(address, 16), line.text)
        for line in lines[:20]
        for address in re.findall(r"\$&([0-9A-F]+)", line.text, re.IGNORECASE)
    ]
    strings = [
        (number, address, value, source)
        for number, address, source in address_references
        if (value := _memory_string(address, support_files)) is not None
    ]
    title_reference = next(
        ((address, value, source) for _number, address, value, source in strings if "TAB(" in source),
        None,
    )
    banner_reference = next(
        ((address, value) for _number, address, value, source in strings if "TAB(" not in source and "Screens" in source),
        None,
    )
    title = title_reference[1] if title_reference else "Universal Menu"
    title_x_match = re.search(r"TAB\((\d+)\)", title_reference[2] if title_reference else "")
    title_x = int(title_x_match.group(1)) if title_x_match else max(0, (columns - len(title)) // 2)
    banner = banner_reference[1] if banner_reference else "f0=EXIT,f3=DATA1/2,f5=Search,f7=AZ Jump"
    page_size_match = re.search(r"R%=\s*(\d+)", text)
    page_size = int(page_size_match.group(1)) if page_size_match else 26
    title_colour_match = re.search(r"COLOUR\s*(\d+)\s*:\s*PRINT\s*TAB", text, re.IGNORECASE)
    title_colour = int(title_colour_match.group(1)) if title_colour_match else 2

    return {
        "supported": True,
        "kind": "bbc-basic-universal-menu",
        "program": program_name,
        "programSha256": digest,
        "decodedLines": len(lines),
        "mode": mode,
        "columns": columns,
        "rows": rows,
        "palette": logical_palette,
        "paletteCommands": palettes,
        "textWindow": text_window,
        "title": {"text": title, "x": title_x, "y": 0, "colour": title_colour},
        "banner": {"text": banner, "x": 0, "y": 1, "colour": 3},
        "status": {"x": 0, "y": 2, "colour": 3, "template": "{screens} Screens. At:{page}"},
        "entries": {
            "x": text_window["left"],
            "y": text_window["top"],
            "pageSize": page_size,
            "labelStart": "A",
            "titleColour": 2,
            "publisherColour": 3,
            "separator": ",",
        },
        "databases": [name.upper() for name in databases],
        "helpers": [name.upper() for name in loaded_helpers],
        "limitations": [
            "The preview interprets the installed menu's display path and database renderer; it does not execute selected software.",
        ],
    }
