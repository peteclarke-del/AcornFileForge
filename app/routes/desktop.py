"""Desktop-only adapters kept outside the shared image API."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path

from flask import Blueprint, jsonify
from werkzeug.datastructures import FileStorage

from ..disk_service import DiskError, DiskService
from ..image_opening import open_image_upload
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


def create_desktop_blueprint(service: DiskService) -> Blueprint:
    blueprint = Blueprint("desktop", __name__)

    @blueprint.post("/api/desktop/open-path")
    @request_effect("lifecycle", "opening a local desktop image session")
    def open_local_path():
        data = payload()
        image_path, descriptor_path = _image_pair(data)
        with ExitStack() as stack:
            image_stream = stack.enter_context(image_path.open("rb"))
            image = FileStorage(stream=image_stream, filename=image_path.name)
            descriptor = None
            if descriptor_path is not None:
                descriptor_stream = stack.enter_context(descriptor_path.open("rb"))
                descriptor = FileStorage(
                    stream=descriptor_stream,
                    filename=descriptor_path.name,
                )
            session = open_image_upload(
                service,
                image,
                descriptor,
                target_hardware=str(data.get("targetHardware") or "auto"),
                rom_options=(
                    data.get("rom") if isinstance(data.get("rom"), dict) else None
                ),
                force_kind=str(data.get("forceKind") or "") or None,
            )
        return jsonify(image=service.summary(session))

    return blueprint


__all__ = ["create_desktop_blueprint"]
