from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .disk_service import DiskService, ImageSession


MENU_FILES = {"!BOOT", "GAMDATA", "GAMINDX", "PUBDATA", "PUBINDX", "UNIMENU"}


def _looks_like_holder(entries: list[dict]) -> bool:
    """Recognise bulk-copy grouping directories without mistaking a disk for one."""
    files = [
        item for item in entries
        if item.get("type") not in {"dir", "directory"}
        and str(item.get("name", "")).upper() not in MENU_FILES
    ]
    directories = [
        item for item in entries if item.get("type") in {"dir", "directory"}
    ]
    if files or not directories:
        return False
    generic = sum(
        bool(re.fullmatch(r"DISC-\d{4,}", str(item.get("name", "")), re.I))
        for item in directories
    )
    return len(directories) > 10 or generic >= max(2, (len(directories) * 3 + 3) // 4)


def discover_adfs_menu_paths(
    service: DiskService,
    session: ImageSession,
    root: str,
) -> tuple[list[str], list[str]]:
    """Return real software directories, expanding one structural holder layer."""
    root_listing = service.list_directory(session, root, None)
    paths: list[str] = []
    holders: list[str] = []
    for row in root_listing["entries"]:
        if row.get("type") not in {"dir", "directory"}:
            continue
        path = f"{root}.{row['name']}" if root != "$" else f"$.{row['name']}"
        listing = service.list_directory(session, path, None)
        if _looks_like_holder(listing["entries"]):
            holders.append(path)
            paths.extend(
                f"{path}.{child['name']}"
                for child in listing["entries"]
                if child.get("type") in {"dir", "directory"}
            )
        else:
            paths.append(path)
    return paths, holders


class MountedAdfsView:
    """Small DiskService-compatible read view backed by one open ADFS mount."""

    def __init__(self, mount):
        self.mount = mount
        self._listings: dict[str, dict] = {}

    def list_directory(self, _session: ImageSession, path: str, _slot: int | None) -> dict:
        if path in self._listings:
            return self._listings[path]
        rows = []
        for entry in self.mount.iter_entries(path):
            row = {
                "name": str(entry.name), "type": "dir" if entry.is_dir else "file",
                "length": int(entry.length or 0), "load": 0, "exec": 0,
            }
            if not entry.is_dir:
                try:
                    metadata = self.mount.acorn_meta(entry.path)
                    row["load"] = int(metadata.load_address or 0)
                    row["exec"] = int(metadata.exec_address or 0)
                except (AttributeError, OSError, RuntimeError, ValueError):
                    pass
            rows.append(row)
        directory_title = ""
        try:
            directory_title = str(self.mount._navigate(path).title or "")
        except (AttributeError, OSError, RuntimeError, ValueError):
            pass
        listing = {
            "entries": rows, "path": path, "title": directory_title,
            "directoryTitle": directory_title,
        }
        self._listings[path] = listing
        return listing

    def read_file(self, _session: ImageSession, _slot: int | None, path: str) -> bytes:
        return self.mount.read_bytes(path)


def scan_adfs_menu_directories(
    service: DiskService,
    session: ImageSession,
    root: str,
) -> tuple[list[dict], list[str]]:
    """Scan grouped ADFS software through one mount instead of many CLI processes."""
    from .menu_service import analyse_adfs_directory

    with service.adfs_mount(session) as mount:
        view = MountedAdfsView(mount)
        paths, holders = discover_adfs_menu_paths(view, session, root)
        metadata = [analyse_adfs_directory(view, session, path) for path in paths]
    return metadata, holders
