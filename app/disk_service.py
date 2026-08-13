from __future__ import annotations

import io
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import uuid
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Callable

from .checkpoints import CheckpointError, CheckpointStore
from .content_kind import LISTING_SNIFF_LIMIT, analyse_content, metadata_kind
from .formats import ADFS_EXTENSIONS, DFS_EXTENSIONS, HFE_EXTENSIONS, MMB_EXTENSIONS, ROM_EXTENSIONS, TAPE_EXTENSIONS
from .rom import (
    DEFAULT_BANK_SIZE,
    MAX_ROM_SIZE,
    RomError,
    bank_count,
    bank_number,
    inspect_bank as inspect_rom_bank,
    inspect_image as inspect_rom_image,
    make_sideways_template,
    parse_sideways_header,
    read_bank as read_rom_bank,
    validate_bank_size,
    validate_layout,
    validate_platform,
)
from .rom_workbench import normalise_project
from .editor_project import editor_project_key, normalise_editor_project
from .dfs_compat import repair_dfs_basic_wildcards
from .hfe import HFEError, HFEHeader, parse_hfe_header
from .uef import (
    TapeFile,
    UEFContents,
    UEFError,
    basic_unopened_channel_io,
    is_tokenized_basic,
    parse_uef,
    rewrite_basic_loader,
)


MMB_HEADER_SIZE = 8192
MMB_SLOT_SIZE = 204800
MMB_ENTRY_SIZE = 16
MMB_MAX_SLOTS = 511
COPY_BUFFER_SIZE = 8 * 1024 * 1024
FICLONE = 0x40049409
BEEBSCSI_SECTOR_SIZE = 256
BEEBSCSI_SECTORS_PER_TRACK = 33
BEEBSCSI_MAX_SECTORS = 0x1FFFFF
BEEBSCSI_MAX_SIZE = BEEBSCSI_MAX_SECTORS * BEEBSCSI_SECTOR_SIZE
ADFS_OLD_ROOT_OFFSET = 2 * BEEBSCSI_SECTOR_SIZE
ADFS_OLD_DIRECTORY_TAIL = 0x4CB
ADFS_OLD_DIRECTORY_SIZE = 5 * BEEBSCSI_SECTOR_SIZE
ADFS_OLD_DIRECTORY_ENTRY_OFFSET = 5
ADFS_OLD_DIRECTORY_ENTRY_SIZE = 26
ADFS_OLD_DIRECTORY_MAX_ENTRIES = 47


SESSION_OWNER: ContextVar[str | None] = ContextVar("acorn_session_owner", default=None)


class DiskError(RuntimeError):
    pass


class EmptyDiskError(DiskError):
    """Signals that a bulk extraction needs a user skip/abort decision."""

    def __init__(self, disk: dict):
        self.disk = disk
        super().__init__(
            f"MMB slot {disk['sourceSlot']} · {disk['sourceName']} has an empty DFS catalogue."
        )


class DestinationExistsError(DiskError):
    """Signals that a bulk extraction needs a keep/replace/abort decision."""

    def __init__(self, conflict: dict):
        self.conflict = conflict
        super().__init__(
            f"MMB slot {conflict['sourceSlot']} · {conflict['sourceName']} cannot use "
            f"{conflict['destination']} because that directory already exists."
        )


@dataclass
class ImageSession:
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


class DiskService:
    def __init__(self, work_dir: str | Path):
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.sessions: dict[str, ImageSession] = {}
        self._lock = threading.RLock()
        self.checkpoints = CheckpointStore(self._copy_local_file)

    @staticmethod
    @contextmanager
    def _locked_sessions(*sessions: ImageSession):
        """Acquire one or more session locks once, in a stable order."""
        locks = {
            id(session.lock): session.lock
            for session in sessions
        }
        with ExitStack() as stack:
            for _identity, lock in sorted(locks.items()):
                stack.enter_context(lock)
            yield

    @contextmanager
    def adfs_mount(self, session: ImageSession):
        """Open a trusted working ADFS image without probing or copying it.

        Oaknut's general-purpose resolver identifies an image from scratch on
        every command.  Its ADFS probe deliberately copies the whole image and
        walks the complete directory tree.  That is useful for an unknown host
        file, but wasteful for a session which was already identified when it
        was opened.  A BeebSCSI DAT can be hundreds of megabytes, so use one
        live mmap for the duration of an application operation instead.
        """
        if session.kind != "adfs":
            raise DiskError("This operation requires an ADFS image.")
        try:
            from oaknut.filesystem import create_filesystem, geometry_from_dsc, reader_for
        except ImportError as exc:
            raise DiskError("The Oaknut ADFS filesystem API is unavailable.") from exc

        with session.lock:
            reader = reader_for(session.path, writable=True)
            mount = None
            try:
                geometry = None
                if session.descriptor_path and session.descriptor_path.is_file():
                    geometry = geometry_from_dsc(session.descriptor_path.read_bytes())
                mount = create_filesystem("adfs").open(reader, geometry)
                yield mount
            except DiskError:
                raise
            except Exception as exc:
                raise DiskError(self._friendly_engine_error(str(exc))) from exc
            finally:
                # _ADFSMount does not currently expose close(), but its
                # DiscImage owns the memoryview borrowed from ImageReader.
                # Release that view before closing the mmap.
                if mount is not None:
                    adfs = getattr(mount, "_adfs", None)
                    unified = getattr(adfs, "_d", None)
                    disc_image = getattr(unified, "_disc_image", None)
                    try:
                        close_adfs = getattr(adfs, "close", None)
                        if callable(close_adfs):
                            close_adfs()
                    finally:
                        close_disc = getattr(disc_image, "close", None)
                        if callable(close_disc):
                            close_disc()
                reader.close()

    @contextmanager
    def romfs_mount(self, session: ImageSession, *, writable: bool = False):
        """Open one already-identified ROMFS image without probing it again."""
        if session.kind != "romfs":
            raise DiskError("This operation requires an Acorn ROMFS image.")
        if writable:
            self.require_writable_geometry(session)
        try:
            from oaknut.filesystem import create_filesystem, reader_for
        except ImportError as exc:
            raise DiskError("The Oaknut ROMFS filesystem API is unavailable.") from exc
        with session.lock:
            reader = reader_for(session.path, writable=writable)
            try:
                mount = create_filesystem("acorn-romfs").open(reader, None)
                yield mount
            except DiskError:
                raise
            except Exception as exc:
                raise DiskError(self._friendly_engine_error(str(exc))) from exc
            finally:
                reader.close()

    def romfs_details(self, session: ImageSession) -> dict:
        """Return decoded ROMFS identity, safety and capacity information."""
        try:
            from oaknut.romfs.romfs import ROMFS
            romfs = ROMFS.from_bytes(session.path.read_bytes())
        except Exception as exc:
            raise DiskError(f"The ROMFS catalogue is invalid: {exc}") from exc
        warnings = []
        if not romfs.is_complete:
            warnings.append(
                "The ROMFS block chain has no end marker. It may be truncated or one part of a multi-ROM set."
            )
        if romfs.is_complete and not romfs.is_plain:
            warnings.append(
                "Executable or opaque content follows the ROMFS catalogue, so this composite image is read-only."
            )
        fs_end = int(getattr(romfs, "_fs_end", session.path.stat().st_size))
        total = session.path.stat().st_size
        return {
            "title": romfs.title,
            "headerTitle": romfs.header_title,
            "version": romfs.version,
            "copyright": romfs.copyright,
            "romType": romfs.rom_type,
            "dataOffset": romfs.data_offset,
            "fileCount": len(romfs.data_files),
            "complete": romfs.is_complete,
            "plain": romfs.is_plain,
            "readOnly": not romfs.is_complete or not romfs.is_plain,
            "capacity": {
                "available": romfs.is_complete and romfs.is_plain,
                "unit": "bytes",
                "total": total,
                "used": min(total, fs_end),
                "free": max(0, total - fs_end),
                "reason": "Composite and multi-ROM images cannot report safely writable tail space."
                if not (romfs.is_complete and romfs.is_plain) else None,
            },
            "warnings": warnings,
        }

    def set_romfs_properties(
        self,
        session: ImageSession,
        *,
        title: str,
        version: int,
        copyright_text: str,
    ) -> None:
        """Update ROMFS catalogue and paged-ROM identity as one guarded edit."""
        if session.kind != "romfs":
            raise DiskError("This image does not contain an Acorn ROMFS filesystem.")
        title = str(title or "").strip()
        if not title or len(title) > 8:
            raise DiskError("A ROMFS title can contain 1 to 8 characters.")
        copyright_text = str(copyright_text or "").strip()
        if not copyright_text.startswith("(C)"):
            raise DiskError("A paged-ROM copyright must begin with (C).")
        if len(copyright_text) > 120:
            raise DiskError("A paged-ROM copyright can contain at most 120 characters.")
        try:
            version = int(version)
        except (TypeError, ValueError) as exc:
            raise DiskError("ROMFS version must be from 0 to 255.") from exc
        if not 0 <= version <= 255:
            raise DiskError("ROMFS version must be from 0 to 255.")
        original = session.path.read_bytes()
        try:
            with self.romfs_mount(session, writable=True) as mount:
                mount.set_title(title)
            from oaknut.romfs.romfs import set_copyright, set_version
            data = set_version(session.path.read_bytes(), version)
            session.path.write_bytes(set_copyright(data, copyright_text))
        except Exception as exc:
            session.path.write_bytes(original)
            raise DiskError(f"The ROMFS paged-ROM header could not be updated: {exc}") from exc
        self._mark_mutated(session, None)

    @staticmethod
    def _append_warning(session: ImageSession, warning: str) -> None:
        if warning not in session.warnings:
            session.warnings.append(warning)

    @staticmethod
    def safe_filename(name: str) -> str:
        name = Path(name or "image").name
        return re.sub(r"[^A-Za-z0-9._() +!-]", "_", name)[:180] or "image"

    def _persist_session(self, session: ImageSession) -> None:
        metadata = {
            "id": session.id,
            "name": session.name,
            "kind": session.kind,
            "descriptorName": session.descriptor_name,
            "descriptorFile": session.descriptor_path.name if session.descriptor_path else None,
            "slotSourceNames": {
                str(slot): name
                for slot, name in session.slot_source_names.items()
            },
            "adfsSourceNames": session.adfs_source_names,
            "distributionName": session.distribution_name,
            "targetHardware": session.target_hardware,
            "hardwareProfile": session.hardware_profile,
            "workingFile": session.path.name,
            "hfeOriginalFile": session.hfe_original_path.name if session.hfe_original_path else None,
            "hfeVersion": session.hfe_version,
            "hfeReadOnly": session.hfe_read_only,
            "hfeLayout": session.hfe_layout,
            "hfeExportFile": (
                session.hfe_export_path.name if session.hfe_export_path else None
            ),
            "romBankSize": session.rom_bank_size,
            "romEraseByte": session.rom_erase_byte,
            "romPlatform": session.rom_platform,
            "romLayout": session.rom_layout,
            "romComponentNames": session.rom_component_names,
            "romProject": session.rom_project,
            "editorProjects": session.editor_projects,
            "dirty": session.dirty,
            "finalisedMtimeNs": session.finalised_mtime_ns,
            "ownerId": session.owner_id,
            "warnings": session.warnings,
        }
        target = session.path.parent / "session.json"
        temporary = session.path.parent / "session.json.tmp"
        temporary.write_text(json.dumps(metadata, separators=(",", ":")), encoding="utf-8")
        temporary.replace(target)

    def _restore_session(self, image_id: str) -> ImageSession:
        if not re.fullmatch(r"[0-9a-f]{32}", image_id):
            raise DiskError("That image session no longer exists.")
        folder = self.work_dir / image_id
        metadata_path = folder / "session.json"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            name = self.safe_filename(metadata["name"])
            path = folder / self.safe_filename(metadata.get("workingFile") or name)
            if not path.is_file() or path.parent != folder:
                raise ValueError
            descriptor_name = metadata.get("descriptorName")
            descriptor_file = metadata.get("descriptorFile")
            descriptor_path = folder / descriptor_file if descriptor_file else None
            if descriptor_path and (not descriptor_path.is_file() or descriptor_path.parent != folder):
                descriptor_path = None
                descriptor_name = None
            kind = metadata.get("kind") or self.detect_kind(name)
            if kind not in {"mmb", "dfs", "adfs", "tape", "rom"}:
                raise ValueError
            session = ImageSession(
                id=image_id,
                name=name,
                kind=kind,
                path=path,
                descriptor_name=descriptor_name,
                descriptor_path=descriptor_path,
                dirty=bool(metadata.get("dirty", True)),
                slot_source_names={
                    int(slot): str(name)
                    for slot, name in metadata.get("slotSourceNames", {}).items()
                },
                adfs_source_names={
                    str(path): str(name)
                    for path, name in metadata.get("adfsSourceNames", {}).items()
                },
                distribution_name=metadata.get("distributionName"),
                target_hardware=str(metadata.get("targetHardware") or "auto"),
                hardware_profile=(
                    dict(metadata.get("hardwareProfile") or {})
                    if isinstance(metadata.get("hardwareProfile"), dict)
                    else {}
                ),
                hfe_original_path=(
                    folder / self.safe_filename(metadata["hfeOriginalFile"])
                    if metadata.get("hfeOriginalFile")
                    else None
                ),
                hfe_version=metadata.get("hfeVersion"),
                hfe_read_only=bool(metadata.get("hfeReadOnly")),
                hfe_layout=metadata.get("hfeLayout"),
                hfe_export_path=(
                    folder / self.safe_filename(metadata["hfeExportFile"])
                    if metadata.get("hfeExportFile")
                    else None
                ),
                rom_bank_size=validate_bank_size(int(metadata.get("romBankSize", DEFAULT_BANK_SIZE))),
                rom_erase_byte=int(metadata.get("romEraseByte", 0xFF)) & 0xFF,
                rom_platform=str(metadata.get("romPlatform") or "bbc-master-electron"),
                rom_layout=str(metadata.get("romLayout") or "linear"),
                rom_component_names=[
                    self.safe_filename(name)
                    for name in metadata.get("romComponentNames", [])
                    if name
                ],
                rom_project=normalise_project(metadata.get("romProject")),
                editor_projects={
                    str(key): normalise_editor_project(value)
                    for key, value in dict(metadata.get("editorProjects") or {}).items()
                },
                finalised_mtime_ns=(
                    int(metadata["finalisedMtimeNs"])
                    if metadata.get("finalisedMtimeNs") is not None
                    else None
                ),
                owner_id=metadata.get("ownerId"),
                warnings=[
                    str(warning)
                    for warning in metadata.get("warnings", [])
                    if "contains ambiguous ADFS command" not in str(warning)
                ],
            )
            if session.hfe_original_path and not session.hfe_original_path.is_file():
                raise ValueError
            if session.hfe_export_path and not session.hfe_export_path.is_file():
                session.hfe_export_path = None
            if session.kind == "tape":
                session.tape = parse_uef(path.read_bytes())
            self._normalise_beebscsi_dat_size(session)
            if session.descriptor_path and session.path.suffix.lower() == ".dat":
                self._optimise_sparse_file(session.path)
        except (OSError, KeyError, ValueError, json.JSONDecodeError, UEFError) as exc:
            raise DiskError("That image session no longer exists.") from exc
        with self._lock:
            self.sessions[image_id] = session
        return session

    @staticmethod
    def detect_kind(name: str) -> str:
        ext = Path(name).suffix.lower()
        if ext in MMB_EXTENSIONS:
            return "mmb"
        if ext in DFS_EXTENSIONS:
            return "dfs"
        if ext in ADFS_EXTENSIONS:
            return "adfs"
        if ext in TAPE_EXTENSIONS:
            return "tape"
        if ext in HFE_EXTENSIONS:
            return "hfe"
        if ext in ROM_EXTENSIONS:
            return "rom"
        return "unknown"

    def identify_kind(self, path: Path) -> str:
        result = self._run_json(["identify", "--as", "json", str(path)])
        rows = result.get("reports", {}).get("candidates", {}).get("rows", [])
        if not rows:
            raise DiskError("The file does not contain a recognised Acorn filesystem.")
        filesystem = str(rows[0].get("filesystem", "")).lower()
        if filesystem in {"acorn-dfs", "watford-dfs"}:
            return "dfs"
        if filesystem in {"adfs", "afs"}:
            return "adfs"
        if filesystem == "acorn-romfs":
            return "romfs"
        raise DiskError(f"The detected {filesystem or 'unknown'} filesystem is not supported.")

    @staticmethod
    def validate_leaf_name(session: ImageSession, name: str, slot: int | None = None) -> str:
        name = str(name or "")
        if session.kind == "romfs":
            if not name:
                raise DiskError("Enter a ROMFS filename.")
            if len(name) > 10:
                raise DiskError("ROMFS filenames can contain at most 10 characters.")
            try:
                name.encode("latin-1")
            except UnicodeEncodeError as exc:
                raise DiskError("ROMFS filenames must use Latin-1 characters.") from exc
            if "\0" in name or any(ord(char) < 32 for char in name):
                raise DiskError("ROMFS filenames cannot contain NUL or control characters in the editor.")
            return name
        name = name.strip()
        is_dfs = session.kind == "dfs" or (session.kind == "mmb" and slot is not None)
        limit = 7 if is_dfs else 10
        label = "DFS" if is_dfs else "ADFS"
        if not name:
            raise DiskError(f"Enter a {label} filename.")
        if len(name) > limit:
            raise DiskError(f"{label} filenames can contain at most {limit} characters.")
        if any(ord(char) < 32 or char in ".:*#/" for char in name):
            raise DiskError(f"“{name}” contains a character that cannot be used in a {label} filename.")
        return name

    @staticmethod
    def require_writable_geometry(session: ImageSession) -> None:
        if session.hfe_read_only:
            raise DiskError(
                "This HFE uses advanced track features or contains unreadable sectors. "
                "It can be browsed and copied from, but cannot be rewritten safely."
            )
        if session.kind == "romfs":
            try:
                from oaknut.romfs.romfs import ROMFS
                romfs = ROMFS.from_bytes(session.path.read_bytes())
            except Exception as exc:
                raise DiskError(f"The ROMFS image cannot be edited safely: {exc}") from exc
            if not romfs.is_complete:
                raise DiskError(
                    "This ROMFS image is incomplete or part of a multi-ROM set. "
                    "It can be browsed and extracted, but not rebuilt safely."
                )
            if not romfs.is_plain:
                raise DiskError(
                    "This composite ROMFS image contains executable code after its files. "
                    "It is read-only because moving that code could break absolute addresses."
                )
        if (
            session.kind == "adfs"
            and session.path.suffix.lower() == ".dat"
            and session.descriptor_path is None
        ):
            raise DiskError(
                "This BeebSCSI DAT image was opened without its matching DSC geometry file. "
                "Reopen the original DAT and DSC together before making changes."
            )

    def create_from_stream(
        self,
        name: str,
        stream: BinaryIO,
        descriptor: tuple[str, BinaryIO] | None = None,
        target_hardware: str = "auto",
        rom_options: dict | None = None,
        force_kind: str | None = None,
    ) -> ImageSession:
        safe_name = self.safe_filename(name)
        kind = self.detect_kind(safe_name)
        if force_kind:
            if force_kind != "rom":
                raise DiskError("Only the raw ROM format override is supported.")
            kind = force_kind
        if descriptor and not safe_name.lower().endswith(".dat"):
            raise DiskError("A DSC descriptor can only accompany a BeebSCSI DAT image.")
        if descriptor and Path(self.safe_filename(descriptor[0])).suffix.lower() != ".dsc":
            raise DiskError("The BeebSCSI geometry file must use the DSC extension.")
        if (
            safe_name.lower().endswith(".dat")
            and descriptor
            and Path(self.safe_filename(descriptor[0])).stem.casefold()
            != Path(safe_name).stem.casefold()
        ):
            raise DiskError(f"Choose {Path(safe_name).stem}.dsc for this DAT image.")
        image_id = uuid.uuid4().hex
        folder = self.work_dir / image_id
        folder.mkdir()
        path = folder / safe_name
        self._copy_stream(stream, path)

        descriptor_name = None
        descriptor_path = None
        if descriptor:
            descriptor_name = self.safe_filename(descriptor[0])
            descriptor_path = folder / descriptor_name
            self._copy_stream(descriptor[1], descriptor_path)

        try:
            return self._finalize_new_session(
                image_id,
                safe_name,
                path,
                descriptor_name,
                descriptor_path,
                kind,
                target_hardware,
                rom_options,
            )
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise

    def _finalize_new_session(
        self,
        image_id: str,
        name: str,
        path: Path,
        descriptor_name: str | None,
        descriptor_path: Path | None,
        kind: str,
        target_hardware: str = "auto",
        rom_options: dict | None = None,
    ) -> ImageSession:
        if kind == "hfe":
            path, kind, hfe_original, hfe_header, hfe_read_only, hfe_layout, hfe_warnings = self._open_hfe(path)
        else:
            hfe_original = None
            hfe_header = None
            hfe_read_only = False
            hfe_warnings = []
            hfe_layout = None
        # BIN is also used for ADFS images.  Prefer ROM only when the contents
        # carry a structurally valid sideways-ROM header; .rom is explicit.
        if kind == "adfs" and path.suffix.lower() == ".bin":
            with path.open("rb") as source:
                if parse_sideways_header(source.read(DEFAULT_BANK_SIZE)):
                    kind = "rom"
        if kind == "rom":
            try:
                if self.identify_kind(path) == "romfs":
                    kind = "romfs"
            except DiskError:
                pass
        identified = kind == "unknown"
        if identified:
            kind = self.identify_kind(path)
        session = ImageSession(
            id=image_id,
            name=name,
            kind=kind,
            path=path,
            descriptor_name=descriptor_name,
            descriptor_path=descriptor_path,
            target_hardware=self._target_hardware(target_hardware),
            hfe_original_path=hfe_original,
            hfe_version=hfe_header.version if hfe_header else None,
            hfe_read_only=hfe_read_only,
            hfe_layout=hfe_layout,
            warnings=hfe_warnings,
        )
        if kind == "mmb":
            self.list_slots(session)
        elif kind == "tape":
            try:
                session.tape = parse_uef(path.read_bytes())
            except UEFError as exc:
                raise DiskError(str(exc)) from exc
        elif kind == "rom":
            rom_options = rom_options or {}
            try:
                session.rom_platform = validate_platform(rom_options.get("platform"))
                session.rom_layout = validate_layout(rom_options.get("layout"))
            except RomError as exc:
                raise DiskError(str(exc)) from exc
            session.rom_component_names = [
                self.safe_filename(name)
                for name in rom_options.get("componentNames", [])
                if str(name).strip()
            ]
            size = path.stat().st_size
            if not size or size > MAX_ROM_SIZE:
                raise DiskError("ROM images must contain between 1 byte and 64 MiB.")
            if size % DEFAULT_BANK_SIZE:
                session.warnings.append(
                    f"The final ROM bank is partial ({size % DEFAULT_BANK_SIZE:,} bytes). "
                    "It is preserved exactly; choose another bank size if this layout is intentional."
                )
        elif kind == "romfs":
            details = self.romfs_details(session)
            if details["readOnly"]:
                session.warnings.extend(details["warnings"])
        elif not identified:
            detected_kind = self.identify_kind(path)
            if detected_kind != kind:
                session.kind = detected_kind
        self._normalise_beebscsi_dat_size(session)
        if session.descriptor_path and session.path.suffix.lower() == ".dat":
            self._optimise_sparse_file(session.path)
        self._apply_target_hardware(session)
        with self._lock:
            self.sessions[image_id] = session
        self._persist_session(session)
        return session

    @staticmethod
    def _hfe_working_suffix(kind: str, size: int, sides: int) -> str:
        if kind == "dfs":
            return ".dsd" if sides == 2 or size > MMB_SLOT_SIZE else ".ssd"
        return {163840: ".ads", 327680: ".adm", 655360: ".adl"}.get(size, ".adf")

    def _open_hfe(self, original: Path) -> tuple[Path, str, Path, HFEHeader, bool, str | None, list[str]]:
        try:
            with original.open("rb") as source:
                header = parse_hfe_header(source.read(512))
        except (OSError, HFEError) as exc:
            raise DiskError(str(exc)) from exc
        raw = original.parent / "hfe-decoded.img"
        info = self._run_hxcfe([f"-finput:{original}", "-infos"])
        self._run_hxcfe([
            f"-finput:{original}",
            "-conv:RAW_LOADER",
            f"-foutput:{raw}",
        ])
        if not raw.is_file() or not raw.stat().st_size:
            raise DiskError("The HFE image did not contain a usable sector filesystem.")
        kind = self.identify_kind(raw)
        hfe_layout = (
            {163840: "ACORN_ADFS_160K", 327680: "ACORN_ADFM_320K", 655360: "ACORN_ADFL_640K"}.get(raw.stat().st_size)
            if kind == "adfs"
            else None
        )
        working = raw.with_suffix(self._hfe_working_suffix(kind, raw.stat().st_size, header.sides))
        raw.replace(working)
        bad_match = re.search(r"Number of bad sectors\s*:\s*(\d+)", info, re.IGNORECASE)
        bad_sectors = int(bad_match.group(1)) if bad_match else 0
        read_only = header.advanced or bad_sectors > 0
        warnings = [
            f"Opened HFE {header.version}: {header.tracks} tracks, {header.sides} side"
            f"{'s' if header.sides != 1 else ''}, {header.bitrate or 'variable'} Kbit/s."
        ]
        if read_only:
            reason = "advanced timing/track features" if header.advanced else f"{bad_sectors} unreadable sector(s)"
            warnings.append(
                f"This HFE contains {reason}. It is read-only to preserve data that a sector editor cannot represent."
            )
        return working, kind, original, header, read_only, hfe_layout, warnings

    @staticmethod
    def _beebscsi_descriptor_size(descriptor_path: Path) -> int | None:
        """Return the device capacity declared by a BeebSCSI mode descriptor."""
        try:
            descriptor = descriptor_path.read_bytes()
        except OSError:
            return None
        if len(descriptor) < 16:
            return None
        cylinders = (descriptor[13] << 8) | descriptor[14]
        heads = descriptor[15]
        if not cylinders or not heads:
            return None
        return (
            cylinders
            * heads
            * BEEBSCSI_SECTORS_PER_TRACK
            * BEEBSCSI_SECTOR_SIZE
        )

    @staticmethod
    def _adfs_old_map_size(image_path: Path) -> int | None:
        """Return the filesystem extent stored in an old-format ADFS map."""
        try:
            with image_path.open("rb") as image:
                map_sector = image.read(BEEBSCSI_SECTOR_SIZE)
        except OSError:
            return None
        if len(map_sector) != BEEBSCSI_SECTOR_SIZE:
            return None
        sectors = int.from_bytes(map_sector[0xFC:0xFF], "little")
        if not sectors or sectors > BEEBSCSI_MAX_SECTORS:
            return None
        return sectors * BEEBSCSI_SECTOR_SIZE

    @staticmethod
    def _range_is_zero(path: Path, start: int) -> bool:
        """Check a prospective compatibility tail without loading it into RAM."""
        with path.open("rb") as image:
            image.seek(start)
            while chunk := image.read(COPY_BUFFER_SIZE):
                if chunk.strip(b"\0"):
                    return False
        return True

    @staticmethod
    def _target_hardware(value: str | None) -> str:
        profile = str(value or "auto").strip().lower()
        if profile not in {
            "auto",
            "electron-plus3",
            "bbc-master",
            "beebscsi",
            "risc-os",
        }:
            raise DiskError("Unknown ADFS target hardware profile.")
        return profile

    def _apply_target_hardware(self, session: ImageSession) -> None:
        """Apply repairs and checks required by the selected ADFS consumer."""
        if session.kind != "adfs" or session.target_hardware == "auto":
            return
        if session.target_hardware not in {
            "electron-plus3",
            "bbc-master",
            "beebscsi",
        }:
            return
        if session.target_hardware == "beebscsi" and (
            session.path.suffix.lower() != ".dat"
            or session.descriptor_path is None
        ):
            raise DiskError(
                "The BeebSCSI target requires a DAT image and its matching DSC."
            )
        if session.path.suffix.lower() == ".dat" and session.descriptor_path is None:
            raise DiskError(
                "This 8-bit BeebSCSI target requires the DAT and matching DSC "
                "to be opened together."
            )
        machine = {
            "electron-plus3": "Electron Plus 3 ADFS",
            "bbc-master": "BBC/Master 8-bit ADFS",
            "beebscsi": "BeebSCSI on Electron, BBC or Master",
        }[session.target_hardware]
        try:
            repairs = self._finalise_beebscsi_directories(session)
        except DiskError as exc:
            raise DiskError(f"This image is not compatible with {machine}: {exc}") from exc
        if repairs:
            self._append_warning(
                session,
                f"Repaired {repairs} old-ADFS directory sequence field"
                f"{'s' if repairs != 1 else ''} for {machine}.",
            )

    @staticmethod
    def _validate_created_beebscsi_pair(session: ImageSession) -> None:
        """Reject a newly created pair that real BeebSCSI firmware cannot mount."""
        descriptor_path = session.descriptor_path
        if descriptor_path is None:
            raise DiskError("The disk engine did not create the BeebSCSI DSC descriptor.")
        try:
            descriptor = descriptor_path.read_bytes()
            actual_size = session.path.stat().st_size
        except OSError as exc:
            raise DiskError("The new BeebSCSI DAT/DSC pair could not be verified.") from exc
        if len(descriptor) != 22:
            raise DiskError("The new BeebSCSI DSC descriptor is not exactly 22 bytes.")
        block_size = int.from_bytes(descriptor[9:12], "big")
        cylinders = int.from_bytes(descriptor[13:15], "big")
        heads = descriptor[15]
        if block_size != BEEBSCSI_SECTOR_SIZE or not cylinders or not 1 <= heads <= 16:
            raise DiskError("The new BeebSCSI DSC contains unsupported hardware geometry.")
        expected_size = (
            cylinders
            * heads
            * BEEBSCSI_SECTORS_PER_TRACK
            * block_size
        )
        if expected_size > BEEBSCSI_MAX_SIZE:
            raise DiskError(
                "The requested BeebSCSI image exceeds ADFS's 21-bit sector limit "
                f"of {BEEBSCSI_MAX_SIZE:,} bytes."
            )
        map_size = DiskService._adfs_old_map_size(session.path)
        if map_size is None:
            raise DiskError(
                "The new BeebSCSI DAT does not contain a valid old-format ADFS map."
            )
        if map_size > expected_size:
            raise DiskError(
                "The ADFS filesystem is larger than the capacity declared by its DSC."
            )
        if actual_size != map_size:
            raise DiskError(
                "The BeebSCSI DAT must end at the ADFS map boundary; its DSC may "
                "declare a slightly larger device geometry."
            )

    @staticmethod
    def _canonicalise_created_beebscsi_root(
        session: ImageSession,
        title: str,
    ) -> None:
        """Write the CR-terminated old-directory fields expected by BBC ADFS."""
        tail = ADFS_OLD_ROOT_OFFSET + ADFS_OLD_DIRECTORY_TAIL
        try:
            with session.path.open("r+b") as image:
                image.seek(ADFS_OLD_ROOT_OFFSET)
                header = image.read(5)
                image.seek(tail + 47)
                footer = image.read(6)
                if (
                    len(header) != 5
                    or header[1:5] != b"Hugo"
                    or len(footer) != 6
                    or footer[0] != header[0]
                    or footer[1:5] != b"Hugo"
                    or footer[5] != 0
                ):
                    raise DiskError(
                        "The disk engine created an invalid ADFS root directory."
                    )

                # OldDirName and OldDirTitle are CR-terminated strings. Some
                # desktop tools tolerate NUL-only padding, but BBC ADFS does
                # not consistently do so on hard-disc volumes.
                directory_name = b"$\r".ljust(10, b"\0")
                title_bytes = title.encode("ascii", "replace")[:18]
                directory_title = (title_bytes + b"\r").ljust(19, b"\0")
                image.seek(tail + 1)
                image.write(directory_name)
                image.seek(tail + 14)
                image.write(directory_title)
        except OSError as exc:
            raise DiskError(
                "The new BeebSCSI ADFS root directory could not be finalised."
            ) from exc

    def _normalise_beebscsi_dat_size(self, session: ImageSession) -> None:
        """Keep a DAT at the ADFS extent used by official BeebSCSI images."""
        if (
            session.path.suffix.lower() != ".dat"
            or session.descriptor_path is None
        ):
            return
        geometry_size = self._beebscsi_descriptor_size(session.descriptor_path)
        if geometry_size is None:
            self._append_warning(
                session,
                "The DSC geometry could not be read; the DAT size was left unchanged.",
            )
            return
        map_size = self._adfs_old_map_size(session.path)
        if map_size is None:
            self._append_warning(
                session,
                "The old-format ADFS map size could not be read; the DAT size was "
                "left unchanged.",
            )
            return
        actual = session.path.stat().st_size
        if map_size > geometry_size:
            self._append_warning(
                session,
                f"The ADFS filesystem is {map_size - geometry_size:,} bytes larger "
                "than the DSC device capacity; the DAT was left unchanged.",
            )
            return
        if actual > map_size and self._range_is_zero(session.path, map_size):
            with session.path.open("r+b") as image:
                image.truncate(map_size)
            session.dirty = True
            self._append_warning(
                session,
                f"Removed an all-zero {actual - map_size:,}-byte geometry tail so "
                "the DAT matches the official BeebSCSI ADFS layout.",
            )
        elif actual > map_size:
            self._append_warning(
                session,
                f"The DAT contains non-zero data beyond its ADFS map boundary and "
                "was not truncated.",
            )
        elif actual < map_size:
            self._append_warning(
                session,
                f"The DAT is {map_size - actual:,} bytes shorter than its ADFS map "
                "extent and was not padded because filesystem data may be missing.",
            )

    @staticmethod
    def _optimise_sparse_file(path: Path) -> None:
        """Turn allocated zero ranges into holes without changing file bytes."""
        try:
            original = path.stat()
            subprocess.run(
                ["fallocate", "--dig-holes", str(path)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            os.utime(
                path,
                ns=(original.st_atime_ns, original.st_mtime_ns),
                follow_symlinks=False,
            )
        except (OSError, subprocess.CalledProcessError):
            # Sparse optimisation is an optional performance improvement. The
            # image remains valid on filesystems or platforms without it.
            return

    @staticmethod
    def _finalise_beebscsi_directories(session: ImageSession) -> int:
        """Synchronise old ADFS directory sequence numbers for BBC hardware.

        Old ADFS stores a directory's master sequence both in the directory
        block and in its entry in the parent directory. Desktop tools can
        traverse a tree when these differ, but BBC ADFS reports ``Broken
        directory``. Oaknut currently increments the directory copy while
        editing without updating the parent copy, so repair the relationship
        before a BeebSCSI pair leaves the application.
        """
        if session.kind != "adfs":
            return 0

        image_size = session.path.stat().st_size
        seen: set[int] = set()
        patches: list[tuple[int, int]] = []

        def display_name(raw: bytes) -> str:
            plain = bytes(value & 0x7F for value in raw)
            end = next(
                (index for index, value in enumerate(plain) if value in (0, 13)),
                len(plain),
            )
            return plain[:end].decode("ascii", "replace") or "?"

        with session.lock, session.path.open("r+b") as image:
            def visit(
                sector: int,
                expected_parent: int,
                path: str,
            ) -> int:
                offset = sector * BEEBSCSI_SECTOR_SIZE
                if (
                    sector in seen
                    or sector < 2
                    or offset + ADFS_OLD_DIRECTORY_SIZE > image_size
                ):
                    raise DiskError(
                        f"The BeebSCSI directory tree is invalid at {path}."
                    )
                seen.add(sector)
                image.seek(offset)
                data = image.read(ADFS_OLD_DIRECTORY_SIZE)
                tail = ADFS_OLD_DIRECTORY_TAIL
                signature = data[1:5]
                if (
                    signature != b"Hugo"
                    or data[tail + 48 : tail + 52] != signature
                    or data[tail + 47] != data[0]
                    or data[tail + 52] != 0
                ):
                    raise DiskError(
                        f"The BeebSCSI directory metadata is invalid at {path}."
                    )
                parent = int.from_bytes(data[tail + 11 : tail + 14], "little")
                if parent != expected_parent:
                    raise DiskError(
                        f"The BeebSCSI parent link is invalid at {path}."
                    )

                # Do not reinterpret the sequence value here. The Plus 3 ROM
                # tests the two directory copies for equality; guessing an
                # encoding after the event can silently change the identity
                # of a directory. Only synchronise the parent copy below.
                sequence = data[0]

                for index in range(ADFS_OLD_DIRECTORY_MAX_ENTRIES):
                    entry = (
                        ADFS_OLD_DIRECTORY_ENTRY_OFFSET
                        + index * ADFS_OLD_DIRECTORY_ENTRY_SIZE
                    )
                    if data[entry] == 0:
                        break
                    name_bytes = data[entry : entry + 10]
                    if not name_bytes[3] & 0x80:
                        continue
                    child_sector = int.from_bytes(
                        data[entry + 22 : entry + 25],
                        "little",
                    )
                    child_path = f"{path}.{display_name(name_bytes)}"
                    child_sequence = visit(child_sector, sector, child_path)
                    if data[entry + 25] != child_sequence:
                        patches.append((offset + entry + 25, child_sequence))
                return sequence

            visit(2, 2, "$")
            for offset, sequence in patches:
                image.seek(offset)
                image.write(bytes((sequence,)))

        if patches:
            session.dirty = True
        return len(patches)

    @staticmethod
    def _old_map_checksum(block: bytes | bytearray) -> int:
        """Return the Acorn checksum for one old-map sector.

        ADFS processes bytes &FE back to &00 and carries an overflow into
        the *next* byte processed.  That makes byte order significant; a
        forward end-around sum happens to agree for many maps, but can be
        one out after the free-space list changes.
        """
        checksum = 0
        carry = 0
        for value in reversed(block[: BEEBSCSI_SECTOR_SIZE - 1]):
            total = checksum + value + carry
            checksum = total & 0xFF
            carry = 1 if total > 0xFF else 0
        return checksum

    @staticmethod
    def _advance_beebscsi_disc_id(session: ImageSession) -> bool:
        """Give a changed DAT a new old-map identity and valid checksum."""
        with session.lock:
            source_mtime = session.path.stat().st_mtime_ns
            if session.finalised_mtime_ns == source_mtime:
                return False
            with session.path.open("r+b") as image:
                map_data = bytearray(image.read(2 * BEEBSCSI_SECTOR_SIZE))
                if len(map_data) != 2 * BEEBSCSI_SECTOR_SIZE:
                    raise DiskError("The BeebSCSI free-space map is incomplete.")
                if (
                    DiskService._old_map_checksum(map_data[:256]) != map_data[255]
                    or DiskService._old_map_checksum(map_data[256:]) != map_data[511]
                ):
                    raise DiskError("The BeebSCSI free-space map checksum is invalid.")
                disc_id = (int.from_bytes(map_data[507:509], "little") + 1) & 0xFFFF
                map_data[507:509] = disc_id.to_bytes(2, "little")
                map_data[511] = DiskService._old_map_checksum(map_data[256:])
                image.seek(256)
                image.write(map_data[256:])
            session.dirty = True
            session.finalised_mtime_ns = session.path.stat().st_mtime_ns
            return True

    def prepare_download(
        self,
        session: ImageSession,
        progress: Callable[[str, int | None, int | None], None] | None = None,
    ) -> Path:
        """Finalise an image so the downloaded bytes are hardware-ready."""
        report = progress or (lambda _message, _current=None, _total=None: None)
        is_beebscsi = bool(
            session.descriptor_path and session.path.suffix.lower() == ".dat"
        )
        if is_beebscsi:
            self._optimise_sparse_file(session.path)
        if (
            is_beebscsi
            and not session.dirty
            and session.finalised_mtime_ns == session.path.stat().st_mtime_ns
        ):
            report("The previously validated hardware-ready pair is prepared", 1, 1)
            return session.path
        total = 5 if is_beebscsi else 2
        report("Applying the selected hardware profile", 0, total)
        # A paired DAT receives the same directory validation immediately
        # below. Avoid traversing a large directory tree twice during save.
        if not is_beebscsi:
            self._apply_target_hardware(session)
        if is_beebscsi:
            report("Checking DAT size against the DSC geometry", 1, total)
            self._normalise_beebscsi_dat_size(session)
            report("Checking old-ADFS directory copies", 2, total)
            repairs = self._finalise_beebscsi_directories(session)
            if repairs:
                self._append_warning(
                    session,
                    f"Repaired {repairs} old-ADFS directory sequence field"
                    f"{'s' if repairs != 1 else ''} for 8-bit hardware.",
                )
            report("Updating the ADFS disc identity and map checksum", 3, total)
            if self._advance_beebscsi_disc_id(session):
                self._append_warning(
                    session,
                    "Advanced the ADFS disc ID and rebuilt its map checksum so "
                    "8-bit ADFS recognises the edited volume as changed.",
                )
            report("Validating the final DAT and DSC pair", 4, total)
            self._validate_created_beebscsi_pair(session)
            self._optimise_sparse_file(session.path)
            report("The hardware-ready pair is prepared", total, total)
        if session.hfe_original_path:
            report("Encoding and verifying the HFE image", 1, total)
            output = self._prepare_hfe_download(session)
            report("The hardware-ready image is prepared", total, total)
            return output
        if not is_beebscsi:
            report("The hardware-ready image is prepared", total, total)
        return session.path

    def _prepare_hfe_download(self, session: ImageSession) -> Path:
        if not session.dirty:
            if session.hfe_export_path and session.hfe_export_path.is_file():
                return session.hfe_export_path
            return session.hfe_original_path
        self.require_writable_geometry(session)
        output = session.path.parent / f"{Path(session.name).stem}-edited.hfe"
        verification = session.path.parent / "hfe-save-check.img"
        output.unlink(missing_ok=True)
        verification.unlink(missing_ok=True)
        self._run_hxcfe([
            f"-finput:{session.path}",
            *([f"-uselayout:{session.hfe_layout}"] if session.hfe_layout else []),
            "-conv:HXC_HFE",
            f"-foutput:{output}",
            f"-reffile:{session.hfe_original_path}",
        ])
        self._run_hxcfe([
            f"-finput:{output}",
            "-conv:RAW_LOADER",
            f"-foutput:{verification}",
        ])
        try:
            if verification.read_bytes() != session.path.read_bytes():
                raise DiskError(
                    "The edited sectors did not survive HFE encoding exactly, so the original HFE was left unchanged."
                )
        finally:
            verification.unlink(missing_ok=True)
        session.hfe_export_path = output
        return output

    def mark_saved(self, session: ImageSession) -> None:
        """Record that the current working bytes have been prepared for download."""
        with session.lock:
            session.dirty = False
            self._persist_session(session)

    @staticmethod
    def _copy_stream(stream: BinaryIO, target: Path) -> None:
        """Use an in-kernel copy for spooled uploads, with a portable fallback."""
        seekable = getattr(stream, "seekable", lambda: False)()
        start = stream.tell() if seekable else None
        with target.open("wb") as output:
            try:
                source_fd = stream.fileno()
                while os.sendfile(
                    output.fileno(),
                    source_fd,
                    None,
                    COPY_BUFFER_SIZE,
                ):
                    pass
                return
            except (AttributeError, io.UnsupportedOperation, OSError):
                output.seek(0)
                output.truncate()
                if start is not None:
                    stream.seek(start)
                shutil.copyfileobj(stream, output, length=COPY_BUFFER_SIZE)

    @staticmethod
    def _copy_local_file(source: Path, target: Path) -> None:
        """Clone or sparsely copy a local image without allocating zero ranges."""
        try:
            import fcntl

            with source.open("rb") as source_file, target.open("wb") as target_file:
                fcntl.ioctl(target_file.fileno(), FICLONE, source_file.fileno())
            return
        except OSError:
            target.unlink(missing_ok=True)
        try:
            subprocess.run(
                [
                    "cp",
                    "--reflink=auto",
                    "--sparse=always",
                    "--",
                    str(source),
                    str(target),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        except (OSError, subprocess.CalledProcessError):
            target.unlink(missing_ok=True)
        shutil.copyfile(source, target)

    def get(self, image_id: str) -> ImageSession:
        try:
            session = self.sessions[image_id]
        except KeyError:
            session = self._restore_session(image_id)
        owner_id = SESSION_OWNER.get()
        if owner_id is None:
            return session
        if not session.owner_id or not secrets.compare_digest(
            session.owner_id,
            owner_id,
        ):
            raise DiskError("That image session no longer exists.")
        return session

    def recoverable_sessions(self, limit: int = 50) -> list[dict]:
        """List persisted working images without opening their large data files."""
        recovered: list[dict] = []
        owner_id = SESSION_OWNER.get()
        for metadata_path in self.work_dir.glob("*/session.json"):
            image_id = metadata_path.parent.name
            if not re.fullmatch(r"[0-9a-f]{32}", image_id):
                continue
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                persisted_owner = metadata.get("ownerId")
                if owner_id is not None and persisted_owner != owner_id:
                    continue
                name = self.safe_filename(metadata["name"])
                working_name = self.safe_filename(metadata.get("workingFile") or name)
                image_path = metadata_path.parent / working_name
                if not image_path.is_file() or image_path.parent != metadata_path.parent:
                    continue
                stat = image_path.stat()
                descriptor_file = metadata.get("descriptorFile")
                descriptor_path = (
                    metadata_path.parent / self.safe_filename(descriptor_file)
                    if descriptor_file
                    else None
                )
                recovered.append({
                    "id": image_id,
                    "name": name,
                    "kind": str(metadata.get("kind") or self.detect_kind(name)),
                    "size": stat.st_size,
                    "modified": stat.st_mtime_ns // 1_000_000,
                    "hasDescriptor": bool(descriptor_path and descriptor_path.is_file()),
                    "targetHardware": str(metadata.get("targetHardware") or "auto"),
                })
            except (OSError, KeyError, ValueError, json.JSONDecodeError):
                continue
        recovered.sort(key=lambda item: item["modified"], reverse=True)
        return recovered[: max(1, min(int(limit), 100))]

    def clear_recoverable_sessions(self, image_ids: list[str] | None = None) -> int:
        """Delete only working copies owned by the current browser identity."""
        owner_id = SESSION_OWNER.get()
        if owner_id is None:
            raise DiskError("Session ownership is unavailable for this request.")
        requested = set(image_ids) if image_ids is not None else None
        removed = 0
        for metadata_path in tuple(self.work_dir.glob("*/session.json")):
            image_id = metadata_path.parent.name
            if requested is not None and image_id not in requested:
                continue
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                persisted_owner = str(metadata.get("ownerId") or "")
                if not persisted_owner or not secrets.compare_digest(persisted_owner, owner_id):
                    continue
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            with self._lock:
                self.sessions.pop(image_id, None)
            shutil.rmtree(metadata_path.parent, ignore_errors=True)
            removed += 1
        return removed

    def discard_session(self, session: ImageSession) -> None:
        with self._lock:
            self.sessions.pop(session.id, None)
        shutil.rmtree(session.path.parent, ignore_errors=True)

    def rename_session(self, session: ImageSession, requested_name: str) -> None:
        """Rename an image for display, recovery and download without moving its working file."""
        requested_name = str(requested_name or "").strip()
        if not requested_name or requested_name != Path(requested_name).name:
            raise DiskError("Enter a filename without a directory path.")

        current_suffix = Path(session.name).suffix
        requested_suffix = Path(requested_name).suffix
        if current_suffix:
            if not requested_suffix:
                requested_name += current_suffix
            elif requested_suffix.casefold() != current_suffix.casefold():
                raise DiskError(f"Keep the {current_suffix} extension for this image.")
        elif requested_suffix:
            raise DiskError("This image has no extension; keep its filename extensionless.")

        safe_name = self.safe_filename(requested_name)
        if safe_name != requested_name:
            raise DiskError("Use letters, numbers, spaces and ordinary filename punctuation only.")
        if not Path(safe_name).stem:
            raise DiskError("Enter a filename before the extension.")
        if safe_name == session.name:
            return

        with session.lock:
            session.name = safe_name
            if session.descriptor_path:
                descriptor_suffix = Path(session.descriptor_name or ".dsc").suffix or ".dsc"
                session.descriptor_name = f"{Path(safe_name).stem}{descriptor_suffix}"
            session.hfe_export_path = None
            self._persist_session(session)

    def list_checkpoints(self, session: ImageSession) -> list[dict]:
        with session.lock:
            return self.checkpoints.list(session)

    def create_checkpoint(
        self,
        session: ImageSession,
        name: str,
        *,
        automatic: bool = False,
        reason: str | None = None,
    ) -> dict:
        with session.lock:
            try:
                return self.checkpoints.create(
                    session,
                    name,
                    automatic=automatic,
                    reason=reason,
                )
            except CheckpointError as exc:
                raise DiskError(str(exc)) from exc

    def begin_automatic_checkpoint(self, session: ImageSession, reason: str) -> dict:
        """Capture the image before one API operation and return a finalisation token."""
        with session.lock:
            fingerprint = self.checkpoints.fingerprint(session)
            checkpoint = self.create_checkpoint(
                session,
                f"Before {reason}",
                automatic=True,
                reason=reason,
            )
        return {"checkpoint": checkpoint, "fingerprint": fingerprint}

    def finish_automatic_checkpoint(self, session: ImageSession, token: dict) -> None:
        """Discard a speculative undo point when the request changed nothing."""
        with session.lock:
            try:
                unchanged = self.checkpoints.fingerprint(session) == token["fingerprint"]
            except OSError:
                unchanged = False
            if unchanged:
                try:
                    self.checkpoints.delete(session, token["checkpoint"]["id"])
                except CheckpointError:
                    pass
            else:
                self.checkpoints.prune_automatic(session)
            # Every API mutation passes through this finaliser. Persist the
            # resulting dirty/export state here so recovery cannot resurrect
            # an edited image as though it were still saved.
            self._persist_session(session)

    def rollback_automatic_checkpoint(self, session: ImageSession, token: dict) -> None:
        """Restore a failed mutation and remove its now-redundant undo point."""
        checkpoint_id = str(token["checkpoint"]["id"])
        self.restore_checkpoint(session, checkpoint_id)
        try:
            self.delete_checkpoint(session, checkpoint_id)
        except DiskError:
            pass

    def restore_checkpoint(self, session: ImageSession, checkpoint_id: str) -> dict:
        with session.lock:
            try:
                restored = self.checkpoints.restore(session, checkpoint_id)
            except CheckpointError as exc:
                raise DiskError(str(exc)) from exc
            for cached in session.slot_cache.values():
                cached.unlink(missing_ok=True)
            session.slot_cache.clear()
            session.menu_slot = None
            session.menu_type = None
            session.menu_scanned = False
            session.menu_entries = None
            session.adfs_menu_roots = None
            session.hfe_export_path = None
            session.finalised_mtime_ns = None
            if session.kind == "tape":
                try:
                    session.tape = parse_uef(session.path.read_bytes())
                except UEFError as exc:
                    raise DiskError(str(exc)) from exc
            self._persist_session(session)
            return restored

    def undo_last_change(self, session: ImageSession) -> dict:
        with session.lock:
            latest = self.checkpoints.latest_automatic(session)
            if latest is None:
                raise DiskError("There is no automatic checkpoint to undo.")
            restored = self.restore_checkpoint(session, latest["id"])
            try:
                self.checkpoints.delete(session, latest["id"])
            except CheckpointError as exc:
                raise DiskError(str(exc)) from exc
            return restored

    def delete_checkpoint(self, session: ImageSession, checkpoint_id: str) -> None:
        with session.lock:
            try:
                self.checkpoints.delete(session, checkpoint_id)
            except CheckpointError as exc:
                raise DiskError(str(exc)) from exc

    def summary(self, session: ImageSession) -> dict:
        checkpoints = self.list_checkpoints(session)
        romfs = self.romfs_details(session) if session.kind == "romfs" else None
        return {
            "id": session.id,
            "name": session.name,
            "kind": session.kind,
            "size": session.path.stat().st_size,
            "dirty": session.dirty,
            "hasDescriptor": bool(session.descriptor_path),
            "descriptorName": session.descriptor_name,
            "doubleSided": session.path.name.lower().endswith(".dsd"),
            "containerFormat": "hfe" if session.hfe_original_path else None,
            "readOnly": session.hfe_read_only or bool(romfs and romfs["readOnly"]),
            "rom": ({
                "bankSize": session.rom_bank_size,
                "bankCount": bank_count(session.path.stat().st_size, session.rom_bank_size),
                "eraseByte": session.rom_erase_byte,
                "platform": session.rom_platform,
                "layout": session.rom_layout,
                "componentNames": session.rom_component_names,
                "project": session.rom_project,
            } if session.kind == "rom" else None),
            "romfs": romfs,
            "targetHardware": session.target_hardware,
            "hardwareProfile": session.hardware_profile,
            "warnings": [
                *session.warnings,
                *(list(session.tape.warnings) if session.tape else []),
            ],
            "checkpoints": {
                "total": len(checkpoints),
                "named": sum(not item["automatic"] for item in checkpoints),
                "canUndo": any(item["automatic"] for item in checkpoints),
            },
        }

    def list_slots(self, session: ImageSession) -> list[dict]:
        size = session.path.stat().st_size
        if size < MMB_HEADER_SIZE + MMB_SLOT_SIZE:
            raise DiskError("The MMB image is too small to contain a disk.")
        count = min(MMB_MAX_SLOTS, (size - MMB_HEADER_SIZE) // MMB_SLOT_SIZE)
        with session.path.open("rb") as image:
            header = image.read(MMB_HEADER_SIZE)
        slots = []
        for number in range(count):
            offset = 16 + number * MMB_ENTRY_SIZE
            entry = header[offset : offset + MMB_ENTRY_SIZE]
            if len(entry) < MMB_ENTRY_SIZE:
                break
            status = entry[15]
            title = entry[:12].decode("latin-1", "replace").rstrip("\0 ")
            formatted = status < 0x80
            invalid = status == 0xFF
            slots.append(
                {
                    "slot": number,
                    "name": title if formatted and title else ("Untitled disk" if formatted else "Empty slot"),
                    "legacyTitle": title if not formatted else "",
                    "type": "disk",
                    "formatted": formatted,
                    "empty": not formatted,
                    "writable": 0 < status < 0x80,
                    "invalid": invalid,
                    "status": status,
                }
            )
        return slots

    def preview_image_contents(
        self,
        session: ImageSession,
        limit: int = 500,
    ) -> dict:
        """Return a bounded, read-only preview suitable for an import plan."""
        limit = max(1, min(int(limit), 1000))
        if session.kind == "rom":
            rows = self.list_rom_banks(session)
            return {
                "entries": [{
                    "path": f"Bank {row['bank']:03d}",
                    "name": row["name"],
                    "type": "ROM bank",
                    "size": row["length"],
                    "detail": row["filetype"],
                } for row in rows[:limit]],
                "total": len(rows),
                "truncated": len(rows) > limit,
                "summary": f"{len(rows)} ROM bank(s) of {session.rom_bank_size:,} bytes",
            }
        if session.kind == "romfs":
            listing = self.list_directory(session, "$", None)
            rows = listing["entries"]
            return {
                "entries": [{
                    "path": row["path"],
                    "name": row["name"],
                    "type": "ROMFS file",
                    "size": row["length"],
                    "detail": f"load &{row['load']:X} · execute &{row['exec']:X} · {row['attr']}",
                } for row in rows[:limit]],
                "total": len(rows),
                "truncated": len(rows) > limit,
                "summary": f"{len(rows)} file(s) in {listing['title']} ROMFS",
            }
        if session.kind == "mmb":
            slots = [slot for slot in self.list_slots(session) if slot["formatted"]]
            entries = [
                {
                    "path": f"Slot {slot['slot']}",
                    "name": slot["name"],
                    "type": "disk",
                    "detail": "read / write" if slot["writable"] else "read-only",
                }
                for slot in slots[:limit]
            ]
            return {
                "entries": entries,
                "total": len(slots),
                "truncated": len(slots) > limit,
                "summary": f"{len(slots)} formatted MMB disk slot(s)",
            }
        if session.kind == "tape":
            tape = self._tape(session)
            entries = [
                {
                    "path": "$",
                    "name": item.name,
                    "type": "file",
                    "size": len(item.data),
                    "detail": "complete" if item.complete else "incomplete",
                }
                for item in tape.files[:limit]
            ]
            return {
                "entries": entries,
                "total": len(tape.files),
                "truncated": len(tape.files) > limit,
                "summary": f"{len(tape.files)} reconstructed tape file(s)",
            }

        entries: list[dict] = []
        pending: list[tuple[str, int | None]] = []
        if session.kind == "dfs" and session.path.name.lower().endswith(".dsd"):
            pending.extend([("", 0), ("", 2)])
        elif session.kind == "dfs":
            pending.append(("", None))
        else:
            pending.append(("$", None))
        visited: set[tuple[str, int | None]] = set()
        truncated = False
        while pending:
            path, side = pending.pop(0)
            identity = (path.casefold(), side)
            if identity in visited:
                continue
            visited.add(identity)
            listing = self.list_directory(session, path, None, side)
            prefix = f"Side {side}" if side is not None else path
            for row in listing["entries"]:
                if session.kind == "dfs" and row.get("virtual"):
                    pending.append((str(row.get("name") or "$"), side))
                    continue
                if len(entries) >= limit:
                    truncated = True
                    break
                name = str(row.get("name") or "Untitled")
                item_path = (
                    f"$.{name}" if path == "$" else f"{path}.{name}"
                )
                entries.append({
                    "path": prefix,
                    "name": name,
                    "type": row.get("type", "file"),
                    "size": row.get("size"),
                    "detail": (
                        f"load {row.get('loadHex')} · exec {row.get('executeHex')}"
                        if row.get("loadHex") or row.get("executeHex")
                        else ""
                    ),
                })
                if session.kind == "adfs" and row.get("type") == "dir":
                    pending.append((item_path, None))
            if truncated:
                break
        return {
            "entries": entries,
            "total": len(entries),
            "truncated": truncated or bool(pending),
            "summary": f"{len(entries)} visible object(s)" + (" or more" if truncated else ""),
        }

    def find_mmb_slot_with_catalogue_files(
        self,
        session: ImageSession,
        required_names: set[str],
    ) -> int | None:
        """Find a DFS menu slot directly, without mounting every MMB disk."""
        return self.find_mmb_slots_with_catalogue_files(
            session,
            {"match": required_names},
        ).get("match")

    def find_mmb_slots_with_catalogue_files(
        self,
        session: ImageSession,
        required_groups: dict[str, set[str]],
    ) -> dict[str, int]:
        """Find several DFS menu signatures in one sequential catalogue scan."""
        if session.kind != "mmb":
            return {}
        pending = {
            key: {str(name).upper() for name in names}
            for key, names in required_groups.items()
        }
        matches = {}
        slots = self.list_slots(session)
        with session.lock, session.path.open("rb") as image:
            for entry in slots:
                if not pending:
                    break
                if not entry["formatted"]:
                    continue
                if str(entry.get("name") or "").upper().startswith("MBACKUP-"):
                    continue
                slot = int(entry["slot"])
                image.seek(MMB_HEADER_SIZE + slot * MMB_SLOT_SIZE)
                catalogue = image.read(512)
                if len(catalogue) != 512:
                    continue
                file_count = (catalogue[256 + 5] & 0xF8) // 8
                if file_count > 31:
                    continue
                names = {
                    catalogue[8 + offset * 8 : 15 + offset * 8]
                    .decode("latin-1", "replace")
                    .rstrip("\0 ")
                    .upper()
                    for offset in range(file_count)
                }
                for key, required in tuple(pending.items()):
                    if required.issubset(names):
                        matches[key] = slot
                        del pending[key]
        return matches

    def create_blank(
        self,
        format_name: str,
        title: str,
        capacity: str | None = None,
        target_hardware: str = "auto",
        options: dict | None = None,
    ) -> ImageSession:
        hfe_formats = {
            "hfe-ssd": "ssd",
            "hfe-dsd": "dsd",
            "hfe-adfs-s": "adfs-s",
            "hfe-adfs-m": "adfs-m",
            "hfe-adfs-l": "adfs-l",
        }
        target_hardware = self._blank_target_hardware(
            format_name,
            target_hardware,
        )
        native_format = hfe_formats.get(format_name, format_name)
        formats = {
            "ssd": ("blank.ssd", []),
            "dsd": ("blank.dsd", []),
            "adfs-s": ("blank.ads", []),
            "adfs-m": ("blank.adm", []),
            "adfs-l": ("blank.adl", []),
            "beebscsi": (
                "scsi0.dat",
                ["--geometry", f"capacity={capacity or '20MB'}"],
            ),
            "adfs-hard": (
                "blank.dat",
                ["--geometry", f"capacity={capacity or '20MB'}"],
            ),
            "adfs-physical": (
                "blank.dat",
                ["--geometry", f"capacity={capacity or '20MB'}"],
            ),
        }
        if native_format == "romfs":
            options = options or {}
            geometry = str(options.get("geometry") or capacity or "16k").lower().replace("ib", "").replace(" ", "")
            geometry = {"8k": "8k", "8ki": "8k", "8192": "8k", "16k": "16k", "16ki": "16k", "16384": "16k"}.get(geometry, geometry)
            if geometry not in {"8k", "16k"}:
                raise DiskError("ROMFS images can be 8 KiB or 16 KiB.")
            romfs_title = str(title or "ROMFS").strip()
            if not romfs_title or len(romfs_title) > 8:
                raise DiskError("A created ROMFS title can contain 1 to 8 characters.")
            copyright_text = str(options.get("copyright") or "(C) 2026 Acorn File Forge").strip()
            if not copyright_text.startswith("(C)"):
                raise DiskError("A paged-ROM copyright must begin with (C).")
            if len(copyright_text) > 120:
                raise DiskError("A paged-ROM copyright can contain at most 120 characters.")
            try:
                version = int(str(options.get("version", 1)), 0)
            except ValueError as exc:
                raise DiskError("ROMFS version must be from 0 to 255.") from exc
            if not 0 <= version <= 255:
                raise DiskError("ROMFS version must be from 0 to 255.")
            image_id = uuid.uuid4().hex
            folder = self.work_dir / image_id
            folder.mkdir()
            path = folder / f"{self.safe_filename(romfs_title) or 'ROMFS'}.rom"
            try:
                self._run([
                    "create", "--filesystem", "acorn-romfs", "--geometry", geometry,
                    "--title", romfs_title, str(path),
                ])
                from oaknut.romfs.romfs import set_copyright, set_version
                data = set_version(path.read_bytes(), version)
                data = set_copyright(data, copyright_text)
                path.write_bytes(data)
                session = ImageSession(
                    image_id, path.name, "romfs", path, dirty=True,
                    target_hardware=self._target_hardware(target_hardware),
                )
            except Exception as exc:
                shutil.rmtree(folder, ignore_errors=True)
                if isinstance(exc, DiskError):
                    raise
                raise DiskError(f"The ROMFS image could not be created: {exc}") from exc
        elif native_format == "rom":
            options = options or {}
            try:
                bank_size = validate_bank_size(int(options.get("bankSize", DEFAULT_BANK_SIZE)))
                total_size = int(options.get("totalSize", bank_size))
            except (TypeError, ValueError, RomError) as exc:
                raise DiskError(str(exc) or "Choose valid ROM dimensions.") from exc
            if total_size < 1 or total_size > MAX_ROM_SIZE:
                raise DiskError("ROM images must contain between 1 byte and 64 MiB.")
            erase_byte = int(options.get("eraseByte", 0xFF)) & 0xFF
            image_id = uuid.uuid4().hex
            folder = self.work_dir / image_id
            folder.mkdir()
            path = folder / f"{self.safe_filename(title) or 'blank'}.rom"
            try:
                template = str(options.get("template") or "blank")
                first = (
                    make_sideways_template(bank_size, title, erase_byte)
                    if template == "sideways"
                    else bytes((erase_byte,)) * min(bank_size, total_size)
                )
                with path.open("wb") as image:
                    image.write(first[:total_size])
                    if total_size > len(first):
                        chunk = bytes((erase_byte,)) * min(COPY_BUFFER_SIZE, total_size - len(first))
                        remaining = total_size - len(first)
                        while remaining:
                            part = chunk[:remaining]
                            image.write(part)
                            remaining -= len(part)
                session = ImageSession(
                    image_id, path.name, "rom", path, dirty=True,
                    rom_bank_size=bank_size,
                    rom_erase_byte=erase_byte,
                    rom_platform=validate_platform(options.get("platform")),
                    rom_layout=validate_layout(options.get("layout")),
                    rom_component_names=[
                        self.safe_filename(name)
                        for name in options.get("componentNames", [])
                        if name
                    ],
                )
            except Exception:
                shutil.rmtree(folder, ignore_errors=True)
                raise
        elif native_format == "mmb":
            image_id = uuid.uuid4().hex
            folder = self.work_dir / image_id
            folder.mkdir()
            path = folder / "blank.mmb"
            try:
                header = bytearray(MMB_HEADER_SIZE)
                header[:4] = bytes((0, 1, 2, 3))
                for slot in range(MMB_MAX_SLOTS):
                    header[16 + slot * MMB_ENTRY_SIZE + 15] = 0xF0
                with path.open("wb") as image:
                    image.write(header)
                    image.truncate(MMB_HEADER_SIZE + MMB_MAX_SLOTS * MMB_SLOT_SIZE)
                session = ImageSession(image_id, path.name, "mmb", path, dirty=True)
            except Exception:
                shutil.rmtree(folder, ignore_errors=True)
                raise
        else:
            try:
                filename, extra = formats[native_format]
            except KeyError as exc:
                raise DiskError("Unknown blank image format.") from exc
            image_id = uuid.uuid4().hex
            folder = self.work_dir / image_id
            folder.mkdir()
            path = folder / filename
            try:
                self._run(["create", *extra, "--title", title[:12], str(path)])
                generated_descriptor = path.with_suffix(".dsc")
                output_names = {
                    "adfs-hard": "HardDisc4.hdf",
                    "adfs-physical": "physical-drive.raw",
                }
                if native_format in output_names:
                    output_path = folder / output_names[native_format]
                    path.replace(output_path)
                    path = output_path
                    generated_descriptor.unlink(missing_ok=True)
                descriptor_path = (
                    generated_descriptor
                    if native_format == "beebscsi" and generated_descriptor.is_file()
                    else None
                )
                if native_format == "beebscsi" and descriptor_path is None:
                    raise DiskError(
                        "The disk engine did not create the BeebSCSI DSC descriptor."
                    )
                session = ImageSession(
                    image_id,
                    path.name,
                    self.detect_kind(path.name),
                    path,
                    descriptor_name=descriptor_path.name if descriptor_path else None,
                    descriptor_path=descriptor_path,
                    dirty=True,
                    target_hardware=self._target_hardware(target_hardware),
                )
                self._normalise_beebscsi_dat_size(session)
                if native_format == "beebscsi":
                    self._canonicalise_created_beebscsi_root(session, title[:12])
                    self._validate_created_beebscsi_pair(session)
                self._apply_target_hardware(session)
                if native_format == "beebscsi":
                    self._optimise_sparse_file(session.path)
                if format_name in hfe_formats:
                    original = folder / f"{self.safe_filename(title) or 'blank'}.hfe"
                    hfe_layout = {
                        "hfe-adfs-s": "ACORN_ADFS_160K",
                        "hfe-adfs-m": "ACORN_ADFM_320K",
                        "hfe-adfs-l": "ACORN_ADFL_640K",
                    }.get(format_name)
                    self._run_hxcfe([
                        f"-finput:{path}",
                        *([f"-uselayout:{hfe_layout}"] if hfe_layout else []),
                        "-conv:HXC_HFE",
                        f"-foutput:{original}",
                    ])
                    header = parse_hfe_header(original.read_bytes()[:512])
                    session.name = original.name
                    session.hfe_original_path = original
                    session.hfe_version = header.version
                    session.hfe_layout = hfe_layout
                    session.warnings.append(
                        f"Created an editable HFE {header.version} container around {path.suffix[1:].upper()}."
                    )
            except Exception:
                shutil.rmtree(folder, ignore_errors=True)
                raise
        with self._lock:
            self.sessions[session.id] = session
        self._persist_session(session)
        return session

    @staticmethod
    def _blank_target_hardware(
        format_name: str,
        requested: str | None,
    ) -> str:
        """Apply only target profiles that are meaningful for a new format."""
        forced = {
            "beebscsi": "beebscsi",
            "adfs-hard": "risc-os",
            "adfs-physical": "risc-os",
        }
        if format_name in forced:
            return forced[format_name]
        selectable_adfs = {
            "adfs-s",
            "adfs-m",
            "adfs-l",
            "hfe-adfs-s",
            "hfe-adfs-m",
            "hfe-adfs-l",
        }
        if format_name == "romfs":
            requested = str(requested or "auto")
            return requested if requested in {"auto", "electron-plus3", "bbc-master"} else "auto"
        if format_name in selectable_adfs:
            return str(requested or "auto")
        return "auto"

    @staticmethod
    def _dfs_title(data: bytes) -> str:
        if len(data) < 512:
            return ""
        return (data[:8] + data[256:260]).decode("latin-1", "replace").rstrip("\0 ")

    @staticmethod
    def _split_dsd(data: bytes) -> tuple[bytes, bytes]:
        if len(data) != MMB_SLOT_SIZE * 2:
            raise DiskError("An MMB can only accept a standard 400 KiB DSD image.")
        track_size = 10 * 256
        side_0 = b"".join(data[offset : offset + track_size] for offset in range(0, len(data), track_size * 2))
        side_2 = b"".join(data[offset : offset + track_size] for offset in range(track_size, len(data), track_size * 2))
        return side_0, side_2

    def _write_slot(self, session: ImageSession, slot: int, data: bytes, title: str | None = None) -> None:
        slot = self._check_slot(session, slot)
        if len(data) > MMB_SLOT_SIZE:
            raise DiskError("The SSD image is larger than a 200 KiB MMB slot.")
        padded = data.ljust(MMB_SLOT_SIZE, b"\0")
        display_title = (title or self._dfs_title(padded) or f"DISK{slot:03d}")
        title_bytes = display_title.encode("latin-1", "replace")[:12].ljust(12, b"\0")
        with session.lock, session.path.open("r+b") as image:
            image.seek(16 + slot * MMB_ENTRY_SIZE)
            image.write(title_bytes + b"\0\0\0" + b"\x0f")
            image.seek(MMB_HEADER_SIZE + slot * MMB_SLOT_SIZE)
            image.write(padded)
        session.slot_cache.pop(slot, None)
        session.dirty = True

    def insert_slot_bytes(
        self,
        session: ImageSession,
        slot: int,
        data: bytes,
        filename: str,
        display_title: str | None = None,
    ) -> list[int]:
        if session.kind != "mmb":
            raise DiskError("Disk images can only be inserted into MMB slots.")
        suffix = Path(filename).suffix.lower()
        validation_path = session.path.parent / f"validate-{uuid.uuid4().hex}{suffix}"
        validation_path.write_bytes(data)
        try:
            self._run(["validate", str(validation_path)])
        finally:
            validation_path.unlink(missing_ok=True)
        if suffix == ".dsd":
            if slot + 1 >= MMB_MAX_SLOTS:
                raise DiskError("A DSD needs two adjacent MMB slots.")
            sides = self._split_dsd(data)
            slots = self.list_slots(session)
            if not slots[slot]["empty"] or not slots[slot + 1]["empty"]:
                raise DiskError("A DSD needs two adjacent empty MMB slots.")
            repaired_sides = []
            for side_index, side in enumerate(sides):
                repaired, changes = repair_dfs_basic_wildcards(side)
                repaired_sides.append(repaired)
                for change in changes:
                    self._append_warning(
                        session,
                        f"MMFS compatibility change on DSD side {side_index + 1}: {change}.",
                    )
            self._write_slot(session, slot, repaired_sides[0], display_title)
            self._write_slot(session, slot + 1, repaired_sides[1], display_title)
            return [slot, slot + 1]
        if suffix != ".ssd":
            raise DiskError("Only SSD or DSD images can be inserted into an MMB.")
        data, changes = repair_dfs_basic_wildcards(data)
        for change in changes:
            self._append_warning(session, f"MMFS compatibility change: {change}.")
        self._write_slot(session, slot, data, display_title)
        return [slot]

    def insert_slot_from_session(
        self,
        target: ImageSession,
        target_slot: int,
        source: ImageSession,
        source_slot: int | None,
    ) -> list[int]:
        if source.kind == "mmb":
            if source_slot is None:
                raise DiskError("Select an MMB source disk first.")
            data = self._slot_path(source, source_slot).read_bytes()
            filename = "disk.ssd"
            display_title = self.list_slots(source)[source_slot]["name"]
        elif source.kind == "dfs":
            data = source.path.read_bytes()
            filename = source.name
            visible_title = Path(source.name).stem
            display_title = visible_title if visible_title.casefold() != "blank" else None
        else:
            raise DiskError("Only DFS disks can be inserted into an MMB.")
        inserted = self.insert_slot_bytes(target, target_slot, data, filename, display_title)
        if source.hfe_read_only:
            self._append_warning(
                target,
                "Inserted the readable DFS sectors from an advanced HFE. "
                "Track timing, weak bits and protection data cannot be stored in an MMB slot.",
            )
        source_name = (
            source.slot_source_names.get(source_slot)
            if source.kind == "mmb" and source_slot is not None
            else source.distribution_name or source.name
        )
        if source_name:
            self.set_slot_source_name(target, inserted, source_name)
        return inserted

    def set_slot_source_name(
        self,
        session: ImageSession,
        slots: list[int],
        source_name: str,
    ) -> None:
        safe_name = str(source_name).replace("\\", "/")[-500:]
        for slot in slots:
            session.slot_source_names[self._check_slot(session, int(slot))] = safe_name
        self._persist_session(session)

    def set_adfs_source_name(
        self,
        session: ImageSession,
        path: str,
        source_name: str,
    ) -> None:
        session.adfs_source_names[str(path)] = str(source_name).replace(
            "\\",
            "/",
        )[-500:]
        self._persist_session(session)

    def set_distribution_name(
        self,
        session: ImageSession,
        source_name: str,
    ) -> None:
        session.distribution_name = str(source_name).replace("\\", "/")[-500:]
        self._persist_session(session)

    def clear_slot(self, session: ImageSession, slot: int) -> None:
        self.clear_slots(session, [slot])

    def clear_slots(self, session: ImageSession, slot_numbers: list[int]) -> list[int]:
        checked = list(dict.fromkeys(self._check_slot(session, int(slot)) for slot in slot_numbers))
        if not checked:
            raise DiskError("Select at least one MMB disk to eject.")
        with session.lock, session.path.open("r+b") as image:
            for slot in checked:
                image.seek(16 + slot * MMB_ENTRY_SIZE)
                image.write(b"\0" * 15 + b"\xf0")
                image.seek(MMB_HEADER_SIZE + slot * MMB_SLOT_SIZE)
                image.write(b"\0" * MMB_SLOT_SIZE)
        for slot in checked:
            session.slot_cache.pop(slot, None)
            session.slot_source_names.pop(slot, None)
            if session.menu_slot == slot:
                session.menu_slot = None
                session.menu_type = None
                session.menu_scanned = True
                session.menu_entries = None
        session.dirty = True
        self._persist_session(session)
        return checked

    def protect_slot(self, session: ImageSession, slot: int, writable: bool) -> None:
        self.protect_slots(session, [slot], writable)

    def protect_slots(
        self,
        session: ImageSession,
        slot_numbers: list[int],
        writable: bool,
    ) -> list[int]:
        slots = self.list_slots(session)
        checked = list(dict.fromkeys(self._check_slot(session, int(slot)) for slot in slot_numbers))
        if not checked:
            raise DiskError("Select at least one formatted MMB slot.")
        empty = [slot for slot in checked if not slots[slot]["formatted"]]
        if empty:
            raise DiskError(
                "Empty MMB slots cannot be marked read-only or read/write."
            )
        with session.lock, session.path.open("r+b") as image:
            for slot in checked:
                image.seek(16 + slot * MMB_ENTRY_SIZE + 15)
                image.write(b"\x0f" if writable else b"\x00")
        session.dirty = True
        return checked

    def move_slot(self, session: ImageSession, source_slot: int, target_slot: int) -> None:
        source_slot = self._check_slot(session, source_slot)
        target_slot = self._check_slot(session, target_slot)
        if source_slot == target_slot:
            return
        with session.lock, session.path.open("r+b") as image:
            image.seek(16 + source_slot * MMB_ENTRY_SIZE)
            source_entry = image.read(MMB_ENTRY_SIZE)
            image.seek(16 + target_slot * MMB_ENTRY_SIZE)
            target_entry = image.read(MMB_ENTRY_SIZE)
            image.seek(MMB_HEADER_SIZE + source_slot * MMB_SLOT_SIZE)
            source_data = image.read(MMB_SLOT_SIZE)
            image.seek(MMB_HEADER_SIZE + target_slot * MMB_SLOT_SIZE)
            target_data = image.read(MMB_SLOT_SIZE)
            image.seek(16 + source_slot * MMB_ENTRY_SIZE)
            image.write(target_entry)
            image.seek(16 + target_slot * MMB_ENTRY_SIZE)
            image.write(source_entry)
            image.seek(MMB_HEADER_SIZE + source_slot * MMB_SLOT_SIZE)
            image.write(target_data)
            image.seek(MMB_HEADER_SIZE + target_slot * MMB_SLOT_SIZE)
            image.write(source_data)
        session.slot_cache.pop(source_slot, None)
        session.slot_cache.pop(target_slot, None)
        if session.menu_slot == source_slot:
            session.menu_slot = target_slot
        elif session.menu_slot == target_slot:
            session.menu_slot = source_slot
        source_name = session.slot_source_names.pop(source_slot, None)
        target_name = session.slot_source_names.pop(target_slot, None)
        if source_name is not None:
            session.slot_source_names[target_slot] = source_name
        if target_name is not None:
            session.slot_source_names[source_slot] = target_name
        self._persist_session(session)
        session.dirty = True

    def paste_mmb_slots(
        self,
        source: ImageSession,
        target: ImageSession,
        source_slots: list[int],
        target_start: int,
        *,
        cut: bool = False,
        replace: bool = False,
    ) -> dict:
        """Copy an MMB slot selection while preserving gaps and safe overlap.

        Source bytes are snapshotted before anything is written.  That makes an
        overlapping cut within one MMB behave like a block move, rather than a
        sequence of swaps which can destroy a later source slot.
        """
        if source.kind != "mmb" or target.kind != "mmb":
            raise DiskError("MMB slot paste requires an MMB source and destination.")
        checked = sorted({self._check_slot(source, int(slot)) for slot in source_slots})
        source_index = self.list_slots(source)
        checked = [slot for slot in checked if source_index[slot]["formatted"]]
        if not checked:
            raise DiskError("Copy or cut at least one formatted MMB slot first.")
        target_start = self._check_slot(target, int(target_start))
        first = checked[0]
        mapping = [(slot, target_start + slot - first) for slot in checked]
        target_count = len(self.list_slots(target))
        if any(destination >= target_count for _slot, destination in mapping):
            raise DiskError(
                "The pasted slot range would extend beyond the end of the MMB image."
            )
        same_image = source.id == target.id
        if same_image and all(slot == destination for slot, destination in mapping):
            return {
                "pasted": False,
                "noChange": True,
                "sourceSlots": checked,
                "targetSlots": [destination for _slot, destination in mapping],
                "conflicts": [],
            }

        target_index = self.list_slots(target)
        available_cut_slots = set(checked) if cut and same_image else set()
        conflicts = [
            {
                "slot": destination,
                "name": target_index[destination]["name"],
            }
            for _slot, destination in mapping
            if target_index[destination]["formatted"]
            and destination not in available_cut_slots
        ]
        if conflicts and not replace:
            return {
                "pasted": False,
                "sourceSlots": checked,
                "targetSlots": [destination for _slot, destination in mapping],
                "conflicts": conflicts,
            }

        snapshots: dict[int, tuple[bytes, bytes, str | None]] = {}
        with self._locked_sessions(source, target):
            with source.path.open("rb") as image:
                for slot in checked:
                    image.seek(16 + slot * MMB_ENTRY_SIZE)
                    entry = image.read(MMB_ENTRY_SIZE)
                    image.seek(MMB_HEADER_SIZE + slot * MMB_SLOT_SIZE)
                    disk = image.read(MMB_SLOT_SIZE)
                    if len(entry) != MMB_ENTRY_SIZE or len(disk) != MMB_SLOT_SIZE:
                        raise DiskError(f"MMB slot {slot} could not be read completely.")
                    snapshots[slot] = (
                        entry,
                        disk,
                        source.slot_source_names.get(slot),
                    )

            if cut:
                with source.path.open("r+b") as image:
                    for slot in checked:
                        image.seek(16 + slot * MMB_ENTRY_SIZE)
                        image.write(b"\0" * 15 + b"\xf0")
                        image.seek(MMB_HEADER_SIZE + slot * MMB_SLOT_SIZE)
                        image.write(b"\0" * MMB_SLOT_SIZE)

            with target.path.open("r+b") as image:
                for slot, destination in mapping:
                    entry, disk, _source_name = snapshots[slot]
                    image.seek(16 + destination * MMB_ENTRY_SIZE)
                    image.write(entry)
                    image.seek(MMB_HEADER_SIZE + destination * MMB_SLOT_SIZE)
                    image.write(disk)

        destinations = {destination for _slot, destination in mapping}
        if cut:
            for slot in checked:
                source.slot_cache.pop(slot, None)
                source.slot_source_names.pop(slot, None)
        for slot, destination in mapping:
            target.slot_cache.pop(destination, None)
            target.slot_source_names.pop(destination, None)
            source_name = snapshots[slot][2]
            if source_name is not None:
                target.slot_source_names[destination] = source_name

        if cut and same_image and source.menu_slot in checked:
            source.menu_slot = dict(mapping)[source.menu_slot]
        elif target.menu_slot in destinations and target.menu_slot not in {
            destination for slot, destination in mapping if slot == source.menu_slot
        }:
            target.menu_slot = None
            target.menu_type = None
            target.menu_scanned = False
            target.menu_entries = None

        source.dirty = source.dirty or cut
        target.dirty = True
        if cut and not same_image:
            self._persist_session(source)
        self._persist_session(target)
        return {
            "pasted": True,
            "sourceSlots": checked,
            "targetSlots": [destination for _slot, destination in mapping],
            "conflicts": conflicts,
            "cut": cut,
        }

    def set_mmb_drive_mapping(
        self,
        session: ImageSession,
        drive: int,
        slot: int,
    ) -> None:
        """Set one power-on MMFS drive mapping in the 16-byte MMB header."""
        if session.kind != "mmb":
            raise DiskError("Drive mappings are only stored in MMB images.")
        if drive not in range(4):
            raise DiskError("An MMB drive number must be from 0 to 3.")
        slot = self._check_slot(session, slot)
        with session.lock, session.path.open("r+b") as image:
            image.seek(drive)
            image.write(bytes((slot & 0xFF,)))
            image.seek(4 + drive)
            image.write(bytes(((slot >> 8) & 0xFF,)))
        session.dirty = True
        self._persist_session(session)

    def rename_slot(self, session: ImageSession, slot: int, title: str) -> None:
        title_bytes = title.encode("latin-1", "replace")[:12].ljust(12, b"\0")
        with session.lock, session.path.open("r+b") as image:
            image.seek(16 + self._check_slot(session, slot) * MMB_ENTRY_SIZE)
            image.write(title_bytes)
        session.dirty = True

    def _check_slot(self, session: ImageSession, slot: int) -> int:
        count = min(MMB_MAX_SLOTS, (session.path.stat().st_size - MMB_HEADER_SIZE) // MMB_SLOT_SIZE)
        if slot < 0 or slot >= count:
            raise DiskError("MMB slot is out of range.")
        return slot

    def _slot_path(self, session: ImageSession, slot: int) -> Path:
        slot = self._check_slot(session, slot)
        cached = session.slot_cache.get(slot)
        if cached and cached.exists():
            return cached
        path = session.path.parent / f"slot-{slot:03d}.ssd"
        with session.lock, session.path.open("rb") as source, path.open("wb") as target:
            source.seek(MMB_HEADER_SIZE + slot * MMB_SLOT_SIZE)
            data = source.read(MMB_SLOT_SIZE)
            if len(data) != MMB_SLOT_SIZE:
                raise DiskError("The MMB slot is truncated.")
            target.write(data)
        session.slot_cache[slot] = path
        return path

    def slot_download(self, session: ImageSession, slot: int) -> tuple[bytes, str]:
        """Return one formatted MMB slot as a standalone DFS SSD image."""
        if session.kind != "mmb":
            raise DiskError("This image is not an MMB container.")
        checked = self._check_slot(session, int(slot))
        entry = self.list_slots(session)[checked]
        if not entry["formatted"]:
            raise DiskError("That MMB slot is empty.")
        stem = self.safe_filename(str(entry.get("name") or f"slot-{checked:03d}"))
        if stem.lower().endswith(".ssd"):
            stem = stem[:-4]
        with session.lock:
            data = self._slot_path(session, checked).read_bytes()
        return data, f"{stem or f'slot-{checked:03d}'}.ssd"

    def _sync_slot(self, session: ImageSession, slot: int) -> None:
        slot_path = self._slot_path(session, slot)
        data = slot_path.read_bytes()
        if len(data) > MMB_SLOT_SIZE:
            raise DiskError("The edited DFS disk no longer fits in its MMB slot.")
        with session.lock, session.path.open("r+b") as target:
            target.seek(MMB_HEADER_SIZE + slot * MMB_SLOT_SIZE)
            target.write(data.ljust(MMB_SLOT_SIZE, b"\0"))
        session.dirty = True

    def _mark_mutated(
        self,
        session: ImageSession,
        slot: int | None,
    ) -> None:
        """Persist an edited MMB working slot or mark a direct image dirty."""
        if session.kind == "mmb":
            if slot is None:
                raise DiskError("Select an MMB disk slot first.")
            self._sync_slot(session, slot)
        else:
            session.dirty = True
        session.hfe_export_path = None
        session.content_kind_cache.clear()

    def resolve(self, session: ImageSession, slot: int | None) -> Path:
        if session.kind != "mmb":
            return session.path
        if slot is None:
            raise DiskError("Select an MMB disk slot first.")
        return self._slot_path(session, slot)

    @staticmethod
    def inner_for(session: ImageSession, inner: str, side: int | None) -> str:
        if session.kind == "romfs":
            return "" if inner in {"", "$"} else inner
        if not session.path.name.lower().endswith(".dsd"):
            return inner
        drive = 2 if side == 2 else 0
        if inner == "":
            return f":{drive}"
        if inner == "$":
            return f":{drive}.$"
        return f":{drive}.{inner}"

    @staticmethod
    def compound(path: Path, inner: str | None = None) -> str:
        return f"{path}:{inner}" if inner is not None else str(path)

    @staticmethod
    def _capacity_from_mount(mount) -> dict:
        try:
            total = max(0, int(mount.size_bytes()))
            free = min(total, max(0, int(mount.free_bytes())))
        except (AttributeError, TypeError, ValueError):
            return {
                "available": False,
                "reason": "This filesystem does not report free-space capacity.",
            }
        return {
            "available": total > 0,
            "unit": "bytes",
            "total": total,
            "used": total - free,
            "free": free,
        }

    def _listing_content_kind(
        self,
        session: ImageSession,
        slot: int | None,
        side: int | None,
        path: str,
        row: dict,
        reader: Callable[[], bytes],
    ) -> str | None:
        """Classify one listed file without remounting or reading large payloads."""
        hint = metadata_kind(str(row.get("name") or ""), row.get("filetype"))
        if hint:
            return hint
        length = int(row.get("length") or 0)
        if length <= 0 or length > LISTING_SNIFF_LIMIT:
            return None
        key = (
            slot, side, str(path).casefold(), length,
            int(row.get("load") or 0), int(row.get("exec") or 0), str(row.get("filetype") or ""),
        )
        cached = session.content_kind_cache.get(key)
        if cached:
            return cached
        try:
            kind = analyse_content(reader(), path)[0]
        except Exception:
            # A damaged or unusually encoded file must not prevent its parent
            # directory from being listed. It can still be inspected on open.
            return None
        session.content_kind_cache[key] = kind
        return kind

    def _list_adfs_mount(self, mount, inner: str, session: ImageSession) -> dict:
        """Return the same stable row schema as ``disc ls --as json``."""
        try:
            from oaknut.disc.cli import _natural_name_key
            from oaknut.file import format_access_text
            from oaknut.filesystem import AcornMetadata, Datestamped, Filetyped
        except ImportError as exc:
            raise DiskError("The Oaknut ADFS listing API is unavailable.") from exc

        target = inner or "$"
        if not mount.exists(target):
            raise DiskError(f"Path not found: {target}")
        if not mount.stat(target).is_dir:
            raise DiskError(f"{target} is not a directory.")

        rows: list[dict] = []
        for child in sorted(mount.iter_entries(target), key=lambda entry: _natural_name_key(entry.name)):
            if child.is_dir:
                rows.append({
                    "name": child.name,
                    "type": "dir",
                    "load": "",
                    "exec": "",
                    "filetype": "",
                    "datestamp": "",
                    "length": sum(1 for _entry in mount.iter_entries(child.path)),
                    "attr": "",
                })
                continue

            load = execute = 0
            attr = ""
            filetype: int | str = ""
            datestamp = ""
            if isinstance(mount, AcornMetadata):
                metadata = mount.acorn_meta(child.path)
                load = int(metadata.load_address or 0)
                execute = int(metadata.exec_address or 0)
                if metadata.access is not None:
                    attr = format_access_text(metadata.access)
            if isinstance(mount, Filetyped):
                value = mount.filetype(child.path)
                if value is not None:
                    filetype = int(value)
            if isinstance(mount, Datestamped):
                value = mount.datestamp(child.path)
                if value is not None:
                    datestamp = value.isoformat(sep="T", timespec="milliseconds")
            row = {
                "name": child.name,
                "type": "file",
                "load": load,
                "exec": execute,
                "filetype": filetype,
                "datestamp": datestamp,
                "length": int(child.length),
                "attr": attr,
            }
            content_kind = self._listing_content_kind(
                session, None, None, str(child.path), row,
                lambda child_path=str(child.path): mount.read_bytes(child_path),
            )
            if content_kind:
                row["contentKind"] = content_kind
            rows.append(row)

        capacity = DiskService._capacity_from_mount(mount)
        free = capacity.get("free")
        return {
            "entries": rows,
            "title": str(getattr(mount, "title", "") or session.name),
            "description": f"Free: {free:,} bytes" if isinstance(free, int) else "",
            "path": target,
            "capacity": capacity,
        }

    def browse_directory(
        self,
        session: ImageSession,
        inner: str,
        slot: int | None,
        side: int | None = None,
    ) -> dict:
        """List one directory and return its capacity without a second mount."""
        if session.kind == "rom":
            listing = self.list_directory(session, "$", None)
            listing["capacity"] = self.capacity(session, None)
            return listing
        if session.kind == "romfs":
            listing = self.list_directory(session, "$", None)
            listing["capacity"] = self.capacity(session, None)
            return listing
        if session.kind == "adfs" and slot is None:
            with self.adfs_mount(session) as mount:
                return self._list_adfs_mount(mount, inner or "$", session)
        listing = self.list_directory(session, inner, slot, side)
        is_open_dfs_disk = session.kind == "dfs" or (session.kind == "mmb" and slot is not None)
        if is_open_dfs_disk:
            if inner == "$":
                root_rows = []
                for row in listing["entries"]:
                    root_rows.append({**row, "path": f"$.{row['name']}", "cataloguePrefix": "$"})
                grouped_rows = []
                seen_prefixes: set[str] = set()
                for row in sorted(
                    self.list_dfs_catalogue_files(session, slot, side),
                    key=lambda item: (str(item.get("prefix", "$")).casefold(), str(item.get("name", "")).casefold()),
                ):
                    prefix = str(row.get("prefix") or "$")
                    if prefix == "$":
                        continue
                    grouped_rows.append({
                        **row,
                        "leafName": row["name"],
                        "name": f"{prefix}.{row['name']}",
                        "cataloguePrefix": prefix,
                        "catalogueBreak": prefix not in seen_prefixes,
                    })
                    seen_prefixes.add(prefix)
                listing["entries"] = root_rows + grouped_rows
                group_count = len(seen_prefixes) + 1
                listing["description"] = (
                    f"{len(listing['entries'])} files in {group_count} DFS catalogue "
                    f"group{'s' if group_count != 1 else ''}"
                )
        listing["capacity"] = self.capacity(session, slot)
        return listing

    def list_rom_banks(self, session: ImageSession) -> list[dict]:
        if session.kind != "rom":
            raise DiskError("This image is not a ROM.")
        with session.lock:
            return inspect_rom_image(
                session.path,
                session.rom_bank_size,
                session.rom_erase_byte,
            )

    def inspect_rom_bank(self, session: ImageSession, bank: int) -> dict:
        """Decode one bank deeply without bloating every directory listing."""
        if session.kind != "rom":
            raise DiskError("This image is not a ROM.")
        rows = self.list_rom_banks(session)
        summary = next((row for row in rows if int(row["bank"]) == int(bank)), None)
        if summary is None:
            raise DiskError(f"ROM bank {bank} does not exist.")
        try:
            data = read_rom_bank(session.path, int(bank), session.rom_bank_size)
        except RomError as exc:
            raise DiskError(str(exc)) from exc
        decoded = inspect_rom_bank(
            data,
            int(bank),
            session.rom_erase_byte,
            include_contents=True,
            include_risc_os_modules=(
                session.rom_platform == "archimedes"
                or bool(summary.get("extensionHeader"))
            ),
        )
        decoded["matchingBanks"] = summary.get("matchingBanks", [])
        if summary.get("extensionHeader"):
            decoded["extensionHeader"] = summary["extensionHeader"]
            decoded["filetype"] = summary["filetype"]
            decoded["structures"] = summary["structures"]
        return decoded

    def configure_rom(
        self,
        session: ImageSession,
        *,
        bank_size: int,
        erase_byte: int,
        platform: str,
        layout: str,
    ) -> None:
        if session.kind != "rom":
            raise DiskError("This image is not a ROM.")
        try:
            session.rom_bank_size = validate_bank_size(bank_size)
        except RomError as exc:
            raise DiskError(str(exc)) from exc
        session.warnings = [
            warning
            for warning in session.warnings
            if not warning.startswith("The final ROM bank is partial")
        ]
        partial = session.path.stat().st_size % session.rom_bank_size
        if partial:
            session.warnings.append(
                f"The final ROM bank is partial ({partial:,} bytes). It is preserved exactly."
            )
        session.rom_erase_byte = int(erase_byte) & 0xFF
        try:
            session.rom_platform = validate_platform(platform)
            session.rom_layout = validate_layout(layout)
        except RomError as exc:
            raise DiskError(str(exc)) from exc
        session.dirty = True
        (session.path.parent / "download-ready.zip").unlink(missing_ok=True)
        (session.path.parent / "download-ready.json").unlink(missing_ok=True)
        self._persist_session(session)

    def put_rom_bank(self, session: ImageSession, data: bytes, bank: int | None = None) -> int:
        if session.kind != "rom":
            raise DiskError("This image is not a ROM.")
        if not data:
            raise DiskError("The selected ROM bank is empty.")
        if len(data) > session.rom_bank_size:
            raise DiskError(
                f"That file contains {len(data):,} bytes and does not fit one "
                f"{session.rom_bank_size:,}-byte bank. Split it into banks or change the ROM layout first."
            )
        rows = self.list_rom_banks(session)
        if bank is None:
            bank = next((int(row["bank"]) for row in rows if row["empty"]), len(rows))
        if bank < 0:
            raise DiskError("Choose a ROM bank.")
        offset = bank * session.rom_bank_size
        padded = data.ljust(session.rom_bank_size, bytes((session.rom_erase_byte,)))
        with session.lock, session.path.open("r+b") as image:
            current_size = session.path.stat().st_size
            if offset > current_size:
                image.seek(current_size)
                image.write(bytes((session.rom_erase_byte,)) * (offset - current_size))
            image.seek(offset)
            image.write(padded)
        self._mark_mutated(session, None)
        self._persist_session(session)
        return bank

    def clear_rom_banks(self, session: ImageSession, banks: list[int]) -> list[int]:
        if session.kind != "rom":
            raise DiskError("This image is not a ROM.")
        count = bank_count(session.path.stat().st_size, session.rom_bank_size)
        selected = sorted(set(int(bank) for bank in banks))
        if not selected or any(bank < 0 or bank >= count for bank in selected):
            raise DiskError("Choose one or more existing ROM banks.")
        blank = bytes((session.rom_erase_byte,)) * session.rom_bank_size
        with session.lock, session.path.open("r+b") as image:
            for bank in selected:
                offset = bank * session.rom_bank_size
                image.seek(offset)
                length = min(session.rom_bank_size, session.path.stat().st_size - offset)
                image.write(blank[:length])
        self._mark_mutated(session, None)
        self._persist_session(session)
        return selected

    def move_rom_banks(self, session: ImageSession, sources: list[int], target_start: int) -> list[int]:
        """Move banks atomically, including overlapping source/target ranges."""
        if session.kind != "rom":
            raise DiskError("This image is not a ROM.")
        source_banks = [int(bank) for bank in sources]
        if not source_banks or len(set(source_banks)) != len(source_banks):
            raise DiskError("Choose distinct ROM banks to move.")
        count = bank_count(session.path.stat().st_size, session.rom_bank_size)
        if (
            any(bank < 0 or bank >= count for bank in source_banks)
            or target_start < 0
            or target_start > count
        ):
            raise DiskError("Choose valid ROM bank positions.")
        targets = list(range(int(target_start), int(target_start) + len(source_banks)))
        data = [read_rom_bank(session.path, bank, session.rom_bank_size) for bank in source_banks]
        blank = bytes((session.rom_erase_byte,)) * session.rom_bank_size
        with session.lock, session.path.open("r+b") as image:
            for bank in set(source_banks) - set(targets):
                image.seek(bank * session.rom_bank_size)
                image.write(blank)
            for bank, content in zip(targets, data, strict=True):
                image.seek(bank * session.rom_bank_size)
                image.write(content.ljust(session.rom_bank_size, bytes((session.rom_erase_byte,))))
        self._mark_mutated(session, None)
        self._persist_session(session)
        return targets

    def rename_rom_bank(self, session: ImageSession, bank: int, title: str) -> None:
        try:
            data = bytearray(read_rom_bank(session.path, bank, session.rom_bank_size))
        except RomError as exc:
            raise DiskError(str(exc)) from exc
        header = parse_sideways_header(data)
        if header is None:
            raise DiskError("That bank has no editable BBC-family ROM title header.")
        try:
            encoded = str(title).encode("ascii")
        except UnicodeEncodeError as exc:
            raise DiskError("ROM titles can use printable ASCII characters only.") from exc
        marker = int(data[7])
        copyright_end = data.find(0, marker + 1, min(len(data), marker + 192)) if marker < len(data) else -1
        region_end = copyright_end + 1 if copyright_end >= 0 else marker + 1
        version = header.version.encode("ascii", "replace")
        copyright_text = header.copyright.encode("ascii", "replace")
        required = len(encoded) + 1 + len(version) + 1 + len(copyright_text) + 1
        available = region_end - 9
        maximum_title = max(0, available - (required - len(encoded)))
        if not encoded or required > available:
            raise DiskError(
                f"This header has room for a title of 1 to {maximum_title} characters. "
                "Use the hex editor to reorganise the header before making it longer."
            )
        if any(byte < 32 or byte > 126 for byte in encoded):
            raise DiskError("ROM titles can use printable ASCII characters only.")
        data[9:region_end] = bytes((session.rom_erase_byte,)) * available
        cursor = 9
        for value in (encoded, version):
            data[cursor : cursor + len(value)] = value
            cursor += len(value)
            data[cursor] = 0
            cursor += 1
        data[7] = cursor - 1
        data[cursor : cursor + len(copyright_text)] = copyright_text
        data[cursor + len(copyright_text)] = 0
        self.put_rom_bank(session, bytes(data), bank)

    def rom_bank_bytes(self, session: ImageSession, inner: str) -> bytes:
        try:
            return read_rom_bank(session.path, bank_number(inner), session.rom_bank_size)
        except RomError as exc:
            raise DiskError(str(exc)) from exc

    def replace_rom_bytes(self, session: ImageSession, data: bytes) -> None:
        if session.kind != "rom":
            raise DiskError("This image is not a ROM.")
        if not data or len(data) > MAX_ROM_SIZE:
            raise DiskError("ROM images must contain between 1 byte and 64 MiB.")
        temporary = session.path.with_name(f".{session.path.name}.rom-update")
        with session.lock:
            try:
                temporary.write_bytes(data)
                temporary.replace(session.path)
            finally:
                temporary.unlink(missing_ok=True)
            self._mark_mutated(session, None)
            self._persist_session(session)

    def save_rom_project(self, session: ImageSession, document: dict) -> dict:
        if session.kind != "rom":
            raise DiskError("This image is not a ROM.")
        session.rom_project = normalise_project(document)
        session.dirty = True
        self._persist_session(session)
        return session.rom_project

    def editor_project(self, session: ImageSession, path: str, slot: int | None, side: int | None) -> dict:
        key = editor_project_key(path, slot, side)
        return normalise_editor_project(session.editor_projects.get(key))

    def save_editor_project(
        self, session: ImageSession, path: str, slot: int | None, side: int | None, document: dict,
    ) -> dict:
        key = editor_project_key(path, slot, side)
        project = normalise_editor_project(document)
        with session.lock:
            session.editor_projects[key] = project
            self._persist_session(session)
        return project

    def move_editor_projects(
        self,
        session: ImageSession,
        moves: list[dict],
        slot: int | None,
        side: int | None,
    ) -> int:
        """Follow file and directory moves without orphaning editor annotations."""
        replacements = sorted(
            (
                (str(item.get("source") or "").rstrip("."), str(item.get("destination") or "").rstrip("."))
                for item in moves
                if item.get("source") and item.get("destination")
            ),
            key=lambda item: len(item[0]),
            reverse=True,
        )
        if not replacements:
            return 0
        changed: dict[str, dict] = {}
        removed: list[str] = []
        slot_key = str(slot) if slot is not None else "-"
        side_key = str(side) if side is not None else "-"
        for key, project in list(session.editor_projects.items()):
            key_slot, separator, remainder = key.partition("|")
            key_side, separator2, path = remainder.partition("|")
            if not separator or not separator2 or key_slot != slot_key or key_side != side_key:
                continue
            folded = path.casefold()
            for source, destination in replacements:
                source_folded = source.casefold()
                if folded != source_folded and not folded.startswith(source_folded + "."):
                    continue
                suffix = path[len(source):]
                changed[editor_project_key(destination + suffix, slot, side)] = project
                removed.append(key)
                break
        if not removed:
            return 0
        with session.lock:
            for key in removed:
                session.editor_projects.pop(key, None)
            session.editor_projects.update(changed)
            self._persist_session(session)
        return len(removed)

    def delete_editor_projects(
        self,
        session: ImageSession,
        paths: list[str],
        slot: int | None,
        side: int | None,
    ) -> int:
        """Remove annotations belonging to deleted files or directory trees."""
        prefixes = [str(path or "").rstrip(".").casefold() for path in paths if path]
        slot_key = str(slot) if slot is not None else "-"
        side_key = str(side) if side is not None else "-"
        removed = []
        for key in session.editor_projects:
            key_slot, separator, remainder = key.partition("|")
            key_side, separator2, path = remainder.partition("|")
            if not separator or not separator2 or key_slot != slot_key or key_side != side_key:
                continue
            folded = path.casefold()
            if any(folded == prefix or folded.startswith(prefix + ".") for prefix in prefixes):
                removed.append(key)
        if not removed:
            return 0
        with session.lock:
            for key in removed:
                session.editor_projects.pop(key, None)
            self._persist_session(session)
        return len(removed)

    def rom_component_exports(self, session: ImageSession) -> list[tuple[Path, str]]:
        """Create byte-wide chip files for a documented interleaved ROM set."""
        if session.kind != "rom" or not session.rom_layout.startswith("byte-interleaved-"):
            return []
        try:
            component_count = int(session.rom_layout.rsplit("-", 1)[-1])
        except ValueError as exc:
            raise DiskError("The ROM component layout is invalid.") from exc
        if component_count not in {2, 4}:
            raise DiskError("Only two-chip and four-chip ROM layouts can be exported.")
        names = list(session.rom_component_names[:component_count])
        names.extend(
            f"{Path(session.name).stem}-chip-{index + 1}.rom"
            for index in range(len(names), component_count)
        )
        paths = [session.path.parent / f"rom-component-{index}.bin" for index in range(component_count)]
        handles = [path.open("wb") for path in paths]
        try:
            with session.path.open("rb") as source:
                remainder = b""
                while chunk := source.read(COPY_BUFFER_SIZE):
                    chunk = remainder + chunk
                    complete = len(chunk) - (len(chunk) % component_count)
                    body, remainder = chunk[:complete], chunk[complete:]
                    for index, handle in enumerate(handles):
                        handle.write(body[index::component_count])
                if remainder:
                    raise DiskError(
                        f"The ROM size is not divisible by its {component_count}-chip byte layout."
                    )
        finally:
            for handle in handles:
                handle.close()
        return list(zip(paths, [self.safe_filename(name) for name in names], strict=True))

    def list_directory(self, session: ImageSession, inner: str, slot: int | None, side: int | None = None) -> dict:
        if session.kind == "rom":
            if inner not in {"", "$"}:
                raise DiskError("ROM images contain banks, not directories.")
            rows = self.list_rom_banks(session)
            partial = session.path.stat().st_size % session.rom_bank_size
            description = (
                f"{len(rows)} bank{'s' if len(rows) != 1 else ''} × {session.rom_bank_size:,} bytes"
                + (f" · final bank has {partial:,} bytes" if partial else "")
            )
            return {"entries": rows, "title": session.name, "description": description, "path": "$"}
        if session.kind == "romfs":
            if inner not in {"", "$"}:
                raise DiskError("ROMFS is flat and does not contain directories.")
            rows = []
            with self.romfs_mount(session) as mount:
                for entry in mount.iter_entries(""):
                    metadata = mount.acorn_meta(entry.name)
                    access = int(metadata.access or 0)
                    row = {
                        "name": entry.name,
                        "path": entry.name,
                        "type": "file",
                        "load": int(metadata.load_address or 0),
                        "exec": int(metadata.exec_address or 0),
                        "filetype": "",
                        "datestamp": "",
                        "length": int(entry.length or 0),
                        "attr": "RUN" if access & 0x40 else "LOAD",
                        "runOnly": bool(access & 0x40),
                    }
                    content_kind = self._listing_content_kind(
                        session, None, None, entry.name, row,
                        lambda name=entry.name: mount.read_bytes(name),
                    )
                    if content_kind:
                        row["contentKind"] = content_kind
                    rows.append(row)
                title = str(mount.title or session.name)
            details = self.romfs_details(session)
            return {
                "entries": rows,
                "title": title,
                "description": (
                    f"ROMFS {session.path.stat().st_size // 1024} KiB · "
                    f"{len(rows)} file{'s' if len(rows) != 1 else ''} · "
                    f"version {details['version']}"
                ),
                "path": "$",
            }
        if session.kind == "tape":
            tape = self._tape(session)
            if inner not in {"", "$"}:
                raise DiskError("UEF tapes do not contain directories.")
            entries = []
            for item in tape.files:
                row = {
                    "name": item.name,
                    "type": "file",
                    "load": item.load,
                    "exec": item.execute,
                    "filetype": "",
                    "datestamp": "",
                    "length": len(item.data),
                    "attr": "R/" if item.complete else "R/?",
                    "blocks": item.blocks,
                    "complete": item.complete,
                }
                content_kind = metadata_kind(item.name, None) or analyse_content(item.data, item.name)[0]
                if content_kind:
                    row["contentKind"] = content_kind
                entries.append(row)
            return {
                "entries": entries,
                "title": session.name,
                "description": f"UEF {tape.version} · {len(tape.files)} tape files",
                "path": "$",
            }
        if session.kind == "adfs" and slot is None:
            with self.adfs_mount(session) as mount:
                return self._list_adfs_mount(mount, inner or "$", session)
        disk_path = self.resolve(session, slot)
        requested_inner = "$" if inner is None else inner
        resolved_inner = self.inner_for(session, requested_inner, side)
        try:
            result = self._run_json(["ls", "--as", "json", self.compound(disk_path, resolved_inner)])
        except DiskError as error:
            if (session.kind == "dfs" or disk_path.suffix.lower() == ".ssd") and "path not found" in str(error):
                if requested_inner == "":
                    return {
                        "entries": [{
                            "name": "$",
                            "type": "dir",
                            "length": 0,
                            "attr": "",
                            "virtual": True,
                        }],
                        "title": session.name,
                        "description": "1 DFS catalogue group",
                        "path": "",
                    }
                return {
                    "entries": [],
                    "title": session.name,
                    "description": "Empty DFS catalogue group",
                    "path": requested_inner,
                }
            raise
        report = result["reports"]["entries"]
        rows = report["rows"]
        is_dfs = session.kind in {"dfs", "mmb"}
        if is_dfs:
            rows = self._restore_dfs_catalogue_names(
                self.compound(disk_path, resolved_inner),
                rows,
                session,
                slot,
                side,
            )
        if is_dfs and requested_inner == "":
            directories = [
                {
                    **row,
                    "type": "dir",
                    "virtual": True,
                }
                for row in rows
                if row.get("type") in {"dir", "directory"}
            ]
            if not any(str(row.get("name")) == "$" for row in directories):
                directories.append({
                    "name": "$",
                    "type": "dir",
                    "length": 0,
                    "attr": "",
                    "virtual": True,
                })
            rows = sorted(
                directories,
                key=lambda row: (
                    str(row.get("name")) != "$",
                    str(row.get("name", "")).casefold(),
                ),
            )
            report["metadata"]["description"] = (
                f"{len(rows)} DFS catalogue group{'s' if len(rows) != 1 else ''}"
            )
        return {
            "entries": rows,
            "title": report["metadata"].get("title", session.name),
            "description": report["metadata"].get("description", ""),
            "path": requested_inner,
        }

    @staticmethod
    def validate_dfs_prefix(prefix: str) -> str:
        prefix = str(prefix or "").strip().upper()
        if len(prefix) != 1 or (prefix != "$" and not "A" <= prefix <= "Z"):
            raise DiskError("Enter one DFS catalogue prefix: $ or a letter from A to Z.")
        return prefix

    def move_dfs_items(
        self,
        session: ImageSession,
        slot: int | None,
        items: list[dict],
        side: int | None = None,
    ) -> list[dict]:
        """Move DFS files between flat catalogue prefixes in one request."""
        if session.kind not in {"dfs", "mmb"} or (session.kind == "mmb" and slot is None):
            raise DiskError("Catalogue-prefix moves are available only inside a DFS disk.")
        if not isinstance(items, list) or not items:
            raise DiskError("Choose at least one DFS file to move.")
        checked: list[dict] = []
        for item in items:
            source = str(item.get("source") or "")
            destination = str(item.get("destination") or "")
            if "." not in source or "." not in destination:
                raise DiskError("DFS files must include a catalogue prefix and filename.")
            self.validate_dfs_prefix(source.split(".", 1)[0])
            self.validate_dfs_prefix(destination.split(".", 1)[0])
            self.validate_leaf_name(session, destination.split(".", 1)[1], slot)
            checked.append({"source": source, "destination": destination})
        self.require_writable_geometry(session)
        with session.lock:
            disk_path = self.resolve(session, slot)
            for item in checked:
                self._run([
                    "mv",
                    self.compound(
                        disk_path,
                        self.inner_for(session, item["source"], side),
                    ),
                    self.inner_for(session, item["destination"], side),
                ])
            self._mark_mutated(session, slot)
        self.move_editor_projects(session, checked, slot, side)
        return checked

    def list_dfs_catalogue_files(
        self,
        session: ImageSession,
        slot: int | None,
        side: int | None = None,
    ) -> list[dict]:
        """Return every file from the populated DFS prefix groups.

        A DFS catalogue is flat even though its one-character prefixes are
        presented as folders in the workbench.  Asking ``disc ls`` to list
        the root and then starting it again for every prefix was particularly
        noticeable while importing a floppy into a large ADFS image.  Mount
        the already-identified floppy once and walk that small catalogue in
        process instead.
        """
        if session.kind not in {"dfs", "mmb"} or (session.kind == "mmb" and slot is None):
            raise DiskError("Select a DFS disk before listing catalogue groups.")
        try:
            from oaknut.disc.mount import resolve_mount
            from oaknut.file import format_access_text
            from oaknut.filesystem import AcornMetadata
        except ImportError as exc:
            raise DiskError("The Oaknut DFS catalogue API is unavailable.") from exc

        disk_path = self.resolve(session, slot)
        # Resolve the drive/catalogue root rather than ``$`` itself so DFS
        # exposes every one-character prefix, not just the default group.
        root = self.inner_for(session, "", side)
        files: list[dict] = []
        try:
            with session.lock, resolve_mount(self.compound(disk_path, root)) as resolved:
                mount = resolved.mount
                pending = [resolved.path]
                while pending:
                    directory = pending.pop()
                    for entry in mount.iter_entries(directory):
                        if entry.is_dir:
                            pending.append(str(entry.path))
                            continue
                        path = str(entry.path)
                        prefix = path.rsplit(".", 1)[0] if "." in path else "$"
                        load = execute = 0
                        attr = ""
                        if isinstance(mount, AcornMetadata):
                            metadata = mount.acorn_meta(path)
                            load = int(metadata.load_address or 0)
                            execute = int(metadata.exec_address or 0)
                            if metadata.access is not None:
                                attr = format_access_text(metadata.access)
                        files.append({
                            "name": entry.name,
                            "type": "file",
                            "load": load,
                            "exec": execute,
                            "filetype": "",
                            "datestamp": "",
                            "length": int(entry.length),
                            "attr": attr,
                            "prefix": prefix,
                            "path": path,
                        })
                        content_kind = self._listing_content_kind(
                            session, slot, side, path, files[-1],
                            lambda path=path: mount.read_bytes(path),
                        )
                        if content_kind:
                            files[-1]["contentKind"] = content_kind
        except Exception:
            # Retain the command-backed path for unusual third-party DFS
            # variants and for a useful engine error on damaged images.
            files.clear()
            for group in self.list_directory(session, "", slot, side)["entries"]:
                prefix = self.validate_dfs_prefix(str(group.get("name") or ""))
                for row in self.list_directory(session, prefix, slot, side)["entries"]:
                    files.append({
                        **row,
                        "prefix": prefix,
                        "path": f"{prefix}.{row['name']}",
                    })
        return files

    def _restore_dfs_catalogue_names(
        self,
        compound_path: str,
        rows: list[dict],
        session: ImageSession,
        slot: int | None,
        side: int | None,
    ) -> list[dict]:
        """Restore literal dots and classify files in the same DFS mount."""
        try:
            from oaknut.disc.mount import resolve_mount

            with resolve_mount(compound_path) as resolved:
                mount = resolved.mount
                directory = resolved.path
                prefix = f"{directory}." if directory else ""
                names: dict[tuple[str, int, int, int], list[tuple[str, str]]] = {}
                for entry in mount.iter_entries(directory):
                    if entry.is_dir:
                        continue
                    path = str(entry.path)
                    literal_name = path[len(prefix) :] if path.startswith(prefix) else path
                    metadata = mount.acorn_meta(path)
                    key = (
                        literal_name.rsplit(".", 1)[-1].casefold(),
                        int(metadata.load_address or 0),
                        int(metadata.exec_address or 0),
                        int(entry.length or 0),
                    )
                    names.setdefault(key, []).append((literal_name, path))

                restored = []
                for row in rows:
                    key = (
                        str(row.get("name", "")).casefold(),
                        int(row.get("load") or 0),
                        int(row.get("exec") or 0),
                        int(row.get("length") or 0),
                    )
                    matches = names.get(key)
                    candidate = dict(row)
                    source_path = str(row.get("name") or "")
                    if matches:
                        literal_name, source_path = matches.pop(0)
                        candidate["name"] = literal_name
                    content_kind = self._listing_content_kind(
                        session, slot, side, source_path, candidate,
                        lambda source_path=source_path: mount.read_bytes(source_path),
                    )
                    if content_kind:
                        candidate["contentKind"] = content_kind
                    restored.append(candidate)
                return restored
        except (AttributeError, ImportError, OSError, RuntimeError, ValueError):
            return rows

    def stat(self, session: ImageSession, slot: int | None) -> dict:
        disk_path = self.resolve(session, slot)
        return self._run_json(["stat", "--as", "json", str(disk_path)])

    def capacity(self, session: ImageSession, slot: int | None) -> dict:
        """Return authoritative writable capacity for a pane-level filesystem."""
        if session.kind == "rom":
            rows = self.list_rom_banks(session)
            used = sum(not row["empty"] for row in rows)
            return {
                "available": True,
                "unit": "banks",
                "total": len(rows),
                "used": used,
                "free": len(rows) - used,
            }
        if session.kind == "tape":
            return {
                "available": False,
                "reason": "Tape images do not have a fixed free-space capacity.",
            }
        if session.kind == "romfs":
            return self.romfs_details(session)["capacity"]
        if session.kind == "mmb" and slot is None:
            slots = self.list_slots(session)
            used = sum(bool(item["formatted"]) for item in slots)
            total = len(slots)
            return {
                "available": True,
                "unit": "slots",
                "total": total,
                "used": used,
                "free": total - used,
            }
        if session.kind == "adfs" and slot is None:
            with self.adfs_mount(session) as mount:
                return self._capacity_from_mount(mount)

        reports = self.stat(session, slot).get("reports", {})
        rows = [
            row
            for report in reports.values()
            for row in report.get("rows", [])
            if isinstance(row, dict)
            and isinstance(row.get("size"), int)
            and isinstance(row.get("free"), int)
        ]
        if not rows:
            return {
                "available": False,
                "reason": "This filesystem does not report free-space capacity.",
            }
        total = sum(max(0, row["size"]) for row in rows)
        free = min(total, sum(max(0, row["free"]) for row in rows))
        return {
            "available": total > 0,
            "unit": "bytes",
            "total": total,
            "used": total - free,
            "free": free,
        }

    def validate(self, session: ImageSession, slot: int | None) -> str:
        if session.kind == "rom":
            rows = self.list_rom_banks(session)
            recognised = sum(bool(row["header"]) for row in rows)
            partial = session.path.stat().st_size % session.rom_bank_size
            if partial:
                return (
                    f"ROM bytes are readable · {len(rows)} banks · {recognised} BBC-family header(s) · "
                    f"final bank is partial ({partial:,} bytes)"
                )
            return f"ROM bytes are readable · {len(rows)} complete bank(s) · {recognised} BBC-family header(s)"
        if session.kind == "tape":
            tape = self._tape(session)
            suffix = f" · {len(tape.warnings)} warning(s)" if tape.warnings else ""
            return f"Valid UEF {tape.version} · {len(tape.files)} reconstructed file(s){suffix}"
        if session.kind == "romfs":
            details = self.romfs_details(session)
            state = "plain and writable" if not details["readOnly"] else (
                "incomplete and read-only" if not details["complete"] else "composite and read-only"
            )
            return (
                f"Valid ROMFS · all block CRCs passed · {details['fileCount']} file(s) · "
                f"{session.path.stat().st_size // 1024} KiB · {state}"
            )
        disk_path = self.resolve(session, slot)
        self._run(["validate", str(disk_path)])
        return "No structural errors found"

    def mutate(self, session: ImageSession, slot: int | None, args: list[str], side: int | None = None) -> None:
        if session.kind == "tape":
            raise DiskError("UEF tapes are read-only; convert the tape to SSD or DSD before editing files.")
        self.require_writable_geometry(session)
        with session.lock:
            disk_path = self.resolve(session, slot)
            expanded = []
            for part in args:
                if part.startswith("{image}:"):
                    inner = part[len("{image}:") :]
                    expanded.append(self.compound(disk_path, self.inner_for(session, inner, side)))
                else:
                    expanded.append(part.replace("{image}", str(disk_path)))
            self._run(expanded)
            self._mark_mutated(session, slot)

    def make_directory(self, session: ImageSession, path: str) -> None:
        """Create one ADFS directory without re-identifying the whole image."""
        self.require_writable_geometry(session)
        with self.adfs_mount(session) as mount:
            mount.make_directory(path, parents=True, exist_ok=False)
        self._mark_mutated(session, None)

    def set_access(
        self,
        session: ImageSession,
        slot: int | None,
        paths: list[str],
        writable: bool,
        side: int | None = None,
    ) -> list[str]:
        """Set Acorn access on several objects in one writable mount."""
        if session.kind == "tape":
            raise DiskError("UEF tapes do not carry editable file access.")
        self.require_writable_geometry(session)
        targets = list(dict.fromkeys(str(path or "").strip() for path in paths))
        if not targets:
            raise DiskError("Choose at least one file or directory to update.")
        try:
            from oaknut.disc.mount import resolve_mount
            from oaknut.file import Access, AcornMeta
            from oaknut.filesystem import AcornMetadata
        except ImportError as exc:
            raise DiskError("The Oaknut access API is unavailable.") from exc

        if session.kind == "romfs":
            with self.romfs_mount(session, writable=True) as mount:
                original = session.path.read_bytes()
                try:
                    for target in targets:
                        if not mount.exists(target):
                            raise DiskError(f"“{target}” no longer exists.")
                    for target in targets:
                        meta = mount.acorn_meta(target)
                        current = Access(meta.access) if meta.access is not None else Access(0)
                        access = current & ~Access.X if writable else current | Access.X
                        mount.set_acorn_meta(
                            target,
                            AcornMeta(
                                load_address=meta.load_address,
                                exec_address=meta.exec_address,
                                access=int(access),
                            ),
                        )
                except Exception:
                    session.path.write_bytes(original)
                    raise
            self._mark_mutated(session, None)
            return targets

        with session.lock:
            disk_path = self.resolve(session, slot)
            root = self.compound(disk_path, self.inner_for(session, "$", side))
            mount_context = (
                self.adfs_mount(session)
                if session.kind == "adfs" and slot is None
                else resolve_mount(root, writable=True)
            )
            with mount_context as opened:
                mount = opened if session.kind == "adfs" and slot is None else opened.mount
                if not isinstance(mount, AcornMetadata):
                    raise DiskError("This filesystem does not carry Acorn access bits.")
                resolved_targets = [self.inner_for(session, path, side) for path in targets]
                for target in resolved_targets:
                    if not mount.exists(target):
                        raise DiskError(f"“{target}” no longer exists.")
                for target in resolved_targets:
                    meta = mount.acorn_meta(target)
                    current = Access(meta.access) if meta.access is not None else Access(0)
                    access = current & ~Access.L if writable else current | Access.L
                    mount.set_acorn_meta(
                        target,
                        AcornMeta(
                            load_address=meta.load_address,
                            exec_address=meta.exec_address,
                            access=int(access),
                        ),
                    )
            self._mark_mutated(session, slot)
        return targets

    def put(
        self,
        session: ImageSession,
        slot: int | None,
        destination: str,
        host_path: Path,
        load: str | None,
        execute: str | None,
        filetype: str | None,
        side: int | None = None,
    ) -> None:
        if session.kind == "rom":
            self.put_rom_bank(session, host_path.read_bytes())
            return
        if session.kind == "tape":
            raise DiskError("Files cannot be added directly to a UEF tape.")
        self.require_writable_geometry(session)
        if session.kind == "romfs":
            destination = self.validate_leaf_name(session, destination, slot)
            try:
                from oaknut.file import AcornMeta, parse_address
            except ImportError as exc:
                raise DiskError("The Oaknut ROMFS metadata API is unavailable.") from exc
            if filetype:
                raise DiskError("ROMFS stores load and execution addresses, not RISC OS filetypes.")
            parsed_load = parse_address(load) if load else 0
            parsed_execute = parse_address(execute) if execute else 0
            with self.romfs_mount(session, writable=True) as mount:
                original = session.path.read_bytes()
                try:
                    mount.write_bytes(destination, host_path.read_bytes())
                    current = mount.acorn_meta(destination)
                    mount.set_acorn_meta(
                        destination,
                        AcornMeta(
                            load_address=parsed_load,
                            exec_address=parsed_execute,
                            access=current.access,
                        ),
                    )
                except Exception:
                    session.path.write_bytes(original)
                    raise
            self._mark_mutated(session, None)
            return
        if session.kind == "dfs" or (session.kind == "mmb" and slot is not None):
            if "." not in destination:
                raise DiskError("Choose a DFS catalogue group before adding a file.")
            self.validate_dfs_prefix(destination.split(".", 1)[0])
        self.validate_leaf_name(session, destination.rsplit(".", 1)[-1], slot)
        if session.kind == "adfs" and slot is None:
            try:
                from oaknut.file import AcornMeta, parse_address
                from oaknut.file.filetypes import parse_filetype
            except ImportError as exc:
                raise DiskError("The Oaknut ADFS import API is unavailable.") from exc
            if filetype and (load or execute):
                raise DiskError("A RISC OS filetype cannot be combined with load or execute addresses.")
            with self.adfs_mount(session) as mount:
                mount.write_bytes(destination, host_path.read_bytes())
                current = mount.acorn_meta(destination)
                mount.set_acorn_meta(
                    destination,
                    AcornMeta(
                        load_address=parse_address(load) if load else 0,
                        exec_address=parse_address(execute) if execute else 0,
                        access=current.access,
                    ),
                )
                if filetype:
                    mount.set_filetype(destination, parse_filetype(filetype))
            self._mark_mutated(session, None)
            return
        args = ["put"]
        if load:
            args += ["--load", load]
        if execute:
            args += ["--exec", execute]
        if filetype:
            args += ["--filetype", filetype]
        args += [self.compound(self.resolve(session, slot), self.inner_for(session, destination, side)), str(host_path)]
        with session.lock:
            self._run(args)
            self._mark_mutated(session, slot)

    def put_host_tree(
        self,
        session: ImageSession,
        slot: int | None,
        destination_dir: str,
        items: list[dict],
        *,
        preserve_directories: bool,
        replace: bool = False,
        side: int | None = None,
    ) -> dict:
        """Import a reviewed host folder in one writable filesystem mount.

        Each item contains a validated target path relative to
        ``destination_dir`` and a local temporary ``hostPath``.  Keeping the
        complete batch in one mount avoids reopening and checkpointing a large
        ADFS image for every small file.
        """
        if session.kind == "tape" or (session.kind == "mmb" and slot is None):
            raise DiskError("Open a writable disk before importing a host folder.")
        self.require_writable_geometry(session)
        is_dfs = session.kind == "dfs" or (session.kind == "mmb" and slot is not None)
        is_romfs = session.kind == "romfs"
        if preserve_directories and is_romfs:
            raise DiskError("ROMFS is flat. Import the selected files without preserving host folders.")
        if preserve_directories and is_dfs:
            raise DiskError("DFS cannot preserve host folders; import their files into one catalogue group instead.")
        if is_dfs:
            destination_dir = self.validate_dfs_prefix(destination_dir)
        elif not is_romfs and not destination_dir.startswith("$"):
            raise DiskError("Choose a valid ADFS destination directory.")
        if not items:
            raise DiskError("No relevant files were selected for import.")

        plans: list[dict] = []
        seen: set[str] = set()
        for item in items:
            relative = str(item.get("targetPath") or "").replace("\\", "/").strip("/")
            parts = [part for part in relative.split("/") if part]
            if not parts or any(part in {".", ".."} for part in parts):
                raise DiskError("A selected folder contains an invalid relative path.")
            if (is_dfs or is_romfs) and len(parts) != 1:
                raise DiskError(f"{'ROMFS' if is_romfs else 'DFS'} folder imports must use flat target filenames.")
            for part in parts:
                self.validate_leaf_name(session, part, slot)
            destination = parts[0] if is_romfs else ".".join([destination_dir.rstrip("."), *parts])
            key = destination.casefold()
            if key in seen:
                raise DiskError(f"More than one selected file maps to {destination}.")
            seen.add(key)
            plans.append({**item, "parts": parts, "destination": destination})

        try:
            from oaknut.disc.mount import resolve_mount
            from oaknut.file import AcornMeta
        except ImportError as exc:
            raise DiskError("The Oaknut folder import API is unavailable.") from exc

        with session.lock:
            disk_path = self.resolve(session, slot)
            root = self.compound(disk_path, self.inner_for(session, "$", side))
            mount_context = (
                self.romfs_mount(session, writable=True)
                if is_romfs
                else
                self.adfs_mount(session)
                if session.kind == "adfs" and slot is None
                else resolve_mount(root, writable=True)
            )
            with mount_context as opened:
                mount = opened if (session.kind == "adfs" and slot is None) or is_romfs else opened.mount
                original_romfs = session.path.read_bytes() if is_romfs else None
                conflicts: list[str] = []
                directories: set[str] = set()
                if preserve_directories:
                    for plan in plans:
                        for depth in range(1, len(plan["parts"])):
                            directories.add(".".join([destination_dir.rstrip("."), *plan["parts"][:depth]]))
                for directory in sorted(directories, key=lambda value: (value.count("."), value.casefold())):
                    if mount.exists(directory) and not mount.stat(directory).is_dir:
                        raise DiskError(f"{directory} is an ordinary file, so a folder cannot be created there.")
                for plan in plans:
                    destination = plan["destination"]
                    if mount.exists(destination):
                        if mount.stat(destination).is_dir:
                            raise DiskError(f"{destination} is a directory, so a file cannot replace it.")
                        conflicts.append(destination)
                if conflicts and not replace:
                    return {"imported": [], "conflicts": conflicts}
                for directory in sorted(directories, key=lambda value: (value.count("."), value.casefold())):
                    mount.make_directory(directory, parents=True, exist_ok=True)
                imported: list[str] = []

                def parse_address(value, fallback):
                    return int(str(value), 0) if value else fallback

                try:
                    for plan in plans:
                        mount.write_bytes(plan["destination"], Path(plan["hostPath"]).read_bytes())
                        metadata = plan.get("metadata") or {}
                        if metadata.get("load") or metadata.get("execute"):
                            current = mount.acorn_meta(plan["destination"])
                            mount.set_acorn_meta(
                                plan["destination"],
                                AcornMeta(
                                    load_address=parse_address(metadata.get("load"), current.load_address),
                                    exec_address=parse_address(metadata.get("execute"), current.exec_address),
                                    access=current.access,
                                ),
                            )
                        if metadata.get("filetype") and hasattr(mount, "set_filetype"):
                            mount.set_filetype(plan["destination"], metadata["filetype"])
                        imported.append(plan["destination"])
                except Exception:
                    if original_romfs is not None:
                        session.path.write_bytes(original_romfs)
                    raise
            self._mark_mutated(session, slot)
        return {"imported": imported, "conflicts": []}

    def copy(
        self,
        source: ImageSession,
        source_slot: int | None,
        source_inner: str,
        target: ImageSession,
        target_slot: int | None,
        target_inner: str,
        recursive: bool,
        source_side: int | None = None,
        target_side: int | None = None,
    ) -> None:
        if target.kind == "tape":
            raise DiskError("UEF tapes are read-only conversion sources.")
        if source.kind == "rom" or target.kind == "rom":
            if recursive:
                raise DiskError("ROM banks are byte images and cannot contain directories.")
            data = (
                self.rom_bank_bytes(source, source_inner)
                if source.kind == "rom"
                else self.read_file(source, source_slot, source_inner, source_side)
            )
            if target.kind == "rom":
                requested_bank = None
                if str(target_inner).lower().startswith(("bank:", "bank-")):
                    try:
                        requested_bank = bank_number(target_inner)
                    except RomError as exc:
                        raise DiskError(str(exc)) from exc
                self.put_rom_bank(target, data, requested_bank)
            else:
                temp_path = self.work_dir / f"rom-copy-{uuid.uuid4().hex}"
                temp_path.write_bytes(data)
                try:
                    self.put(target, target_slot, target_inner, temp_path, "0x8000", "0x8000", None, target_side)
                finally:
                    temp_path.unlink(missing_ok=True)
            return
        self.require_writable_geometry(target)
        if target.kind == "dfs" or (target.kind == "mmb" and target_slot is not None):
            if "." not in target_inner:
                raise DiskError("Choose a DFS catalogue group before copying a file.")
            self.validate_dfs_prefix(target_inner.split(".", 1)[0])
        self.validate_leaf_name(
            target,
            target_inner if target.kind == "romfs" else target_inner.rsplit(".", 1)[-1],
            target_slot,
        )
        if source.kind == "tape":
            tape_file = self._tape_file(source, source_inner)
            temp_path = self.work_dir / f"tape-copy-{uuid.uuid4().hex}"
            temp_path.write_bytes(tape_file.data)
            try:
                self.put(
                    target,
                    target_slot,
                    target_inner,
                    temp_path,
                    hex(tape_file.load),
                    hex(tape_file.execute),
                    None,
                    target_side,
                )
            finally:
                temp_path.unlink(missing_ok=True)
            return
        source_path = self.resolve(source, source_slot)
        target_path = self.resolve(target, target_slot)
        if target.kind == "adfs" and target_slot is None:
            try:
                from oaknut.disc.cli import (
                    _collect_copy_items,
                    _ensure_dir_chain,
                    _in_global_storage_order,
                    _write_copy_item,
                )
                from oaknut.disc.mount import resolve_mount
            except ImportError as exc:
                raise DiskError("The Oaknut direct-copy API is unavailable.") from exc

            def copy_between_mounts(source_mount, target_mount) -> None:
                items = _collect_copy_items(
                    source_mount,
                    source_inner,
                    dst_mount=target_mount,
                    dst_bare=target_inner,
                    dst_slash=False,
                    recursive=recursive,
                    wildcards=False,
                )
                for item in _in_global_storage_order(source_mount, items):
                    if item["kind"] == "mkdir":
                        _ensure_dir_chain(target_mount, item["dst"])
                    else:
                        self._write_adfs_copy_item(
                            target_mount,
                            str(item["dst"]),
                            item,
                            _write_copy_item,
                        )

            with self._locked_sessions(source, target):
                if source.kind == "adfs" and source_slot is None:
                    if source.id == target.id:
                        with self.adfs_mount(target) as mount:
                            copy_between_mounts(mount, mount)
                    else:
                        with self.adfs_mount(source) as source_mount:
                            with self.adfs_mount(target) as target_mount:
                                copy_between_mounts(source_mount, target_mount)
                else:
                    source_root = self.inner_for(source, "$", source_side)
                    with resolve_mount(self.compound(source_path, source_root)) as source_resolved:
                        with self.adfs_mount(target) as target_mount:
                            copy_between_mounts(source_resolved.mount, target_mount)
            target.dirty = True
            target.hfe_export_path = None
            return
        args = ["cp", "--no-wildcards"]
        if recursive:
            args.append("--recursive")
        args += [
            self.compound(source_path, self.inner_for(source, source_inner, source_side)),
            self.compound(target_path, self.inner_for(target, target_inner, target_side)),
        ]
        with self._locked_sessions(source, target):
            self._run(args)
            self._mark_mutated(target, target_slot)

    def replace_blank_dfs_image(
        self,
        target: ImageSession,
        source: ImageSession,
        source_name: str,
        *,
        target_slot: int | None,
        target_path: str,
    ) -> bool:
        """Install an SSD into a blank SSD without losing its title or catalogue."""
        if (
            target.kind != "dfs"
            or source.kind != "dfs"
            or target_slot is not None
            or target_path != "$"
            or target.path.suffix.lower() != ".ssd"
            or source.path.suffix.lower() != ".ssd"
            or self.list_directory(target, "$", None)["entries"]
        ):
            return False
        target_size = target.path.stat().st_size
        if source.path.stat().st_size > target_size:
            return False
        replacement = target.path.parent / f".online-replacement-{uuid.uuid4().hex}.ssd"
        try:
            with self._locked_sessions(source, target):
                self._copy_local_file(source.path, replacement)
                with replacement.open("ab") as image:
                    image.truncate(target_size)
                replacement.replace(target.path)
                target.name = self.safe_filename(Path(source_name).name)
                target.dirty = True
                target.hfe_export_path = None
                target.finalised_mtime_ns = None
                self._persist_session(target)
        finally:
            replacement.unlink(missing_ok=True)
        return True

    def copy_mmb_slot_to_adfs_directory(
        self,
        source: ImageSession,
        source_slot: int,
        target: ImageSession,
        target_parent: str,
        directory_name: str,
        progress: Callable[[str, int | None, int | None], None] | None = None,
    ) -> str:
        source_name = next(
            (
                str(slot["name"])
                for slot in self.list_slots(source)
                if int(slot["slot"]) == source_slot
            ),
            "Untitled disk",
        )
        results = self.copy_mmb_slots_to_adfs_directories(
            source,
            target,
            [{
                "sourceSlot": source_slot,
                "sourceName": source_name,
                "targetPath": target_parent or "$",
                "directoryName": directory_name,
            }],
            progress,
            stop_on_empty=True,
            stop_on_conflict=False,
        )
        return str(results[0]["destination"])

    def copy_mmb_slots_to_adfs_directories(
        self,
        source: ImageSession,
        target: ImageSession,
        items: list[dict],
        progress: Callable[[str, int | None, int | None], None] | None = None,
        completed: Callable[[dict], None] | None = None,
        skipped: Callable[[dict], None] | None = None,
        stop_on_empty: bool = False,
        stop_on_conflict: bool = False,
        apply_compatibility: bool = True,
    ) -> list[dict]:
        """Copy an MMB batch while mounting the large ADFS target only once."""
        if source.kind != "mmb" or target.kind != "adfs":
            raise DiskError("This operation requires an MMB source and an ADFS destination.")
        self.require_writable_geometry(target)
        report = progress or (lambda _message, _current=None, _total=None: None)
        record_completed = completed or (lambda _result: None)
        record_skipped = skipped or (lambda _result: None)
        total = len(items)
        results: list[dict] = []
        source_names = {
            int(slot["slot"]): str(slot["name"])
            for slot in self.list_slots(source)
        }

        def record_empty_disk(
            slot: int,
            source_name: str,
            destination: str,
            directory_name: str,
            offset: int,
        ) -> None:
            skipped_result = {
                "sourceSlot": slot,
                "sourceName": source_name,
                "destination": destination,
                "directoryName": directory_name,
                "reason": "Empty DFS catalogue",
            }
            if stop_on_empty:
                report(
                    f"Disk {offset + 1} of {total}, slot {slot} · {source_name}: "
                    "empty DFS catalogue; waiting for skip or abort",
                    offset,
                    total,
                )
                raise EmptyDiskError(skipped_result)
            results.append({**skipped_result, "skipped": True})
            record_skipped(skipped_result)
            report(
                f"Disk {offset + 1} of {total}, slot {slot} · {source_name}: "
                "empty DFS catalogue; skipped without creating a directory",
                offset + 1,
                total,
            )

        try:
            from oaknut.disc.cli import (
                _ensure_dir_chain,
                _file_item,
                _in_global_storage_order,
                _walk_post_order_mount,
                _write_copy_item,
            )
            from oaknut.disc.mount import resolve_mount
        except ImportError as exc:
            raise DiskError("The Oaknut bulk-copy API is unavailable.") from exc

        with self._locked_sessions(source, target):
            with self.adfs_mount(target) as target_mount:
                for offset, item in enumerate(items):
                    slot = int(item["sourceSlot"])
                    source_name = source_names.get(
                        slot,
                        str(item.get("sourceName") or "Untitled disk"),
                    )
                    parent = str(item.get("targetPath") or "$")
                    try:
                        name = self.validate_leaf_name(target, item["directoryName"])
                    except DiskError as error:
                        raise DiskError(
                            f"Slot {slot} · {source_name} could not be copied: {error}"
                        ) from error
                    destination = f"{parent}.{name}" if parent != "$" else f"$.{name}"
                    report(
                        f"Preparing disk {offset + 1} of {total}: "
                        f"slot {slot} · {source_name}",
                        offset,
                        total,
                    )
                    if target_mount.exists(destination):
                        conflict = {
                            "sourceSlot": slot,
                            "sourceName": source_name,
                            "destination": destination,
                            "directoryName": name,
                            "reason": "Destination directory already exists",
                        }
                        if self._is_empty_directory(target_mount, destination):
                            report(
                                f"Reusing empty destination directory {destination} for "
                                f"slot {slot} · {source_name}",
                                offset,
                                total,
                            )
                        elif item.get("replaceExisting"):
                            report(
                                f"Removing existing directory {destination} before retrying "
                                f"slot {slot} · {source_name}",
                                offset,
                                total,
                            )
                            for path in _walk_post_order_mount(target_mount, destination):
                                target_mount.remove(path, force=True)
                            target.dirty = True
                        elif stop_on_conflict:
                            raise DestinationExistsError(conflict)
                        else:
                            raise DiskError(
                                f"Slot {slot} · {source_name} could not be copied because "
                                f"“{destination}” already exists in the destination image."
                            )

                    source_path = self.resolve(source, slot)
                    try:
                        with resolve_mount(f"{source_path}:$") as source_resolved:
                            copy_items = self._collect_dfs_catalogue_items(
                                source_resolved.mount,
                                destination,
                                _file_item,
                            )
                            copy_items = _in_global_storage_order(
                                source_resolved.mount,
                                copy_items,
                            )
                            file_items = [
                                copy_item
                                for copy_item in copy_items
                                if copy_item["kind"] == "file"
                            ]
                            if apply_compatibility:
                                loader_repairs, loader_warnings = self._repair_adfs_loader_items(
                                    file_items
                                )
                            else:
                                loader_repairs, loader_warnings = [], []
                            for warning in loader_warnings:
                                self._append_warning(
                                    target,
                                    f"Slot {slot} · {source_name}: {warning}",
                                )
                            for repair in loader_repairs:
                                self._append_warning(
                                    target,
                                    f"Slot {slot} · {source_name}: ADFS compatibility change made: {repair}.",
                                )
                            if not file_items:
                                record_empty_disk(
                                    slot,
                                    source_name,
                                    destination,
                                    name,
                                    offset,
                                )
                                continue
                            _ensure_dir_chain(target_mount, destination)
                            self._set_adfs_directory_title(
                                target_mount,
                                destination,
                                source_name,
                            )
                            file_number = 0
                            for copy_item in copy_items:
                                if copy_item["kind"] == "mkdir":
                                    _ensure_dir_chain(target_mount, copy_item["dst"])
                                    continue
                                file_number += 1
                                report(
                                    f"Disk {offset + 1} of {total}, file "
                                    f"{file_number} of {len(file_items)}: "
                                    f"{copy_item['dst'].rsplit('.', 1)[-1]}",
                                    offset,
                                    total,
                                )
                                self._write_adfs_copy_item(
                                    target_mount,
                                    copy_item["dst"],
                                    copy_item,
                                    _write_copy_item,
                                )
                            candidates = [
                                {
                                    "name": str(copy_item["dst"]).rsplit(".", 1)[-1],
                                    "path": str(copy_item["dst"]).rsplit(".", 1)[0],
                                    "sourceName": str(
                                        copy_item.get("sourceName")
                                        or str(copy_item["dst"])[len(destination) + 1 :]
                                    ),
                                }
                                for copy_item in file_items
                            ]
                            from .menu_service import analyse_copied_dfs_items

                            detected_metadata = analyse_copied_dfs_items(
                                self,
                                source,
                                slot,
                                file_items,
                            )
                    except EmptyDiskError:
                        raise
                    except DestinationExistsError:
                        raise
                    except Exception as error:
                        is_empty_dfs = (
                            source_path.suffix.lower() == ".ssd"
                            and "path not found" in str(error).casefold()
                        )
                        if is_empty_dfs:
                            record_empty_disk(
                                slot,
                                source_name,
                                destination,
                                name,
                                offset,
                            )
                            continue
                        else:
                            if target_mount.exists(destination):
                                try:
                                    for path in _walk_post_order_mount(target_mount, destination):
                                        target_mount.remove(path, force=True)
                                except Exception:
                                    pass
                            raise DiskError(
                                f"Slot {slot} · {source_name} could not be copied "
                                f"to {destination}: {error}"
                            ) from error

                    result = {
                        "sourceSlot": slot,
                        "sourceName": source_name,
                        "destination": destination,
                        "launchCandidates": candidates,
                        "detectedMetadata": detected_metadata,
                        "loaderRepairs": loader_repairs,
                    }
                    results.append(result)
                    record_completed(result)
                    target.dirty = True
                    report(
                        f"Copied disk {offset + 1} of {total}: "
                        f"slot {slot} · {source_name}",
                        offset + 1,
                        total,
                    )
        return results

    @staticmethod
    def _collect_dfs_catalogue_items(
        source_mount,
        destination: str,
        file_item: Callable,
    ) -> list[dict]:
        """Collect raw DFS catalogue entries without synthetic-root traversal."""
        catalogue = getattr(getattr(source_mount, "_dfs", None), "files", None)
        if catalogue is None:
            raise DiskError("The DFS catalogue API is unavailable.")
        directories = sorted(
            {
                str(entry.directory)
                for entry in catalogue
                if str(entry.directory) != "$"
            },
            key=str.casefold,
        )
        used_at_root: set[str] = set()
        target_names: dict[int, str] = {}
        for entry in catalogue:
            if str(entry.directory) == "$":
                target_names[id(entry)] = DiskService._adfs_import_name(
                    str(entry.filename),
                    used_at_root,
                )
        target_directories = {
            directory: DiskService._adfs_import_name(directory, used_at_root)
            for directory in directories
        }
        used_in_directory = {
            directory: set()
            for directory in directories
        }
        for entry in catalogue:
            directory = str(entry.directory)
            if directory != "$":
                target_names[id(entry)] = DiskService._adfs_import_name(
                    str(entry.filename),
                    used_in_directory[directory],
                )
        items = [{"kind": "mkdir", "dst": destination}]
        items.extend(
            {
                "kind": "mkdir",
                "dst": f"{destination}.{target_directories[directory]}",
            }
            for directory in directories
        )
        for entry in catalogue:
            directory = str(entry.directory)
            filename = str(entry.filename)
            source_name = (
                filename
                if directory == "$"
                else f"{directory}.{filename}"
            )
            target_parent = (
                destination
                if directory == "$"
                else f"{destination}.{target_directories[directory]}"
            )
            item = file_item(
                source_mount,
                source_name if directory != "$" else f"$.{filename}",
                f"{target_parent}.{target_names[id(entry)]}",
            )
            if filename.upper() == "!BOOT":
                item["data"] = DiskService._relocate_dfs_boot_script(
                    item["data"],
                    destination,
                )
            item["sourceName"] = source_name
            items.append(item)
        return items

    @staticmethod
    def _relocate_dfs_boot_script(data: bytes, destination: str) -> bytes:
        """Relocate textual DFS-root commands inside an extracted !BOOT."""
        try:
            text = data.decode("latin-1")
        except UnicodeError:
            return data
        meaningful = [
            character
            for character in text
            if character not in "\r\n\t\f"
        ]
        if (
            not meaningful
            or sum(character.isprintable() for character in meaningful)
            / len(meaningful)
            < 0.9
        ):
            return data
        relocated = text.replace("$.", f"{destination}.")
        relocated = re.sub(
            r"(?i)(^|[\r\n])(\s*\*?\s*DIR\s+)\$(?=\s*(?:[:\r\n]|$))",
            lambda match: (
                f"{match.group(1)}{match.group(2)}{destination}"
            ),
            relocated,
        )
        return relocated.encode("latin-1")

    @staticmethod
    def _expand_adfs_oscli_abbreviations(
        data: bytes,
        load_address: int,
        occupied_ranges: list[tuple[int, int]],
    ) -> tuple[bytes, list[str], list[str]]:
        """Expand binary-loader commands whose DFS abbreviations break on ADFS.

        A machine-code loader commonly passes an inline command to OSCLI with
        ``LDX #low: LDY #high: JSR OSCLI``. DFS loaders often abbreviate RUN
        and LOAD as R. and L.; those spellings are ambiguous once ADFS adds
        RENAME/REMOVE and LCAT/LEX/LIB. Full commands are appended and only
        proven immediate pointers are redirected. Existing code never moves.
        """
        base = int(load_address) & 0xFFFF
        if not data or base + len(data) > 0x10000:
            return data, [], []
        original = bytes(data)
        patched = bytearray(original)
        repairs: list[str] = []
        warnings: list[str] = []
        redirected_offsets: set[int] = set()
        appended_for: dict[int, int] = {}
        command_names = {b"R.": b"RUN ", b"L.": b"LOAD "}

        for match in re.finditer(rb"\xA2(?P<low>.)(?:\xA0(?P<high>.)\x20\xF7\xFF)", original, re.DOTALL):
            command_address = match.group("low")[0] | (match.group("high")[0] << 8)
            command_offset = command_address - base
            if command_offset < 0 or command_offset >= len(original):
                continue
            command_end = original.find(b"\r", command_offset, min(len(original), command_offset + 80))
            if command_end < 0:
                continue
            abbreviated = original[command_offset : command_offset + 2].upper()
            prefix = command_names.get(abbreviated)
            if prefix is None:
                continue
            full_command = prefix + original[command_offset + 2 : command_end + 1]
            new_address = appended_for.get(command_offset)
            if new_address is None:
                new_address = base + len(patched)
                new_end = new_address + len(full_command)
                extension = (base + len(original), new_end)
                overlaps_adfs_workspace = extension[0] < 0x1D00 and extension[1] > 0x0E00
                overlaps_file = any(
                    extension[0] < end and extension[1] > start
                    for start, end in occupied_ranges
                    if not (start == base and end == base + len(original))
                )
                if new_end > 0x10000 or overlaps_adfs_workspace or overlaps_file:
                    warnings.append(
                        f"could not safely expand {original[command_offset:command_end].decode('latin-1')} "
                        "because the loader has no proven free address range"
                    )
                    continue
                patched.extend(full_command)
                appended_for[command_offset] = new_address
                repairs.append(
                    f"expanded {original[command_offset:command_end].decode('latin-1')} to "
                    f"{full_command[:-1].decode('latin-1')} for ADFS"
                )
            patched[match.start("low")] = new_address & 0xFF
            patched[match.start("high")] = new_address >> 8
            redirected_offsets.add(command_offset)

        for command_match in re.finditer(rb"(?P<command>[RL]\.[ -~]{1,60})\r", original, re.IGNORECASE):
            if command_match.start("command") not in redirected_offsets:
                command = command_match.group("command").decode("latin-1")
                warnings.append(
                    f"contains ambiguous ADFS command {command}, but no safe immediate OSCLI pointer was found"
                )
        return bytes(patched), list(dict.fromkeys(repairs)), list(dict.fromkeys(warnings))

    @staticmethod
    def _expand_adfs_text_commands(data: bytes) -> tuple[bytes, list[str]]:
        """Expand DFS-style command abbreviations in textual launch scripts."""
        try:
            text = data.decode("latin-1")
        except UnicodeError:
            return data, []
        meaningful = [character for character in text if character not in "\r\n\t\f"]
        if (
            not meaningful
            or sum(character.isprintable() for character in meaningful) / len(meaningful) < 0.9
        ):
            return data, []
        repairs: list[str] = []
        commands = {"R": "RUN", "L": "LOAD", "LO": "LOAD"}
        pattern = re.compile(
            r"(?im)(?P<prefix>^|[\r\n:])(?P<space>\s*\*?\s*)(?P<command>R|L|LO)\.(?P<tail>[^\r\n:]*)"
        )

        def expand(match: re.Match[str]) -> str:
            command = match.group("command").upper()
            expanded = commands[command]
            tail = match.group("tail").lstrip()
            repairs.append(f"expanded {command}.{match.group('tail')} to {expanded} {tail}".rstrip())
            return f"{match.group('prefix')}{match.group('space')}{expanded} {tail}"

        patched = pattern.sub(expand, text)
        return patched.encode("latin-1"), list(dict.fromkeys(repairs))

    @staticmethod
    def _adfs_loader_references(data: bytes) -> set[str]:
        """Return literal files named directly by a first-stage loader."""
        references: set[str] = set()
        patterns = (
            rb"(?i)(?:CHAIN|RUN|LOAD|EXEC)\s+\"?([!+$A-Z0-9_.-]+)",
            rb"(?i)CH\.\s*\"?([!+$A-Z0-9_.-]+)",
            rb"(?i)(?:R|L|LO)\.\s*\"?([!+$A-Z0-9_.-]+)",
            rb"\xD7\s*\"([^\"\r]+)\"",  # tokenised BBC BASIC CHAIN
        )
        for pattern in patterns:
            for match in re.finditer(pattern, data):
                name = match.group(1).decode("latin-1", "replace").strip()
                if name.startswith("$."):
                    name = name[2:]
                if name:
                    references.add(name.casefold())
        return references

    @staticmethod
    def _rewrite_adfs_basic_root_paths(
        data: bytes,
        local_names: set[str],
    ) -> tuple[bytes, list[str], set[str]]:
        """Make proven local ``$.file`` references relative in tokenised BASIC."""
        if not is_tokenized_basic(data):
            return data, [], set()
        rebuilt = bytearray()
        repairs: list[str] = []
        references: set[str] = set()
        position = 0
        pattern = re.compile(rb"\$\.(?P<path>[!+A-Za-z0-9_.-]+)")

        while position + 2 <= len(data) and data[position] == 0x0D:
            if data[position + 1] == 0xFF:
                rebuilt.extend(data[position:])
                return bytes(rebuilt), list(dict.fromkeys(repairs)), references
            if position + 4 > len(data):
                return data, [], set()
            length = data[position + 3]
            if length < 5 or position + length > len(data):
                return data, [], set()
            body = data[position + 4 : position + length]

            def make_relative(match: re.Match[bytes]) -> bytes:
                relative = match.group("path").decode("latin-1", "replace")
                if relative.casefold() not in local_names:
                    return match.group(0)
                repairs.append(f"changed root path $.{relative} to {relative}")
                references.add(relative.casefold())
                return match.group("path")

            patched = pattern.sub(make_relative, body)
            new_length = len(patched) + 4
            if new_length > 255:
                return data, [], set()
            rebuilt.extend(data[position : position + 3])
            rebuilt.append(new_length)
            rebuilt.extend(patched)
            position += length
        return data, [], set()

    @classmethod
    def _repair_adfs_loader_items(cls, file_items: list[dict]) -> tuple[list[str], list[str]]:
        ranges = [
            (int(item.get("load") or 0) & 0xFFFF, (int(item.get("load") or 0) & 0xFFFF) + len(item["data"]))
            for item in file_items
        ]
        repairs: list[str] = []
        warnings: list[str] = []
        seed_names = {"!BOOT", "BOOT", "GO", "MENU", "LOADER", "START"}
        seeds = []
        by_name: dict[str, dict] = {}
        for item in file_items:
            name = str(item.get("sourceName") or item.get("dst") or "loader")
            leaf = name.rsplit(".", 1)[-1].upper()
            by_name.setdefault(name.casefold(), item)
            by_name.setdefault(leaf.casefold(), item)
            if leaf in seed_names:
                seeds.append(item)

        local_names = {
            str(item.get("sourceName") or item.get("dst") or "").casefold()
            for item in file_items
        }
        scan_items: list[dict] = []
        queued = {id(item) for item in seeds}
        queue = list(seeds)
        seed_ids = set(queued)
        while queue:
            item = queue.pop(0)
            scan_items.append(item)
            name = str(item.get("sourceName") or item.get("dst") or "loader")
            root_patched, root_repairs, root_references = cls._rewrite_adfs_basic_root_paths(
                item["data"], local_names
            )
            if root_repairs:
                item["data"] = root_patched
                item.setdefault("loaderRepairs", []).extend(root_repairs)
                repairs.extend(f"{name}: {repair}" for repair in root_repairs)
            if id(item) in seed_ids:
                text_patched, text_repairs = cls._expand_adfs_text_commands(item["data"])
                if text_repairs:
                    item["data"] = text_patched
                    item.setdefault("loaderRepairs", []).extend(text_repairs)
                    repairs.extend(f"{name}: {repair}" for repair in text_repairs)
            # Follow the established entry-point chain once (!BOOT -> HAVEN),
            # then follow only the proven root paths repaired in subsequent
            # tokenised BASIC loaders.  Treating every R./L. found deeper in a
            # program as another loader can accidentally scan ordinary text or
            # data files that happen to have loader-like names.
            references = set(root_references)
            if id(item) in seed_ids:
                references.update(cls._adfs_loader_references(item["data"]))
            for reference in references:
                target = by_name.get(reference) or by_name.get(reference.rsplit(".", 1)[-1])
                if target is not None and id(target) not in queued:
                    queued.add(id(target))
                    queue.append(target)

        for item in scan_items:
            name = str(item.get("sourceName") or item.get("dst") or "loader")
            patched, item_repairs, item_warnings = cls._expand_adfs_oscli_abbreviations(
                item["data"],
                int(item.get("load") or 0),
                ranges,
            )
            if item_repairs:
                item["data"] = patched
                item.setdefault("loaderRepairs", []).extend(item_repairs)
                repairs.extend(f"{name}: {repair}" for repair in item_repairs)
            if item_warnings:
                commands = [
                    warning.split("command ", 1)[1].split(", but", 1)[0]
                    for warning in item_warnings
                    if "command " in warning
                ]
                if commands:
                    examples = ", ".join(commands[:5])
                    suffix = f", plus {len(commands) - 5} more" if len(commands) > 5 else ""
                    warnings.append(
                        f"{name}: loader contains {len(commands)} ambiguous abbreviated command(s) "
                        f"({examples}{suffix}); no safe immediate OSCLI pointer was found"
                    )
                else:
                    warnings.extend(f"{name}: {warning}" for warning in item_warnings)
        return repairs, warnings

    def _repair_copied_adfs_loaders(self, target: ImageSession, directory: str) -> tuple[list[str], list[str]]:
        """Repair an already copied SSD/DSD tree in one writable ADFS mount."""
        try:
            from oaknut.disc.cli import _file_item, _write_copy_item
        except ImportError as exc:
            raise DiskError("The Oaknut loader-repair API is unavailable.") from exc

        with self.adfs_mount(target) as mount:
            pending = [directory]
            items: list[dict] = []
            while pending:
                parent = pending.pop()
                for entry in mount.iter_entries(parent):
                    path = str(entry.path)
                    if entry.is_dir:
                        pending.append(path)
                    else:
                        item = _file_item(mount, path, path)
                        item["sourceName"] = path[len(directory) + 1 :] if path.startswith(f"{directory}.") else path
                        items.append(item)
            repairs, warnings = self._repair_adfs_loader_items(items)
            for item in items:
                if item.get("loaderRepairs"):
                    _write_copy_item(mount, str(item["dst"]), item, True)
        if repairs:
            target.dirty = True
        return repairs, warnings

    @staticmethod
    def _is_empty_directory(mount, path: str) -> bool:
        """Return true only for an existing directory with no child entries."""
        try:
            entry = mount.stat(path)
            return bool(entry.is_dir) and next(iter(mount.iter_entries(path)), None) is None
        except (AttributeError, OSError, RuntimeError, ValueError):
            return False

    @staticmethod
    def _write_adfs_copy_item(
        target_mount,
        destination: str,
        item: dict,
        fallback: Callable,
    ) -> None:
        """Write ADFS data and common DFS metadata in one catalogue update."""
        navigate = getattr(target_mount, "_navigate", None)
        if navigate is None or target_mount.exists(destination):
            fallback(target_mount, destination, item, False)
            return

        from oaknut.file import Access

        access_value = int(item.get("access") or 0)
        target = navigate(destination)
        target.write_bytes(
            item["data"],
            load_address=int(item.get("load") or 0),
            exec_address=int(item.get("exec") or 0),
            access=Access(access_value),
        )
        # write_bytes deliberately applies ADFS defaults beyond the lock bit.
        # One chmod is still required to match the source's complete access
        # mask, but load and execute were already written atomically above.
        target.chmod(access_value)
        filetype = item.get("filetype")
        if filetype is not None:
            target_mount.set_filetype(destination, filetype)
        datestamp = item.get("datestamp")
        if datestamp is not None:
            target_mount.set_datestamp(destination, datestamp)

    @staticmethod
    def _set_adfs_directory_title(mount, path: str, title: str) -> None:
        """Store the source disk title so later menu scans retain useful metadata."""
        try:
            target = mount._navigate(path)
            if getattr(target, "supports_title", False):
                target.title = str(title or "")[:19]
        except (AttributeError, OSError, RuntimeError, ValueError):
            pass

    @staticmethod
    def _unique_import_name(name: str, used: set[str], limit: int) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9!_-]", "_", name.rsplit(".", 1)[-1]) or "FILE"
        base = cleaned[:limit]
        candidate = base
        number = 1
        while candidate.casefold() in used:
            suffix = str(number)
            candidate = f"{base[: limit - len(suffix)]}{suffix}"
            number += 1
        used.add(candidate.casefold())
        return candidate

    @staticmethod
    def _adfs_import_name(name: str, used: set[str]) -> str:
        return DiskService._unique_import_name(name, used, 10)

    def extract_image_to_adfs_directory(
        self,
        source: ImageSession,
        target: ImageSession,
        target_parent: str,
        directory_name: str | None,
        progress: Callable[[str, int | None, int | None], None] | None = None,
        *,
        create_directory: bool = True,
    ) -> str:
        with self._locked_sessions(source, target):
            return self._extract_image_to_adfs_directory(
                source,
                target,
                target_parent,
                directory_name,
                progress,
                create_directory=create_directory,
            )

    def _extract_image_to_adfs_directory(
        self,
        source: ImageSession,
        target: ImageSession,
        target_parent: str,
        directory_name: str | None,
        progress: Callable[[str, int | None, int | None], None] | None = None,
        *,
        create_directory: bool = True,
    ) -> str:
        report = progress or (lambda _message, _current=None, _total=None: None)
        if target.kind != "adfs":
            raise DiskError("Disk images can only be expanded into an ADFS destination.")
        self.require_writable_geometry(target)
        target_parent = target_parent or "$"
        if create_directory:
            directory_name = self.validate_leaf_name(target, directory_name or "")
            target_directory = (
                f"{target_parent}.{directory_name}"
                if target_parent != "$"
                else f"$.{directory_name}"
            )
        else:
            # Resolve the destination before taking a rollback copy. This also
            # rejects stale browser paths without modifying the image.
            self.list_directory(target, target_parent, None)
            target_directory = target_parent
        dfs_rows: dict[int | None, list[dict]] = {}
        if source.kind == "dfs":
            if source.path.name.lower().endswith(".dsd"):
                dfs_rows[0] = self.list_dfs_catalogue_files(source, None, 0)
                dfs_rows[2] = self.list_dfs_catalogue_files(source, None, 2)
                source_has_files = bool(dfs_rows[0] or dfs_rows[2])
            else:
                dfs_rows[None] = self.list_dfs_catalogue_files(source, None)
                source_has_files = bool(dfs_rows[None])
            if not source_has_files:
                raise DiskError(
                    "The DFS disk image is empty. Nothing was extracted."
                )
        elif source.kind == "adfs" and not self.list_directory(source, "$", None)["entries"]:
            raise DiskError(
                "The ADFS disk image is empty. Nothing was extracted."
            )
        if create_directory:
            # Check and create through one trusted mount.  This avoids two
            # complete ADFS opens before an import can begin.
            with self.adfs_mount(target) as target_mount:
                if not target_mount.exists(target_parent):
                    raise DiskError(f"Path not found: {target_parent}")
                if target_mount.exists(target_directory):
                    raise DiskError(
                        f"“{directory_name}” already exists in the destination directory."
                    )
                report(f"Creating destination directory {target_directory}", 0, None)
                target_mount.make_directory(target_directory, parents=True, exist_ok=False)
            self._mark_mutated(target, None)

        rollback_path: Path | None = None
        dirty_before = target.dirty
        warnings_before = list(target.warnings)
        hfe_export_before = target.hfe_export_path
        if not create_directory:
            report(f"Preparing safe extraction into {target_directory}", 0, None)
            rollback_path = target.path.parent / f".import-rollback-{uuid.uuid4().hex}"
            self._copy_local_file(target.path, rollback_path)
        try:
            if source.kind == "tape":
                used: set[str] = set()
                tape_files = self._tape(source).files
                plans = [
                    (tape_file, self._adfs_import_name(tape_file.name, used))
                    for tape_file in tape_files
                ]
                name_map = {
                    source_name: target_name
                    for tape_file, target_name in plans
                    for source_name in (tape_file.name, tape_file.original_name)
                    if source_name and source_name.strip()
                }
                for offset, (tape_file, name) in enumerate(plans):
                    report(f"Extracting tape file {tape_file.name}", offset, len(tape_files))
                    next_name = plans[offset + 1][1] if offset + 1 < len(plans) else None
                    payload, loader_changes = rewrite_basic_loader(tape_file.data, next_name, name_map)
                    temp = self.work_dir / f"tape-adfs-{uuid.uuid4().hex}"
                    temp.write_bytes(payload)
                    try:
                        self.put(
                            target,
                            None,
                            f"{target_directory}.{name}",
                            temp,
                            hex(tape_file.load),
                            hex(tape_file.execute),
                            None,
                        )
                    finally:
                        temp.unlink(missing_ok=True)
                    detail = f" and repaired {len(loader_changes)} loader call(s)" if loader_changes else ""
                    report(f"Extracted tape file {tape_file.name}{detail}", offset + 1, len(tape_files))
                    if not tape_file.complete:
                        self._append_warning(
                            target,
                            f"{target_directory}.{name} came from an incomplete tape file and may not run correctly.",
                        )
                if not any(name.casefold() == "!boot" for _item, name in plans):
                    launch_file, launch_name = next(
                        ((item, name) for item, name in plans if item.complete),
                        plans[0],
                    )
                    if basic_unopened_channel_io(launch_file.data):
                        self._append_warning(
                            target,
                            f"{target_directory}: no !BOOT was generated because {launch_name} uses "
                            "a cassette-inherited file channel without opening it. Direct disk launch "
                            "would raise BASIC error 222 (Channel).",
                        )
                    else:
                        command = (
                            f'CHAIN "{launch_name}"\r'
                            if is_tokenized_basic(launch_file.data)
                            else f"*RUN {launch_name}\r"
                        )
                        temp = self.work_dir / f"tape-adfs-boot-{uuid.uuid4().hex}"
                        temp.write_bytes(command.encode("latin-1"))
                        try:
                            self.put(target, None, f"{target_directory}.!BOOT", temp, "0", "0", None)
                        finally:
                            temp.unlink(missing_ok=True)
                if len(plans) > 1 and not is_tokenized_basic(plans[0][0].data):
                    self._append_warning(
                        target,
                        f"{target_directory}: the initial UEF loader is not tokenised BASIC, so its internal "
                        "cassette calls could not be rewritten automatically.",
                    )
            elif source.kind == "mmb":
                used_dirs: set[str] = set()
                formatted_slots = [slot for slot in self.list_slots(source) if slot["formatted"]]
                batch_items = [
                    {
                        "sourceSlot": slot["slot"],
                        "sourceName": slot["name"],
                        "targetPath": target_directory,
                        "directoryName": self._adfs_import_name(slot["name"], used_dirs),
                    }
                    for slot in formatted_slots
                ]
                self.copy_mmb_slots_to_adfs_directories(
                    source,
                    target,
                    batch_items,
                    report,
                )
            elif source.kind == "dfs" and source.path.name.lower().endswith(".dsd"):
                side_zero = dfs_rows[0]
                side_two = dfs_rows[2]
                if side_zero and side_two:
                    for side, rows in ((0, side_zero), (2, side_two)):
                        report(f"Extracting DFS side {side}", side // 2, 2)
                        side_directory = f"{target_directory}.SIDE{side}"
                        self.make_directory(target, side_directory)
                        self._copy_rows_to_adfs(source, None, side, rows, target, side_directory, report)
                        report(f"Extracted DFS side {side}", side // 2 + 1, 2)
                else:
                    side = 0 if side_zero else 2
                    self._copy_rows_to_adfs(
                        source, None, side, side_zero or side_two, target, target_directory, report
                    )
            else:
                if source.kind == "dfs":
                    self._copy_image_listing_to_adfs(
                        source,
                        None,
                        None,
                        target,
                        target_directory,
                        report,
                        rows=dfs_rows[None],
                    )
                else:
                    self._copy_image_listing_to_adfs(
                        source, None, None, target, target_directory, report
                    )
            if source.kind in {"dfs", "tape", "adfs"}:
                report("Checking copied loaders for ADFS command conflicts", None, None)
                loader_repairs, loader_warnings = self._repair_copied_adfs_loaders(
                    target,
                    target_directory,
                )
                for warning in loader_warnings:
                    self._append_warning(target, f"{target_directory}: {warning}")
                for repair in loader_repairs:
                    self._append_warning(
                        target,
                        f"{target_directory}: ADFS compatibility change made: {repair}.",
                    )
                if loader_repairs:
                    report(
                        f"Repaired {len(loader_repairs)} ADFS loader command conflict(s)",
                        None,
                        None,
                    )
        except Exception:
            if create_directory:
                try:
                    self._run([
                        "rm",
                        "--force",
                        "--recursive",
                        self.compound(target.path, target_directory),
                    ])
                except Exception:
                    pass
            elif rollback_path and rollback_path.is_file():
                rollback_path.replace(target.path)
                target.dirty = dirty_before
                target.warnings = warnings_before
                target.hfe_export_path = hfe_export_before
            raise
        finally:
            if rollback_path:
                rollback_path.unlink(missing_ok=True)
        target.dirty = True
        target.hfe_export_path = None
        return target_directory

    def _copy_image_listing_to_adfs(
        self,
        source: ImageSession,
        source_slot: int | None,
        source_side: int | None,
        target: ImageSession,
        target_directory: str,
        progress: Callable[[str, int | None, int | None], None] | None = None,
        *,
        rows: list[dict] | None = None,
    ) -> None:
        if rows is None:
            rows = (
                self.list_dfs_catalogue_files(source, source_slot, source_side)
                if source.kind in {"dfs", "mmb"}
                else self.list_directory(source, "$", source_slot, source_side)["entries"]
            )
        self._copy_rows_to_adfs(
            source, source_slot, source_side, rows, target, target_directory, progress
        )

    def _copy_rows_to_adfs(
        self,
        source: ImageSession,
        source_slot: int | None,
        source_side: int | None,
        rows: list[dict],
        target: ImageSession,
        target_directory: str,
        progress: Callable[[str, int | None, int | None], None] | None = None,
    ) -> None:
        report = progress or (lambda _message, _current=None, _total=None: None)
        if not rows:
            return
        source_path = self.resolve(source, source_slot)
        report(f"Copying the complete disk catalogue in one batch", 0, len(rows))
        if target.kind == "adfs" and source.kind in {"dfs", "mmb"}:
            try:
                from oaknut.disc.cli import (
                    _ensure_dir_chain,
                    _file_item,
                    _in_global_storage_order,
                    _write_copy_item,
                )
                from oaknut.disc.mount import resolve_mount
            except ImportError as exc:
                raise DiskError("The Oaknut direct-copy API is unavailable.") from exc
            source_root = self.inner_for(source, "$", source_side)
            with self._locked_sessions(source, target):
                with resolve_mount(self.compound(source_path, source_root)) as source_resolved:
                    copy_items = self._collect_dfs_catalogue_items(
                        source_resolved.mount,
                        target_directory,
                        _file_item,
                    )
                    copy_items = _in_global_storage_order(source_resolved.mount, copy_items)
                with self.adfs_mount(target) as target_mount:
                    for item in copy_items:
                        if item["kind"] == "mkdir":
                            _ensure_dir_chain(target_mount, item["dst"])
                        else:
                            self._write_adfs_copy_item(
                                target_mount,
                                str(item["dst"]),
                                item,
                                _write_copy_item,
                            )
            target.dirty = True
            target.hfe_export_path = None
            report("Copied the complete disk catalogue", len(rows), len(rows))
            return
        if target.kind == "adfs" and source.kind == "adfs":
            try:
                from oaknut.disc.cli import (
                    _collect_copy_items,
                    _ensure_dir_chain,
                    _in_global_storage_order,
                    _write_copy_item,
                )
            except ImportError as exc:
                raise DiskError("The Oaknut direct-copy API is unavailable.") from exc

            def copy_between_mounts(source_mount, target_mount) -> None:
                copy_items = _collect_copy_items(
                    source_mount,
                    "$",
                    dst_mount=target_mount,
                    dst_bare=target_directory,
                    dst_slash=True,
                    recursive=True,
                    wildcards=False,
                )
                copy_items = _in_global_storage_order(source_mount, copy_items)
                for item in copy_items:
                    if item["kind"] == "mkdir":
                        _ensure_dir_chain(target_mount, item["dst"])
                    else:
                        self._write_adfs_copy_item(
                            target_mount,
                            str(item["dst"]),
                            item,
                            _write_copy_item,
                        )

            with self._locked_sessions(source, target):
                if source.id == target.id:
                    with self.adfs_mount(target) as mount:
                        copy_between_mounts(mount, mount)
                else:
                    with self.adfs_mount(source) as source_mount:
                        with self.adfs_mount(target) as target_mount:
                            copy_between_mounts(source_mount, target_mount)
            target.dirty = True
            target.hfe_export_path = None
            report("Copied the complete disk catalogue", len(rows), len(rows))
            return
        source_pattern = "*" if source.kind in {"dfs", "mmb"} else "$.*"
        self._run(
            [
                "cp",
                "--recursive",
                self.compound(
                    source_path,
                    self.inner_for(source, source_pattern, source_side),
                ),
                self.compound(target.path, target_directory),
            ]
        )
        report("Copied the complete disk catalogue", len(rows), len(rows))

    def read_file(self, session: ImageSession, slot: int | None, inner: str, side: int | None = None) -> bytes:
        if session.kind == "rom":
            return self.rom_bank_bytes(session, inner)
        if session.kind == "tape":
            return self._tape_file(session, inner).data
        if session.kind == "romfs":
            with self.romfs_mount(session) as mount:
                return mount.read_bytes(inner)
        if session.kind == "adfs" and slot is None:
            with self.adfs_mount(session) as mount:
                return mount.read_bytes(inner)
        disk_path = self.resolve(session, slot)
        return self._run(["get", "--meta-format", "none", self.compound(disk_path, self.inner_for(session, inner, side)), "-"], binary=True)

    def file_metadata(
        self,
        session: ImageSession,
        slot: int | None,
        inner: str,
        side: int | None = None,
    ) -> dict:
        """Return portable Acorn metadata for one exported loose file."""
        if session.kind == "rom":
            data = self.rom_bank_bytes(session, inner)
            return {"load": 0x8000, "execute": 0x8000, "access": 1, "length": len(data)}
        if session.kind == "tape":
            item = self._tape_file(session, inner)
            return {
                "load": item.load,
                "execute": item.execute,
                "access": 0,
                "length": len(item.data),
            }
        if session.kind == "romfs":
            with self.romfs_mount(session) as mount:
                stat = mount.stat(inner)
                metadata = mount.acorn_meta(inner)
                return {
                    "load": int(metadata.load_address or 0),
                    "execute": int(metadata.exec_address or 0),
                    "access": int(metadata.access or 0),
                    "length": int(stat.length or 0),
                }
        try:
            from oaknut.disc.mount import resolve_mount
        except ImportError as exc:
            raise DiskError("The Oaknut metadata API is unavailable.") from exc
        if session.kind == "adfs" and slot is None:
            with self.adfs_mount(session) as mount:
                stat = mount.stat(inner)
                metadata = mount.acorn_meta(inner)
                return {
                    "load": int(metadata.load_address or 0),
                    "execute": int(metadata.exec_address or 0),
                    "access": int(metadata.access or 0),
                    "length": int(stat.length or 0),
                }
        disk_path = self.resolve(session, slot)
        root = self.compound(disk_path, self.inner_for(session, "$", side))
        with session.lock, resolve_mount(root) as resolved:
            target = self.inner_for(session, inner, side)
            stat = resolved.mount.stat(target)
            metadata = resolved.mount.acorn_meta(target)
            return {
                "load": int(metadata.load_address or 0),
                "execute": int(metadata.exec_address or 0),
                "access": int(metadata.access or 0),
                "length": int(stat.length or 0),
            }

    def export_file(
        self,
        session: ImageSession,
        slot: int | None,
        inner: str,
        side: int | None = None,
    ) -> Path:
        """Export an image file without buffering its contents in application RAM."""
        target = self.work_dir / f"download-{uuid.uuid4().hex}"
        if session.kind == "rom":
            target.write_bytes(self.rom_bank_bytes(session, inner))
            return target
        if session.kind == "tape":
            target.write_bytes(self._tape_file(session, inner).data)
            return target
        if session.kind == "romfs":
            with self.romfs_mount(session) as mount:
                target.write_bytes(mount.read_bytes(inner))
            return target
        if session.kind == "adfs" and slot is None:
            with self.adfs_mount(session) as mount:
                target.write_bytes(mount.read_bytes(inner))
            return target
        disk_path = self.resolve(session, slot)
        try:
            self._run(
                [
                    "get",
                    "--meta-format",
                    "none",
                    self.compound(
                        disk_path,
                        self.inner_for(session, inner, side),
                    ),
                    str(target),
                ]
            )
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return target

    def compact(self, session: ImageSession, slot: int | None, order: str | None = None) -> None:
        if session.kind == "romfs":
            raise DiskError("ROMFS is rebuilt into storage order after every edit and does not need compaction.")
        if session.kind == "tape":
            raise DiskError("UEF tapes cannot be compacted; convert to a disk image first.")
        self.require_writable_geometry(session)
        disk_path = self.resolve(session, slot)
        args = ["compact"]
        if order:
            args += ["--order", order]
        args.append(str(disk_path))
        with session.lock:
            self._run(args)
            self._mark_mutated(session, slot)

    @staticmethod
    def _tape(session: ImageSession) -> UEFContents:
        if session.tape is None:
            try:
                session.tape = parse_uef(session.path.read_bytes())
            except UEFError as exc:
                raise DiskError(str(exc)) from exc
        return session.tape

    def _tape_file(self, session: ImageSession, inner: str) -> TapeFile:
        name = inner.rsplit(".", 1)[-1]
        for item in self._tape(session).files:
            if item.name.casefold() == name.casefold():
                return item
        raise DiskError(f"Tape file “{name}” was not found.")

    @staticmethod
    def _dfs_conversion_name(name: str, used: set[str]) -> str:
        return DiskService._unique_import_name(name, used, 7)

    def convert_uef(self, session: ImageSession, disk_format: str) -> tuple[ImageSession, list[dict]]:
        if session.kind != "tape":
            raise DiskError("Only UEF tapes can be converted.")
        if disk_format not in {"ssd", "dsd"}:
            raise DiskError("A UEF can be converted to SSD or DSD.")
        tape = self._tape(session)
        if not tape.files:
            raise DiskError("No standard Acorn tape files were found to place on a DFS disk.")
        title = Path(session.name).stem[:12] or "UEF"
        target = self.create_blank(disk_format, title)
        new_name = self.safe_filename(f"{Path(session.name).stem}.{disk_format}")
        new_path = target.path.with_name(new_name)
        target.path.rename(new_path)
        target.path = new_path
        target.name = new_name
        self._persist_session(target)
        used: set[str] = set()
        plans: list[tuple[TapeFile, str]] = [
            (tape_file, self._dfs_conversion_name(tape_file.name, used))
            for tape_file in tape.files
        ]
        name_map = {
            source_name: dfs_name
            for tape_file, dfs_name in plans
            for source_name in (tape_file.name, tape_file.original_name)
            if source_name and source_name.strip()
        }
        converted: list[dict] = []
        generated_boot: dict | None = None
        boot_name = next((name for tape_file, name in plans if tape_file.name.casefold() == "!boot"), None)
        if boot_name is None:
            launch_file, launch_name = next(
                ((item, name) for item, name in plans if item.complete),
                plans[0],
            )
            if basic_unopened_channel_io(launch_file.data):
                self._append_warning(
                    target,
                    f"No !BOOT was generated because {launch_name} uses a cassette-inherited "
                    "file channel without opening it. Direct disk launch would raise BASIC "
                    "error 222 (Channel).",
                )
            else:
                command = f'CHAIN "{launch_name}"\r' if is_tokenized_basic(launch_file.data) else f"*RUN {launch_name}\r"
                temp_path = self.work_dir / f"uef-boot-{uuid.uuid4().hex}"
                temp_path.write_bytes(command.encode("latin-1"))
                try:
                    # Reserve the boot file before the tape payload fills the disk.
                    self.put(target, None, "$.!BOOT", temp_path, "0", "0", None, 0 if disk_format == "dsd" else None)
                finally:
                    temp_path.unlink(missing_ok=True)
                generated_boot = {
                    "source": "Generated disk boot",
                    "destination": "!BOOT",
                    "side": 0,
                    "complete": True,
                    "generated": True,
                    "loaderChanges": [f"Created {command.strip()} as the disk boot command."],
                }
        current_side = 0
        for position, (tape_file, dfs_name) in enumerate(plans):
            next_name = plans[position + 1][1] if position + 1 < len(plans) else None
            payload, loader_changes = rewrite_basic_loader(tape_file.data, next_name, name_map)
            temp_path = self.work_dir / f"uef-convert-{uuid.uuid4().hex}"
            temp_path.write_bytes(payload)
            try:
                try:
                    self.put(
                        target,
                        None,
                        f"$.{dfs_name}",
                        temp_path,
                        hex(tape_file.load),
                        hex(tape_file.execute),
                        None,
                        current_side if disk_format == "dsd" else None,
                    )
                except DiskError:
                    if disk_format != "dsd" or current_side == 2:
                        raise
                    current_side = 2
                    self.put(
                        target,
                        None,
                        f"$.{dfs_name}",
                        temp_path,
                        hex(tape_file.load),
                        hex(tape_file.execute),
                        None,
                        current_side,
                    )
            finally:
                temp_path.unlink(missing_ok=True)
            converted.append(
                {
                    "source": tape_file.name,
                    "destination": dfs_name,
                    "side": current_side if disk_format == "dsd" else 0,
                    "complete": tape_file.complete,
                    "inferredName": tape_file.inferred_name,
                    "loaderChanges": list(loader_changes),
                }
            )

        if generated_boot:
            converted.append(generated_boot)
        try:
            self._run(["opt", str(target.path), "3"])
            self._mark_mutated(target, None)
        except DiskError as exc:
            self._append_warning(target, f"The files were converted, but DFS boot option 3 could not be set: {exc}")

        if len(plans) > 1 and not is_tokenized_basic(plans[0][0].data):
            self._append_warning(
                target,
                "The initial tape loader is not tokenised BASIC. Its internal cassette calls could not be "
                "rewritten automatically; test the converted disk before relying on it.",
            )
        for tape_file, dfs_name in plans:
            if not tape_file.complete:
                self._append_warning(
                    target,
                    f"{dfs_name} was recovered from an incomplete tape file and may not run correctly.",
                )
        return target, converted

    @staticmethod
    def _friendly_engine_error(message: str) -> str:
        if "exceeds disc bounds" in message and "Sector range" in message:
            return (
                "The ADFS image geometry is incomplete or invalid. "
                "For a BeebSCSI DAT image, reopen the original DAT with its matching DSC file."
            )
        if "Traceback (most recent call last)" in message:
            lines = [line.strip() for line in message.splitlines() if line.strip()]
            message = lines[-1] if lines else ""
            message = re.sub(
                r"^(?:[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception)):\s*",
                "",
                message,
            )
        return re.sub(r"^Error:\s*", "", message).strip() or "Disk operation failed."

    @staticmethod
    def _run(args: list[str], binary: bool = False) -> bytes | str:
        args = [argument for argument in args if argument != ""]
        try:
            result = subprocess.run(
                ["disc", *args],
                capture_output=True,
                check=False,
                timeout=240,
            )
        except FileNotFoundError as exc:
            raise DiskError("The Oaknut disk engine is not installed.") from exc
        except subprocess.TimeoutExpired as exc:
            raise DiskError("The disk operation timed out.") from exc
        if result.returncode:
            message = result.stderr.decode("utf-8", "replace").strip()
            raise DiskError(DiskService._friendly_engine_error(message))
        return result.stdout if binary else result.stdout.decode("utf-8", "replace")

    @staticmethod
    def _run_hxcfe(args: list[str]) -> str:
        try:
            result = subprocess.run(
                ["hxcfe", *args],
                capture_output=True,
                check=False,
                timeout=240,
            )
        except FileNotFoundError as exc:
            raise DiskError("The HFE conversion engine is not installed.") from exc
        except subprocess.TimeoutExpired as exc:
            raise DiskError("The HFE conversion timed out.") from exc
        output = (result.stdout + result.stderr).decode("utf-8", "replace")
        if result.returncode:
            raise DiskError(DiskService._friendly_engine_error(output))
        return output

    @classmethod
    def _run_json(cls, args: list[str]) -> dict:
        output = cls._run(args)
        try:
            return json.loads(output)
        except json.JSONDecodeError as exc:
            raise DiskError("The disk engine returned an unreadable response.") from exc
