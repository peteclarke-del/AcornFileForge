from __future__ import annotations

import io
import re
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from flask import Blueprint, jsonify, request

from ..acorn_metadata import spark_metadata
from ..archive_utils import validated_zip_members
from ..catalog_service import CatalogueService, archive_members
from ..disk_service import DiskError, DiskService
from ..formats import DFS_EXTENSIONS, HFE_EXTENSIONS, TAPE_EXTENSIONS
from ..menu.analysis import analyse_adfs_directory, analyse_disk, enrich_if_ambiguous
from ..menu.mmb import (
    find_menu_slot,
    installed_mmb_menus,
    parse_mmb_menu_data,
)
from .common import payload
from .effects import image_mutation, request_effect


DISK_EXTENSIONS = DFS_EXTENSIONS | HFE_EXTENSIONS | TAPE_EXTENSIONS


def _catalogue_identities(value: object) -> set[str]:
    """Return conservative comparable names for a catalogue or installed item."""
    text = Path(str(value or "")).stem.strip()
    if not text:
        return set()
    without_attribution = re.sub(r"\s+\([^()]*(?:\)|$)", "", text).strip()
    return {
        identity
        for candidate in {text, without_attribution}
        if (identity := re.sub(r"[^a-z0-9]+", " ", candidate.casefold()).strip())
    }


def _first_empty_runs(service: DiskService, session, start: int, needed: int) -> int | None:
    slots = service.list_slots(session)
    for cursor in list(range(max(0, start), len(slots))) + list(range(0, max(0, start))):
        if cursor + needed <= len(slots) and all(slots[number]["empty"] for number in range(cursor, cursor + needed)):
            return cursor
    return None


def _disk_members(filename: str, content: bytes) -> list[tuple[str, bytes]]:
    return [
        (name, data) for name, data in archive_members(filename, content)
        if Path(name).suffix.lower() in DISK_EXTENSIONS
    ]


def _preferred_disk_members(filename: str, content: bytes) -> list[tuple[str, bytes]]:
    """Keep every disk in the best available format, not duplicate tape variants."""
    members = _disk_members(filename, content)
    if not members:
        return []
    priority = {".ssd": 0, ".dsd": 1, ".hfe": 2, ".uef": 3}
    best = min(priority.get(Path(name).suffix.lower(), 99) for name, _data in members)
    return [
        (name, data)
        for name, data in members
        if priority.get(Path(name).suffix.lower(), 99) == best
    ]


def _copy_disk_files(service: DiskService, source, target, target_slot, target_path, target_side):
    sides = [0, 2] if source.path.name.lower().endswith(".dsd") else [None]
    copied = 0
    for source_side in sides:
        rows = service.list_dfs_catalogue_files(source, None, source_side)
        preserve_prefixes = any(row["prefix"] != "$" for row in rows)
        for row in rows:
            name = str(row["name"])
            destination_prefix = row["prefix"] if preserve_prefixes else target_path
            destination = f"{destination_prefix}.{name}"
            service.copy(source, None, row["path"], target, target_slot, destination, False, source_side, target_side)
            copied += 1
    if not copied:
        raise DiskError("The downloaded disk image is empty, so nothing was installed.")
    return copied


def _install_riscos_package(service: DiskService, target, target_path: str, content: bytes) -> int:
    if target.kind != "adfs":
        raise DiskError("RISC OS packages can only be installed into an ADFS or RISC OS image.")
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise DiskError("The downloaded RISC OS package is not a valid ZIP file.") from exc
    installed = 0
    made = set()
    try:
        for info in validated_zip_members(archive):
            path = PurePosixPath(info.filename)
            if not path.parts or path.parts[0].casefold() == "riscpkg" or ".." in path.parts:
                continue
            parts = [part for part in path.parts if part not in {"", "."}]
            if info.is_dir() or not parts:
                continue
            parent = target_path
            for part in parts[:-1]:
                parent = f"{parent}.{part}" if parent != "$" else f"$.{part}"
                if parent.casefold() not in made:
                    service.mutate(target, None, ["mkdir", "-p", "{image}:" + parent])
                    made.add(parent.casefold())
            destination = f"{parent}.{parts[-1]}" if parent != "$" else f"$.{parts[-1]}"
            metadata = spark_metadata(info.extra) or {}
            load = hex(metadata["load"]) if "load" in metadata else None
            execute = hex(metadata["execute"]) if "execute" in metadata else None
            filetype = f"{metadata['filetype']:03X}" if metadata.get("filetype") is not None else None
            with tempfile.NamedTemporaryFile(dir=service.work_dir, delete=False) as temporary:
                temporary.write(archive.read(info)); host_path = Path(temporary.name)
            try:
                service.put(target, None, destination, host_path, load, execute, filetype)
            finally:
                host_path.unlink(missing_ok=True)
            installed += 1
    finally:
        archive.close()
    if not installed:
        raise DiskError("The package did not contain any installable RISC OS files.")
    return installed


def create_catalog_blueprint(service: DiskService, work_dir: Path) -> Blueprint:
    catalogue = CatalogueService(work_dir)
    blueprint = Blueprint("catalog", __name__)

    @blueprint.get("/api/catalog/sources")
    def sources():
        return jsonify(sources=catalogue.sources())

    @blueprint.put("/api/catalog/sources")
    @request_effect("external", "saving Online Library source configuration")
    def save_sources():
        return jsonify(sources=catalogue.save_sources(payload().get("sources", [])))

    @blueprint.get("/api/images/<image_id>/catalog/search")
    def search(image_id):
        session = service.get(image_id)
        machine = str(request.args.get("machine") or "all")
        selected_sources = {item for item in request.args.get("sources", "").split(",") if item} or None
        rows, failures = catalogue.search(str(request.args.get("q") or ""), machine, selected_sources)
        installed = set()
        if session.kind == "mmb":
            for slot in service.list_slots(session):
                if slot["formatted"]:
                    installed.update(_catalogue_identities(slot["name"]))
            for name in session.slot_source_names.values():
                installed.update(_catalogue_identities(name))
            try:
                for menu in installed_mmb_menus(service, session):
                    menu_type = str(menu.get("type") or "")
                    if menu_type not in {"universal", "universal-4r", "spi-game-menu"}:
                        continue
                    data_file = "$.EGAMDAT" if menu_type == "universal-4r" else "$.GAMDATA"
                    entries = parse_mmb_menu_data(
                        service.read_file(session, int(menu["slot"]), data_file),
                        menu_type,
                    )
                    for entry in entries:
                        installed.update(_catalogue_identities(entry.get("title")))
                        installed.update(_catalogue_identities(entry.get("diskTitle")))
            except DiskError:
                pass
        else:
            try:
                for entry in service.list_directory(session, str(request.args.get("path") or "$"), request.args.get("slot", type=int))["entries"]:
                    installed.update(_catalogue_identities(entry["name"]))
            except DiskError:
                pass
        for row in rows:
            candidates = _catalogue_identities(row["title"])
            candidates.update(_catalogue_identities(Path(str(row.get("pageUrl") or "")).stem))
            row["installed"] = bool(candidates & installed)
        if request.args.get("scope") == "missing":
            rows = [row for row in rows if not row["installed"]]
        return jsonify(items=rows, failures=failures)

    @blueprint.post("/api/images/<image_id>/catalog/install")
    @image_mutation("installing software from the Online Library")
    def install(image_id):
        data = payload(); target = service.get(image_id)
        item_ids = [str(item) for item in data.get("itemIds", [])]
        if not item_ids or len(item_ids) > 100:
            raise DiskError("Choose between 1 and 100 online catalogue items.")
        target_path = str(data.get("path") or "$")
        target_slot = data.get("slot"); target_slot = int(target_slot) if target_slot is not None else None
        target_side = data.get("side"); target_side = int(target_side) if target_side is not None else None
        explicit_slots = [int(slot) for slot in data.get("slots", [])]
        cursor = int(data.get("startSlot", explicit_slots[0] if explicit_slots else 0))
        add_to_menu = bool(data.get("addToMenu", True))
        results = []
        for offset, item_id in enumerate(item_ids):
            source = None
            try:
                filename, content, item = catalogue.download(
                    item_id,
                    "adfs" if target.kind == "adfs" else "dfs",
                )
                if item["artifactType"] == "riscos-package":
                    count = _install_riscos_package(service, target, target_path, content)
                    results.append({"id": item_id, "title": item["title"], "installed": count, "slots": [], "metadata": None})
                    continue
                members = _preferred_disk_members(filename, content)
                if not members:
                    raise DiskError("No supported SSD, DSD, HFE or UEF image was found in the download.")
                for member_name, member_data in members:
                    source = service.create_from_stream(Path(member_name).name, io.BytesIO(member_data))
                    if target.kind == "mmb" and target_slot is None:
                        if source.kind not in {"dfs"}:
                            raise DiskError("Only DFS SSD, DSD and DFS-formatted HFE images can be inserted into an MMB.")
                        needed = 2 if source.path.name.lower().endswith(".dsd") else 1
                        requested = explicit_slots[offset] if offset < len(explicit_slots) else cursor
                        chosen = _first_empty_runs(service, target, requested, needed)
                        if chosen is None:
                            raise DiskError("No suitable empty MMB slot remains.")
                        slots = service.insert_slot_from_session(target, chosen, source, None)
                        source_label = f"{item['title']} ({item.get('publisher') or 'Unknown'}).{Path(member_name).suffix.lstrip('.')}"
                        service.set_slot_source_name(target, slots, source_label)
                        metadata = analyse_disk(service, target, slots[0]) if add_to_menu and find_menu_slot(service, target) is not None else None
                        if metadata and metadata.get("ambiguous"):
                            metadata = enrich_if_ambiguous(metadata)
                        if metadata:
                            metadata["title"] = str(item.get("title") or metadata["title"])
                            metadata["publisher"] = str(item.get("publisher") or metadata["publisher"])
                            metadata.setdefault("sources", []).append(item.get("sourceName", "Online Library"))
                            metadata.setdefault("evidence", []).append("Title and publisher loaded from the selected online catalogue record.")
                        results.append({"id": item_id, "title": item["title"], "installed": 1, "slots": slots, "metadata": metadata})
                        cursor = slots[-1] + 1
                    elif target.kind == "adfs":
                        create_dir = bool(data.get("createDirectory", False))
                        directory = re.sub(r"[^A-Za-z0-9!_-]", "_", item["title"])[:10] or "ONLINE"
                        destination = service.extract_image_to_adfs_directory(source, target, target_path, directory, create_directory=create_dir)
                        metadata = analyse_adfs_directory(service, target, destination) if add_to_menu else None
                        if metadata:
                            metadata["title"] = str(item.get("title") or metadata["title"])
                            metadata["publisher"] = str(item.get("publisher") or metadata["publisher"])
                            metadata.setdefault("sources", []).append(item.get("sourceName", "Online Library"))
                            metadata.setdefault("evidence", []).append(
                                "Title and publisher loaded from the selected online catalogue record."
                            )
                        results.append({"id": item_id, "title": item["title"], "installed": 1, "path": destination, "slots": [], "metadata": metadata})
                    else:
                        if service.replace_blank_dfs_image(
                            target,
                            source,
                            member_name,
                            target_slot=target_slot,
                            target_path=target_path,
                        ):
                            count = len(service.list_dfs_catalogue_files(target, target_slot, target_side))
                        else:
                            count = _copy_disk_files(service, source, target, target_slot, target_path, target_side)
                        results.append({"id": item_id, "title": item["title"], "installed": count, "slots": [], "metadata": None})
                    service.discard_session(source); source = None
            except DiskError as exc:
                results.append({"id": item_id, "title": catalogue.item(item_id).get("title", item_id), "error": str(exc), "slots": []})
            finally:
                if source:
                    service.discard_session(source)
        if not any(not result.get("error") for result in results):
            raise DiskError(results[0]["error"])
        return jsonify(image=service.summary(target), items=results)

    return blueprint
