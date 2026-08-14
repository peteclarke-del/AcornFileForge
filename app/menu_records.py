from __future__ import annotations

import re
import struct

from .errors import DiskError


def normalise_page(value: object, default: str = "1900") -> str:
    """Return the complete hexadecimal PAGE address used by Universal Menu."""
    text = str(value or "").strip().upper().removeprefix("&")
    if not text:
        return default
    if not re.fullmatch(r"[0-9A-F]{1,4}", text):
        return text
    number = int(text, 16)
    if len(text) <= 2:
        number <<= 8
    return f"{number:X}"


def menu_page_field(value: object) -> str:
    """Encode PAGE as the high-byte field expected by Universal Menu."""
    page = normalise_page(value)
    return page[:-2] if len(page) > 2 and page.endswith("00") else page


def legacy_page_field_count(raw_database: bytes) -> int:
    """Count old PAGE fields stored as full addresses instead of high bytes."""
    count = 0
    for line in raw_database.decode("latin-1", "replace").splitlines():
        fields = line.split(",")
        if len(fields) < 5:
            continue
        page = fields[4].strip().upper()
        if len(page) > 2 and page.endswith("00"):
            count += 1
    return count


def _basic_integer(value: int) -> bytes:
    return b"\x40" + struct.pack(">I", max(0, int(value)))


def build_index(lines: list[bytes]) -> bytes:
    screens = [lines[pos : pos + 26] for pos in range(0, len(lines), 26)] or [[]]
    first_screen: list[int] = []
    current = 0
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        first_screen.append(current)
        for index, page in enumerate(screens):
            if any(line[:1].decode("latin-1", "ignore").upper() == letter for line in page):
                current = index
                first_screen[-1] = index
                break
    values = [
        len(screens),
        len(screens[-1]),
        *first_screen,
        *(sum(len(line) + 2 for line in page) for page in screens),
    ]
    return b"".join(_basic_integer(value) for value in values)


_MENU_MINOR_WORDS = {
    "a", "an", "and", "as", "at", "but", "by", "for", "from", "in",
    "into", "nor", "of", "on", "or", "the", "to", "vs", "with",
}
_MENU_ACRONYMS = {
    "ADFS", "AQOS", "BBC", "CPU", "DFS", "FIFA", "MMFS", "RAM", "REVS",
    "RISC", "ROM", "SAS", "UFO", "UK", "USA",
}
_ROMAN_NUMERAL = re.compile(r"^(?:I|II|III|IV|V|VI|VII|VIII|IX|X)$")


def menu_title_case(value: object) -> str:
    """Apply readable title case only to metadata supplied wholly in capitals."""
    title = " ".join(str(value or "").strip().split())
    letters = [character for character in title if character.isalpha()]
    if not letters or not all(character.isupper() for character in letters):
        return title
    parts = re.split(r"([\s-]+)", title)
    word_positions = [index for index, part in enumerate(parts) if part and not re.fullmatch(r"[\s-]+", part)]
    first_word = word_positions[0] if word_positions else -1
    last_word = word_positions[-1] if word_positions else -1
    for index in word_positions:
        word = parts[index]
        bare = re.sub(r"^[^A-Z0-9]+|[^A-Z0-9]+$", "", word)
        if not bare:
            continue
        if bare in _MENU_ACRONYMS or _ROMAN_NUMERAL.fullmatch(bare) or any(character.isdigit() for character in bare):
            replacement = bare
        elif bare.casefold() in _MENU_MINOR_WORDS and index not in {first_word, last_word}:
            replacement = bare.lower()
        else:
            replacement = bare[:1].upper() + bare[1:].lower()
        parts[index] = word.replace(bare, replacement, 1)
    return "".join(parts)


def fit_menu_display_fields(title: object, publisher: object, width: int = 38) -> tuple[str, str]:
    """Fit ``title,publisher`` after the menu's two-character A- label."""

    def trim(value: str, limit: int) -> str:
        if len(value) <= limit:
            return value
        shortened = value[:limit].rstrip()
        boundary = shortened.rfind(" ")
        return shortened[:boundary] if boundary >= max(1, limit * 2 // 3) else shortened

    clean_title = menu_title_case(title)
    clean_publisher = " ".join(str(publisher or "").strip().split())
    if not clean_publisher:
        return trim(clean_title, width), ""
    title_limit = min(30, max(1, width - 2))
    clean_title = trim(clean_title, title_limit)
    publisher_limit = max(0, width - len(clean_title) - 1)
    return clean_title, trim(clean_publisher, publisher_limit)


def parse_menu_data(data: bytes, publisher_view: bool = False) -> list[dict]:
    rows = []
    for offset, raw in enumerate(data.decode("latin-1", "replace").splitlines()):
        fields = raw.split(",")
        if len(fields) < 6:
            continue
        first, second, filename, action, page, disk = fields[:6]
        system = action[:1] if offset == 0 and action[:1] in {"D", "B", "M", "H"} else "M"
        if offset == 0 and action[:1] in {"D", "B", "M", "H"}:
            action = action[1:]
            if not action and filename.upper() == "!BOOT":
                action = "E"
        rows.append({
            "title": second if publisher_view else first,
            "publisher": first if publisher_view else second,
            "filename": filename,
            "action": action,
            "page": normalise_page(page),
            "diskTitle": disk,
            "system": system,
        })
    return rows


def parse_spi_menu_data(data: bytes, publisher_view: bool = False) -> list[dict]:
    """Read Ray Harper's three-field Electron SPI/SDI menu records."""
    rows = []
    for raw in data.decode("latin-1", "replace").splitlines():
        fields = raw.split(",")
        if len(fields) < 3:
            continue
        first, second, disk = fields[:3]
        rows.append({
            "title": second if publisher_view else first,
            "publisher": first if publisher_view else second,
            "filename": "!BOOT",
            "action": "E",
            "page": "1900",
            "diskTitle": disk,
            "system": "M",
        })
    return rows


def parse_mmb_menu_data(data: bytes, menu_type: str | None, publisher_view: bool = False) -> list[dict]:
    if menu_type == "spi-game-menu":
        return parse_spi_menu_data(data, publisher_view=publisher_view)
    return parse_menu_data(data, publisher_view=publisher_view)


def serialise_menu(
    entries: list[dict],
    publisher_view: bool = False,
    system: str = "M",
    *,
    preserve_order: bool = False,
    preserve_first_action: bool = False,
) -> tuple[bytes, bytes]:
    key = (lambda item: (item["publisher"].casefold(), item["title"].casefold())) if publisher_view else (
        lambda item: (item["title"].casefold(), item["publisher"].casefold())
    )
    ordered = list(entries) if preserve_order else sorted(entries, key=key)
    lines = []
    for offset, item in enumerate(ordered):
        display_title, display_publisher = fit_menu_display_fields(item["title"], item["publisher"])
        first, second = (display_publisher, display_title) if publisher_view else (display_title, display_publisher)
        action = (
            f"{system}{item['action']}"
            if offset == 0 and preserve_first_action
            else system if offset == 0
            else item["action"]
        )
        fields = [first, second, item["filename"], action, menu_page_field(item["page"]), item["diskTitle"]]
        safe = [str(value or "").replace(",", " ").replace("\r", " ").replace("\n", " ") for value in fields]
        lines.append(",".join(safe).encode("latin-1", "replace"))
    return b"\r\n".join(lines) + (b"\r\n" if lines else b""), build_index(lines)


def serialise_spi_menu(entries: list[dict], publisher_view: bool = False) -> tuple[bytes, bytes]:
    key = (
        (lambda item: (item["publisher"].casefold(), item["title"].casefold()))
        if publisher_view
        else (lambda item: (item["title"].casefold(), item["publisher"].casefold()))
    )
    lines = []
    for item in sorted(entries, key=key):
        display_title, display_publisher = fit_menu_display_fields(item["title"], item["publisher"])
        first, second = (display_publisher, display_title) if publisher_view else (display_title, display_publisher)
        fields = (first, second, item["diskTitle"])
        safe = [str(value or "").replace(",", " ").replace("\r", " ").replace("\n", " ") for value in fields]
        lines.append(",".join(safe).encode("latin-1", "replace"))
    return b"\r\n".join(lines) + (b"\r\n" if lines else b""), build_index(lines)


def normalise_record(metadata: dict, system: str) -> dict:
    is_adfs = system == "H"
    title, publisher = fit_menu_display_fields(metadata.get("title", ""), metadata.get("publisher", ""))
    record = {
        "title": title,
        "publisher": publisher,
        "filename": str(metadata.get("filename", "")).strip()[: 10 if is_adfs else 7],
        "action": str(metadata.get("action", "")).strip().upper(),
        "page": normalise_page(metadata.get("page", "1900")),
        "diskTitle": str(
            (metadata.get("path") or metadata.get("diskTitle", ""))
            if is_adfs else metadata.get("diskTitle", "")
        ).strip(),
        "system": system,
    }
    if not is_adfs:
        record["diskTitle"] = record["diskTitle"][:12]
    if not record["title"] or not record["filename"] or not record["diskTitle"]:
        location = "ADFS directory path" if is_adfs else "MMB disk title"
        raise DiskError(f"Title, launch filename and {location} are required.")
    return record


def normalise_mmb_record(metadata: dict, menu_type: str | None) -> dict:
    if menu_type != "spi-game-menu":
        return normalise_record(metadata, "M")
    title, publisher = fit_menu_display_fields(metadata.get("title", ""), metadata.get("publisher", ""))
    record = {
        "title": title,
        "publisher": publisher,
        "filename": "!BOOT",
        "action": "E",
        "page": "1900",
        "diskTitle": str(metadata.get("diskTitle", "")).strip()[:12],
        "system": "M",
    }
    if not record["title"] or not record["diskTitle"]:
        raise DiskError("Title and MMB disk title are required for an SPI Game Menu entry.")
    return record
