from __future__ import annotations

import re
from dataclasses import dataclass

from .menu_interpreter import _TOKENS, decode_basic


DFS_CATALOGUE_SIZE = 512
DFS_MAX_FILES = 31
DFS_SECTOR_SIZE = 256
_FILE_COMMAND_TOKENS = {
    code
    for code, name in _TOKENS.items()
    if name in {"CHAIN", "LOAD", "RUN", "SAVE", "OPENIN", "OPENUP", "OPENOUT", "*"}
}
_QUOTED_TEXT = re.compile(rb'"([^"\r]+)"')


@dataclass(frozen=True)
class DFSFile:
    directory: str
    name: str
    start: int
    length: int
    load: int
    execute: int

    @property
    def path(self) -> str:
        return f"{self.directory}.{self.name}"


def dfs_catalogue_files(image: bytes) -> list[DFSFile]:
    """Read the small part of a standard DFS catalogue needed for safe patches."""
    if len(image) < DFS_CATALOGUE_SIZE:
        return []
    file_count = (image[0x105] & 0xF8) // 8
    if file_count > DFS_MAX_FILES:
        return []
    files: list[DFSFile] = []
    for index in range(file_count):
        name_offset = 8 + index * 8
        metadata_offset = 0x108 + index * 8
        name = bytes(value & 0x7F for value in image[name_offset : name_offset + 7])
        name = name.decode("latin-1", "replace").rstrip("\0 ")
        directory = chr(image[name_offset + 7] & 0x7F)
        packed = image[metadata_offset + 6]
        load = int.from_bytes(image[metadata_offset : metadata_offset + 2], "little")
        load |= (packed & 0x0C) << 14
        execute = int.from_bytes(image[metadata_offset + 2 : metadata_offset + 4], "little")
        execute |= (packed & 0xC0) << 10
        length = int.from_bytes(image[metadata_offset + 4 : metadata_offset + 6], "little")
        length |= (packed & 0x30) << 12
        start_sector = image[metadata_offset + 7] | ((packed & 0x03) << 8)
        start = start_sector * DFS_SECTOR_SIZE
        if name and start >= DFS_CATALOGUE_SIZE and start + length <= len(image):
            files.append(DFSFile(directory, name, start, length, load, execute))
    return files


def _looks_like_tokenized_basic(data: bytes) -> bool:
    """Accept strict BBC BASIC plus old programs that end at the final line.

    A few published disks omit the usual 0x0D,0xFF terminator. BBC BASIC can
    still load their complete line records, so PAGE inference must not reject
    them merely because the decoder quite correctly regards them as malformed.
    """
    if decode_basic(data):
        return True
    position = 0
    lines = 0
    while position < len(data):
        if data[position:] == b"\r":
            position += 1
            break
        if position + 4 > len(data) or data[position] != 0x0D:
            return False
        length = data[position + 3]
        if length < 4 or position + length > len(data):
            return False
        position += length
        lines += 1
    return lines > 0 and position == len(data)


def _resolve_dfs_reference(
    files: list[DFSFile], reference: str, current_directory: str
) -> DFSFile | None:
    value = reference.strip()
    if value.startswith("$."):
        directory, leaf = "$", value[2:]
    elif "." in value:
        prefix, leaf = value.rsplit(".", 1)
        directory = prefix[-1:] or current_directory
    else:
        directory, leaf = current_directory, value
    return next(
        (
            item for item in files
            if item.directory.casefold() == directory.casefold()
            and item.name.casefold() == leaf.casefold()
        ),
        None,
    )


def infer_dfs_launch_page(
    image: bytes,
    filename: str,
    action: str,
) -> tuple[str | None, str]:
    """Infer a menu PAGE from the actual launch path without guessing."""
    files = dfs_catalogue_files(image)
    requested = str(filename or "").strip()
    launch = _resolve_dfs_reference(files, requested, "$")
    if launch is None:
        return None, f"launch file {requested or '(blank)'} is absent"
    data = image[launch.start : launch.start + launch.length]
    if str(action or "").upper() == "" and _looks_like_tokenized_basic(data):
        page = launch.load & 0xFFFF
        if 0x800 <= page <= 0x7F00:
            return f"{page:X}", f"{launch.path} is tokenised BASIC saved at &{page:X}"

    if str(action or "").upper() == "E":
        text = data.decode("latin-1", "replace")
        explicit = re.search(r"(?i)\bPA(?:GE|\.)?\s*=\s*&([0-9A-F]{3,4})", text)
        if explicit:
            return explicit.group(1).upper(), f"{launch.path} explicitly sets PAGE=&{explicit.group(1).upper()}"
        chain = re.search(r'(?i)\bCH(?:AIN|\.)?\s*"([^"\r]+)"', text)
        if chain:
            target_name = chain.group(1)
            target = _resolve_dfs_reference(files, target_name, launch.directory)
            if target is not None:
                target_data = image[target.start : target.start + target.length]
                page = target.load & 0xFFFF
                if _looks_like_tokenized_basic(target_data) and 0x800 <= page <= 0x7F00:
                    return f"{page:X}", f"{launch.path} chains tokenised BASIC {target.path} saved at &{page:X}"
        run = re.search(r'(?i)(?:^|:)\s*\*?R(?:UN)?\.?\s*"?([^"\s\r]+)', text)
        if run:
            target = _resolve_dfs_reference(files, run.group(1), launch.directory)
            if target is not None and not _looks_like_tokenized_basic(
                image[target.start : target.start + target.length]
            ):
                return None, f"{launch.path} runs machine code {target.path}; BASIC PAGE is not used"
    return None, f"{launch.path} does not expose a provable BASIC PAGE"


def _command_string(line: bytes, quote_at: int) -> bool:
    statement = line[:quote_at].rsplit(b":", 1)[-1]
    return any(token in statement for token in _FILE_COMMAND_TOKENS)


def _exact_wildcard_target(reference: str, directory: str, files: list[DFSFile]) -> tuple[DFSFile, str] | None:
    value = reference.strip()
    if "#" not in value or not value or any(character in value for character in "&%()+=,;"):
        return None
    prefix = ""
    command_match = re.match(r"(?i)^(?:\*?(?:CHAIN|LOAD|RUN|SAVE)\s+)(.+)$", value)
    if command_match:
        prefix = value[: command_match.start(1)]
        value = command_match.group(1).strip()
    if " " in value:
        return None
    target_directory = directory
    target_name = value
    if "." in value:
        candidate_directory, target_name = value.rsplit(".", 1)
        target_directory = candidate_directory[-1:] or directory
    pattern = re.compile("^" + re.escape(target_name).replace(r"\#", ".") + "$", re.IGNORECASE)
    matches = [
        item
        for item in files
        if item.directory.casefold() == target_directory.casefold() and pattern.fullmatch(item.name)
    ]
    if len(matches) != 1:
        return None
    exact_name = matches[0].name
    repaired_value = value[: len(value) - len(target_name)] + exact_name
    if repaired_value == value:
        return None
    return matches[0], prefix + repaired_value


def repair_dfs_basic_wildcards(image: bytes) -> tuple[bytes, list[str]]:
    """Replace provable BASIC ``#`` wildcards with exact DFS catalogue names.

    DFS accepts ``#`` as a one-character wildcard, but some MMFS versions do
    not resolve it consistently. A replacement is made only when the BASIC
    string belongs to a file command and exactly one file in the relevant DFS
    directory matches it. The replacement has identical length, so catalogue
    extents and tokenised BASIC line lengths remain unchanged.
    """
    files = dfs_catalogue_files(image)
    if not files:
        return image, []
    repaired = bytearray(image)
    changes: list[str] = []
    for source in files:
        original = bytes(repaired[source.start : source.start + source.length])
        lines = decode_basic(original)
        if not lines:
            continue
        patched = bytearray(original)
        position = 0
        for line in lines:
            length = original[position + 3]
            body_start = position + 4
            for match in _QUOTED_TEXT.finditer(line.body):
                if not _command_string(line.body, match.start()):
                    continue
                reference = match.group(1).decode("latin-1", "replace")
                target = _exact_wildcard_target(reference, source.directory, files)
                if target is None:
                    continue
                matched_file, replacement = target
                encoded = replacement.encode("latin-1", "replace")
                if len(encoded) != len(match.group(1)):
                    continue
                start = body_start + match.start(1)
                patched[start : start + len(encoded)] = encoded
                changes.append(
                    f'{source.path} line {line.number}: {reference} → {replacement} '
                    f'(exact file {matched_file.path})'
                )
            position += length
        if patched != original:
            repaired[source.start : source.start + source.length] = patched
    return bytes(repaired), changes
