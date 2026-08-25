"""Desktop-only adapters kept outside the shared image API."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
import tempfile

from flask import Blueprint, jsonify, request

from acorn_greaseweazle import (
    DRIVE_CHOICES,
    GreaseweazleClient,
    GreaseweazleError,
    image_format,
    stable_snapshot,
)

from ..disk_service import DiskError, DiskService
from ..desktop_state import DesktopClientState
from ..image_opening import open_image_path, open_rom_component_paths
from ..operations import OperationRegistry
from ..rom_components import MAX_ROM_COMPONENTS
from .common import payload
from .effects import request_effect


def _regular_file(value: object, label: str) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise DiskError(f"Choose {label}.")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise DiskError(f"The desktop {label} must use an absolute path.")
    try:
        path = path.resolve(strict=True)
    except OSError as exc:
        raise DiskError(f"The desktop {label} no longer exists: {path}") from exc
    if not path.is_file():
        raise DiskError(f"The desktop {label} is not a regular file: {path}")
    return path


def _matching_sibling(path: Path, suffix: str) -> Path | None:
    wanted = f"{path.stem}{suffix}".casefold()
    try:
        return next(
            item for item in path.parent.iterdir()
            if item.is_file() and item.name.casefold() == wanted
        )
    except (OSError, StopIteration):
        return None


def _image_pair(data: dict) -> tuple[Path, Path | None]:
    image = _regular_file(data.get("path"), "image")
    descriptor_value = data.get("descriptorPath")
    descriptor = (
        _regular_file(descriptor_value, "DSC descriptor")
        if descriptor_value else None
    )
    if image.suffix.casefold() == ".dsc":
        descriptor = image
        image = _matching_sibling(image, ".dat")
        if image is None:
            raise DiskError(f"Choose the DAT file matching {descriptor.name}.")
    elif image.suffix.casefold() == ".dat" and descriptor is None:
        descriptor = _matching_sibling(image, ".dsc")
    return image, descriptor


def _selected_slot(service: DiskService, session, value: object) -> int:
    try:
        slot = int(value)
    except (TypeError, ValueError) as exc:
        raise DiskError("Select one formatted MMB slot to write.") from exc
    slots = service.list_slots(session)
    if slot < 0 or slot >= len(slots) or not slots[slot].get("formatted"):
        raise DiskError("Select one formatted MMB slot to write.")
    return slot


def _physical_media_details(service: DiskService, session, slot_value: object = None) -> dict:
    if session.kind == "mmb":
        slot = _selected_slot(service, session, slot_value)
        entry = service.list_slots(session)[slot]
        name = str(entry.get("name") or f"slot-{slot:03d}")
        if not name.casefold().endswith(".ssd"):
            name += ".ssd"
    else:
        slot = None
        name = session.name
        if session.kind == "adfs" and service.summary(session).get("hardDisk"):
            raise DiskError(
                "A hard-disk image cannot be written to a floppy drive. Open an ADFS floppy image instead."
            )
    try:
        media_format = image_format(name)
    except GreaseweazleError as exc:
        raise DiskError(str(exc)) from exc
    return {
        "name": name,
        "slot": slot,
        "format": media_format.label,
        "automaticVerification": media_format.automatic_verification,
    }


@contextmanager
def _physical_media(service: DiskService, session, details: dict, progress):
    """Expose finalised media without allowing later edits to change the write."""
    temporary: Path | None = None
    try:
        if session.kind == "mmb":
            progress(f"Extracting MMB slot {details['slot']} into a stable SSD snapshot", 0, None)
            data, name = service.slot_download(session, details["slot"])
            handle = tempfile.NamedTemporaryFile(
                dir=service.work_dir,
                prefix="physical-slot-",
                suffix=Path(name).suffix or ".ssd",
                delete=False,
            )
            temporary = Path(handle.name)
            with handle:
                handle.write(data)
            source = temporary
        else:
            progress("Finalising the working image before physical media access", 0, None)
            with session.lock:
                source = service.prepare_download(
                    session,
                    lambda message, _current=None, _total=None: progress(message, None, None),
                )
        snapshot_context = stable_snapshot(source, service.work_dir)
        with session.lock:
            snapshot = snapshot_context.__enter__()
        try:
            yield snapshot
        finally:
            snapshot_context.__exit__(None, None, None)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def create_desktop_blueprint(
    service: DiskService,
    operations: OperationRegistry | None = None,
    client_state: DesktopClientState | None = None,
) -> Blueprint:
    operations = operations or OperationRegistry()
    blueprint = Blueprint("desktop", __name__)

    @blueprint.get("/api/desktop/client-state")
    def get_client_state():
        return jsonify((client_state or DesktopClientState(service.work_dir / "client-state.json")).read())

    @blueprint.put("/api/desktop/client-state")
    @request_effect("external", "saving durable Linux desktop preferences")
    def put_client_state():
        data = payload()
        state = client_state or DesktopClientState(service.work_dir / "client-state.json")
        document = state.update(
            local_storage=data.get("localStorage") if "localStorage" in data else None,
            collection=data.get("collection") if "collection" in data else None,
        )
        return jsonify(version=document["version"])

    @blueprint.post("/api/desktop/open-path")
    @request_effect("lifecycle", "opening a local desktop image session")
    def open_local_path():
        data = payload()
        component_values = data.get("componentPaths")
        if isinstance(component_values, list) and len(component_values) > 1:
            if data.get("forceKind") != "rom":
                raise DiskError("Multiple native paths require an explicit ROM component-set plan.")
            if len(component_values) > MAX_ROM_COMPONENTS:
                raise DiskError(
                    f"A ROM set cannot contain more than {MAX_ROM_COMPONENTS} components."
                )
            components = [
                _regular_file(value, "ROM component") for value in component_values
            ]
            rom = data.get("rom") if isinstance(data.get("rom"), dict) else {}
            try:
                session = open_rom_component_paths(
                    service,
                    components,
                    layout=str(rom.get("layout") or "linear"),
                    platform=str(rom.get("platform") or "bbc-master-electron"),
                )
            except (OSError, ValueError) as exc:
                raise DiskError(str(exc)) from exc
            return jsonify(image=service.summary(session))
        image_path, descriptor_path = _image_pair(data)
        session = open_image_path(
            service,
            image_path,
            descriptor_path,
            target_hardware=str(data.get("targetHardware") or "auto"),
            rom_options=(
                data.get("rom") if isinstance(data.get("rom"), dict) else None
            ),
            force_kind=str(data.get("forceKind") or "") or None,
        )
        return jsonify(image=service.summary(session))

    @blueprint.get("/api/desktop/images/<image_id>/physical-floppy")
    @request_effect("external", "probing Greaseweazle physical-floppy access")
    def physical_floppy_status(image_id):
        session = service.get(image_id)
        details = _physical_media_details(service, session, request.args.get("slot"))
        probe = GreaseweazleClient().probe()
        return jsonify(
            available=probe.available,
            command=probe.command,
            detail=probe.detail,
            drives=[{"id": drive, "label": f"Drive {drive}"} for drive in DRIVE_CHOICES],
            media=details,
        )

    @blueprint.post("/api/desktop/images/<image_id>/physical-floppy")
    @request_effect("external", "writing a physical floppy through Greaseweazle")
    def write_physical_floppy(image_id):
        data = payload()
        session = service.get(image_id)
        details = _physical_media_details(service, session, data.get("slot"))
        operation_id = str(data.get("operationId") or "") or None
        try:
            with operations.tracked(
                operation_id,
                f"Preparing {details['name']} for physical drive {data.get('drive') or ''}",
                "Physical floppy write complete",
            ) as progress:
                with _physical_media(service, session, details, progress) as image:
                    result = GreaseweazleClient().write(
                        image,
                        str(data.get("drive") or ""),
                        progress,
                    )
        except GreaseweazleError as exc:
            raise DiskError(str(exc)) from exc
        return jsonify(result=asdict(result), media=details)

    return blueprint


__all__ = ["create_desktop_blueprint"]
