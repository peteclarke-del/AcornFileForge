from __future__ import annotations

import gzip
import io
import re


LISTING_SNIFF_LIMIT = 128 * 1024
SCRIPT_NAMES = {"!boot", "boot", "startup", "start", "loader", "menu"}
SCRIPT_COMMAND_RE = re.compile(
    r"^\s*(?:\*\s*([A-Za-z][A-Za-z0-9.]*)\s*(.*)|"
    r"(CHAIN|RUN|LOAD|SAVE|EXEC|DIR|LIB|DRIVE|BASIC|FX|KEY|MODE|VDU|PAGE|HIMEM|LOMEM|"
    r"PRINT|CLS|CLG|COLOUR|GCOL|SOUND|ENVELOPE|IF|FOR|REPEAT|PROC|CALL|OSCLI)\b\s*(.*))$",
    re.IGNORECASE,
)


def format_basic_listing(source: str) -> str:
    """Give every numbered BBC BASIC line one visible separator after its number."""
    formatted = []
    for line in source.splitlines():
        match = re.match(r"^(\d+)(.*)$", line)
        if not match:
            formatted.append(line)
            continue
        number, body = match.groups()
        formatted.append(f"{number} {body[1:] if body.startswith((' ', chr(9))) else body}")
    return "\n".join(formatted)


def basic_details(data: bytes) -> dict | None:
    try:
        from oaknut.basic import BASIC_II, BASIC_V, Verdict, detect, detokenise, scan_program
    except ImportError:
        return None
    detection = detect(data)
    if detection.verdict not in {Verdict.BASIC, Verdict.BASIC_TRAILING}:
        return None
    program_length = int(detection.program_length or len(data))
    program = data[:program_length]
    basic_v_lines = list(scan_program(program, dialect=BASIC_V))
    uses_basic_v_escape = any(
        token.token in BASIC_V.escape
        and token.value in BASIC_V.escape[token.token].values()
        for line in basic_v_lines
        for token in line.tokens
    )
    dialect = BASIC_V if uses_basic_v_escape else BASIC_II
    try:
        source = format_basic_listing(detokenise(program, dialect=dialect))
        lines = basic_v_lines if dialect is BASIC_V else list(scan_program(program, dialect=dialect))
    except Exception:
        return None
    return {
        "source": source,
        "dialect": dialect.name,
        "lineCount": len(lines),
        "firstLine": lines[0].line_number if lines else None,
        "lastLine": lines[-1].line_number if lines else None,
        "trailingBytes": len(data) - program_length,
        "editable": dialect is BASIC_II and len(data) <= 64 * 1024 and len(data) == program_length,
    }


def script_details(data: bytes, path: str, printable_ratio: float) -> dict | None:
    """Recognise line-oriented *EXEC/BASIC command scripts without trusting only the name."""
    if not data or b"\0" in data or printable_ratio < 0.70:
        return None
    text = data.decode("latin-1", "replace").replace("\r\n", "\n").replace("\r", "\n")
    meaningful = [line for line in text.splitlines() if line.strip()]
    commands = []
    for line_number, line in enumerate(text.splitlines(), 1):
        match = SCRIPT_COMMAND_RE.match(line)
        if not match:
            continue
        star_command, star_arguments, basic_command, basic_arguments = match.groups()
        commands.append({
            "line": line_number,
            "action": (star_command or basic_command or "").upper(),
            "arguments": (star_arguments if star_command else basic_arguments or "").strip(),
            "osCommand": bool(star_command),
        })
    leaf = path.rsplit(".", 1)[-1].casefold()
    named_script = leaf in SCRIPT_NAMES or leaf.startswith("!boot")
    enough_commands = commands and len(commands) >= max(1, (len(meaningful) + 1) // 2)
    if not named_script and not enough_commands:
        return None
    return {
        "lineCount": len(text.splitlines()),
        "commandCount": len(commands),
        "commands": commands,
        "namedScript": named_script,
    }


def is_uef_container(data: bytes) -> bool:
    """Recognise raw or gzip-compressed UEF data from a bounded prefix."""
    if data.startswith(b"UEF File!\0"):
        return True
    if not data.startswith(b"\x1f\x8b"):
        return False
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
            return compressed.read(10) == b"UEF File!\0"
    except (gzip.BadGzipFile, EOFError, OSError):
        return False


def analyse_content(data: bytes, path: str) -> tuple[str, dict | None, dict | None, float]:
    """Classify complete, bounded file bytes using the editor's content rules."""
    if is_uef_container(data):
        return "container", None, None, 0.0
    basic = basic_details(data)
    printable = sum(value in (9, 10, 13) or 32 <= value < 127 for value in data)
    printable_ratio = printable / len(data) if data else 0.0
    script = None if basic else script_details(data, path, printable_ratio)
    kind = "basic" if basic else "script" if script else "text" if data and printable_ratio >= 0.82 else "binary"
    return kind, basic, script, printable_ratio


def metadata_kind(name: str, filetype: int | str | None) -> str | None:
    """Return a reliable kind that needs no content read, or None to sniff bytes."""
    try:
        value = int(str(filetype), 0) if filetype not in (None, "") else None
    except (TypeError, ValueError):
        value = None
    lowered = str(name or "").casefold()
    leaf = lowered.rsplit(".", 1)[-1]
    if value == 0xFFB or lowered.endswith((".bas", ".basic")):
        return "basic"
    if value == 0xFEB or leaf in SCRIPT_NAMES or leaf.startswith("!boot"):
        return "script"
    if value == 0xFFF or lowered.endswith((".txt", ".text", ".md")) or leaf in {"readme", "license", "copying"}:
        return "text"
    return None
