from __future__ import annotations

import bz2
import gzip
import io
import lzma
import posixpath
import tarfile
import zipfile

from .content_kind import LISTING_SNIFF_LIMIT, analyse_content, metadata_kind
from .disk_service import DiskError
from .uef import UEFError, parse_uef


ARCHIVE_EXTENSIONS = (
    ".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz", ".tbz2",
    ".tar.xz", ".txz", ".gz", ".gzip", ".bz2", ".xz", ".uef",
)
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_MEMBER_BYTES = 128 * 1024 * 1024
MAX_ENTRIES = 20_000


class ArchiveError(DiskError):
    pass


def is_archive_name(name: str) -> bool:
    lowered = str(name or "").casefold()
    return any(lowered.endswith(extension) for extension in ARCHIVE_EXTENSIONS)


def is_uef_container(data: bytes) -> bool:
    """Sniff raw or gzip-compressed UEF data without expanding the whole tape."""
    if data.startswith(b"UEF File!\0"):
        return True
    if not data.startswith(b"\x1f\x8b"):
        return False
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
            return compressed.read(10) == b"UEF File!\0"
    except (gzip.BadGzipFile, EOFError, OSError):
        return False


def _safe_name(value: str) -> str:
    name = str(value or "").replace("\\", "/").lstrip("/")
    normalised = posixpath.normpath(name)
    if normalised in {"", "."}:
        return ""
    if normalised == ".." or normalised.startswith("../"):
        raise ArchiveError("The archive contains an unsafe parent path.")
    return normalised


def _standalone_name(filename: str) -> str:
    lowered = filename.casefold()
    for suffix in (".gzip", ".gz", ".bz2", ".xz"):
        if lowered.endswith(suffix):
            return filename[:-len(suffix)] or "contents"
    return "contents"


def _uef_member_kind(name: str, data: bytes) -> str:
    return metadata_kind(name, None) or analyse_content(data, name)[0]


def _bounded_member_kind(name: str, size: int, reader) -> str | None:
    """Classify a small archive member while its parent archive is already open."""
    hint = metadata_kind(name, None)
    if hint:
        return hint
    if size <= 0 or size > LISTING_SNIFF_LIMIT:
        return None
    try:
        data = reader()
    except (EOFError, OSError, RuntimeError, ValueError, zipfile.BadZipFile, tarfile.TarError):
        return None
    return analyse_content(data, name)[0] if len(data) == size else None


def _archive_kind(data: bytes, filename: str) -> str:
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ArchiveError("That archive is too large to browse safely in memory.")
    if is_uef_container(data):
        return "uef"
    stream = io.BytesIO(data)
    if zipfile.is_zipfile(stream):
        return "zip"
    stream.seek(0)
    try:
        with tarfile.open(fileobj=stream, mode="r:*"):
            return "tar"
    except (tarfile.TarError, EOFError, OSError):
        pass
    lowered = filename.casefold()
    if data.startswith(b"\x1f\x8b") or lowered.endswith((".gz", ".gzip")):
        return "gzip"
    if data.startswith(b"BZh") or lowered.endswith(".bz2"):
        return "bz2"
    if data.startswith(b"\xfd7zXZ\x00") or lowered.endswith(".xz"):
        return "xz"
    raise ArchiveError("That file is not a supported UEF, ZIP, TAR, GZIP, BZIP2 or XZ container.")


def _members(data: bytes, filename: str) -> tuple[str, list[dict]]:
    kind = _archive_kind(data, filename)
    rows: list[dict] = []
    if kind == "uef":
        try:
            tape = parse_uef(data)
        except UEFError as exc:
            raise ArchiveError(f"That UEF tape container is damaged: {exc}") from exc
        used: dict[str, int] = {}
        for index, item in enumerate(tape.files[:MAX_ENTRIES]):
            base = _safe_name(item.name).replace("/", "_") or f"TapeFile{index + 1}"
            used[base.casefold()] = used.get(base.casefold(), 0) + 1
            occurrence = used[base.casefold()]
            name = base if occurrence == 1 else f"{base}~{occurrence}"
            rows.append({
                "name": name, "size": len(item.data), "dir": False, "source": index,
                "load": item.load, "execute": item.execute, "complete": item.complete,
                "contentKind": _uef_member_kind(item.name, item.data),
            })
    elif kind == "zip":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for item in archive.infolist()[:MAX_ENTRIES]:
                name = _safe_name(item.filename)
                if name:
                    row = {"name": name, "size": item.file_size, "dir": item.is_dir(), "source": item.filename}
                    if not item.is_dir():
                        content_kind = _bounded_member_kind(
                            name, item.file_size,
                            lambda item=item: archive.read(item),
                        )
                        if content_kind:
                            row["contentKind"] = content_kind
                    rows.append(row)
    elif kind == "tar":
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
            for item in archive.getmembers()[:MAX_ENTRIES]:
                name = _safe_name(item.name)
                if name and (item.isdir() or item.isfile()):
                    row = {"name": name, "size": item.size, "dir": item.isdir(), "source": item.name}
                    if item.isfile():
                        def read_tar_member(item=item):
                            expanded = archive.extractfile(item)
                            return expanded.read() if expanded else b""
                        content_kind = _bounded_member_kind(name, item.size, read_tar_member)
                        if content_kind:
                            row["contentKind"] = content_kind
                    rows.append(row)
    else:
        rows.append({"name": _safe_name(_standalone_name(filename)), "size": None, "dir": False, "source": ""})
    if len(rows) >= MAX_ENTRIES:
        raise ArchiveError(f"The archive contains at least {MAX_ENTRIES:,} entries, which exceeds the safe browsing limit.")
    return kind, rows


def list_archive(data: bytes, filename: str, directory: str = "") -> dict:
    kind, members = _members(data, filename)
    current = _safe_name(directory)
    prefix = f"{current}/" if current else ""
    children: dict[str, dict] = {}
    for member in members:
        if not member["name"].startswith(prefix) or member["name"] == current:
            continue
        remainder = member["name"][len(prefix):]
        leaf, separator, _tail = remainder.partition("/")
        if not leaf:
            continue
        child = children.setdefault(leaf, {
            "name": leaf, "type": "dir" if separator or member["dir"] else "file",
            "length": 0, "attr": "RO", "archiveEntry": True,
        })
        if separator or member["dir"]:
            child["type"] = "dir"
        elif child["type"] != "dir":
            child["length"] = int(member["size"] or 0)
            if member.get("contentKind"):
                child["contentKind"] = member["contentKind"]
            if kind == "uef":
                child.update(
                    load=member["load"], exec=member["execute"],
                    attr="R/" if member["complete"] else "R/?",
                    complete=member["complete"],
                    contentKind=member["contentKind"],
                )
    entries = sorted(children.values(), key=lambda row: (row["type"] != "dir", row["name"].casefold()))
    return {
        "entries": entries,
        "description": f"Read-only {kind.upper()} {'tape container' if kind == 'uef' else 'archive'} · {len(members):,} member(s)",
        "archiveKind": kind,
        "member": current,
    }


def read_archive_member_details(data: bytes, filename: str, member_name: str) -> tuple[bytes, dict]:
    wanted = _safe_name(member_name)
    kind, members = _members(data, filename)
    match = next((row for row in members if row["name"] == wanted and not row["dir"]), None)
    if not match:
        raise ArchiveError("That archive member does not exist or is not a regular file.")
    if match["size"] is not None and int(match["size"]) > MAX_MEMBER_BYTES:
        raise ArchiveError("That archive member is too large to open safely.")
    if kind == "uef":
        content = parse_uef(data).files[int(match["source"])].data
    elif kind == "zip":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            with archive.open(match["source"]) as expanded:
                content = expanded.read(MAX_MEMBER_BYTES + 1)
    elif kind == "tar":
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
            extracted = archive.extractfile(match["source"])
            if extracted is None:
                raise ArchiveError("That TAR member could not be read.")
            content = extracted.read(MAX_MEMBER_BYTES + 1)
    elif kind == "gzip":
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as expanded:
            content = expanded.read(MAX_MEMBER_BYTES + 1)
    elif kind == "bz2":
        decompressor = bz2.BZ2Decompressor()
        content = decompressor.decompress(data, max_length=MAX_MEMBER_BYTES + 1)
    else:
        decompressor = lzma.LZMADecompressor()
        content = decompressor.decompress(data, max_length=MAX_MEMBER_BYTES + 1)
    if len(content) > MAX_MEMBER_BYTES:
        raise ArchiveError("That expanded archive member exceeds the safe opening limit.")
    return content, {
        "length": len(content),
        "load": int(match.get("load") or 0),
        "execute": int(match.get("execute") or 0),
        "attr": "R/",
        "archiveKind": kind,
        "contentKind": match.get("contentKind"),
    }


def read_archive_member(data: bytes, filename: str, member_name: str) -> bytes:
    return read_archive_member_details(data, filename, member_name)[0]
