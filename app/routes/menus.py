from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import Blueprint, jsonify, request

from ..dfs_compat import infer_dfs_launch_page
from ..disk_service import DiskError, DiskService
from ..menu_interpreter import interpret_menu_program
from ..menu_service import (
    analyse_disk,
    audit_adfs_menu_pages,
    audit_mmb_menu_pages,
    backup_mmb_menu_slot,
    append_adfs_menu_entry,
    append_adfs_menu_entries,
    create_adfs_menu,
    configure_mmb_universal_page,
    edit_mmb_menu_entries,
    enrich_if_ambiguous,
    find_menu_slot,
    has_adfs_menu,
    install_mmb_menu,
    installed_mmb_menu,
    installed_mmb_menus,
    is_mmb_menu_backup_title,
    mmb_menu_data_path,
    mmb_universal_page,
    parse_menu_data,
    parse_mmb_menu_data,
    reorder_adfs_menu,
    restore_mmb_menu_slot,
    replace_mmb_menu,
    refresh_mmc_desktop_catalogue,
    scan_adfs_menu_directories,
    update_menu,
)
from .common import payload


def _enrich_ambiguous(items: list[dict], workers: int = 3) -> None:
    ambiguous = [item for item in items if item["ambiguous"]]
    if ambiguous:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(enrich_if_ambiguous, ambiguous))


def _interpreted_preview(
    service: DiskService,
    session,
    *,
    slot: int | None,
    root: str,
    program_name: str,
) -> dict:
    rows = service.list_directory(session, root, slot)["entries"]
    by_name = {str(row["name"]).upper(): row for row in rows}

    def path(name: str) -> str:
        return f"$.{name}" if slot is not None or root == "$" else f"{root}.{name}"

    program = service.read_file(session, slot, path(program_name))
    support = {}
    for name in ("TXT2SCN", "SHOW"):
        row = by_name.get(name)
        if row is None:
            continue
        support[name] = (
            int(row.get("load") or 0) & 0xFFFF,
            service.read_file(session, slot, path(str(row["name"]))),
        )
    return interpret_menu_program(program_name, program, support)


def create_menus_blueprint(service: DiskService, template_dir: Path) -> Blueprint:
    blueprint = Blueprint("menus", __name__)

    @blueprint.post("/api/images/<image_id>/metadata/scan")
    def scan_slot_metadata(image_id):
        data = payload()
        metadata = analyse_disk(service, service.get(image_id), int(data["slot"]))
        if data.get("online", True) and metadata["ambiguous"]:
            enrich_if_ambiguous(metadata)
        return jsonify(metadata=metadata)

    @blueprint.post("/api/images/<image_id>/metadata/page")
    def scan_slot_page(image_id):
        data = payload()
        session = service.get(image_id)
        if session.kind != "mmb":
            raise DiskError("PAGE lookup by MMB slot requires an MMB image.")
        slot = int(data["slot"])
        image = service._slot_path(session, slot).read_bytes()
        page, evidence = infer_dfs_launch_page(
            image,
            str(data.get("filename") or ""),
            str(data.get("action") or ""),
        )
        return jsonify(page=page, applicable="PAGE is not used" not in evidence, evidence=evidence)

    @blueprint.get("/api/images/<image_id>/menu")
    def menu_status(image_id):
        session = service.get(image_id)
        menus = installed_mmb_menus(service, session)
        selected = menus[0] if menus else {}
        slot = selected.get("slot")
        menu_type = selected.get("type")
        data_file = "$.EGAMDAT" if menu_type == "universal-4r" else "$.GAMDATA"
        entries = (
            parse_mmb_menu_data(
                service.read_file(session, slot, data_file),
                menu_type,
            )
            if slot is not None
            and menu_type in {"universal", "universal-4r", "spi-game-menu"}
            else []
        )
        return jsonify(
            configured=slot is not None,
            menuSlot=slot,
            menuType=menu_type,
            menus=menus,
            entries=entries,
            menuPage=mmb_universal_page(service, session),
        )

    @blueprint.get("/api/images/<image_id>/menu/detected")
    def menu_detected(image_id):
        session = service.get(image_id)
        if session.kind == "mmb":
            menus = installed_mmb_menus(service, session)
            return jsonify(
                detected=bool(menus),
                menus=menus,
            )
        if session.kind == "adfs":
            root = request.args.get("root", "$")
            return jsonify(
                detected=has_adfs_menu(service, session, root),
                root=root,
            )
        return jsonify(detected=False)

    @blueprint.get("/api/images/<image_id>/menu/preview")
    def menu_preview(image_id):
        session = service.get(image_id)
        if session.kind == "mmb":
            slot, menu_type = installed_mmb_menu(service, session)
            if slot is None:
                raise DiskError("This MMB image does not have an installed menu.")
            if menu_type not in {"universal", "universal-4r", "spi-game-menu"}:
                raise DiskError(
                    "This catalogue-browser menu has no game-launch records to preview."
                )
            data_file = "$.EGAMDAT" if menu_type == "universal-4r" else "$.GAMDATA"
            entries = parse_mmb_menu_data(
                service.read_file(session, slot, data_file),
                menu_type,
            )
            program_name = {
                "universal-4r": "UNMNU4R",
                "spi-game-menu": "GAMECOL",
            }.get(menu_type, "UNIMENU")
            return jsonify(
                kind="mmb",
                location=f"MMB slot {slot}",
                menuSlot=slot,
                menuType=menu_type,
                root="$",
                entries=entries,
                interpretation=_interpreted_preview(
                    service,
                    session,
                    slot=slot,
                    root="$",
                    program_name=program_name,
                ),
            )
        if session.kind == "adfs":
            root = request.args.get("root", "$")
            if not has_adfs_menu(service, session, root):
                raise DiskError(f"No installed ADFS menu was found in {root}.")
            entries = parse_menu_data(service.read_file(session, None, f"{root}.GAMDATA"))
            return jsonify(
                kind="adfs",
                location=f"ADFS {root}",
                menuSlot=None,
                root=root,
                entries=entries,
                interpretation=_interpreted_preview(
                    service,
                    session,
                    slot=None,
                    root=root,
                    program_name="UNIMENU",
                ),
            )
        raise DiskError("Installed menu previews are available for MMB and ADFS images.")

    @blueprint.post("/api/images/<image_id>/menu/entry")
    def add_menu_entry(image_id):
        data = payload()
        session = service.get(image_id)
        if session.kind != "mmb":
            raise DiskError("MMB game-menu entries can only be added to an MMB image.")
        result = update_menu(
            service,
            session,
            data.get("metadata", {}),
            int(data.get("menuSlot", 0)),
            template_dir,
        )
        return jsonify(image=service.summary(session), **result)

    @blueprint.post("/api/images/<image_id>/menu/install")
    def install_menu(image_id):
        data = payload()
        session = service.get(image_id)
        menu_type = str(data.get("menuType") or "universal")
        if menu_type == "copy-other":
            source = service.get(str(data.get("sourceImage") or ""))
            source_menus = installed_mmb_menus(service, source)
            requested_slot = data.get("sourceMenuSlot")
            source_menu = next(
                (
                    item
                    for item in source_menus
                    if requested_slot is not None
                    and int(item["slot"]) == int(requested_slot)
                ),
                source_menus[0] if requested_slot is None and source_menus else None,
            )
            if source_menu is None:
                raise DiskError("No recognised menu was found in the other MMB.")
            source_slot = int(source_menu["slot"])
            source_type = str(source_menu["type"])
            target_slot = int(data.get("menuSlot", 0))
            inserted = service.insert_slot_from_session(
                session,
                target_slot,
                source,
                source_slot,
            )
            session.menu_slot = inserted[0]
            session.menu_type = source_type
            session.menu_scanned = True
            session.menu_entries = None
            service.set_mmb_drive_mapping(session, 0, inserted[0])
            if source_type == "mmc-desktop":
                refresh_mmc_desktop_catalogue(service, session, inserted[0])
            elif source_type in {"universal", "universal-4r"}:
                audit_mmb_menu_pages(service, session)
            return jsonify(
                image=service.summary(session),
                menuSlot=inserted[0],
                menuType=source_type,
                installed=True,
            )
        result = install_mmb_menu(
            service,
            session,
            int(data.get("menuSlot", 0)),
            template_dir,
            menu_type,
        )
        if menu_type == "universal":
            result.update(configure_mmb_universal_page(
                service,
                session,
                data.get("menuPage", "current"),
            ))
        return jsonify(image=service.summary(session), **result)

    @blueprint.post("/api/images/<image_id>/menu/page")
    def configure_menu_page(image_id):
        data = payload()
        session = service.get(image_id)
        with session.lock:
            result = configure_mmb_universal_page(
                service,
                session,
                data.get("menuPage", "current"),
            )
        return jsonify(image=service.summary(session), **result)

    @blueprint.post("/api/images/<image_id>/menu/page-audit")
    def audit_menu_pages(image_id):
        session = service.get(image_id)
        with session.lock:
            result = audit_mmb_menu_pages(service, session)
        return jsonify(image=service.summary(session), **result)

    @blueprint.post("/api/images/<image_id>/menu/backup")
    def backup_menu_slot(image_id):
        data = payload()
        session = service.get(image_id)
        with session.lock:
            result = backup_mmb_menu_slot(
                service,
                session,
                int(data["destinationSlot"]),
            )
        return jsonify(image=service.summary(session), **result)

    @blueprint.post("/api/images/<image_id>/menu/restore")
    def restore_menu_slot(image_id):
        data = payload()
        session = service.get(image_id)
        with session.lock:
            result = restore_mmb_menu_slot(
                service,
                session,
                int(data["backupSlot"]),
            )
        return jsonify(image=service.summary(session), **result)

    @blueprint.post("/api/images/<image_id>/menu/refresh")
    def refresh_menu(image_id):
        session = service.get(image_id)
        slot, menu_type = installed_mmb_menu(service, session)
        if slot is None or menu_type != "mmc-desktop":
            raise DiskError("MMC Desktop is not installed in this MMB image.")
        entries = refresh_mmc_desktop_catalogue(service, session, slot)
        return jsonify(
            image=service.summary(session),
            menuSlot=slot,
            menuType=menu_type,
            entries=entries,
        )

    @blueprint.post("/api/images/<image_id>/adfs-menu/scan")
    def scan_adfs_menu(image_id):
        data = payload()
        session = service.get(image_id)
        if session.kind != "adfs":
            raise DiskError("Directory menus are only available for ADFS images.")
        root = data.get("root", "$")
        metadata, holders = scan_adfs_menu_directories(service, session, root)
        if data.get("online", True):
            _enrich_ambiguous(metadata, workers=4)
        return jsonify(root=root, entries=metadata, holders=holders)

    @blueprint.post("/api/images/<image_id>/adfs-menu/create")
    def build_adfs_menu(image_id):
        data = payload()
        session = service.get(image_id)
        with session.lock:
            result = create_adfs_menu(
                service,
                session,
                data.get("root", "$"),
                data.get("entries", []),
                template_dir,
            )
        return jsonify(image=service.summary(session), **result)

    @blueprint.post("/api/images/<image_id>/adfs-menu/entry")
    def add_adfs_menu_entry(image_id):
        data = payload()
        session = service.get(image_id)
        with session.lock:
            result = append_adfs_menu_entry(
                service,
                session,
                data.get("root", "$"),
                data.get("metadata", {}),
                template_dir,
            )
        return jsonify(image=service.summary(session), **result)

    @blueprint.post("/api/images/<image_id>/adfs-menu/entries")
    def add_adfs_menu_entries(image_id):
        data = payload()
        session = service.get(image_id)
        with session.lock:
            result = append_adfs_menu_entries(
                service,
                session,
                data.get("root", "$"),
                data.get("metadata", []),
                template_dir,
            )
        return jsonify(image=service.summary(session), **result)

    @blueprint.post("/api/images/<image_id>/adfs-menu/reorder")
    def reorder_adfs_menu_entries(image_id):
        data = payload()
        session = service.get(image_id)
        with session.lock:
            result = reorder_adfs_menu(
                service,
                session,
                data.get("root", "$"),
                data.get("order", []),
            )
        return jsonify(image=service.summary(session), **result)

    @blueprint.post("/api/images/<image_id>/adfs-menu/page-audit")
    def audit_adfs_pages(image_id):
        data = payload()
        session = service.get(image_id)
        with session.lock:
            result = audit_adfs_menu_pages(
                service,
                session,
                str(data.get("root") or "$"),
            )
        return jsonify(image=service.summary(session), **result)

    @blueprint.post("/api/images/<image_id>/mmb-menu/scan")
    def scan_mmb_menu(image_id):
        data = payload()
        session = service.get(image_id)
        if session.kind != "mmb":
            raise DiskError("MMB menu scanning requires an MMB image.")
        menu_slot = find_menu_slot(service, session)
        if menu_slot is None:
            raise DiskError("Create an MMB menu before scanning its disks.")
        current = parse_mmb_menu_data(
            service.read_file(session, menu_slot, mmb_menu_data_path(session)),
            session.menu_type,
        )
        known = {item["diskTitle"].casefold() for item in current}
        mode = data.get("mode", "missing")
        candidates = [
            item["slot"]
            for item in service.list_slots(session)
            if item["formatted"]
            and item["slot"] != menu_slot
            and not is_mmb_menu_backup_title(item.get("name"))
            and (mode != "missing" or item["name"].casefold() not in known)
        ]
        with ThreadPoolExecutor(max_workers=4) as pool:
            metadata = list(
                pool.map(
                    lambda slot: analyse_disk(service, session, slot),
                    candidates,
                )
            )
        if data.get("online", True):
            _enrich_ambiguous(metadata)
        return jsonify(
            menuSlot=menu_slot,
            menuType=session.menu_type,
            entries=metadata,
            existing=len(current),
            mode=mode,
        )

    @blueprint.post("/api/images/<image_id>/mmb-menu/rebuild")
    def rebuild_mmb_menu(image_id):
        data = payload()
        session = service.get(image_id)
        result = replace_mmb_menu(
            service,
            session,
            data.get("entries", []),
            append=data.get("mode") == "missing",
        )
        return jsonify(image=service.summary(session), **result)

    @blueprint.put("/api/images/<image_id>/mmb-menu/entries")
    def edit_mmb_menu(image_id):
        data = payload()
        session = service.get(image_id)
        with session.lock:
            result = edit_mmb_menu_entries(
                service,
                session,
                data.get("entries", []),
                data.get("expectedEntries", []),
            )
        return jsonify(image=service.summary(session), **result)

    return blueprint
