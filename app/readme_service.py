from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from .dfs_compat import dfs_catalogue_files
from .disk_service import MMB_ENTRY_SIZE, MMB_HEADER_SIZE, MMB_MAX_SLOTS, MMB_SLOT_SIZE

if TYPE_CHECKING:
    from .disk_service import DiskService, ImageSession


def timestamped_archive_name(image_name: str, generated: datetime | None = None) -> str:
    moment = generated or datetime.now().astimezone()
    stem = Path(image_name).stem or "acorn-image"
    return f"{stem}-{moment:%Y%m%d-%H%M%S}.zip"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hex(value: object) -> str:
    if value in (None, ""):
        return "-"
    if isinstance(value, str):
        return value
    return f"&{int(value):X}"


def _safe_cell(value: object) -> str:
    return str(value if value not in (None, "") else "-").replace("|", "\\|").replace("\n", " ")


def _dfs_rows(data: bytes) -> list[str]:
    return [
        f"| `{_safe_cell(item.path)}` | {item.length:,} | `{item.load:06X}` | `{item.execute:06X}` |"
        for item in dfs_catalogue_files(data)
    ]


def _mmb_catalogue(path: Path, source_names: dict[int, str]) -> list[str]:
    lines = [
        "## MMB slot catalogue",
        "",
        "All 511 addressable slots are listed. Empty slots can receive an SSD image later.",
        "",
    ]
    with path.open("rb") as image:
        header = image.read(MMB_HEADER_SIZE)
        count = min(MMB_MAX_SLOTS, max(0, (path.stat().st_size - MMB_HEADER_SIZE) // MMB_SLOT_SIZE))
        for slot in range(MMB_MAX_SLOTS):
            if slot >= count:
                lines.extend((f"### Slot {slot:03d}: unavailable", ""))
                continue
            entry = header[16 + slot * MMB_ENTRY_SIZE : 16 + (slot + 1) * MMB_ENTRY_SIZE]
            status = entry[15] if len(entry) == MMB_ENTRY_SIZE else 0xFF
            title = entry[:12].decode("latin-1", "replace").rstrip("\0 ")
            if status >= 0x80:
                lines.extend((f"### Slot {slot:03d}: empty", "", f"Header status: `&{status:02X}`", ""))
                continue
            access = "read/write" if status > 0 else "read-only"
            image.seek(MMB_HEADER_SIZE + slot * MMB_SLOT_SIZE)
            disk = image.read(MMB_SLOT_SIZE)
            files = _dfs_rows(disk)
            lines.extend(
                (
                    f"### Slot {slot:03d}: {title or 'Untitled disk'}",
                    "",
                    f"Access: **{access}** · Header status: `&{status:02X}` · Files: **{len(files)}**",
                    "",
                )
            )
            if source_names.get(slot):
                lines.extend((f"Imported/source name: `{source_names[slot]}`", ""))
            if files:
                lines.extend(("| DFS name | Bytes | Load | Execute |", "|---|---:|---:|---:|", *files, ""))
            else:
                lines.extend(("The disk has an empty DFS catalogue.", ""))
    return lines


def _row_line(path: str, row: dict) -> str:
    kind = "directory" if row.get("type") in {"dir", "directory"} else "file"
    size = row.get("length", row.get("size", "-"))
    load = row.get("loadHex", row.get("load"))
    execute = row.get("executeHex", row.get("exec"))
    return (
        f"| `{_safe_cell(path)}` | {kind} | {_safe_cell(size)} | "
        f"`{_safe_cell(_hex(load))}` | `{_safe_cell(_hex(execute))}` | {_safe_cell(row.get('attr'))} |"
    )


def _filesystem_catalogue(service: DiskService, session: ImageSession) -> list[str]:
    lines = [
        "## Filesystem catalogue",
        "",
        "| Path | Type | Bytes | Load | Execute | Attributes |",
        "|---|---|---:|---:|---:|---|",
    ]
    if session.kind == "tape":
        listing = service.list_directory(session, "$", None)
        lines.extend(_row_line(f"$.{row.get('name', 'Untitled')}", row) for row in listing["entries"])
        return [*lines, ""]

    pending: list[tuple[str, int | None]] = (
        [("$", 0), ("$", 2)]
        if session.kind == "dfs" and session.path.name.lower().endswith(".dsd")
        else [("$", None)]
    )
    visited: set[tuple[str, int | None]] = set()
    object_count = 0
    while pending:
        directory, side = pending.pop(0)
        identity = (directory.casefold(), side)
        if identity in visited:
            continue
        visited.add(identity)
        listing = service.list_directory(session, directory, None, side)
        for row in listing["entries"]:
            name = str(row.get("name") or "Untitled")
            inner_path = f"$.{name}" if directory == "$" else f"{directory}.{name}"
            display_path = f"Side {side}: {inner_path}" if side is not None else inner_path
            lines.append(_row_line(display_path, row))
            object_count += 1
            if session.kind == "adfs" and row.get("type") in {"dir", "directory"}:
                pending.append((inner_path, None))
            if object_count >= 100_000:
                lines.extend(("", "Catalogue stopped at the 100,000-object safety limit."))
                pending.clear()
                break
    if object_count == 0:
        lines.append("| _(empty)_ | - | - | - | - | - |")
    return [*lines, ""]


def build_download_readme(
    service: DiskService,
    session: ImageSession,
    image_path: Path,
    generated: datetime | None = None,
) -> str:
    moment = generated or datetime.now().astimezone()
    container = "HFE" if session.hfe_original_path else session.kind.upper()
    lines = [
        f"# {session.name}",
        "",
        "This archive was prepared by Acorn File Forge, the open-source Acorn image workshop.",
        "Project: https://github.com/peteclarke-del/AcornFileForge",
        "",
        "## Image details",
        "",
        f"- Generated: {moment.isoformat(timespec='seconds')}",
        f"- Container / filesystem: {container} / {session.kind.upper()}",
        f"- Target hardware profile: {session.target_hardware}",
        f"- Image filename: `{session.name}`",
        f"- Image size: {image_path.stat().st_size:,} bytes",
        f"- Image SHA-256: `{_sha256(image_path)}`",
    ]
    if session.descriptor_path:
        lines.extend(
            (
                f"- Descriptor filename: `{session.descriptor_name}`",
                f"- Descriptor size: {session.descriptor_path.stat().st_size:,} bytes",
                f"- Descriptor SHA-256: `{_sha256(session.descriptor_path)}`",
            )
        )
    if session.hfe_original_path:
        lines.extend(
            (
                f"- HFE version: {session.hfe_version or 'unknown'}",
                f"- HFE write support: {'read-only' if session.hfe_read_only else 'editable and sector-verified'}",
            )
        )
    lines.extend(
        (
            "",
            "## Using this archive",
            "",
            "Keep this README beside the image so its catalogue, target and checksums stay with it.",
            "Verify the SHA-256 value after copying or writing it to media. Work from a backup, then test the edited image in an emulator or on disposable media before replacing a known-good card or disk.",
        )
    )
    if session.descriptor_path:
        lines.extend(
            (
                "",
                "The DAT and DSC are a matched BeebSCSI pair. Keep both files together in the `BeebSCSI0` directory and do not substitute a descriptor from another image.",
            )
        )
    if session.kind == "mmb":
        from .menu_service import installed_mmb_menus

        menus = installed_mmb_menus(service, session)
        lines.extend(
            (
                "",
                "MMB slot numbering is zero-based. Slot access reflects the MMB catalogue flag, not protection inside individual DFS files.",
                "Installed menus may depend on exact disk titles, PAGE values and slot mappings. Preserve the menu slot and make a checkpoint before reorganising disks.",
                "",
                "## Recognised MMB menus",
                "",
                *(
                    [f"- Slot {int(menu['slot']):03d}: {menu['type']}" for menu in menus]
                    or ["- No recognised menu program was found."]
                ),
                "",
                *_mmb_catalogue(image_path, session.slot_source_names),
            )
        )
    else:
        lines.extend(("", *_filesystem_catalogue(service, session)))
    warnings = [*session.warnings, *(list(session.tape.warnings) if session.tape else [])]
    lines.extend(("## Warnings and compatibility notes", ""))
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- No compatibility warnings were recorded for this working copy.")
    lines.extend(
        (
            "",
            "## Technical notes",
            "",
            "Acorn filenames, load addresses and execution addresses are significant. Renaming a loader or moving software between DFS and ADFS can break relative file references even when every file copied successfully.",
            "DFS and MMB cannot preserve flux timing, weak sectors or every copy-protection feature. HFE can contain track-level information that is not representable after filesystem editing.",
            "ADFS directory and free-space metadata must match the selected hardware profile. BeebSCSI DAT images also require their matching DSC geometry.",
            "For current documentation, releases and issue reporting, visit https://github.com/peteclarke-del/AcornFileForge.",
            "",
        )
    )
    return "\n".join(lines)


def write_download_readme(
    service: DiskService,
    session: ImageSession,
    image_path: Path,
    generated: datetime | None = None,
) -> Path:
    target = session.path.parent / "download-README.md"
    target.write_text(build_download_readme(service, session, image_path, generated), encoding="utf-8")
    return target
