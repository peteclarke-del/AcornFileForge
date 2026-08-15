from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from .adfs_menu_discovery import discover_adfs_menu_paths, scan_adfs_menu_directories
from .dfs_compat import dfs_catalogue_files, infer_dfs_launch_page
from .errors import DiskError
from .metadata_lookup import (
    best_distribution_filename as best_distribution_filename,
    enrich_from_distribution_filename,
    enrich_if_ambiguous as enrich_if_ambiguous,
    lookup_online as lookup_online,
    parse_distribution_filename as parse_distribution_filename,
)
from .menu_records import (
    build_index as build_index,
    fit_menu_display_fields as fit_menu_display_fields,
    legacy_page_field_count as _legacy_page_field_count,
    menu_title_case as menu_title_case,
    normalise_mmb_record as _normalise_mmb_record,
    normalise_page as _normalise_page,
    normalise_record as _normalise_record,
    parse_menu_data as parse_menu_data,
    parse_mmb_menu_data as parse_mmb_menu_data,
    parse_spi_menu_data as parse_spi_menu_data,
    serialise_menu as serialise_menu,
    serialise_spi_menu as serialise_spi_menu,
)
from .mmb_layout import (
    SLOT_SIZE as MMB_SLOT_SIZE,
    entry_offset as mmb_entry_offset,
    slot_offset as mmb_slot_offset,
)
from .menu.mmb_discovery import (
    ACORN_USER_FILES,
    ELECTRON_MAGAZINE_FILES,
    MENU_FILES,
    MMC_DESKTOP_FILES,
    SPI_GAME_MENU_FILES,
    UNIVERSAL_4R_FILES,
    find_menu_slot,
    installed_mmb_menu,
    installed_mmb_menus,
    is_mmb_menu_backup_title,
    is_universal_menu,
    menu_type_from_ssd as _menu_type_from_ssd,
)

if TYPE_CHECKING:
    from .disk_service import DiskService, ImageSession


CONVENTIONAL_LAUNCHERS = (
    "!RUN",
    "!START",
    "!MENU",
    "SSDMENU",
    "DISKMENU",
    "MENU",
    "LOADER",
    "START",
    "GAME",
    "RUN",
    "GO",
    "BOOT",
)


def _number(value) -> int:
    if isinstance(value, int):
        return value
    raw = str(value or "0").strip()
    explicit_hex = raw.startswith("&") or raw.lower().startswith("0x")
    text = raw.removeprefix("&").removeprefix("0x").removeprefix("0X")
    try:
        return int(text, 16 if explicit_hex or re.search(r"[A-Fa-f]", text) else 10)
    except ValueError:
        return 0


def _clean_title(value: str) -> str:
    value = re.sub(r"[_-]+", " ", value or "")
    value = re.sub(r"\b(?:SIDE|DISC|DISK)\s*[012AB]?\b", "", value, flags=re.I)
    return re.sub(r"\s+", " ", value).strip().title()


def _exec_script(data: bytes) -> str | None:
    """Return an Acorn command file as text, or None when it looks binary."""
    if not data or b"\0" in data:
        return None
    text = data.decode("latin-1")
    meaningful = [character for character in text if character not in "\r\n\t\f"]
    if not meaningful:
        return None
    printable = sum(character.isprintable() for character in meaningful)
    return text if printable / len(meaningful) >= 0.9 else None


def _read_exec_script(
    service: DiskService,
    session: ImageSession,
    row: dict,
    *,
    path: str,
    slot: int | None,
) -> str | None:
    filename = str(row["name"])
    source_path = f"$.{filename}" if path == "$" else f"{path}.{filename}"
    try:
        return _exec_script(service.read_file(session, slot, source_path))
    except (KeyError, OSError, UnicodeError, RuntimeError):
        return None


def _detect_launcher(
    service: DiskService,
    session: ImageSession,
    entries: list[dict],
    *,
    path: str,
    slot: int | None,
) -> tuple[tuple[str, str] | None, dict | None, int, list[str], list[str]]:
    by_name = {str(row.get("name", "")).upper(): row for row in entries}
    evidence: list[str] = []
    warnings: list[str] = []
    chosen: tuple[str, str] | None = None
    launch_signals = 0

    ssdmenu_row = by_name.get("SSDMENU")
    if ssdmenu_row:
        chosen = ("CHAIN", str(ssdmenu_row["name"]))
        launch_signals = 1
        evidence.append(
            "Found SSDMENU; it takes priority over !BOOT and will be launched with *CHAIN"
        )

    boot_row = by_name.get("!BOOT")
    if chosen is None and boot_row:
        boot = _read_exec_script(service, session, boot_row, path=path, slot=slot)
        if boot is not None:
            chosen = ("EXEC", str(boot_row["name"]))
            launch_signals = 1
            evidence.append("Found a readable !BOOT command file; it will be launched with *EXEC")
            commands = [
                match.group(1).upper()
                for match in re.finditer(
                    r"(?im)(?:^|:)\s*(?:\*)?\s*(CH(?:AIN)?|RUN|EXEC|LOAD)\b",
                    boot,
                )
            ]
            if commands:
                evidence.append(
                    f"!BOOT contains {len(commands)} recognised launch command"
                    f"{'' if len(commands) == 1 else 's'}"
                )
        else:
            warnings.append("The !BOOT file is empty, unreadable, or appears to be binary, so it cannot be used with *EXEC.")

    if chosen is None:
        conventional_rows = [
            by_name[name]
            for name in CONVENTIONAL_LAUNCHERS
            if name in by_name
        ]
        if not conventional_rows:
            conventional_rows = sorted(
                (
                    row
                    for row in entries
                    if str(row.get("name", "")).upper() not in MENU_FILES
                    and re.fullmatch(
                        r"!?[A-Z0-9_-]*MENU[A-Z0-9_-]*",
                        str(row.get("name", "")),
                        re.I,
                    )
                ),
                key=lambda row: (
                    len(str(row.get("name", ""))),
                    str(row.get("name", "")).casefold(),
                ),
            )
        if conventional_rows:
            conventional = conventional_rows[0]
            script = _read_exec_script(
                service,
                session,
                conventional,
                path=path,
                slot=slot,
            )
            if script is not None:
                chosen = ("EXEC", str(conventional["name"]))
                evidence.append(
                    f"Examined {conventional['name']} and found a readable "
                    "command file; it will be launched with *EXEC"
                )
            else:
                action = "CHAIN" if _number(conventional.get("load")) & 0xFFFF == 0x1900 else "RUN"
                chosen = (action, str(conventional["name"]))
                evidence.append(
                    f"Examined conventional launcher {conventional['name']}; "
                    f"its metadata indicates *{action}"
                )
            launch_signals = 1
            if len(conventional_rows) > 1:
                warnings.append(
                    f"Several conventional launchers were found; "
                    f"{conventional['name']} was selected by launcher priority."
                )

    if chosen is None:
        basic = [
            row
            for row in entries
            if _number(row.get("load")) & 0xFFFF == 0x1900
            and str(row.get("name", "")).upper() not in MENU_FILES
        ]
        if len(basic) == 1:
            chosen = ("CHAIN", str(basic[0]["name"]))
            launch_signals = 1
            evidence.append("Found one BBC BASIC program at &1900")
        elif not entries:
            warnings.append("The disk is empty.")
        else:
            warnings.append("No single launch program could be identified.")
    row = by_name.get(chosen[1].upper()) if chosen else None
    return chosen, row, launch_signals, evidence, warnings


def analyse_disk(service: DiskService, session: ImageSession, slot: int) -> dict:
    slots = service.list_slots(session)
    listing = service.list_directory(session, "$", slot)
    entries = [
        row
        for row in listing["entries"]
        if row.get("type") not in {"dir", "directory"}
    ]
    disk_title = slots[slot]["name"]
    chosen, row, launch_signal_count, evidence, warnings = _detect_launcher(
        service,
        session,
        entries,
        path="$",
        slot=slot,
    )
    filename = chosen[1] if chosen else ""
    action_map = {"CH": "", "CHAIN": "", "RUN": "R", "EXEC": "E", "LOAD": "L"}
    action = action_map.get(chosen[0], "") if chosen else ""
    load = _number(row.get("load")) if row else 0
    page = f"{load & 0xFFFF:X}" if load else "1900"
    slot_path = getattr(service, "_slot_path", None)
    if chosen and callable(slot_path):
        try:
            inferred_page, page_evidence = infer_dfs_launch_page(
                slot_path(session, slot).read_bytes(),
                filename,
                action,
            )
            if inferred_page:
                page = inferred_page
                evidence.append(f"PAGE inferred from launch path: {page_evidence}")
        except (OSError, RuntimeError):
            pass
    title = _clean_title(disk_title)
    generic_title = not title or bool(re.fullmatch(r"(?:DIS[CK]|UNTITLED)\s*\d*", title, re.I))
    confidence = 0
    if title and not generic_title:
        confidence += 25
    if chosen:
        confidence += 45
    if launch_signal_count == 1:
        confidence += 20
    if row:
        confidence += 10
    duplicate_title = sum(
        1 for item in slots
        if item["formatted"] and item["name"].casefold() == disk_title.casefold()
    ) > 1
    if duplicate_title:
        warnings.append("This MMB disk title is not unique; *DIN may select the wrong image.")
    launch_obvious = bool(filename and launch_signal_count == 1)
    ambiguous = confidence < 75 or not filename or generic_title or duplicate_title
    metadata = {
        "title": title,
        "publisher": "",
        "filename": filename[:7],
        "action": action,
        "page": page,
        "diskTitle": disk_title[:12],
        "system": "M",
        "slot": slot,
        "confidence": confidence,
        "ambiguous": ambiguous,
        "launchObvious": launch_obvious,
        "evidence": evidence,
        "warnings": warnings,
        "sources": [],
        "matches": [],
        "launchCandidates": [
            {"name": str(row["name"]), "path": "$"}
            for row in entries
        ],
    }
    source_name = getattr(session, "slot_source_names", {}).get(slot)
    if source_name:
        enrich_from_distribution_filename(metadata, source_name)
    return metadata


def analyse_copied_dfs_items(
    service: DiskService,
    session: ImageSession,
    slot: int,
    items: list[dict],
) -> dict:
    """Analyse files already read during a bulk copy without reopening the slot."""

    class CopiedCatalogueView:
        def __init__(self) -> None:
            self.entries: list[dict] = []
            self.files: dict[str, bytes] = {}
            self.slots = service.list_slots(session)
            for item in items:
                name = str(
                    item.get("sourceName")
                    or str(item.get("dst", "")).rsplit(".", 1)[-1]
                )
                self.entries.append(
                    {
                        "name": name,
                        "type": "file",
                        "load": int(item.get("load") or 0),
                        "exec": int(item.get("exec") or 0),
                        "length": len(item.get("data") or b""),
                    }
                )
                self.files[f"$.{name}".casefold()] = bytes(item.get("data") or b"")

        def list_directory(
            self,
            _session: ImageSession,
            _path: str,
            _slot: int,
        ) -> dict:
            return {"entries": self.entries}

        def read_file(
            self,
            _session: ImageSession,
            _slot: int,
            path: str,
        ) -> bytes:
            return self.files[path.casefold()]

        def list_slots(self, _session: ImageSession) -> list[dict]:
            return self.slots

    return analyse_disk(CopiedCatalogueView(), session, slot)


def analyse_adfs_directory(service: DiskService, session: ImageSession, path: str) -> dict:
    listing = service.list_directory(session, path, None)
    entries = [
        row
        for row in listing["entries"]
        if row.get("type") not in {"dir", "directory"}
    ]
    chosen, row, launch_signal_count, evidence, warnings = _detect_launcher(
        service,
        session,
        entries,
        path=path,
        slot=None,
    )
    filename = chosen[1] if chosen else ""
    action = {"CH": "", "CHAIN": "", "RUN": "R", "EXEC": "E", "LOAD": "L"}.get(chosen[0], "") if chosen else ""
    load = _number(row.get("load")) if row else 0
    title = _clean_title(
        str(listing.get("directoryTitle") or path.rsplit(".", 1)[-1])
    )
    confidence = (25 if title else 0) + (45 if chosen else 0) + (20 if launch_signal_count == 1 else 0) + (10 if row else 0)
    launch_obvious = bool(filename and launch_signal_count == 1)
    candidates = [
        {
            "name": str(item["name"]),
            "path": path,
            "page": f"{_number(item.get('load')) & 0xFFFF:X}" if _number(item.get("load")) else None,
        }
        for item in entries
    ]
    for directory in (
        item for item in listing["entries"]
        if item.get("type") in {"dir", "directory"}
    ):
        child_path = f"{path}.{directory['name']}"
        try:
            child_entries = service.list_directory(session, child_path, None)["entries"]
        except RuntimeError:
            continue
        candidates.extend(
            {
                "name": str(item["name"]),
                "path": child_path,
                "page": f"{_number(item.get('load')) & 0xFFFF:X}" if _number(item.get("load")) else None,
            }
            for item in child_entries
            if item.get("type") not in {"dir", "directory"}
        )
    metadata = {
        "title": title,
        "publisher": "",
        "filename": filename[:10],
        "action": action,
        "page": f"{load & 0xFFFF:X}" if load else "1900",
        "diskTitle": path,
        "system": "H",
        "path": path,
        "confidence": confidence,
        "ambiguous": confidence < 75 or not filename,
        "launchObvious": launch_obvious,
        "evidence": evidence,
        "warnings": warnings,
        "sources": [],
        "matches": [],
        "launchCandidates": candidates,
    }
    source_name = getattr(session, "adfs_source_names", {}).get(path)
    if source_name:
        enrich_from_distribution_filename(metadata, source_name)
    return metadata


def _put_bytes(
    service: DiskService,
    session: ImageSession,
    slot: int | None,
    destination: str,
    content: bytes,
    load: str | int = "0",
    execute: str | int = "0",
) -> None:
    with tempfile.NamedTemporaryFile(
        dir=service.work_dir,
        prefix="menu-",
        delete=False,
    ) as temporary:
        temporary.write(content)
        path = Path(temporary.name)
    try:
        service.put(
            session,
            slot,
            destination,
            path,
            str(load),
            str(execute),
            None,
        )
    finally:
        path.unlink(missing_ok=True)


def _write_databases(
    service: DiskService,
    session: ImageSession,
    entries: list[dict],
    system: str,
    *,
    slot: int | None = None,
    root: str = "$",
    preserve_game_order: bool = False,
) -> None:
    launcher_path = "$.UNIMENU" if slot is not None else _adfs_child(root, "UNIMENU")
    launcher_update: bytes | None = None
    preserve_first_action = False
    is_upgradeable_universal = (
        session.kind == "adfs" and system == "H"
    ) or (
        session.kind == "mmb" and session.menu_type == "universal"
    )
    if is_upgradeable_universal:
        try:
            launcher = service.read_file(session, slot, launcher_path)
            patched_launcher, preserve_first_action = _upgrade_universal_launcher_program(launcher)
            if patched_launcher != launcher:
                launcher_update = patched_launcher
        except (OSError, RuntimeError):
            preserve_first_action = False

    if session.kind == "mmb" and session.menu_type == "spi-game-menu":
        game_data, game_index = serialise_spi_menu(entries)
        pub_data, pub_index = serialise_spi_menu(entries, publisher_view=True)
        databases = (
            ("GAMDATA", game_data),
            ("GAMINDX", game_index),
            ("PUBDATA", pub_data),
            ("PUBINDX", pub_index),
        )
    else:
        databases = _database_contents(
            entries,
            system,
            preserve_game_order=preserve_game_order,
            preserve_first_action=preserve_first_action,
        )
    if session.kind == "mmb" and session.menu_type == "universal-4r":
        rename = {
            "GAMDATA": "EGAMDAT",
            "GAMINDX": "EGAMIDX",
            "PUBDATA": "EPUBDAT",
            "PUBINDX": "EPUBIDX",
        }
        databases = tuple((rename[name], content) for name, content in databases)
    try:
        from oaknut.disc.mount import resolve_mount
    except ImportError:
        if launcher_update is not None:
            _put_bytes(service, session, slot, launcher_path, launcher_update)
        for name, content in databases:
            destination = f"$.{name}" if slot is not None else f"{root}.{name}"
            _put_bytes(service, session, slot, destination, content)
        if system == "H":
            _put_bytes(
                service,
                session,
                None,
                _adfs_child(root, "!BOOT"),
                _adfs_boot_content(root),
            )
        return

    def write_to_mount(mount) -> None:
        if launcher_update is not None:
            mount.write_bytes(launcher_path, launcher_update)
        for name, content in databases:
            destination = f"$.{name}" if slot is not None else f"{root}.{name}"
            mount.write_bytes(destination, content)
        if system == "H":
            mount.write_bytes(
                _adfs_child(root, "!BOOT"),
                _adfs_boot_content(root),
            )

    disk_path = service.resolve(session, slot)
    if session.kind == "adfs" and slot is None:
        with service.adfs_mount(session) as mount:
            write_to_mount(mount)
    else:
        with session.lock, resolve_mount(f"{disk_path}:$", writable=True) as resolved:
            write_to_mount(resolved.mount)
    if session.kind == "mmb":
        if slot is None:
            raise DiskError("An MMB menu operation requires a target slot.")
        service._sync_slot(session, slot)
    else:
        session.dirty = True


def _database_contents(
    entries: list[dict],
    system: str,
    *,
    preserve_game_order: bool = False,
    preserve_first_action: bool = False,
) -> tuple[tuple[str, bytes], ...]:
    game_data, game_index = serialise_menu(
        entries,
        system=system,
        preserve_order=preserve_game_order,
        preserve_first_action=preserve_first_action,
    )
    pub_data, pub_index = serialise_menu(
        entries,
        publisher_view=True,
        system=system,
        preserve_first_action=preserve_first_action,
    )
    databases = (
        ("GAMDATA", game_data),
        ("GAMINDX", game_index),
        ("PUBDATA", pub_data),
        ("PUBINDX", pub_index),
    )
    return databases


def _replace_tokenised_basic_lines(program: bytes, replacements: dict[int, bytes]) -> bytes | None:
    """Replace complete BBC BASIC line bodies while rebuilding record lengths."""
    rebuilt = bytearray()
    seen: set[int] = set()
    position = 0
    while position + 2 <= len(program) and program[position] == 0x0D:
        if program[position + 1] == 0xFF:
            rebuilt.extend(program[position:])
            return bytes(rebuilt) if set(replacements).issubset(seen) else None
        if position + 4 > len(program):
            return None
        length = program[position + 3]
        if length < 4 or position + length > len(program):
            return None
        number = int.from_bytes(program[position + 1 : position + 3], "big")
        body = replacements.get(number, program[position + 4 : position + length])
        new_length = len(body) + 4
        if new_length > 255:
            return None
        rebuilt.extend(program[position : position + 3])
        rebuilt.append(new_length)
        rebuilt.extend(body)
        if number in replacements:
            seen.add(number)
        position += length
    return None


def _upgrade_universal_launcher_program(program: bytes) -> tuple[bytes, bool]:
    """Apply compatible launch-record and vertically-centred list upgrades."""
    old_action_lines = {
        105: b"fld$(5)=fld$(1)",
        2005: b'G$=\xa4luv:\xf2field:E%=\xa42pge:\xe7\xa7"DBMH",fld$(1))>0\x8cfld$(1)=""',
    }
    new_action_lines = {
        105: b"fld$(5)=\xc0fld$(1),1)",
        2005: (
            b'G$=\xa4luv:\xf2field:E%=\xa42pge:\xe7\xa7"DBMH",'
            b"\xc0fld$(1),1))>0\x8cfld$(1)=\xc1fld$(1),2)"
        ),
    }
    old_list_line = b"\xdd\xf2scn:\xe7S%=\xa3 \x8c\xdb"
    new_list_line = old_list_line + b":\xf1"
    bodies: dict[int, bytes] = {}
    position = 0
    while position + 4 <= len(program) and program[position] == 0x0D:
        if program[position + 1] == 0xFF:
            break
        length = program[position + 3]
        if length < 4 or position + length > len(program):
            return program, False
        number = int.from_bytes(program[position + 1 : position + 3], "big")
        if number in {*old_action_lines, 1100}:
            bodies[number] = program[position + 4 : position + length]
        position += length
    replacements: dict[int, bytes] = {}
    for number, old_body in old_action_lines.items():
        body = bodies.get(number)
        if body == old_body:
            replacements[number] = new_action_lines[number]
        elif body != new_action_lines[number]:
            return program, False
    list_body = bodies.get(1100)
    if list_body == old_list_line:
        replacements[1100] = new_list_line
    elif list_body not in {None, new_list_line}:
        return program, False
    if not replacements:
        return program, True
    patched = _replace_tokenised_basic_lines(program, replacements)
    return (patched, True) if patched is not None else (program, False)


def _adfs_boot_content(root: str) -> bytes:
    """Start the menu with its directory as CSD for relative database opens."""
    return f'DIR {root}\rCH."UNIMENU"\r'.encode("latin-1")


def _template_slot_path(service: DiskService, template_dir: Path) -> Path:
    template = template_dir / "universal.ssd"
    if not template.is_file():
        raise DiskError("No Universal Menu template is available.")
    if template.stat().st_size != MMB_SLOT_SIZE:
        raise DiskError("The Universal Menu template is truncated.")
    return template


def create_adfs_menu(
    service: DiskService,
    session: ImageSession,
    root: str,
    entries: list[dict],
    template_dir: Path,
) -> dict:
    if session.kind != "adfs":
        raise DiskError("An ADFS menu can only be created in an ADFS image.")
    if not entries:
        raise DiskError("No child directories were supplied for the menu.")
    template = _template_slot_path(service, template_dir)
    try:
        from oaknut.disc.cli import _file_item, _write_copy_item
        from oaknut.disc.mount import resolve_mount
    except ImportError as exc:
        raise DiskError("The Oaknut menu-copy API is unavailable.") from exc

    support_files = ("UNIMENU", "SHOW", "TXT2SCN", "UNIREAD")
    with resolve_mount(f"{template}:$") as source_resolved:
        with service.adfs_mount(session) as target_mount:
            for name in support_files:
                source_path = f"$.{name}"
                destination = f"{root}.{name}"
                if target_mount.exists(destination):
                    target_mount.remove(destination, force=True)
                item = _file_item(
                    source_resolved.mount,
                    source_path,
                    destination,
                )
                service._write_adfs_copy_item(
                    target_mount,
                    destination,
                    item,
                    _write_copy_item,
                )
            boot_path = f"{root}.!BOOT"
            if target_mount.exists(boot_path):
                target_mount.remove(boot_path, force=True)
            service._write_adfs_copy_item(
                target_mount,
                boot_path,
                {
                    "data": _adfs_boot_content(root),
                    "load": 0,
                    "exec": 0,
                    "access": 3,
                    "filetype": None,
                    "datestamp": None,
                },
                _write_copy_item,
            )
    session.dirty = True
    records = [_normalise_record(item, "H") for item in entries]
    _write_databases(service, session, records, "H", root=root)
    cached_roots = getattr(session, "adfs_menu_roots", None)
    if cached_roots is not None and root not in cached_roots:
        cached_roots.append(root)
    return {"root": root, "entries": len(records)}


def has_adfs_menu(service: DiskService, session: ImageSession, root: str) -> bool:
    try:
        names = {str(row["name"]).upper() for row in service.list_directory(session, root, None)["entries"]}
        return MENU_FILES.issubset(names)
    except Exception:
        return False


def _adfs_child(root: str, name: str) -> str:
    return f"$.{name}" if root == "$" else f"{root}.{name}"


def _adfs_ancestors(path: str) -> list[str]:
    parts = str(path).split(".")
    return [".".join(parts[:length]) for length in range(1, len(parts) + 1)]


def _rewrite_adfs_path(path: str, moves: list[dict]) -> str:
    rewritten = str(path)
    for move in sorted(
        (item for item in moves if item["isDirectory"]),
        key=lambda item: len(item["source"]),
        reverse=True,
    ):
        source = move["source"]
        if rewritten.casefold() == source.casefold():
            return move["destination"]
        if rewritten.casefold().startswith(f"{source}.".casefold()):
            return move["destination"] + rewritten[len(source) :]
    return rewritten


def _scan_adfs_menu_roots(mount) -> list[str]:
    roots: list[str] = []
    pending = ["$"]
    while pending:
        root = pending.pop()
        entries = list(mount.iter_entries(root))
        names = {str(entry.name).upper() for entry in entries}
        if MENU_FILES.issubset(names):
            roots.append(root)
        pending.extend(
            _adfs_child(root, str(entry.name))
            for entry in entries
            if entry.is_dir
        )
    return sorted(roots, key=lambda value: (value.count("."), value.casefold()))


def installed_adfs_menus(service: DiskService, session: ImageSession) -> list[dict]:
    """Return every installed ADFS menu and its parsed records in one mount."""
    if session.kind != "adfs":
        return []
    with service.adfs_mount(session) as mount:
        roots = _scan_adfs_menu_roots(mount)
        session.adfs_menu_roots = roots
        return [
            {
                "root": root,
                "type": "adfs-universal",
                "entries": parse_menu_data(
                    mount.read_bytes(_adfs_child(root, "GAMDATA"))
                ),
            }
            for root in roots
        ]


def test_installed_adfs_menu_entries(
    service: DiskService,
    session: ImageSession,
    root: str | None = None,
    progress=None,
) -> tuple[list[str], list[dict]]:
    """Test every ADFS menu launcher through one reusable read-only mount."""
    if session.kind != "adfs":
        return [], []
    tests: list[dict] = []
    with service.adfs_mount(session) as mount:
        view = _MountedAdfsView(mount)
        if root is None:
            roots = _scan_adfs_menu_roots(mount)
            session.adfs_menu_roots = roots
        else:
            candidate = str(root or "$")
            names = {
                str(entry.name).upper()
                for entry in mount.iter_entries(candidate)
            }
            roots = [candidate] if MENU_FILES.issubset(names) else []
        for root in roots:
            entries = parse_menu_data(view.read_file(session, None, _adfs_child(root, "GAMDATA")))
            for offset, entry in enumerate(entries):
                if progress and offset % 20 == 0:
                    progress(
                        f"Testing {root} menu entry {offset + 1} of {len(entries)}",
                        offset,
                        len(entries),
                    )
                problems: list[str] = []
                directory = str(entry.get("diskTitle") or root)
                launcher = str(entry.get("filename") or "")
                try:
                    page, evidence, applicable = _adfs_launch_page(
                        view, session, directory, launcher,
                        str(entry.get("action") or ""),
                    )
                except Exception as exc:
                    page, evidence, applicable = None, str(exc), True
                if page and _normalise_page(entry.get("page")) != _normalise_page(page):
                    problems.append(f"PAGE should be &{page}")
                if applicable and page is None:
                    problems.append("Launcher PAGE could not be proved")
                tests.append({
                    "index": offset,
                    "menuRoot": root,
                    "title": entry.get("title", ""),
                    "diskTitle": directory,
                    "launcher": launcher,
                    "action": entry.get("action", ""),
                    "page": entry.get("page", ""),
                    "passed": not problems,
                    "problems": problems,
                    "evidence": evidence,
                })
    return roots, tests


def _installed_adfs_menus(
    mount,
    session: ImageSession,
    paths: list[str],
) -> list[dict]:
    cached_roots = getattr(session, "adfs_menu_roots", None)
    if cached_roots is None:
        cached_roots = _scan_adfs_menu_roots(mount)
        session.adfs_menu_roots = cached_roots
    candidate_roots = {
        ancestor
        for path in paths
        for ancestor in _adfs_ancestors(path)
    }
    candidate_roots.update(cached_roots)
    menus = []
    for root in sorted(candidate_roots, key=len):
        if not all(
            mount.exists(_adfs_child(root, name))
            for name in MENU_FILES
        ):
            continue
        menus.append(
            {
                "root": root,
                "entries": parse_menu_data(
                    mount.read_bytes(_adfs_child(root, "GAMDATA"))
                ),
            }
        )
    return menus


def _write_adfs_menu_records(mount, root: str, entries: list[dict]) -> None:
    for name, content in _database_contents(
        entries,
        "H",
        preserve_game_order=True,
    ):
        mount.write_bytes(_adfs_child(root, name), content)
    mount.write_bytes(_adfs_child(root, "!BOOT"), _adfs_boot_content(root))


def _rewrite_adfs_menu_records(entries: list[dict], moves: list[dict]) -> int:
    changed = 0
    for record in entries:
        old_directory = str(record["diskTitle"])
        new_directory = _rewrite_adfs_path(old_directory, moves)
        old_filename = str(record["filename"])
        new_filename = old_filename
        launch_path = _adfs_child(old_directory, old_filename)
        for move in moves:
            if move["isDirectory"]:
                continue
            if launch_path.casefold() == move["source"].casefold():
                new_directory = move["destination"].rsplit(".", 1)[0]
                new_filename = move["destination"].rsplit(".", 1)[-1]
                break
        if (
            new_directory.casefold() != old_directory.casefold()
            or new_filename.casefold() != old_filename.casefold()
        ):
            record["diskTitle"] = new_directory
            record["filename"] = new_filename
            changed += 1
    return changed


def move_adfs_items(
    service: DiskService,
    session: ImageSession,
    items: list[dict],
) -> dict:
    """Move ADFS objects and rewrite relevant installed-menu launch paths."""
    if session.kind != "adfs":
        raise DiskError("Same-image drag moves are available for ADFS images.")
    if not items:
        raise DiskError("Choose at least one file or directory to move.")
    service.require_writable_geometry(session)
    def normalise(value: object) -> str:
        path = str(value or "").strip().rstrip(".")
        if path != "$" and not path.startswith("$."):
            raise DiskError("ADFS moves require a full path beginning with $.")
        if path == "$":
            raise DiskError("The ADFS root directory cannot be moved.")
        return path

    with service.adfs_mount(session) as mount:
        moves: list[dict] = []
        destinations: set[str] = set()
        for raw in items:
            source = normalise(raw.get("source"))
            destination = normalise(raw.get("destination"))
            service.validate_leaf_name(
                session,
                destination.rsplit(".", 1)[-1],
            )
            if source.casefold() == destination.casefold():
                continue
            if not mount.exists(source):
                raise DiskError(f"Source path “{source}” no longer exists.")
            entry = mount.stat(source)
            if entry.is_dir and destination.casefold().startswith(
                f"{source}.".casefold()
            ):
                raise DiskError("A directory cannot be moved inside itself.")
            destination_key = destination.casefold()
            if destination_key in destinations:
                raise DiskError(f"More than one item would become “{destination}”.")
            destinations.add(destination_key)
            if mount.exists(destination):
                raise DiskError(
                    f"“{destination}” already exists. Choose another destination."
                )
            parent = destination.rsplit(".", 1)[0]
            if not mount.exists(parent) or not mount.stat(parent).is_dir:
                raise DiskError(f"Destination directory “{parent}” does not exist.")
            moves.append(
                {
                    "source": source,
                    "destination": destination,
                    "isDirectory": bool(entry.is_dir),
                }
            )
        if not moves:
            return {"moved": [], "menuEntriesUpdated": 0, "menuRoots": []}

        menus = _installed_adfs_menus(
            mount,
            session,
            [move["source"] for move in moves],
        )

        for move in moves:
            mount.rename(move["source"], move["destination"])

        menu_entries_updated = 0
        updated_roots: list[str] = []
        for menu in menus:
            changed = _rewrite_adfs_menu_records(menu["entries"], moves)
            if not changed:
                continue
            new_root = _rewrite_adfs_path(menu["root"], moves)
            _write_adfs_menu_records(mount, new_root, menu["entries"])
            updated_roots.append(new_root)
            menu_entries_updated += changed
        session.adfs_menu_roots = [
            _rewrite_adfs_path(root, moves)
            for root in (session.adfs_menu_roots or [])
        ]
        session.adfs_source_names = {
            _rewrite_adfs_path(path, moves): source_name
            for path, source_name in session.adfs_source_names.items()
        }

    session.dirty = True
    service.move_editor_projects(session, moves, None, None)
    service._persist_session(session)
    return {
        "moved": moves,
        "menuEntriesUpdated": menu_entries_updated,
        "menuRoots": updated_roots,
    }


def delete_adfs_items(
    service: DiskService,
    session: ImageSession,
    paths: list[str],
) -> dict:
    """Delete ADFS objects and rewrite affected installed menus once."""
    if session.kind != "adfs":
        raise DiskError("This deletion helper requires an ADFS image.")
    service.require_writable_geometry(session)
    sources = list(dict.fromkeys(str(path or "").strip().rstrip(".") for path in paths))
    if not sources:
        raise DiskError("Choose at least one ADFS file or directory to delete.")
    if any(source == "$" or not source.startswith("$.") for source in sources):
        raise DiskError("Choose ADFS files or directories below $.")
    try:
        from oaknut.disc.cli import _walk_post_order_mount
    except ImportError as exc:
        raise DiskError("The Oaknut ADFS delete API is unavailable.") from exc

    with service.adfs_mount(session) as mount:
        deleted_items = []
        for source in sources:
            if not mount.exists(source):
                raise DiskError(f"“{source}” no longer exists.")
            deleted_items.append(
                {"path": source, "isDirectory": bool(mount.stat(source).is_dir)}
            )

        # A selected directory already includes anything selected below it. Removing
        # descendants from the work list avoids a misleading second "not found".
        directories = [
            item["path"] for item in deleted_items if item["isDirectory"]
        ]
        deleted_items = [
            item
            for item in deleted_items
            if not any(
                item["path"].casefold().startswith(f"{directory}.".casefold())
                for directory in directories
                if item["path"].casefold() != directory.casefold()
            )
        ]
        menus = _installed_adfs_menus(
            mount,
            session,
            [item["path"] for item in deleted_items],
        )
        removed = 0
        rewritten: list[tuple[str, list[dict]]] = []
        for menu in menus:
            retained = []
            for record in menu["entries"]:
                directory = str(record["diskTitle"])
                points_to_deleted_item = any(
                    (
                        item["isDirectory"]
                        and (
                            directory.casefold() == item["path"].casefold()
                            or directory.casefold().startswith(
                                f"{item['path']}.".casefold()
                            )
                        )
                    )
                    or (
                        not item["isDirectory"]
                        and directory.casefold()
                        == item["path"].rsplit(".", 1)[0].casefold()
                        and str(record["filename"]).casefold()
                        == item["path"].rsplit(".", 1)[-1].casefold()
                    )
                    for item in deleted_items
                )
                if points_to_deleted_item:
                    removed += 1
                else:
                    retained.append(record)
            if len(retained) != len(menu["entries"]):
                rewritten.append((menu["root"], retained))

        for item in deleted_items:
            if item["isDirectory"]:
                for target in _walk_post_order_mount(mount, item["path"]):
                    mount.remove(target, force=True)
            else:
                mount.remove(item["path"], force=True)

        def path_was_deleted(path: str) -> bool:
            return any(
                path.casefold() == item["path"].casefold()
                or (
                    item["isDirectory"]
                    and path.casefold().startswith(f"{item['path']}.".casefold())
                )
                for item in deleted_items
            )

        for root, entries in rewritten:
            if path_was_deleted(root):
                continue
            _write_adfs_menu_records(mount, root, entries)
        session.adfs_menu_roots = [
            root
            for root in (session.adfs_menu_roots or [])
            if not path_was_deleted(root)
        ]
        session.adfs_source_names = {
            path: source_name
            for path, source_name in session.adfs_source_names.items()
            if not path_was_deleted(path)
        }

    session.dirty = True
    service.delete_editor_projects(
        session,
        [item["path"] for item in deleted_items],
        None,
        None,
    )
    service._persist_session(session)
    result = {
        "deletedItems": deleted_items,
        "menuEntriesRemoved": removed,
    }
    if len(deleted_items) == 1:
        result.update(
            deletedPath=deleted_items[0]["path"],
            deletedDirectory=deleted_items[0]["isDirectory"],
        )
    return result


def _append_replacing_identity(entries: list[dict], record: dict) -> list[dict]:
    """Append a menu record after replacing the same disk-title/title pair."""
    identity = (record["diskTitle"].casefold(), record["title"].casefold())
    return [
        item
        for item in entries
        if (item["diskTitle"].casefold(), item["title"].casefold()) != identity
    ] + [record]


def append_adfs_menu_entry(
    service: DiskService,
    session: ImageSession,
    root: str,
    metadata: dict,
    template_dir: Path,
) -> dict:
    record = _normalise_record(metadata, "H")
    if not has_adfs_menu(service, session, root):
        return create_adfs_menu(service, session, root, [record], template_dir)
    entries = parse_menu_data(service.read_file(session, None, f"{root}.GAMDATA"))
    entries = _append_replacing_identity(entries, record)
    _write_databases(
        service,
        session,
        entries,
        "H",
        root=root,
        preserve_game_order=True,
    )
    return {"root": root, "entries": len(entries)}


def append_adfs_menu_entries(
    service: DiskService,
    session: ImageSession,
    root: str,
    metadata_items: list[dict],
    template_dir: Path,
) -> dict:
    """Append or replace many ADFS menu records with one database rewrite."""
    records = [_normalise_record(metadata, "H") for metadata in metadata_items]
    if not records:
        raise DiskError("No ADFS menu entries were supplied.")
    if not has_adfs_menu(service, session, root):
        return create_adfs_menu(service, session, root, records, template_dir)
    entries = parse_menu_data(service.read_file(session, None, f"{root}.GAMDATA"))
    replaced_entries = {
        (
            record["diskTitle"].casefold(),
            record["title"].casefold(),
        )
        for record in records
    }
    entries = [
        item
        for item in entries
        if (
            item["diskTitle"].casefold(),
            item["title"].casefold(),
        ) not in replaced_entries
    ]
    entries.extend(records)
    _write_databases(
        service,
        session,
        entries,
        "H",
        root=root,
        preserve_game_order=True,
    )
    return {"root": root, "entries": len(entries)}


def _menu_record_identity(record: dict) -> tuple[str, ...]:
    return tuple(
        str(record.get(field, "")).casefold()
        for field in (
            "diskTitle",
            "title",
            "publisher",
            "filename",
            "action",
            "page",
        )
    )


def reorder_adfs_menu(
    service: DiskService,
    session: ImageSession,
    root: str,
    ordered_entries: list[object],
) -> dict:
    """Rewrite an installed ADFS menu in an explicit title-view order."""
    if session.kind != "adfs":
        raise DiskError("Directory-menu ordering is only available for ADFS images.")
    if not has_adfs_menu(service, session, root):
        raise DiskError(f"No installed ADFS menu was found in {root}.")

    entries = parse_menu_data(service.read_file(session, None, f"{root}.GAMDATA"))
    by_identity: dict[tuple[str, ...], dict] = {}
    for entry in entries:
        key = _menu_record_identity(entry)
        if key in by_identity:
            raise DiskError("The installed menu contains an identical duplicate entry.")
        by_identity[key] = entry

    requested = [
        (
            _menu_record_identity(item)
            if isinstance(item, dict)
            else (str(item).casefold(),)
        )
        for item in ordered_entries
    ]
    if requested and len(requested[0]) == 1:
        if len({str(entry["diskTitle"]).casefold() for entry in entries}) != len(entries):
            raise DiskError(
                "This menu has several titles in one directory. Refresh its "
                "preview before saving the order."
            )
        by_identity = {
            (str(entry["diskTitle"]).casefold(),): entry
            for entry in entries
        }
    if len(requested) != len(set(requested)):
        raise DiskError("The requested menu order contains a duplicate entry.")
    if set(requested) != set(by_identity):
        raise DiskError(
            "The menu changed while its preview was open. Refresh the preview and try again."
        )

    reordered = [by_identity[identity] for identity in requested]
    _write_databases(
        service,
        session,
        reordered,
        "H",
        root=root,
        preserve_game_order=True,
    )
    return {"root": root, "entries": len(reordered)}


def _adfs_launch_page(
    service: DiskService,
    session: ImageSession,
    directory: str,
    filename: str,
    action: str,
) -> tuple[str | None, str, bool]:
    """Return (PAGE, evidence, applicable) for one installed ADFS record."""
    entries = service.list_directory(session, directory, None)["entries"]
    launch = next(
        (
            item for item in entries
            if item.get("type") not in {"dir", "directory"}
            and str(item.get("name", "")).casefold() == filename.casefold()
        ),
        None,
    )
    if launch is None:
        return None, f"launch file {directory}.{filename} is absent", True
    action = action.upper()
    if action not in {"", "E"}:
        return None, f"{action or 'CHAIN'} does not use BASIC PAGE", False
    launch_path = _adfs_child(directory, str(launch["name"]))
    load = _number(launch.get("load")) & 0xFFFF
    if action == "":
        if load:
            return f"{load:X}", f"{launch_path} is saved at &{load:X}", True
        return None, f"{launch_path} has no usable saved load address", True

    data = service.read_file(session, None, launch_path)
    text = data.decode("latin-1", "replace")
    explicit = re.search(r"(?i)\bPA(?:GE|\.)?\s*=\s*&([0-9A-F]{3,4})", text)
    if explicit:
        return explicit.group(1).upper(), f"{launch_path} explicitly sets PAGE=&{explicit.group(1).upper()}", True
    chain = re.search(r'(?i)\bCH(?:AIN|\.)?\s*"([^"\r]+)"', text)
    if chain:
        reference = chain.group(1).strip()
        target_path = reference if reference.startswith("$") else _adfs_child(directory, reference)
        parent, leaf = target_path.rsplit(".", 1)
        target = next(
            (
                item for item in service.list_directory(session, parent, None)["entries"]
                if item.get("type") not in {"dir", "directory"}
                and str(item.get("name", "")).casefold() == leaf.casefold()
            ),
            None,
        )
        target_load = _number(target.get("load")) & 0xFFFF if target else 0
        if target_load:
            return f"{target_load:X}", f"{launch_path} chains {target_path} saved at &{target_load:X}", True
    run = re.search(r'(?i)(?:^|:)\s*\*?R(?:UN)?\.?\s*"?([^"\s\r]+)', text)
    if run:
        return None, f"{launch_path} runs machine code; BASIC PAGE is not used", False
    return None, f"{launch_path} does not expose a provable BASIC PAGE", True


def audit_adfs_menu_pages(
    service: DiskService,
    session: ImageSession,
    root: str,
) -> dict:
    """Audit and repair PAGE records in an installed ADFS directory menu."""
    if session.kind != "adfs":
        raise DiskError("ADFS PAGE auditing requires an ADFS image.")
    if not has_adfs_menu(service, session, root):
        raise DiskError(f"No installed ADFS menu was found in {root}.")
    raw_database = service.read_file(session, None, _adfs_child(root, "GAMDATA"))
    entries = parse_menu_data(raw_database)
    legacy_fields = _legacy_page_field_count(raw_database)
    corrections: list[dict] = []
    unresolved: list[dict] = []
    verified = 0
    not_applicable = 0
    checked: set[tuple[str, str, str]] = set()
    for entry in entries:
        directory = str(entry.get("diskTitle") or root)
        filename = str(entry.get("filename") or "")
        action = str(entry.get("action") or "")
        key = (directory.casefold(), filename.casefold(), action.upper())
        checked.add(key)
        try:
            inferred, evidence, applicable = _adfs_launch_page(
                service, session, directory, filename, action
            )
        except Exception as exc:
            inferred, evidence, applicable = None, str(exc), True
        if not applicable:
            not_applicable += 1
            continue
        if inferred is None:
            unresolved.append({
                "title": entry["title"], "path": directory,
                "filename": filename, "reason": evidence,
            })
            continue
        verified += 1
        if _normalise_page(inferred) != _normalise_page(entry.get("page")):
            corrections.append({
                "title": entry["title"], "path": directory,
                "filename": filename, "from": _normalise_page(entry.get("page")),
                "to": _normalise_page(inferred), "evidence": evidence,
            })
            entry["page"] = inferred

    launcher = service.read_file(session, None, _adfs_child(root, "UNIMENU"))
    patched_launcher, compatible = _upgrade_universal_launcher_program(launcher)
    program_repairs = int(compatible and patched_launcher != launcher)
    rewritten = bool(corrections or legacy_fields or program_repairs)
    protected_names = ("GAMDATA", "GAMINDX", "PUBDATA", "PUBINDX", "UNIMENU")
    originals = {
        name: service.read_file(session, None, _adfs_child(root, name))
        for name in protected_names
    }
    try:
        if rewritten:
            _write_databases(
                service, session, entries, "H", root=root,
                preserve_game_order=True,
            )
        service.validate(session, None)
    except Exception:
        for name, content in originals.items():
            _put_bytes(service, session, None, _adfs_child(root, name), content)
        raise
    return {
        "root": root,
        "menuType": "adfs-universal",
        "entries": len(entries),
        "launchPathsChecked": len(checked),
        "verified": verified,
        "notApplicable": not_applicable,
        "corrected": len(corrections),
        "encodingRepairs": legacy_fields,
        "programRepairs": program_repairs,
        "unresolved": unresolved,
        "corrections": corrections,
        "rewritten": rewritten,
        "validation": "passed",
    }


def backup_mmb_menu_slot(
    service: DiskService,
    session: ImageSession,
    destination_slot: int,
) -> dict:
    """Copy the active menu SSD to a read-only, detection-safe backup slot."""
    if session.kind != "mmb":
        raise DiskError("Menu-slot backups require an MMB image.")
    source_slot, menu_type = installed_mmb_menu(service, session)
    if source_slot is None:
        raise DiskError("No installed MMB menu was found to back up.")
    destination_slot = service._check_slot(session, int(destination_slot))
    slots = service.list_slots(session)
    if not slots[destination_slot]["empty"]:
        raise DiskError("Choose an empty MMB slot for the menu backup.")
    data = service._slot_path(session, source_slot).read_bytes()
    if len(data) != MMB_SLOT_SIZE:
        raise DiskError("The installed menu slot is truncated.")
    title = f"MBACKUP-{source_slot:03d}"[:12]
    title_bytes = title.encode("latin-1").ljust(12, b"\0")
    with session.lock, session.path.open("r+b") as image:
        image.seek(mmb_entry_offset(destination_slot))
        image.write(title_bytes + b"\0\0\0" + b"\0")
        image.seek(mmb_slot_offset(destination_slot))
        image.write(data)
    session.slot_cache.pop(destination_slot, None)
    session.dirty = True
    service._persist_session(session)
    return {
        "menuSlot": source_slot,
        "menuType": menu_type,
        "backupSlot": destination_slot,
        "backupTitle": title,
        "readOnly": True,
    }


def restore_mmb_menu_slot(
    service: DiskService,
    session: ImageSession,
    backup_slot: int,
) -> dict:
    """Restore a labelled menu backup over the active menu slot, with rollback."""
    if session.kind != "mmb":
        raise DiskError("Menu-slot restore requires an MMB image.")
    menu_slot, _current_type = installed_mmb_menu(service, session)
    if menu_slot is None:
        raise DiskError("No active MMB menu slot was found to restore.")
    backup_slot = service._check_slot(session, int(backup_slot))
    slots = service.list_slots(session)
    if not is_mmb_menu_backup_title(slots[backup_slot].get("name")):
        raise DiskError("Choose a menu slot created by Backup menu slot.")
    replacement = service._slot_path(session, backup_slot).read_bytes()
    menu_type = _menu_type_from_ssd(replacement)
    if menu_type is None:
        raise DiskError("The selected backup no longer contains a recognised MMB menu.")
    original = service._slot_path(session, menu_slot).read_bytes()
    try:
        with session.lock, session.path.open("r+b") as image:
            image.seek(mmb_slot_offset(menu_slot))
            image.write(replacement)
        session.slot_cache.pop(menu_slot, None)
        service.validate(session, menu_slot)
    except Exception:
        with session.lock, session.path.open("r+b") as image:
            image.seek(mmb_slot_offset(menu_slot))
            image.write(original)
        session.slot_cache.pop(menu_slot, None)
        raise
    session.menu_slot = menu_slot
    session.menu_type = menu_type
    session.menu_scanned = True
    session.menu_entries = None
    service.set_mmb_drive_mapping(session, 0, menu_slot)
    session.dirty = True
    service._persist_session(session)
    return {
        "menuSlot": menu_slot,
        "menuType": menu_type,
        "backupSlot": backup_slot,
        "validation": "passed",
    }


def metadata_records_from_mmb_menu(
    service: DiskService,
    session: ImageSession,
    slot: int,
) -> list[dict]:
    """Return every cached Universal Menu record that refers to an MMB slot."""
    menu_slot = find_menu_slot(service, session)
    if menu_slot is None or menu_slot == slot:
        return []
    if session.menu_entries is None:
        try:
            data_file = (
                "$.EGAMDAT"
                if session.menu_type == "universal-4r"
                else "$.GAMDATA"
            )
            session.menu_entries = parse_mmb_menu_data(
                service.read_file(session, menu_slot, data_file),
                session.menu_type,
            )
        except (OSError, RuntimeError):
            session.menu_entries = []
    disk_title = service.list_slots(session)[slot]["name"]
    matching_records = [
        item
        for item in session.menu_entries
        if item["diskTitle"].casefold() == disk_title.casefold()
    ]
    count = len(matching_records)
    return [
        {
            **record,
            "page": _normalise_page(record.get("page")),
            "slot": slot,
            "confidence": 100,
            "ambiguous": False,
            "launchObvious": True,
            "fromMmbMenu": True,
            "menuRecordCount": count,
            "evidence": [
                (
                    "Loaded title, publisher, and disk title from the existing "
                    "SPI Game Menu; that menu launches the disk's !BOOT"
                    if getattr(session, "menu_type", None) == "spi-game-menu"
                    else "Loaded title, publisher, launch file, action, PAGE, and "
                    "disk title from the existing MMB Universal Menu"
                ),
                (
                    f"Found {count} existing menu titles on this MMB disk"
                    if count > 1
                    else "Found one existing menu title on this MMB disk"
                ),
            ],
            "warnings": [],
            "sources": [],
            "matches": [],
        }
        for record in matching_records
    ]


def continuation_metadata_from_mmb_menu(
    service: DiskService,
    session: ImageSession,
    slot: int,
) -> dict | None:
    """Identify a numbered continuation disk whose family has a menu entry."""
    menu_slot = find_menu_slot(service, session)
    if menu_slot is None or menu_slot == slot:
        return None
    if session.menu_entries is None:
        metadata_records_from_mmb_menu(service, session, slot)
    disk_title = str(service.list_slots(session)[slot]["name"])
    match = re.fullmatch(r"(.*?)(\d+)", disk_title)
    if not match or int(match.group(2)) == 0:
        return None
    family = match.group(1).casefold()
    related = [
        record
        for record in (session.menu_entries or [])
        if (
            (record_match := re.fullmatch(
                r"(.*?)(\d+)",
                str(record.get("diskTitle", "")),
            ))
            and record_match.group(1).casefold() == family
            and int(record_match.group(2)) < int(match.group(2))
        )
    ]
    if not related:
        return None
    primary = min(
        related,
        key=lambda record: int(
            re.fullmatch(r"(.*?)(\d+)", str(record["diskTitle"])).group(2)
        ),
    )
    return {
        "slot": slot,
        "diskTitle": disk_title,
        "continuationOf": str(primary["diskTitle"]),
        "continuationTitle": str(primary["title"]),
        "skipMenu": True,
        "evidence": [
            f"{disk_title} is a numbered continuation of "
            f"{primary['diskTitle']}, whose menu entry launches "
            f"{primary['filename']}"
        ],
        "warnings": [
            "This disk contains continuation data and does not have its own "
            "MMB Universal Menu record."
        ],
    }


def mmb_metadata_for_adfs(
    menu_metadata: dict,
    launch_candidates: list[dict],
    destination: str,
    detected: dict | None = None,
) -> dict:
    """Carry source disk or MMB-menu metadata to a copied ADFS directory."""
    source_filename = str(menu_metadata.get("filename") or "")
    launch = next(
        (
            candidate
            for candidate in launch_candidates
            if str(candidate.get("sourceName") or candidate["name"]).casefold()
            == source_filename.casefold()
        ),
        None,
    )
    fallback = None
    if launch is None and detected and detected.get("launchObvious"):
        detected_filename = str(detected.get("filename") or "")
        fallback = next(
            (
                candidate
                for candidate in launch_candidates
                if str(candidate.get("sourceName") or candidate["name"]).casefold()
                == detected_filename.casefold()
            ),
            None,
        )
    effective_launch = launch or fallback
    fallback_used = fallback is not None
    metadata = {
        **(detected or {}),
        **menu_metadata,
        "page": _normalise_page(menu_metadata.get("page")),
        "filename": (
            effective_launch["name"]
            if effective_launch
            else source_filename
        ),
        "action": (
            str(detected.get("action") or "")
            if fallback_used
            else str(menu_metadata.get("action") or "")
        ),
        "system": "H",
        "path": effective_launch["path"] if effective_launch else destination,
        "diskTitle": destination,
        "launchCandidates": launch_candidates,
        "launchObvious": bool(
            (menu_metadata.get("launchObvious") and launch)
            or (detected and detected.get("launchObvious") and fallback)
        ),
        "ambiguous": bool(
            menu_metadata.get("ambiguous")
            or effective_launch is None
        ),
        "evidence": [
            *menu_metadata.get("evidence", []),
            *(
                detected.get("evidence", [])
                if fallback_used and detected
                else []
            ),
        ],
    }
    if fallback_used:
        metadata["warnings"] = [
            *menu_metadata.get("warnings", []),
            f"The MMB menu launcher {source_filename} is absent; using "
            f"{fallback['sourceName']} as the disk's detected compilation-menu "
            "fallback.",
        ]
    elif source_filename and launch is None:
        metadata["warnings"] = [
            *metadata.get("warnings", []),
            "The MMB menu launch file was not found in the copied directory.",
        ]
    return metadata


def install_template(
    service: DiskService,
    session: ImageSession,
    menu_slot: int,
    template_dir: Path,
    menu_type: str = "universal",
) -> None:
    menu_slot = service._check_slot(session, menu_slot)
    slots = service.list_slots(session)
    if slots[menu_slot]["formatted"]:
        raise RuntimeError(f"Slot {menu_slot} is occupied and cannot hold the menu disk.")
    template_files = {
        "universal": "universal.ssd",
        "spi-game-menu": "spi-game-menu.ssd",
        "electron-magazine": "electron-magazine.ssd",
        "acorn-user": "acorn-user.ssd",
    }
    try:
        template = template_dir / template_files[menu_type]
    except KeyError as exc:
        raise RuntimeError("Unknown MMB menu type.") from exc
    if not template.is_file():
        raise RuntimeError("No MMB menu template is available.")
    data = template.read_bytes()
    if len(data) != MMB_SLOT_SIZE:
        raise RuntimeError("The MMB menu template is truncated.")
    titles = {
        "universal": "AFF_UNIMENU",
        "spi-game-menu": "SPI-GAMEMNU",
        "electron-magazine": "ELK_MAGMENU",
        "acorn-user": "ACORN_USER",
    }
    title = titles[menu_type]
    service._write_slot(session, menu_slot, data, title)
    service.set_mmb_drive_mapping(session, 0, menu_slot)
    session.menu_slot = menu_slot
    session.menu_type = menu_type
    session.menu_scanned = True


def refresh_mmc_desktop_catalogue(
    service: DiskService,
    session: ImageSession,
    menu_slot: int,
) -> int:
    """Rebuild MMC Desktop's fixed-width DISCCAT from current MMB slots."""
    raw = bytearray(service.read_file(session, menu_slot, "$.DISCCAT"))
    record_offset = 10
    record_size = 16
    record_count = 648
    required_size = record_offset + record_size * record_count
    if len(raw) < required_size:
        raise DiskError("The MMC Desktop DISCCAT file is truncated.")
    raw[record_offset:required_size] = b" " * (record_size * record_count)
    count = 0
    for item in service.list_slots(session):
        slot = int(item["slot"])
        if not item["formatted"] or is_mmb_menu_backup_title(item.get("name")) or slot >= record_count:
            continue
        record = f"{slot:>3} {str(item['name'])[:12]:<12}".encode(
            "latin-1",
            "replace",
        )
        start = record_offset + slot * record_size
        raw[start : start + record_size] = record
        count += 1
    _put_bytes(
        service,
        session,
        menu_slot,
        "$.DISCCAT",
        bytes(raw),
    )
    return count


def install_mmb_menu(
    service: DiskService,
    session: ImageSession,
    menu_slot: int,
    template_dir: Path,
    menu_type: str = "universal",
) -> dict:
    if session.kind != "mmb":
        raise DiskError("A menu disk can only be installed in an MMB image.")
    existing, existing_type = installed_mmb_menu(service, session)
    if existing is not None:
        return {
            "menuSlot": existing,
            "menuType": existing_type,
            "installed": False,
        }
    try:
        install_template(
            service,
            session,
            menu_slot,
            template_dir,
            menu_type,
        )
    except RuntimeError as exc:
        raise DiskError(str(exc)) from exc
    if menu_type in {"universal", "spi-game-menu"}:
        _write_databases(service, session, [], "M", slot=menu_slot)
    session.menu_entries = []
    return {
        "menuSlot": menu_slot,
        "menuType": menu_type,
        "installed": True,
    }


def configure_mmb_universal_page(
    service: DiskService,
    session: ImageSession,
    page: str,
) -> dict:
    """Configure the Universal Menu boot script without guessing MMFS safety."""
    menu_slot = find_menu_slot(service, session)
    if menu_slot is None or session.menu_type != "universal":
        raise DiskError("A Games Universal Menu must be installed before setting its PAGE.")
    selected = str(page or "current").strip().upper().lstrip("&")
    if selected in {"", "CURRENT", "UNCHANGED"}:
        selected = "current"
        content = b'CH."UNIMENU"\r'
    elif selected in {"800", "E00"}:
        content = f'PAGE=&{selected}\rCH."UNIMENU"\r'.encode("ascii")
    else:
        raise DiskError("Choose current PAGE, &800, or &E00 for Universal Menu.")
    _put_bytes(service, session, menu_slot, "$.!BOOT", content)
    return {"menuSlot": menu_slot, "menuType": session.menu_type, "menuPage": selected}


def mmb_universal_page(service: DiskService, session: ImageSession) -> str:
    menu_slot = find_menu_slot(service, session)
    if menu_slot is None or session.menu_type != "universal":
        return "current"
    try:
        boot = service.read_file(session, menu_slot, "$.!BOOT").decode("latin-1")
    except (OSError, RuntimeError):
        return "current"
    match = re.search(r"\bPAGE\s*=\s*&([0-9A-F]+)", boot, re.IGNORECASE)
    return match.group(1).upper() if match else "current"


def update_menu(
    service: DiskService,
    session: ImageSession,
    metadata: dict,
    menu_slot: int,
    template_dir: Path,
) -> dict:
    actual = find_menu_slot(service, session)
    installed = actual is None
    if actual is None:
        try:
            install_template(service, session, menu_slot, template_dir)
        except RuntimeError as exc:
            raise DiskError(str(exc)) from exc
        actual = menu_slot
    if installed:
        entries = []
    else:
        try:
            entries = parse_mmb_menu_data(
                service.read_file(session, actual, mmb_menu_data_path(session)),
                session.menu_type,
            )
        except Exception as exc:
            raise DiskError(
                "The existing MMB menu database could not be read, so it was left unchanged."
            ) from exc
    record = _normalise_mmb_record(metadata, session.menu_type)
    entries = _append_replacing_identity(entries, record)
    _write_mmb_databases(service, session, actual, entries)
    return {"menuSlot": actual, "entries": len(entries), "record": record}


def _write_mmb_databases(
    service: DiskService,
    session: ImageSession,
    menu_slot: int,
    entries: list[dict],
) -> None:
    _write_databases(service, session, entries, "M", slot=menu_slot)
    session.menu_entries = [dict(item) for item in entries]


def mmb_menu_data_path(session: ImageSession) -> str:
    return (
        "$.EGAMDAT"
        if getattr(session, "menu_type", None) == "universal-4r"
        else "$.GAMDATA"
    )


def replace_mmb_menu(
    service: DiskService,
    session: ImageSession,
    entries: list[dict],
    append: bool = False,
) -> dict:
    menu_slot = find_menu_slot(service, session)
    if menu_slot is None:
        raise DiskError("Create an MMB menu before rebuilding its entries.")
    current = (
        parse_mmb_menu_data(
            service.read_file(session, menu_slot, mmb_menu_data_path(session)),
            session.menu_type,
        )
        if append
        else []
    )
    by_disk = {
        (
            item["diskTitle"].casefold(),
            item["title"].casefold(),
        ): item
        for item in current
    }
    for item in entries:
        record = _normalise_mmb_record(item, session.menu_type)
        by_disk[
            (
                record["diskTitle"].casefold(),
                record["title"].casefold(),
            )
        ] = record
    records = list(by_disk.values())
    _write_mmb_databases(service, session, menu_slot, records)
    return {"menuSlot": menu_slot, "entries": len(records)}


def audit_mmb_menu_pages(service: DiskService, session: ImageSession) -> dict:
    """Check every Universal Menu launcher and repair provable PAGE errors."""
    if session.kind != "mmb":
        raise DiskError("PAGE auditing requires an MMB image.")
    menu_slot = find_menu_slot(service, session)
    if menu_slot is None:
        raise DiskError("Create an MMB menu before auditing PAGE values.")
    if session.menu_type not in {"universal", "universal-4r"}:
        if session.menu_type == "spi-game-menu":
            raise DiskError("SPI Game Menu entries execute !BOOT and do not store a PAGE value.")
        raise DiskError("This installed menu does not contain per-entry PAGE values.")

    data_path = mmb_menu_data_path(session)
    raw_database = service.read_file(session, menu_slot, data_path)
    entries = parse_mmb_menu_data(raw_database, session.menu_type)
    legacy_fields = _legacy_page_field_count(raw_database)
    slots_by_title: dict[str, list[int]] = {}
    for item in service.list_slots(session):
        if item.get("formatted") and int(item["slot"]) != menu_slot:
            slots_by_title.setdefault(str(item["name"]).casefold(), []).append(int(item["slot"]))

    disk_cache: dict[int, bytes] = {}
    inference_cache: dict[tuple[int, str, str], tuple[str | None, str]] = {}
    corrections: list[dict] = []
    unresolved: list[dict] = []
    verified = 0
    not_applicable = 0
    for entry in entries:
        matching = slots_by_title.get(str(entry["diskTitle"]).casefold(), [])
        if len(matching) != 1:
            unresolved.append({
                "title": entry["title"],
                "diskTitle": entry["diskTitle"],
                "reason": "The disk title is missing or is not unique.",
            })
            continue
        slot = matching[0]
        action = str(entry.get("action") or "").upper()
        if action not in {"", "E"}:
            not_applicable += 1
            continue
        key = (slot, str(entry["filename"]).casefold(), action)
        if key not in inference_cache:
            disk_cache.setdefault(slot, service._slot_path(session, slot).read_bytes())
            inference_cache[key] = infer_dfs_launch_page(
                disk_cache[slot], str(entry["filename"]), action
            )
        inferred, evidence = inference_cache[key]
        if inferred is None:
            if "PAGE is not used" in evidence:
                not_applicable += 1
            else:
                unresolved.append({
                    "title": entry["title"], "slot": slot,
                    "diskTitle": entry["diskTitle"], "filename": entry["filename"],
                    "reason": evidence,
                })
            continue
        verified += 1
        if _normalise_page(inferred) != _normalise_page(entry.get("page")):
            corrections.append({
                "title": entry["title"], "slot": slot,
                "diskTitle": entry["diskTitle"], "filename": entry["filename"],
                "from": _normalise_page(entry.get("page")), "to": _normalise_page(inferred),
                "evidence": evidence,
            })
            entry["page"] = inferred

    program_repairs = 0
    if session.menu_type == "universal":
        launcher = service.read_file(session, menu_slot, "$.UNIMENU")
        patched_launcher, compatible = _upgrade_universal_launcher_program(launcher)
        program_repairs = int(compatible and patched_launcher != launcher)
    rewritten = bool(corrections or legacy_fields or program_repairs)
    if rewritten:
        original_slot = service._slot_path(session, menu_slot).read_bytes()
        try:
            _write_mmb_databases(service, session, menu_slot, entries)
            service.validate(session, menu_slot)
        except Exception:
            with session.lock, session.path.open("r+b") as image:
                image.seek(mmb_slot_offset(menu_slot))
                image.write(original_slot)
            session.slot_cache.pop(menu_slot, None)
            raise
    else:
        service.validate(session, menu_slot)

    return {
        "menuSlot": menu_slot,
        "menuType": session.menu_type,
        "entries": len(entries),
        "launchPathsChecked": len(inference_cache),
        "verified": verified,
        "notApplicable": not_applicable,
        "corrected": len(corrections),
        "encodingRepairs": legacy_fields,
        "programRepairs": program_repairs,
        "unresolved": unresolved,
        "corrections": corrections,
        "rewritten": rewritten,
        "validation": "passed",
    }


def edit_mmb_menu_entries(
    service: DiskService,
    session: ImageSession,
    entries: list[object],
    expected_entries: list[object],
) -> dict:
    """Atomically replace a Universal Menu after validating every record."""
    if session.kind != "mmb":
        raise DiskError("Universal Menu editing requires an MMB image.")
    menu_slot = find_menu_slot(service, session)
    if menu_slot is None or session.menu_type not in {
        "universal", "universal-4r", "spi-game-menu"
    }:
        raise DiskError("Only an installed Universal or SPI Game Menu can be edited.")

    current = parse_mmb_menu_data(
        service.read_file(session, menu_slot, mmb_menu_data_path(session)),
        session.menu_type,
    )
    expected = [
        _menu_record_identity(item)
        for item in expected_entries
        if isinstance(item, dict)
    ]
    if expected_entries and expected != [
        _menu_record_identity(item) for item in current
    ]:
        raise DiskError(
            "The menu changed while the editor was open. Refresh the preview and try again."
        )

    records = []
    identities = set()
    current_identities = {_menu_record_identity(item) for item in current}
    for item in entries:
        if not isinstance(item, dict):
            raise DiskError("The edited menu contains an invalid record.")
        record = _normalise_mmb_record(item, session.menu_type)
        identity = (
            record["diskTitle"].casefold(),
            record["title"].casefold(),
        )
        if identity in identities:
            raise DiskError(
                f'{record["title"]} is duplicated for disk {record["diskTitle"]}.'
            )
        identities.add(identity)
        records.append(record)

    slots_by_title: dict[str, list[int]] = {}
    for slot in service.list_slots(session):
        if slot.get("formatted") and int(slot["slot"]) != menu_slot:
            slots_by_title.setdefault(str(slot["name"]).casefold(), []).append(
                int(slot["slot"])
            )

    catalogues: dict[int, set[str]] = {}
    for record in records:
        # Existing legacy records may already refer to a removed disk. Permit
        # them to remain temporarily so the editor can repair or remove bad
        # entries one at a time, but validate every changed/new record.
        if _menu_record_identity(record) in current_identities:
            continue
        matching_slots = slots_by_title.get(record["diskTitle"].casefold(), [])
        if not matching_slots:
            raise DiskError(
                f'{record["title"]} refers to missing MMB disk {record["diskTitle"]}.'
            )
        if len(matching_slots) > 1:
            raise DiskError(
                f'{record["title"]} refers to non-unique MMB disk title '
                f'{record["diskTitle"]}. Rename the disks before saving the menu.'
            )
        target_slot = matching_slots[0]
        if target_slot not in catalogues:
            catalogues[target_slot] = {
                str(row["name"]).casefold()
                for row in service.list_directory(session, "$", target_slot)["entries"]
                if row.get("type") not in {"dir", "directory"}
            }
        if record["filename"].casefold() not in catalogues[target_slot]:
            raise DiskError(
                f'{record["title"]} launcher {record["filename"]} does not exist '
                f'in slot {target_slot} · {record["diskTitle"]}.'
            )

    _write_mmb_databases(service, session, menu_slot, records)
    return {"menuSlot": menu_slot, "entries": len(records)}


def eject_mmb_slots(
    service: DiskService,
    session: ImageSession,
    slot_numbers: list[int],
) -> dict:
    """Eject MMB disks and remove menu records that can no longer resolve."""
    if session.kind != "mmb":
        raise DiskError("MMB slot ejection requires an MMB image.")
    try:
        requested = list(dict.fromkeys(int(slot) for slot in slot_numbers))
    except (TypeError, ValueError) as exc:
        raise DiskError("The MMB slot selection is invalid.") from exc
    if not requested:
        raise DiskError("Select at least one MMB disk to eject.")

    with session.lock:
        slots = {int(row["slot"]): row for row in service.list_slots(session)}
        for slot in requested:
            row = slots.get(slot)
            if row is None or not row.get("formatted"):
                raise DiskError(f"MMB slot {slot} is no longer a formatted disk.")

        menu_slot, menu_type = installed_mmb_menu(service, session)
        removed_entries = []
        if menu_slot not in requested and menu_type in {
            "universal", "universal-4r", "spi-game-menu"
        }:
            current = parse_mmb_menu_data(
                service.read_file(session, menu_slot, mmb_menu_data_path(session)),
                menu_type,
            )
            remaining_titles = {
                str(row.get("name") or "").casefold()
                for slot, row in slots.items()
                if slot not in requested and row.get("formatted")
            }
            orphaned_titles = {
                str(slots[slot].get("name") or "").casefold()
                for slot in requested
            } - remaining_titles
            removed_entries = [
                entry for entry in current
                if str(entry.get("diskTitle") or "").casefold() in orphaned_titles
            ]
            if removed_entries:
                remaining = [
                    entry for entry in current
                    if str(entry.get("diskTitle") or "").casefold() not in orphaned_titles
                ]
                edit_mmb_menu_entries(service, session, remaining, current)

        cleared = service.clear_slots(session, requested)
    return {
        "slots": cleared,
        "menuEntriesRemoved": len(removed_entries),
        "removedEntries": removed_entries,
    }
