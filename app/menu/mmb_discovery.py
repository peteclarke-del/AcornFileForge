from __future__ import annotations

from typing import TYPE_CHECKING

from ..dfs_compat import dfs_catalogue_files

if TYPE_CHECKING:
    from ..disk_service import DiskService, ImageSession


MENU_FILES = {"!BOOT", "GAMDATA", "GAMINDX", "PUBDATA", "PUBINDX", "UNIMENU"}
SPI_GAME_MENU_FILES = {"!BOOT", "DOEXEC", "GAMECOL", "GAMDATA", "GAMINDX", "PUBDATA", "PUBINDX"}
UNIVERSAL_4R_FILES = {"!BOOT", "EGAMDAT", "EGAMIDX", "EPUBDAT", "EPUBIDX", "UNMNU4R"}
MMC_DESKTOP_FILES = {"!BOOT", "DISCCAT", "GO-DTOP", "GO-MMC"}
ELECTRON_MAGAZINE_FILES = {"!BOOT", "EUITEMS", "EUVOLUM", "MAGMENU", "UNIMENU"}
ACORN_USER_FILES = {"!BOOT", "AU1DATA", "AU2DATA", "UNIMENU"}


def is_mmb_menu_backup_title(value: object) -> bool:
    return str(value or "").upper().startswith("MBACKUP-")


def is_universal_menu(service: DiskService, session: ImageSession, slot: int) -> bool:
    try:
        names = {str(row["name"]).upper() for row in service.list_directory(session, "$", slot)["entries"]}
        return MENU_FILES.issubset(names)
    except Exception:
        return False


def find_menu_slot(service: DiskService, session: ImageSession) -> int | None:
    if session.menu_scanned:
        return session.menu_slot if getattr(session, "menu_type", None) != "mmc-desktop" else None
    fast_finder = getattr(service, "find_mmb_slot_with_catalogue_files", None)
    if fast_finder is not None and session.kind == "mmb":
        session.menu_slot = None
        session.menu_type = None
        for menu_type, files in (
            ("universal", MENU_FILES),
            ("universal-4r", UNIVERSAL_4R_FILES),
            ("spi-game-menu", SPI_GAME_MENU_FILES),
        ):
            session.menu_slot = fast_finder(session, files)
            if session.menu_slot is not None:
                session.menu_type = menu_type
                break
        session.menu_scanned = True
        return session.menu_slot
    for entry in service.list_slots(session):
        if entry["formatted"] and not is_mmb_menu_backup_title(entry.get("name")) and is_universal_menu(service, session, entry["slot"]):
            session.menu_slot = entry["slot"]
            session.menu_type = "universal"
            session.menu_scanned = True
            return session.menu_slot
    session.menu_scanned = True
    return None


def installed_mmb_menu(service: DiskService, session: ImageSession) -> tuple[int | None, str | None]:
    menus = installed_mmb_menus(service, session)
    if menus:
        return int(menus[0]["slot"]), str(menus[0]["type"])
    return None, None


def installed_mmb_menus(service: DiskService, session: ImageSession) -> list[dict]:
    """Return every recognised menu disk, including mixed-menu MMB images."""
    if session.kind != "mmb":
        return []
    signatures = (
        ("universal", MENU_FILES),
        ("universal-4r", UNIVERSAL_4R_FILES),
        ("spi-game-menu", SPI_GAME_MENU_FILES),
        ("electron-magazine", ELECTRON_MAGAZINE_FILES),
        ("acorn-user", ACORN_USER_FILES),
        ("mmc-desktop", MMC_DESKTOP_FILES),
    )
    bulk_finder = getattr(service, "find_mmb_slots_with_catalogue_files", None)
    finder = getattr(service, "find_mmb_slot_with_catalogue_files", None)
    if bulk_finder is not None:
        found = bulk_finder(session, dict(signatures))
        candidates = ((menu_type, found.get(menu_type)) for menu_type, _files in signatures)
    elif finder is not None:
        candidates = ((menu_type, finder(session, files)) for menu_type, files in signatures)
    else:
        slot = find_menu_slot(service, session)
        return [{"slot": slot, "type": session.menu_type or "universal"}] if slot is not None else []
    menus = []
    seen_slots = set()
    for menu_type, slot in candidates:
        if slot is not None and slot not in seen_slots:
            menus.append({"slot": slot, "type": menu_type})
            seen_slots.add(slot)
    session.menu_slot = int(menus[0]["slot"]) if menus else None
    session.menu_type = str(menus[0]["type"]) if menus else None
    session.menu_scanned = True
    return menus


def menu_type_from_ssd(data: bytes) -> str | None:
    names = {item.name.upper() for item in dfs_catalogue_files(data)}
    for menu_type, required in (
        ("universal", MENU_FILES),
        ("universal-4r", UNIVERSAL_4R_FILES),
        ("spi-game-menu", SPI_GAME_MENU_FILES),
        ("electron-magazine", ELECTRON_MAGAZINE_FILES),
        ("acorn-user", ACORN_USER_FILES),
        ("mmc-desktop", MMC_DESKTOP_FILES),
    ):
        if required.issubset(names):
            return menu_type
    return None
