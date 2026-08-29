"""Stable ADFS menu API for routes and analysis code."""

from ..adfs_menu_discovery import discover_adfs_menu_paths, scan_adfs_menu_directories
from ..menu_service import (
    append_adfs_menu_entries,
    append_adfs_menu_entry,
    audit_adfs_menu_pages,
    create_adfs_menu,
    delete_adfs_items,
    has_adfs_menu,
    installed_adfs_menus,
    move_adfs_items,
    reorder_adfs_menu,
    test_installed_adfs_menu_entries,
)

__all__ = [
    "append_adfs_menu_entries",
    "append_adfs_menu_entry",
    "audit_adfs_menu_pages",
    "create_adfs_menu",
    "delete_adfs_items",
    "discover_adfs_menu_paths",
    "has_adfs_menu",
    "installed_adfs_menus",
    "move_adfs_items",
    "reorder_adfs_menu",
    "scan_adfs_menu_directories",
    "test_installed_adfs_menu_entries",
]
