from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import Blueprint, jsonify, request

from ..archive_utils import iter_upload_images, open_single_upload_image
from ..disk_service import DiskError, DiskService
from ..formats import DFS_EXTENSIONS, HFE_EXTENSIONS
from ..menu_service import (
    analyse_disk,
    best_distribution_filename,
    enrich_if_ambiguous,
    find_menu_slot,
    installed_mmb_menu,
    refresh_mmc_desktop_catalogue,
)
from .common import optional_int, payload


def _menu_metadata(
    service: DiskService,
    session,
    slot: int,
    source_names: list[str] | None = None,
) -> dict | None:
    if source_names:
        service.set_slot_source_name(
            session,
            [slot],
            best_distribution_filename(source_names),
        )
    if find_menu_slot(service, session) is None:
        return None
    return enrich_if_ambiguous(analyse_disk(service, session, slot))


def _refresh_mmc_desktop(service: DiskService, session) -> None:
    slot, menu_type = installed_mmb_menu(service, session)
    if slot is not None and menu_type == "mmc-desktop":
        refresh_mmc_desktop_catalogue(service, session, slot)


def _post_insert_details(service: DiskService, session, slot: int) -> tuple[dict | None, list[str]]:
    """Keep a completed sector insert successful when optional menu work fails."""
    warnings = []
    try:
        _refresh_mmc_desktop(service, session)
    except DiskError as exc:
        warnings.append(f"The disk was inserted, but MMC Desktop could not be refreshed: {exc}")
    try:
        metadata = _menu_metadata(service, session, slot)
    except DiskError as exc:
        metadata = None
        warnings.append(f"The disk was inserted, but its menu metadata could not be prepared: {exc}")
    return metadata, warnings


def _next_empty_run(slots: list[dict], cursor: int, length: int) -> int | None:
    while cursor + length <= len(slots):
        if all(slots[number]["empty"] for number in range(cursor, cursor + length)):
            return cursor
        cursor += 1
    return None


def create_mmb_blueprint(service: DiskService) -> Blueprint:
    blueprint = Blueprint("mmb", __name__)

    @blueprint.get("/api/images/<image_id>/slots")
    def slots(image_id):
        session = service.get(image_id)
        if session.kind != "mmb":
            raise DiskError("This image is not an MMB container.")
        return jsonify(slots=service.list_slots(session))

    @blueprint.post("/api/images/<image_id>/slots/insert")
    def insert_slot_upload(image_id):
        session = service.get(image_id)
        upload = request.files.get("image")
        if not upload or not upload.filename:
            raise DiskError("Choose an SSD/DSD image or a ZIP containing one.")
        with open_single_upload_image(upload, DFS_EXTENSIONS | HFE_EXTENSIONS) as item:
            if Path(item.filename).suffix.lower() in HFE_EXTENSIONS:
                source = service.create_from_stream(item.filename, item.stream)
                try:
                    if source.kind != "dfs":
                        raise DiskError("Only a DFS-formatted HFE can be inserted into an MMB.")
                    inserted = service.insert_slot_from_session(
                        session, int(request.form["slot"]), source, None
                    )
                finally:
                    service.discard_session(source)
            else:
                inserted = service.insert_slot_bytes(
                    session,
                    int(request.form["slot"]),
                    item.stream.read(),
                    item.filename,
                )
            source_name = best_distribution_filename(item.metadata_names)
        service.set_slot_source_name(session, inserted, source_name)
        metadata, warnings = _post_insert_details(service, session, inserted[0])
        return jsonify(
            image=service.summary(session),
            slots=inserted,
            metadata=metadata,
            warnings=warnings,
        )

    @blueprint.post("/api/images/<image_id>/slots/insert-many")
    def insert_many_slot_uploads(image_id):
        session = service.get(image_id)
        uploads = request.files.getlist("images")
        if not uploads:
            raise DiskError("Choose SSD/DSD images or ZIP files containing them.")
        cursor = int(request.form.get("slot", 0))
        items = []
        ambiguous = []
        has_menu = find_menu_slot(service, session) is not None
        slots = service.list_slots(session)
        for upload in iter_upload_images(uploads, DFS_EXTENSIONS | HFE_EXTENSIONS):
            source = None
            if Path(upload.filename).suffix.lower() in HFE_EXTENSIONS:
                source = service.create_from_stream(upload.filename, upload.stream)
                if source.kind != "dfs":
                    service.discard_session(source)
                    items.append({"filename": upload.filename, "slots": [], "error": "Only a DFS-formatted HFE can be inserted into an MMB."})
                    continue
                needed = 2 if source.path.suffix.lower() == ".dsd" else 1
            else:
                needed = 2 if Path(upload.filename).suffix.lower() == ".dsd" else 1
            chosen = _next_empty_run(slots, cursor, needed)
            if chosen is None:
                if source:
                    service.discard_session(source)
                items.append(
                    {
                        "filename": upload.filename,
                        "slots": [],
                        "error": "No suitable empty MMB slot remains.",
                    }
                )
                continue
            try:
                inserted = (
                    service.insert_slot_from_session(session, chosen, source, None)
                    if source
                    else service.insert_slot_bytes(
                        session, chosen, upload.stream.read(), upload.filename
                    )
                )
                service.set_slot_source_name(
                    session,
                    inserted,
                    best_distribution_filename(upload.metadata_names),
                )
                for number in inserted:
                    slots[number]["empty"] = False
                    slots[number]["formatted"] = True
                metadata = analyse_disk(service, session, inserted[0]) if has_menu else None
                item = {
                    "filename": upload.filename,
                    "slots": inserted,
                    "error": None,
                    "metadata": metadata,
                }
                if metadata and metadata["ambiguous"]:
                    ambiguous.append(metadata)
                items.append(item)
                cursor = inserted[-1] + 1
            except DiskError as exc:
                items.append(
                    {
                        "filename": upload.filename,
                        "slots": [],
                        "error": str(exc),
                        "metadata": None,
                    }
                )
                cursor = chosen + 1
            finally:
                if source:
                    service.discard_session(source)
        if ambiguous:
            with ThreadPoolExecutor(max_workers=3) as pool:
                list(pool.map(enrich_if_ambiguous, ambiguous))
        _refresh_mmc_desktop(service, session)
        return jsonify(image=service.summary(session), items=items)

    @blueprint.post("/api/images/<image_id>/slots/insert-from-image")
    def insert_slot_from_image(image_id):
        data = payload()
        target = service.get(image_id)
        inserted = service.insert_slot_from_session(
            target,
            int(data["targetSlot"]),
            service.get(data["sourceImage"]),
            optional_int(data.get("sourceSlot")),
        )
        metadata, warnings = _post_insert_details(service, target, inserted[0])
        return jsonify(
            image=service.summary(target),
            slots=inserted,
            metadata=metadata,
            warnings=warnings,
        )

    @blueprint.post("/api/images/<image_id>/slots/create-blank")
    def create_blank_slot(image_id):
        data = payload()
        target = service.get(image_id)
        disk_format = str(data.get("format", "ssd")).lower()
        if disk_format not in {"ssd", "dsd"}:
            raise DiskError("A blank MMB disk must be SSD or DSD.")
        target_slot = int(data["targetSlot"])
        if not service.list_slots(target)[target_slot]["empty"]:
            raise DiskError("Choose an empty MMB slot for the blank disk.")
        temporary = service.create_blank(
            disk_format,
            str(data.get("title") or "BLANK"),
        )
        try:
            inserted = service.insert_slot_from_session(
                target,
                target_slot,
                temporary,
                None,
            )
        finally:
            service.discard_session(temporary)
        service.protect_slots(target, inserted, bool(data.get("writable", True)))
        metadata, warnings = _post_insert_details(service, target, inserted[0])
        return jsonify(image=service.summary(target), slots=inserted, metadata=metadata, warnings=warnings)

    @blueprint.post("/api/images/<image_id>/slots/clear")
    def clear_slot(image_id):
        data = payload()
        session = service.get(image_id)
        slots = data.get("slots")
        if slots is None:
            slots = [data["slot"]]
        service.clear_slots(session, [int(slot) for slot in slots])
        _refresh_mmc_desktop(service, session)
        return jsonify(image=service.summary(session))

    @blueprint.post("/api/images/<image_id>/slots/move")
    def move_slot(image_id):
        data = payload()
        session = service.get(image_id)
        service.move_slot(session, int(data["sourceSlot"]), int(data["targetSlot"]))
        _refresh_mmc_desktop(service, session)
        return jsonify(image=service.summary(session))

    @blueprint.post("/api/images/<image_id>/slots/protect")
    def protect_slot(image_id):
        data = payload()
        session = service.get(image_id)
        service.protect_slot(session, int(data["slot"]), bool(data.get("writable")))
        return jsonify(image=service.summary(session))

    @blueprint.post("/api/images/<image_id>/slots/protect-many")
    def protect_many_slots(image_id):
        data = payload()
        session = service.get(image_id)
        slots = service.protect_slots(
            session,
            data.get("slots", []),
            bool(data.get("writable")),
        )
        return jsonify(image=service.summary(session), slots=slots)

    return blueprint
