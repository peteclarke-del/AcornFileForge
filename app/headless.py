"""Reusable orchestration for the supported headless command line interface."""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from .analysis_service import build_manifest
from .checksum import sha256_path
from .disk_service import DiskError, DiskService, ImageSession
from .image_diff import compare_images, manifest_fingerprint
from .image_patch import apply_patch_archive, inspect_patch_archive, write_patch_archive
from .menu_service import (
    configure_mmb_universal_page,
    create_adfs_menu,
    install_mmb_menu,
)


RESULT_FORMAT = "acorn-file-forge-cli-result"
RESULT_VERSION = 1
RECIPE_FORMAT = "acorn-file-forge-recipe"
RECIPE_VERSION = 1
MENU_TEMPLATE_DIR = Path(__file__).with_name("assets") / "menu_templates"
BLANK_FORMATS = frozenset({
    "ssd", "dsd", "adfs-s", "adfs-m", "adfs-l", "adfs-d", "adfs-e",
    "adfs-e-plus", "adfs-f", "adfs-f-plus", "adfs-g", "adfs-g-plus",
    "beebscsi", "adfs-hard", "adfs-physical", "mmb", "rom", "romfs",
    "hfe-ssd", "hfe-dsd", "hfe-adfs-s", "hfe-adfs-m", "hfe-adfs-l",
})
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
RECIPE_ACTIONS = frozenset({"create", "import-file", "compact", "menu-create", "convert-uef", "save"})


def progress_to_stderr(stream):
    """Return a progress callback which leaves stdout available for JSON."""
    previous = None

    def report(message: str, current=None, total=None) -> None:
        nonlocal previous
        state = (message, current, total)
        if state == previous:
            return
        previous = state
        suffix = ""
        if current is not None and total:
            suffix = f" [{current}/{total}]"
        print(f"{message}{suffix}", file=stream, flush=True)

    return report


@contextmanager
def open_image(
    image: Path,
    descriptor: Path | None = None,
    *,
    target_hardware: str = "auto",
    force_kind: str | None = None,
) -> Iterator[tuple[DiskService, ImageSession]]:
    """Open an isolated working copy of an image and discard it afterwards."""
    image = Path(image)
    if not image.is_file():
        raise FileNotFoundError(f"Image not found: {image}")
    if descriptor is not None and not Path(descriptor).is_file():
        raise FileNotFoundError(f"Descriptor not found: {descriptor}")
    with tempfile.TemporaryDirectory(prefix="acorn-file-forge-cli-") as work:
        service = DiskService(work)
        session = _load_image(service, image, descriptor, target_hardware, force_kind)
        try:
            yield service, session
        finally:
            if session.id in service.sessions:
                service.discard_session(session)


def _load_image(
    service: DiskService,
    image: Path,
    descriptor: Path | None,
    target_hardware: str,
    force_kind: str | None,
) -> ImageSession:
    with image.open("rb") as source:
        if descriptor is None:
            return service.create_from_stream(
                image.name,
                source,
                target_hardware=target_hardware,
                force_kind=force_kind,
            )
        with Path(descriptor).open("rb") as companion:
            return service.create_from_stream(
                image.name,
                source,
                (Path(descriptor).name, companion),
                target_hardware=target_hardware,
                force_kind=force_kind,
            )


@contextmanager
def open_image_pair(
    first: Path,
    second: Path,
    *,
    first_descriptor: Path | None = None,
    second_descriptor: Path | None = None,
    target_hardware: str = "auto",
    force_kind: str | None = None,
) -> Iterator[tuple[DiskService, ImageSession, ImageSession]]:
    """Open two images under one service for comparison and patch operations."""
    for path, descriptor in ((first, first_descriptor), (second, second_descriptor)):
        if not Path(path).is_file():
            raise FileNotFoundError(f"Image not found: {path}")
        if descriptor is not None and not Path(descriptor).is_file():
            raise FileNotFoundError(f"Descriptor not found: {descriptor}")
    with tempfile.TemporaryDirectory(prefix="acorn-file-forge-cli-") as work:
        service = DiskService(work)
        left = _load_image(service, Path(first), first_descriptor, target_hardware, force_kind)
        right = _load_image(service, Path(second), second_descriptor, target_hardware, force_kind)
        try:
            yield service, left, right
        finally:
            for session in (left, right):
                if session.id in service.sessions:
                    service.discard_session(session)


def source_identity(
    path: Path,
    *,
    descriptor: Path | None = None,
    service: DiskService | None = None,
    session: ImageSession | None = None,
) -> dict:
    """Build a stable physical and, where available, logical source identity."""
    path = Path(path)
    result = {
        "name": path.name,
        "size": path.stat().st_size,
        "sha256": sha256_path(path),
    }
    if descriptor is not None:
        descriptor = Path(descriptor)
        result["descriptor"] = {
            "name": descriptor.name,
            "size": descriptor.stat().st_size,
            "sha256": sha256_path(descriptor),
        }
    if service is not None and session is not None:
        manifest = build_manifest(service, session)
        result.update(
            kind=session.kind,
            logicalFingerprint=manifest_fingerprint(manifest),
        )
    return result


def verify_identity(path: Path, expected: dict, descriptor: Path | None = None) -> dict:
    """Reject a recipe source whose exact bytes no longer match its record."""
    actual = source_identity(path, descriptor=descriptor)
    for field in ("size", "sha256"):
        if actual.get(field) != expected.get(field):
            raise DiskError(f"Recipe source {path.name} failed its expected {field} check.")
    expected_descriptor = expected.get("descriptor")
    if expected_descriptor:
        if "descriptor" not in actual:
            raise DiskError(f"Recipe source {path.name} requires its recorded descriptor.")
        for field in ("size", "sha256"):
            if actual["descriptor"].get(field) != expected_descriptor.get(field):
                raise DiskError(
                    f"Recipe descriptor {Path(descriptor).name} failed its expected {field} check."
                )
    return actual


def save_image(
    service: DiskService,
    session: ImageSession,
    output: Path,
    *,
    force: bool = False,
    progress=None,
    verify: Callable[[list[dict]], None] | None = None,
) -> list[dict]:
    """Finalise and copy an image, including a matching BeebSCSI descriptor."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    prepared = service.prepare_download(session, progress)
    if session.descriptor_path and output.suffix.lower() != ".dat":
        raise DiskError("A paired BeebSCSI image output must use the DAT extension.")
    outputs = [(prepared, output)]
    if session.descriptor_path:
        outputs.append((session.descriptor_path, output.with_suffix(".dsc")))
    for _source, destination in outputs:
        if destination.exists() and not force:
            raise FileExistsError(f"Output already exists: {destination}")
    staged = []
    try:
        for source, destination in outputs:
            temporary = destination.with_name(
                f".{destination.name}.{uuid.uuid4().hex}.tmp"
            )
            service._copy_local_file(source, temporary)
            staged.append((temporary, destination))
        written = [
            {
                "path": str(destination),
                "size": temporary.stat().st_size,
                "sha256": sha256_path(temporary),
            }
            for temporary, destination in staged
        ]
        if verify:
            verify(written)
        for temporary, destination in staged:
            os.replace(temporary, destination)
    finally:
        for temporary, _destination in staged:
            temporary.unlink(missing_ok=True)
    return written


def create_recipe(
    name: str,
    sources: dict[str, dict],
    actions: list[dict],
    output: dict,
) -> dict:
    """Return the canonical versioned recipe document."""
    return {
        "format": RECIPE_FORMAT,
        "version": RECIPE_VERSION,
        "name": str(name or "Acorn File Forge workflow"),
        "sources": sources,
        "actions": actions,
        "output": output,
    }


def load_recipe(path: Path) -> dict:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DiskError(f"The recipe is not readable JSON: {exc}") from exc
    if document.get("format") != RECIPE_FORMAT or document.get("version") != RECIPE_VERSION:
        raise DiskError(
            f"Only {RECIPE_FORMAT} version {RECIPE_VERSION} recipes are supported."
        )
    if not isinstance(document.get("sources"), dict) or not isinstance(document.get("actions"), list):
        raise DiskError("The recipe must contain source identities and an action list.")
    if not isinstance(document.get("output"), dict):
        raise DiskError("The recipe must contain an output decision.")
    for alias, identity in document["sources"].items():
        if not isinstance(alias, str) or not alias or not isinstance(identity, dict):
            raise DiskError("Every recipe source must have a non-empty alias and identity object.")
        if not isinstance(identity.get("size"), int) or identity["size"] < 0:
            raise DiskError(f"Recipe source {alias} has no valid expected size.")
        if not SHA256_PATTERN.fullmatch(str(identity.get("sha256") or "")):
            raise DiskError(f"Recipe source {alias} has no valid expected SHA-256.")
        descriptor = identity.get("descriptor")
        if descriptor is not None and (
            not isinstance(descriptor, dict)
            or not isinstance(descriptor.get("size"), int)
            or descriptor["size"] < 0
            or not SHA256_PATTERN.fullmatch(str(descriptor.get("sha256") or ""))
        ):
            raise DiskError(f"Recipe source {alias} has an invalid descriptor identity.")
    for index, action in enumerate(document["actions"], start=1):
        if not isinstance(action, dict) or action.get("action") not in RECIPE_ACTIONS:
            raise DiskError(f"Recipe action {index} is not supported or is incomplete.")
        if action.get("action") == "import-file" and action.get("source") not in document["sources"]:
            raise DiskError(f"Recipe action {index} refers to an unverified source alias.")
    return document


def install_menu(
    service: DiskService,
    session: ImageSession,
    *,
    menu_type: str,
    slot: int = 0,
    page: str = "current",
) -> dict:
    """Install one supported MMB menu through the shared menu service."""
    if session.kind != "mmb":
        raise DiskError("Headless menu installation currently supports MMB images.")
    result = install_mmb_menu(service, session, slot, MENU_TEMPLATE_DIR, menu_type)
    if menu_type == "universal":
        result.update(configure_mmb_universal_page(service, session, page))
    return result


def create_directory_menu(
    service: DiskService,
    session: ImageSession,
    *,
    root: str,
    entries: list[dict],
) -> dict:
    """Create an ADFS directory menu from explicit, reviewable records."""
    return create_adfs_menu(service, session, root, entries, MENU_TEMPLATE_DIR)


def compare(service, base: ImageSession, candidate: ImageSession, progress=None) -> dict:
    return compare_images(service, base, candidate, progress)


def write_patch(service, base, candidate, output: Path, progress=None) -> dict:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    return write_patch_archive(service, base, candidate, output, progress)


def inspect_patch(service, session, patch: Path, progress=None) -> dict:
    return inspect_patch_archive(service, session, Path(patch), progress)


def apply_patch(service, session, patch: Path, progress=None) -> dict:
    return apply_patch_archive(service, session, Path(patch), progress)
