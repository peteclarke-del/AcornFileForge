from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .checksum import sha256_path
from .dfs_compat import dfs_catalogue_files
from .mmb_layout import (
    ENTRY_SIZE as MMB_ENTRY_SIZE,
    HEADER_SIZE as MMB_HEADER_SIZE,
    MAX_SLOTS as MMB_MAX_SLOTS,
    SLOT_SIZE as MMB_SLOT_SIZE,
    entry_offset as mmb_entry_offset,
    slot_offset as mmb_slot_offset,
)

if TYPE_CHECKING:
    from .disk_service import DiskService, ImageSession


def timestamped_archive_name(image_name: str, generated: datetime | None = None) -> str:
    moment = generated or datetime.now().astimezone()
    stem = Path(image_name).stem or "acorn-image"
    return f"{stem}-{moment:%Y%m%d-%H%M%S}.zip"


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
            start = mmb_entry_offset(slot)
            entry = header[start : start + MMB_ENTRY_SIZE]
            status = entry[15] if len(entry) == MMB_ENTRY_SIZE else 0xFF
            title = entry[:12].decode("latin-1", "replace").rstrip("\0 ")
            if status >= 0x80:
                lines.extend((f"### Slot {slot:03d}: empty", "", f"Header status: `&{status:02X}`", ""))
                continue
            access = "read/write" if status > 0 else "read-only"
            image.seek(mmb_slot_offset(slot))
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
    if session.kind == "rom":
        lines = [
            "## ROM bank catalogue", "",
            "| Bank | Title | Bytes | Kind | Header | SHA-256 | CRC-32 |",
            "|---:|---|---:|---|---|---|---|",
        ]
        for row in service.list_rom_banks(session):
            header = row.get("header") or {}
            extension = row.get("extensionHeader") or {}
            if header:
                detail = (
                    f"type &{header.get('typeHex')} · {header.get('processor')} · "
                    f"version {header.get('version') or header.get('versionByte')}"
                )
            elif extension:
                detail = (
                    "ExtnROM0 · checksum "
                    + ("valid" if extension.get("checksumValid") else "INVALID")
                )
            else:
                detail = "not recognised"
            lines.append("| " + " | ".join((
                f"{row['bank']:03d}",
                _safe_cell(row["name"]),
                f"{row['length']:,}",
                _safe_cell(row["filetype"]),
                _safe_cell(detail),
                f"`{row['diagnostics']['sha256']}`",
                f"`{row['diagnostics']['crc32']}`",
            )) + " |")
        return [*lines, ""]
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

    if session.kind == "dfs":
        sides = [0, 2] if session.path.name.lower().endswith(".dsd") else [None]
        object_count = 0
        for side in sides:
            for row in service.list_dfs_catalogue_files(session, None, side):
                display_path = row["path"]
                if side is not None:
                    display_path = f"Side {side}: {display_path}"
                lines.append(_row_line(display_path, row))
                object_count += 1
        if object_count == 0:
            lines.append("| _(empty)_ | - | - | - | - | - |")
        return [*lines, ""]

    pending: list[tuple[str, int | None]] = [("$", None)]
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
    *,
    image_checksum: str | None = None,
    descriptor_checksum: str | None = None,
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
        f"- Image SHA-256: `{image_checksum or sha256_path(image_path)}`",
    ]
    profile = session.hardware_profile or {}
    if profile:
        lines.extend((
            f"- Workbench profile: {profile.get('name') or 'Custom'}",
            f"- Base machine: {profile.get('machine') or 'not specified'}",
            "- Hardware additions: " + (", ".join(profile.get("addons") or []) or "stock machine"),
            f"- Managed emulator: {profile.get('emulator') or 'automatic'}",
        ))
    if session.descriptor_path:
        lines.extend(
            (
                f"- Descriptor filename: `{session.descriptor_name}`",
                f"- Descriptor size: {session.descriptor_path.stat().st_size:,} bytes",
                f"- Descriptor SHA-256: `{descriptor_checksum or sha256_path(session.descriptor_path)}`",
            )
        )
    if session.hfe_original_path:
        lines.extend(
            (
                f"- HFE version: {session.hfe_version or 'unknown'}",
                f"- HFE write support: {'read-only' if session.hfe_read_only else 'editable and sector-verified'}",
            )
        )
    if session.kind == "rom":
        lines.extend((
            f"- ROM target family: {session.rom_platform}",
            f"- Logical bank size: {session.rom_bank_size:,} bytes",
            f"- Erased byte: `&{session.rom_erase_byte:02X}`",
            f"- Byte layout: {session.rom_layout}",
            "- Original component order: "
            + (", ".join(session.rom_component_names) or "single image or unspecified"),
            f"- Project hardware notes: {session.rom_project.get('hardware') or 'not recorded'}",
            f"- Saved project symbols: {len(session.rom_project.get('symbols', {}))}",
            f"- Saved emulator test results: {len(session.rom_project.get('tests', []))}",
        ))
    if session.kind == "romfs":
        details = service.romfs_details(session)
        lines.extend((
            f"- ROMFS title: {details['title']}",
            f"- Paged-ROM header title: {details['headerTitle']}",
            f"- ROM version byte: {details['version']}",
            f"- Copyright: {details['copyright']}",
            f"- Catalogue files: {details['fileCount']}",
            f"- Filesystem state: {'plain and editable' if not details['readOnly'] else 'composite or incomplete, read-only'}",
        ))
    lines.extend(
        (
            "",
            "## Using this archive",
            "",
            "Keep this README beside the image so its catalogue, target and checksums stay with it.",
            "Verify the SHA-256 value after copying or writing it to media. Work from a backup, then test the edited image in an emulator or on disposable media before replacing a known-good card or disk.",
            "Before using important media on hardware, reopen a copy in Acorn File Forge and run Analyse > Image health dashboard. For an installed MMB or ADFS menu, also run Analyse > Test menu entries and review every itemised failure.",
        )
    )
    if session.descriptor_path:
        lines.extend(
            (
                "",
                "The DAT and DSC are a matched BeebSCSI pair. Keep both files together in the `BeebSCSI0` directory and do not substitute a descriptor from another image.",
            )
        )
    if session.kind == "rom":
        lines.extend((
            "",
            "## ROM interpretation and maintenance",
            "",
            "ROM images contain raw bytes rather than a filing system. The bank catalogue is a view over the saved byte image in ascending order.",
            "BBC, Master and Electron sideways ROMs normally use 16 KiB banks, although 8 KiB devices and larger banked images exist. Test edited ROMs in an emulator or a spare programmable device before using valuable hardware.",
            "A bank title, role, processor and entry vectors are decoded from proven header structures. Printable strings and plausible RISC OS modules remain evidence rather than invented files or a guarantee of compatibility.",
            "The programmed-byte count means bytes that differ from the configured erased value. It is not filesystem free space. File offsets refer to the complete image; mapped addresses refer to the configured target CPU window.",
            "`ROM-project.json` contains notes, symbols, analysed regions and test results. It is workbench metadata and is not programmed into the ROM device.",
            "Use Tools > ROM Workbench to inspect the bank map and audit, disassemble 6502, ARM or 68000 code, follow reachable instructions and cross-references, compare revisions, build guarded patches and prepare physical chip files.",
            "Workbench comparison patches verify the complete source SHA-256 before applying ranges and the complete target SHA-256 afterwards. A mismatch aborts the operation.",
            "Programmer export does not rewrite the logical ROM. It applies padding or mirroring, optional adjacent-byte and 16-bit word swaps, address-line swaps, then one, two or four physical byte lanes to the programmer download.",
            "A service-ROM scaffold contains inert handlers until a developer supplies code. AFFROMFS is a documented data archive for companion service code and is not mounted by an unmodified MOS.",
            "Exact ROM identities are keyed by complete SHA-256. Different padding, a one-byte edit or a concatenated bank set is a different identity even when the visible title matches.",
        ))
    if session.kind == "romfs":
        lines.extend((
            "",
            "## Acorn ROMFS notes",
            "",
            "This is a standard Acorn data-ROM filesystem for 8-bit BBC, Master and Electron machines. Select it with `*ROM` on compatible filing-system software.",
            "ROMFS is flat. Filenames are case-sensitive and contain up to ten Latin-1 characters. Each file retains its load address, execution address and the ROMFS run-only flag.",
            "Every catalogue block and data block has a CRC. Acorn File Forge rebuilds those CRCs after a file or property change and validates them when the image is reopened.",
            "The run-only flag is ROMFS copy protection. It is not the same attribute as DFS or ADFS locking. A run-only file can be started with `*RUN` but not loaded as ordinary data through the filesystem.",
            "Plain, complete ROMFS images are editable. Composite images containing executable bytes after the catalogue, and incomplete fragments from multi-ROM sets, are opened read-only so absolute code addresses are not moved.",
        ))
    if session.kind == "mmb":
        from .menu_service import installed_mmb_menus

        menus = installed_mmb_menus(service, session)
        lines.extend(
            (
                "",
                "MMB slot numbering is zero-based. Slot access reflects the MMB catalogue flag, not protection inside individual DFS files.",
                "Installed menus may depend on exact disk titles, PAGE values and slot mappings. Preserve the menu slot and make a checkpoint before reorganising disks.",
                "At All disks, Analyse > Check for duplicate games compares installed titles as well as disk content. Removing a menu record does not eject its disk unless that separate choice is confirmed.",
                "Ejecting one or several disks with Slot > Eject selected disks also removes their associated records from a recognised editable Universal or SPI menu.",
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
            "Complete disk images keep file metadata inside their own catalogues, so they do not need an image-level .inf sidecar. Loose files exported from Acorn File Forge are packaged with a matching .inf file instead.",
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
    *,
    image_checksum: str | None = None,
    descriptor_checksum: str | None = None,
) -> Path:
    target = session.path.parent / "download-README.md"
    target.write_text(
        build_download_readme(
            service,
            session,
            image_path,
            generated,
            image_checksum=image_checksum,
            descriptor_checksum=descriptor_checksum,
        ),
        encoding="utf-8",
    )
    return target
