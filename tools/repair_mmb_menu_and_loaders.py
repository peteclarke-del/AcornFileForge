#!/usr/bin/env python3
"""Atomically clean menu display records and provable MMFS loader wildcards."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

from app.dfs_compat import repair_dfs_basic_wildcards
from app.disk_service import MMB_HEADER_SIZE, MMB_SLOT_SIZE, DiskError, DiskService
from app.menu_service import (
    fit_menu_display_fields,
    installed_mmb_menu,
    mmb_menu_data_path,
    parse_mmb_menu_data,
    replace_mmb_menu,
)


IJK_REPEATED_TITLES = {
    "3d-maze", "bozo the brave", "caterpillar", "super hangman",
    "zorakk the conqueror",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--session", required=True)
    args = parser.parse_args()

    service = DiskService(args.work_dir)
    session = service._restore_session(args.session)
    menu_slot, menu_type = installed_mmb_menu(service, session)
    if menu_slot is None or menu_type not in {"universal", "universal-4r", "spi-game-menu"}:
        raise DiskError("The target session has no editable MMB game menu.")
    entries = parse_mmb_menu_data(
        service.read_file(session, menu_slot, mmb_menu_data_path(session)),
        menu_type,
    )
    retained = [
        item for item in entries
        if not (
            item["diskTitle"].casefold() == "ijk-sshdinpl"
            and item["title"].casefold() in IJK_REPEATED_TITLES
        )
    ]
    arcadians_page_fixed = 0
    for item in retained:
        if (
            item["title"].casefold() == "arcadians"
            and item["diskTitle"].casefold() == "acn-arcboxct"
            and item["filename"].casefold() == "ssdmenu"
            and item["page"].upper() != "1900"
        ):
            item["page"] = "1900"
            arcadians_page_fixed += 1
    removed = len(entries) - len(retained)
    display_changed = sum(
        fit_menu_display_fields(item["title"], item["publisher"])
        != (item["title"], item["publisher"])
        for item in retained
    )

    with tempfile.NamedTemporaryFile(dir=session.path.parent, suffix=".mmb", delete=False) as handle:
        temporary_path = Path(handle.name)
    temporary_path.unlink()
    shutil.copy2(session.path, temporary_path)
    working = replace(session, path=temporary_path, slot_cache={}, menu_entries=None)
    loader_repairs: list[dict] = []
    changed_slots: set[int] = set()
    try:
        with temporary_path.open("r+b") as image:
            for item in service.list_slots(working):
                if not item.get("formatted"):
                    continue
                slot = int(item["slot"])
                offset = MMB_HEADER_SIZE + slot * MMB_SLOT_SIZE
                image.seek(offset)
                disk = image.read(MMB_SLOT_SIZE)
                repaired, changes = repair_dfs_basic_wildcards(disk)
                if not changes:
                    continue
                image.seek(offset)
                image.write(repaired)
                changed_slots.add(slot)
                loader_repairs.extend({"slot": slot, "change": change} for change in changes)

        working.menu_slot = menu_slot
        working.menu_type = menu_type
        result = replace_mmb_menu(service, working, retained, append=False)
        service.validate(working, int(menu_slot))
        for slot in changed_slots:
            service.validate(working, slot)

        backup = session.path.with_name(f"{session.path.stem}.before-menu-display-repair.mmb")
        if not backup.exists():
            shutil.copy2(session.path, backup)
        temporary_path.replace(session.path)
        for slot in changed_slots:
            session.path.with_name(f"slot-{slot:03d}.ssd").unlink(missing_ok=True)
        session.menu_entries = working.menu_entries
        session.dirty = True
        for repair in loader_repairs:
            session.warnings.append(
                f"MMFS compatibility change in slot {repair['slot']}: {repair['change']}."
            )
        service._persist_session(session)
        print(json.dumps({
            "session": session.id,
            "menuType": menu_type,
            "entriesBefore": len(entries),
            "entriesAfter": result["entries"],
            "repeatedIjkEntriesRemoved": removed,
            "arcadiansPageFixed": arcadians_page_fixed,
            "titleOrLineFitsChanged": display_changed,
            "loaderRepairs": loader_repairs,
            "backup": str(backup),
            "validation": "passed",
        }, indent=2))
    finally:
        temporary_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
