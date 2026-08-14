from __future__ import annotations

import threading
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path

from .rom import DEFAULT_BANK_SIZE
from .rom_workbench import normalise_project
from .uef import UEFContents


SESSION_OWNER: ContextVar[str | None] = ContextVar("acorn_session_owner", default=None)


@dataclass
class ImageSession:
    """Mutable state for one image open in the workbench.

    The model lives outside ``DiskService`` because checkpoints, operations,
    downloads and menu services all consume the same session contract.
    """

    id: str
    name: str
    kind: str
    path: Path
    descriptor_name: str | None = None
    descriptor_path: Path | None = None
    dirty: bool = False
    slot_cache: dict[int, Path] = field(default_factory=dict)
    tape: UEFContents | None = None
    menu_slot: int | None = None
    menu_type: str | None = None
    menu_scanned: bool = False
    menu_entries: list[dict] | None = None
    adfs_menu_roots: list[str] | None = None
    slot_source_names: dict[int, str] = field(default_factory=dict)
    adfs_source_names: dict[str, str] = field(default_factory=dict)
    distribution_name: str | None = None
    target_hardware: str = "auto"
    hardware_profile: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    finalised_mtime_ns: int | None = None
    hfe_original_path: Path | None = None
    hfe_version: str | None = None
    hfe_read_only: bool = False
    hfe_layout: str | None = None
    hfe_export_path: Path | None = None
    rom_bank_size: int = DEFAULT_BANK_SIZE
    rom_erase_byte: int = 0xFF
    rom_platform: str = "bbc-master-electron"
    rom_layout: str = "linear"
    rom_component_names: list[str] = field(default_factory=list)
    rom_project: dict = field(default_factory=lambda: normalise_project({}))
    editor_projects: dict[str, dict] = field(default_factory=dict)
    content_kind_cache: dict[tuple, str] = field(default_factory=dict)
    owner_id: str | None = field(default_factory=lambda: SESSION_OWNER.get())
    lock: threading.RLock = field(default_factory=threading.RLock)


__all__ = ["ImageSession", "SESSION_OWNER"]
