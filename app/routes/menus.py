from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import Blueprint, jsonify, request
from .effects import image_mutation, request_effect

from ..dfs_compat import infer_dfs_launch_page
from ..disk_service import DiskError, DiskService
from ..menu_interpreter import interpret_menu_program
from ..menu.adfs import (
    audit_adfs_menu_pages,
    append_adfs_menu_entry,
    append_adfs_menu_entries,
    create_adfs_menu,
    has_adfs_menu,
    installed_adfs_menus,
    reorder_adfs_menu,
    scan_adfs_menu_directories,
)
from ..menu.analysis import analyse_disk, enrich_if_ambiguous
from ..menu.mmb import (
    audit_mmb_menu_pages, backup_mmb_menu_slot, configure_mmb_universal_page,
    edit_mmb_menu_entries, find_menu_slot, install_mmb_menu, installed_mmb_menu,
    installed_mmb_menus, is_mmb_menu_backup_title, mmb_menu_data_path,
    mmb_universal_page, parse_menu_data, parse_mmb_menu_data,
    refresh_mmc_desktop_catalogue, replace_mmb_menu, restore_mmb_menu_slot,
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
    @request_effect("read-only", "scanning disk metadata")
    def scan_slot_metadata(image_id):
        data = payload()
        metadata = analyse_disk(service, service.get(image_id), int(data["slot"]))
        if data.get("online", True) and metadata["ambiguous"]:
            enrich_if_ambiguous(metadata)
        return jsonify(metadata=metadata)

    @blueprint.post("/api/images/<image_id>/metadata/page")
    @request_effect("read-only", "detecting a launch PAGE value")
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
            menus = installed_adfs_menus(service, session)
            return jsonify(
                detected=any(menu["root"].casefold() == root.casefold() for menu in menus),
                root=root,
                menus=menus,
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
    @image_mutation("adding a menu entry")
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
    @image_mutation("installing a menu")
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
    @image_mutation("changing the menu PAGE")
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
    @image_mutation("auditing the menu")
    def audit_menu_pages(image_id):
        session = service.get(image_id)
        with session.lock:
            result = audit_mmb_menu_pages(service, session)
        return jsonify(image=service.summary(session), **result)

    @blueprint.post("/api/images/<image_id>/menu/backup")
    @image_mutation("backing up the menu slot")
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
    @image_mutation("restoring the menu slot")
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
    @image_mutation("refreshing the menu catalogue")
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
    @request_effect("read-only", "scanning ADFS menu candidates")
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
    @image_mutation("creating an ADFS menu")
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
    @image_mutation("adding an ADFS menu entry")
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
    @image_mutation("adding ADFS menu entries")
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
    @image_mutation("reordering the ADFS menu")
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
    @image_mutation("auditing the ADFS menu")
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
    @request_effect("read-only", "scanning MMB menu records")
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
    @image_mutation("rebuilding the MMB menu")
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
    @image_mutation("editing the MMB menu")
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

    @blueprint.post("/api/images/<image_id>/mmb-menu/duplicate-cleanup")
    @image_mutation("cleaning duplicate MMB menu records")
    def cleanup_mmb_duplicates(image_id):
        data = payload()
        session = service.get(image_id)
        expected = data.get("expectedEntries", [])
        if not isinstance(expected, list) or not expected:
            raise DiskError("Refresh the duplicate review before changing the menu.")
        try:
            remove_indexes = {int(value) for value in data.get("removeIndexes", [])}
            eject_slots = list(dict.fromkeys(int(value) for value in data.get("ejectSlots", [])))
        except (TypeError, ValueError) as exc:
            raise DiskError("The duplicate cleanup selection is invalid.") from exc
        if not remove_indexes or any(index < 0 or index >= len(expected) for index in remove_indexes):
            raise DiskError("Choose at least one current menu record to remove.")

        with session.lock:
            menu_slot = find_menu_slot(service, session)
            slots = {int(row["slot"]): row for row in service.list_slots(session)}
            for slot in eject_slots:
                row = slots.get(slot)
                if row is None or not row.get("formatted"):
                    raise DiskError(f"MMB slot {slot} is no longer a formatted disk.")
                if slot == menu_slot:
                    raise DiskError("The installed menu disk cannot be ejected by duplicate cleanup.")

            ejected_titles = {
                str(slots[slot].get("name") or "").casefold()
                for slot in eject_slots
            }
            removed_indexes = remove_indexes | {
                offset
                for offset, entry in enumerate(expected)
                if isinstance(entry, dict)
                and str(entry.get("diskTitle") or "").casefold() in ejected_titles
            }
            removed_entries = [
                entry for offset, entry in enumerate(expected)
                if offset in removed_indexes and isinstance(entry, dict)
            ]
            remaining = [
                entry for offset, entry in enumerate(expected)
                if offset not in removed_indexes
            ]
            result = edit_mmb_menu_entries(service, session, remaining, expected)
            if eject_slots:
                service.clear_slots(session, eject_slots)

        return jsonify(
            image=service.summary(session),
            **result,
            removedRecords=len(removed_entries),
            removedEntries=removed_entries,
            ejectedSlots=eject_slots,
        )

    return blueprint
