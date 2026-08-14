from __future__ import annotations

import json
import hashlib
import io
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file
from .effects import image_mutation, request_effect

from ..archive_utils import open_single_upload_image
from ..archive_browser import (
    ArchiveError,
    MAX_ARCHIVE_BYTES,
    archive_member_editable,
    is_archive_name,
    list_archive,
    read_archive_member,
    read_archive_member_details,
    replace_archive_member,
)
from ..disk_service import (
    DestinationExistsError,
    DiskError,
    DiskService,
    EmptyDiskError,
)
from ..formats import ADFS_EXTENSIONS, DFS_EXTENSIONS, HFE_EXTENSIONS, MMB_EXTENSIONS, TAPE_EXTENSIONS
from ..file_editor import (
    MAX_DISASSEMBLY_FILE,
    disassemble_file_data,
    encode_editor_replacement,
    inspect_file_data,
    replace_file_bytes,
)
from ..menu.adfs import delete_adfs_items, move_adfs_items
from ..menu.analysis import (
    analyse_adfs_directory,
    analyse_disk,
    best_distribution_filename,
    enrich_if_ambiguous,
    enrich_from_distribution_filename,
)
from ..menu.mmb import (
    continuation_metadata_from_mmb_menu,
    metadata_records_from_mmb_menu,
    mmb_metadata_for_adfs,
)
from ..operations import OperationCancelled, OperationRegistry
from .common import optional_int, payload


def _metadata_for_directory(
    service: DiskService,
    session,
    path: str,
    source_names: list[str] | None = None,
) -> dict:
    metadata = analyse_adfs_directory(service, session, path)
    if source_names:
        enrich_from_distribution_filename(
            metadata,
            best_distribution_filename(source_names),
        )
    return enrich_if_ambiguous(metadata) if metadata["ambiguous"] else metadata


def _metadata_for_copied_mmb_disks(
    service: DiskService,
    source,
    copied_results: list[dict],
    operations: OperationRegistry,
    operation_id: str | None,
    *,
    online: bool,
) -> list[dict]:
    metadata: list[dict] = []
    for offset, result in enumerate(copied_results):
        operations.update(
            operation_id,
            f"Reading launch metadata for disk {offset + 1} of "
            f"{len(copied_results)}",
            offset,
            len(copied_results),
        )
        menu_records = metadata_records_from_mmb_menu(
            service,
            source,
            result["sourceSlot"],
        )
        if not menu_records:
            continuation = continuation_metadata_from_mmb_menu(
                service,
                source,
                result["sourceSlot"],
            )
            if continuation:
                metadata.append(
                    {
                        **continuation,
                        "path": result["destination"],
                        "sourceSlot": result["sourceSlot"],
                        "sourceName": result["sourceName"],
                    }
                )
                continue
        detected_metadata = result.get("detectedMetadata")
        source_metadata = menu_records or [
            detected_metadata
            or analyse_disk(
                service,
                source,
                result["sourceSlot"],
            )
        ]
        detected_fallback = None
        converted: list[dict] = []
        for record in source_metadata:
            converted_record = mmb_metadata_for_adfs(
                record,
                result["launchCandidates"],
                result["destination"],
            )
            if (
                menu_records
                and not converted_record.get("launchObvious")
            ):
                if detected_fallback is None:
                    detected_fallback = (
                        detected_metadata
                        or analyse_disk(
                            service,
                            source,
                            result["sourceSlot"],
                        )
                    )
                converted_record = mmb_metadata_for_adfs(
                    record,
                    result["launchCandidates"],
                    result["destination"],
                    detected_fallback,
                )
            converted.append(
                {
                    **converted_record,
                    "sourceSlot": result["sourceSlot"],
                    "sourceName": result["sourceName"],
                }
            )
        metadata.extend(converted)
    ambiguous = [
        item
        for item in metadata
        if (
            item.get("ambiguous")
            and not item.get("fromMmbMenu")
            and not item.get("skipMenu")
        )
    ]
    if online and ambiguous:
        operations.update(
            operation_id,
            f"Checking online metadata for {len(ambiguous)} ambiguous "
            f"disk{'s' if len(ambiguous) != 1 else ''}",
            0,
            len(ambiguous),
        )
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [
                pool.submit(enrich_if_ambiguous, item)
                for item in ambiguous
            ]
            for completed_count, future in enumerate(
                as_completed(futures),
                start=1,
            ):
                future.result()
                operations.update(
                    operation_id,
                    f"Checked online metadata for {completed_count} of "
                    f"{len(ambiguous)} ambiguous disks",
                    completed_count,
                    len(ambiguous),
                )
    return metadata


def _partial_mmb_metadata(
    service: DiskService,
    source,
    completed: list[dict],
    operations: OperationRegistry,
    operation_id: str | None,
    *,
    enabled: bool,
) -> list[dict]:
    """Best-effort metadata for a paused batch without masking its decision."""
    if not enabled or not completed:
        return []
    try:
        return _metadata_for_copied_mmb_disks(
            service,
            source,
            completed,
            operations,
            operation_id,
            online=False,
        )
    except Exception:
        return []


def create_files_blueprint(
    service: DiskService,
    work_dir: Path,
    operations: OperationRegistry,
) -> Blueprint:
    blueprint = Blueprint("files", __name__)

    @blueprint.get("/api/operations")
    def operation_history():
        return jsonify(operations=operations.list())

    @blueprint.delete("/api/operations")
    @request_effect("external", "clearing completed operation records")
    def clear_operation_history():
        return jsonify(removed=operations.clear_terminal())

    @blueprint.get("/api/operations/<operation_id>")
    def operation_progress(operation_id):
        return jsonify(operation=operations.get(operation_id))

    @blueprint.post("/api/operations/<operation_id>/cancel")
    @request_effect("external", "requesting operation cancellation")
    def cancel_operation(operation_id):
        return jsonify(operation=operations.cancel(operation_id))

    @blueprint.get("/api/images/<image_id>/tree")
    def tree(image_id):
        result = service.browse_directory(
                service.get(image_id),
                request.args.get("path", "$"),
                optional_int(request.args.get("slot")),
                optional_int(request.args.get("side")),
            )
        for entry in result.get("entries", []):
            if entry.get("type") not in {"dir", "directory", "disk"} and is_archive_name(str(entry.get("name") or "")):
                entry["archive"] = True
                entry["filetype"] = "Archive"
        return jsonify(result)

    def archive_context(image_id):
        session = service.get(image_id)
        path = request.args.get("path", "")
        if not path:
            raise ArchiveError("Choose an archive to browse.")
        slot = optional_int(request.args.get("slot"))
        side = optional_int(request.args.get("side"))
        metadata = service.file_metadata(session, slot, path, side)
        if int(metadata.get("length") or 0) > MAX_ARCHIVE_BYTES:
            raise ArchiveError("That archive is too large to browse safely in memory.")
        data = service.read_file(
            session, slot, path, side,
        )
        return data, str(request.args.get("name") or path.rsplit(".", 1)[-1])

    def archive_member_context(image_id):
        session = service.get(image_id)
        data, filename = archive_context(image_id)
        member = str(request.args.get("member") or "")
        if not member:
            raise ArchiveError("Choose an archive member to inspect.")
        content, metadata = read_archive_member_details(data, filename, member)
        digest = hashlib.sha256(content).hexdigest()
        return session, member, content, metadata, digest

    @blueprint.get("/api/images/<image_id>/archive/tree")
    def archive_tree(image_id):
        data, filename = archive_context(image_id)
        return jsonify(list_archive(data, filename, request.args.get("member", "")))

    @blueprint.get("/api/images/<image_id>/archive/file")
    def archive_file(image_id):
        data, filename = archive_context(image_id)
        member = request.args.get("member", "")
        content = read_archive_member(data, filename, member)
        return send_file(
            io.BytesIO(content), mimetype="application/octet-stream", as_attachment=True,
            download_name=member.rsplit("/", 1)[-1] or "archive-member",
        )

    @blueprint.get("/api/images/<image_id>/archive/inspect")
    def archive_inspect(image_id):
        session, member, content, metadata, digest = archive_member_context(image_id)
        archive_data, filename = archive_context(image_id)
        writable = (
            archive_member_editable(archive_data, filename)
            and not session.hfe_read_only
            and session.kind != "tape"
        )
        return jsonify(inspect_file_data(
            content[:MAX_DISASSEMBLY_FILE], metadata, member, read_only=not writable,
            size=len(content), digest=digest,
        ) | {"archiveSha256": hashlib.sha256(archive_data).hexdigest(), "archiveEditable": writable})

    @blueprint.put("/api/images/<image_id>/archive/inspect")
    @image_mutation("editing a file inside an archive")
    def save_archive_inspect(image_id):
        body = payload()
        session = service.get(image_id)
        path = str(body.get("path") or "")
        member = str(body.get("member") or "")
        if not path or not member:
            raise ArchiveError("Choose an archive member to update.")
        slot = optional_int(body.get("slot"))
        side = optional_int(body.get("side"))
        filename = str(body.get("name") or path.rsplit(".", 1)[-1])
        archive_data = service.read_file(session, slot, path, side)
        archive_digest = hashlib.sha256(archive_data).hexdigest()
        if archive_digest != str(body.get("archiveSha256") or ""):
            raise ArchiveError("The archive changed after the member opened. Reopen it before saving.")
        if session.hfe_read_only or session.kind == "tape" or not archive_member_editable(archive_data, filename):
            raise ArchiveError("This container cannot be rebuilt safely in the current image.")
        original, metadata = read_archive_member_details(archive_data, filename, member)
        if hashlib.sha256(original).hexdigest() != str(body.get("sha256") or ""):
            raise ArchiveError("The archive member changed after it opened. Reopen it before saving.")
        inspection = inspect_file_data(original, metadata, member, read_only=False)
        if not inspection["editable"]:
            raise ArchiveError("This archive member cannot be encoded safely by the source editor.")
        replacement = encode_editor_replacement(
            original, str(body.get("text") or ""), bool(inspection["tokenisedBasic"]),
        )
        rebuilt = replace_archive_member(archive_data, filename, member, replacement)
        image = replace_file_bytes(service, session, path, slot, side, rebuilt, archive_digest)
        saved, saved_metadata = read_archive_member_details(rebuilt, filename, member)
        result = inspect_file_data(saved, saved_metadata, member, read_only=False)
        result.update(archiveSha256=hashlib.sha256(rebuilt).hexdigest(), archiveEditable=True)
        return jsonify(image=image, inspection=result)

    @blueprint.get("/api/images/<image_id>/archive/disassembly")
    def archive_disassembly(image_id):
        session, member, content, metadata, digest = archive_member_context(image_id)
        try:
            origin = int(str(request.args.get("origin")), 0) if request.args.get("origin") not in (None, "") else None
            start = int(str(request.args.get("start") or "0"), 0)
            length = int(str(request.args.get("length")), 0) if request.args.get("length") not in (None, "") else None
        except ValueError as exc:
            raise ArchiveError("Origin, offset and length must be valid decimal or 0x-prefixed numbers.") from exc
        return jsonify(disassemble_file_data(
            content[:MAX_DISASSEMBLY_FILE], metadata, session, member,
            str(request.args.get("architecture") or "auto"),
            origin, start, length,
            size=len(content), digest=digest,
        ))

    @blueprint.get("/api/images/<image_id>/preview")
    def preview_image(image_id):
        return jsonify(service.preview_image_contents(service.get(image_id)))

    @blueprint.get("/api/images/<image_id>/stat")
    def stat(image_id):
        return jsonify(
            service.stat(
                service.get(image_id),
                optional_int(request.args.get("slot")),
            )
        )

    @blueprint.get("/api/images/<image_id>/capacity")
    def capacity(image_id):
        return jsonify(
            capacity=service.capacity(
                service.get(image_id),
                optional_int(request.args.get("slot")),
            )
        )

    @blueprint.post("/api/images/<image_id>/validate")
    @request_effect("read-only", "validating an image without changing it")
    def validate(image_id):
        data = payload()
        return jsonify(
            message=service.validate(
                service.get(image_id),
                optional_int(data.get("slot")),
            )
        )

    @blueprint.post("/api/images/<image_id>/rename")
    @image_mutation("renaming an item")
    def rename(image_id):
        data = payload()
        session = service.get(image_id)
        slot = optional_int(data.get("slot"))
        if session.kind == "mmb" and data.get("slotTitle") is not None:
            service.rename_slot(session, slot, data["slotTitle"])
            result = {}
        elif session.kind == "rom":
            service.rename_rom_bank(session, int(data["bank"]), data.get("title", ""))
            result = {}
        elif session.kind == "adfs":
            result = move_adfs_items(
                service,
                session,
                [{
                    "source": data["source"],
                    "destination": data["destination"],
                }],
            )
        else:
            side = optional_int(data.get("side"))
            service.mutate(
                session,
                slot,
                [
                    "mv",
                    "--force" if data.get("overwrite") else "",
                    "{image}:" + data["source"],
                    data["destination"],
                ],
                side,
            )
            service.move_editor_projects(
                session,
                [{"source": data["source"], "destination": data["destination"]}],
                slot,
                side,
            )
            result = {}
        return jsonify(image=service.summary(session), **result)

    @blueprint.post("/api/images/<image_id>/move")
    @image_mutation("moving items")
    def move_items(image_id):
        session = service.get(image_id)
        result = move_adfs_items(
            service,
            session,
            payload().get("items", []),
        )
        return jsonify(image=service.summary(session), **result)

    @blueprint.post("/api/images/<image_id>/move-dfs")
    @image_mutation("moving DFS files between catalogue groups")
    def move_dfs_items(image_id):
        data = payload()
        session = service.get(image_id)
        moved = service.move_dfs_items(
            session,
            optional_int(data.get("slot")),
            data.get("items", []),
            optional_int(data.get("side")),
        )
        return jsonify(image=service.summary(session), moved=moved)

    @blueprint.post("/api/images/<image_id>/delete")
    @image_mutation("deleting an item")
    def delete(image_id):
        data = payload()
        session = service.get(image_id)
        items = data.get("items")
        if items is None:
            items = [{
                "path": data["path"],
                "recursive": bool(data.get("recursive")),
            }]
        if not isinstance(items, list) or not items:
            raise DiskError("Choose at least one item to delete.")
        if session.kind == "rom":
            banks = [int(item.get("bank")) for item in items]
            service.clear_rom_banks(session, banks)
            result = {"deletedItems": [{"bank": bank} for bank in banks]}
        elif session.kind == "adfs":
            result = delete_adfs_items(
                service,
                session,
                [item["path"] for item in items],
            )
        else:
            slot = optional_int(data.get("slot"))
            side = optional_int(data.get("side"))
            args = ["rm", "--force"]
            if any(item.get("recursive") for item in items):
                args.append("--recursive")
            args.append("{image}:" + items[0]["path"])
            args.extend(
                service.inner_for(session, item["path"], optional_int(data.get("side")))
                for item in items[1:]
            )
            service.mutate(
                session,
                slot,
                args,
                side,
            )
            service.delete_editor_projects(
                session,
                [item["path"] for item in items],
                slot,
                side,
            )
            result = {
                "deletedItems": [
                    {"path": item["path"], "isDirectory": bool(item.get("recursive"))}
                    for item in items
                ]
            }
        return jsonify(image=service.summary(session), **result)

    @blueprint.post("/api/images/<image_id>/mkdir")
    @image_mutation("creating a folder")
    def mkdir(image_id):
        data = payload()
        session = service.get(image_id)
        if session.kind != "adfs":
            raise DiskError(
                "This filing system cannot store directories. "
                "DFS uses one-character catalogue prefixes instead."
            )
        path = str(data.get("path") or "").strip()
        if not path.startswith("$.") or path.endswith("."):
            raise DiskError("Choose a valid ADFS parent directory and folder name.")
        service.validate_leaf_name(session, path.rsplit(".", 1)[-1])
        service.make_directory(session, path)
        return jsonify(image=service.summary(session))

    @blueprint.post("/api/images/<image_id>/empty-file")
    @image_mutation("creating a file")
    def create_empty_file(image_id):
        data = payload()
        session = service.get(image_id)
        slot = optional_int(data.get("slot"))
        side = optional_int(data.get("side"))
        if session.kind in {"rom", "tape"} or (session.kind == "mmb" and slot is None):
            raise DiskError("This view cannot contain ordinary files.")
        destination_dir = str(data.get("destination") or "$").rstrip(".")
        if session.kind == "dfs" or (session.kind == "mmb" and slot is not None):
            destination_dir = service.validate_dfs_prefix(destination_dir)
        name = service.validate_leaf_name(session, str(data.get("name") or ""), slot)
        existing = service.list_directory(session, destination_dir, slot, side)["entries"]
        if any(str(row.get("name") or "").casefold() == name.casefold() for row in existing):
            raise DiskError(f"'{name}' already exists in this directory.")
        destination = name if session.kind == "romfs" else f"{destination_dir}.{name}"
        with tempfile.NamedTemporaryFile(dir=work_dir, prefix="empty-file-", delete=False) as temp:
            temp_path = Path(temp.name)
        try:
            service.put(
                session, slot, destination, temp_path,
                str(data.get("load") or "") or None,
                str(data.get("execute") or "") or None,
                str(data.get("filetype") or "") or None,
                side,
            )
        finally:
            temp_path.unlink(missing_ok=True)
        return jsonify(image=service.summary(session), path=destination)

    @blueprint.post("/api/images/<image_id>/lock")
    @image_mutation("changing file protection")
    def lock(image_id):
        data = payload()
        session = service.get(image_id)
        paths = data.get("paths")
        if paths is None:
            paths = [data["path"]]
        if not isinstance(paths, list) or not paths:
            raise DiskError("Choose at least one file to update.")
        updated = service.set_access(
            session,
            optional_int(data.get("slot")),
            paths,
            bool(data.get("unlock")),
            optional_int(data.get("side")),
        )
        return jsonify(image=service.summary(session), paths=updated)

    @blueprint.post("/api/images/<image_id>/files")
    @image_mutation("adding a file")
    def put_file(image_id):
        upload = request.files.get("file")
        if not upload or not upload.filename:
            raise DiskError("Choose a host file to import.")
        session = service.get(image_id)
        if session.kind == "rom":
            data = upload.read()
            requested = optional_int(request.form.get("bank"))
            inserted = service.put_rom_bank(session, data, requested)
            return jsonify(image=service.summary(session), bank=inserted)
        slot = optional_int(request.form.get("slot"))
        name = request.form.get("targetName") or DiskService.safe_filename(upload.filename)
        name = service.validate_leaf_name(session, name, slot)
        destination_dir = request.form.get("destination", "$").rstrip(".")
        if session.kind == "dfs" or (session.kind == "mmb" and slot is not None):
            destination_dir = service.validate_dfs_prefix(destination_dir)
        destination = name if session.kind == "romfs" else f"{destination_dir}.{name}"
        with tempfile.NamedTemporaryFile(dir=work_dir, prefix="import-", delete=False) as temp:
            upload.save(temp)
            temp_path = Path(temp.name)
        try:
            service.put(
                session,
                slot,
                destination,
                temp_path,
                request.form.get("load"),
                request.form.get("execute"),
                request.form.get("filetype"),
                optional_int(request.form.get("side")),
            )
        finally:
            temp_path.unlink(missing_ok=True)
        return jsonify(image=service.summary(session))

    @blueprint.post("/api/images/<image_id>/rom-banks/blank")
    @image_mutation("appending a blank ROM bank")
    def append_blank_rom_bank(image_id):
        session = service.get(image_id)
        if session.kind != "rom":
            raise DiskError("This image is not a ROM.")
        bank = service.put_rom_bank(
            session,
            bytes((session.rom_erase_byte,)) * session.rom_bank_size,
            len(service.list_rom_banks(session)),
        )
        return jsonify(image=service.summary(session), bank=bank)

    @blueprint.get("/api/images/<image_id>/rom-banks/<int:bank>/inspect")
    def inspect_rom_bank(image_id, bank):
        session = service.get(image_id)
        return jsonify(bank=service.inspect_rom_bank(session, bank))

    @blueprint.post("/api/images/<image_id>/rom-banks/move")
    @image_mutation("moving ROM banks")
    def move_rom_banks(image_id):
        data = payload()
        session = service.get(image_id)
        targets = service.move_rom_banks(
            session,
            [int(bank) for bank in data.get("banks", [])],
            int(data.get("targetStart")),
        )
        return jsonify(image=service.summary(session), banks=targets)

    @blueprint.post("/api/images/<image_id>/folder-import")
    @image_mutation("importing a host folder")
    def put_folder(image_id):
        uploads = request.files.getlist("files")
        try:
            target_paths = json.loads(request.form.get("targetPaths", "[]"))
            metadata = json.loads(request.form.get("metadata", "[]"))
        except json.JSONDecodeError as exc:
            raise DiskError("The folder import plan is invalid.") from exc
        if not uploads or len(uploads) != len(target_paths):
            raise DiskError("The selected files no longer match the folder import plan.")
        if not isinstance(target_paths, list) or not all(isinstance(path, str) for path in target_paths):
            raise DiskError("The folder import paths are invalid.")
        if not metadata:
            metadata = [{} for _upload in uploads]
        if len(metadata) != len(uploads) or not all(isinstance(item, dict) for item in metadata):
            raise DiskError("The folder import metadata is invalid.")
        session = service.get(image_id)
        slot = optional_int(request.form.get("slot"))
        temp_paths: list[Path] = []
        try:
            items = []
            for upload, target_path, file_metadata in zip(uploads, target_paths, metadata, strict=True):
                with tempfile.NamedTemporaryFile(dir=work_dir, prefix="folder-import-", delete=False) as temp:
                    upload.save(temp)
                    temp_path = Path(temp.name)
                temp_paths.append(temp_path)
                items.append({
                    "targetPath": target_path,
                    "hostPath": temp_path,
                    "metadata": file_metadata,
                })
            result = service.put_host_tree(
                session,
                slot,
                request.form.get("destination", "$"),
                items,
                preserve_directories=request.form.get("mode") == "preserve",
                replace=request.form.get("replace") == "true",
                side=optional_int(request.form.get("side")),
            )
        finally:
            for temp_path in temp_paths:
                temp_path.unlink(missing_ok=True)
        return jsonify(image=service.summary(session), **result)

    @blueprint.post("/api/transfer")
    @image_mutation("copying files", target="targetImage")
    def transfer():
        data = payload()
        source = service.get(data["sourceImage"])
        target = service.get(data["targetImage"])
        service.copy(
            source,
            optional_int(data.get("sourceSlot")),
            data["sourcePath"],
            target,
            optional_int(data.get("targetSlot")),
            data["targetPath"],
            bool(data.get("recursive")),
            optional_int(data.get("sourceSide")),
            optional_int(data.get("targetSide")),
        )
        return jsonify(image=service.summary(target))

    @blueprint.post("/api/transfer-slot-to-directory")
    @image_mutation("copying an MMB disk to ADFS", target="targetImage")
    def transfer_slot_to_directory():
        data = payload()
        source = service.get(data["sourceImage"])
        target = service.get(data["targetImage"])
        source_slot = int(data["sourceSlot"])
        operation_id = data.get("operationId")
        with operations.tracked(
            operation_id, "Preparing MMB slot transfer", "Transfer complete"
        ) as progress:
            menu_metadata: list[dict] = []
            if data.get("addMenu"):
                progress("Checking the MMB Universal Menu")
                menu_metadata = metadata_records_from_mmb_menu(
                    service,
                    source,
                    source_slot,
                )
            destination = service.copy_mmb_slot_to_adfs_directory(
                source,
                source_slot,
                target,
                data.get("targetPath", "$"),
                data["directoryName"],
                progress,
            )
            metadata = None
            metadata_entries: list[dict] = []
            if data.get("addMenu"):
                progress("Analysing launch files in the copied directory")
                detected = analyse_adfs_directory(service, target, destination)
                if menu_metadata:
                    metadata_entries = [
                        mmb_metadata_for_adfs(
                            record,
                            detected["launchCandidates"],
                            destination,
                            detected,
                        )
                        for record in menu_metadata
                    ]
                    metadata = metadata_entries[0]
                else:
                    if detected["ambiguous"]:
                        progress("Checking the online software archive")
                        metadata = enrich_if_ambiguous(detected)
                    else:
                        metadata = detected
                    metadata_entries = [metadata]
        return jsonify(
            image=service.summary(target),
            path=destination,
            metadata=metadata,
            metadataEntries=metadata_entries,
        )

    @blueprint.post("/api/transfer-mmb-batch-to-adfs")
    @image_mutation("copying MMB disks to ADFS", target="targetImage")
    def transfer_mmb_batch_to_adfs():
        data = payload()
        source = service.get(data["sourceImage"])
        target = service.get(data["targetImage"])
        operation_id = data.get("operationId")
        completed: list[dict] = []
        skipped: list[dict] = []
        resumable_request = {
            key: value for key, value in data.items() if key != "operationId"
        }

        def partial_response(error: Exception, **extra) -> dict:
            metadata = _partial_mmb_metadata(
                service,
                source,
                completed,
                operations,
                operation_id,
                enabled=bool(data.get("addMenu")),
            )
            operations.details(
                operation_id,
                resumable=True,
                endpoint="/api/transfer-mmb-batch-to-adfs",
                request=resumable_request,
                completed=completed,
                skipped=skipped,
            )
            return {
                "error": str(error),
                "image": service.summary(target),
                "completed": completed,
                "skipped": skipped,
                "metadata": metadata,
                **extra,
            }

        operations.start(operation_id, "Preparing accelerated MMB batch transfer")
        operations.details(
            operation_id,
            resumable=True,
            endpoint="/api/transfer-mmb-batch-to-adfs",
            request=resumable_request,
            completed=[],
            skipped=[],
        )
        try:
            results = service.copy_mmb_slots_to_adfs_directories(
                source,
                target,
                data.get("items", []),
                lambda message, current=None, total=None: operations.update(
                    operation_id, message, current, total
                ),
                completed.append,
                skipped.append,
                stop_on_empty=bool(data.get("stopOnEmpty")),
                stop_on_conflict=bool(data.get("stopOnConflict")),
                apply_compatibility=data.get("compatibility", True) is not False,
            )
            copied_results = [result for result in results if not result.get("skipped")]
            metadata = (
                _metadata_for_copied_mmb_disks(
                    service,
                    source,
                    copied_results,
                    operations,
                    operation_id,
                    online=data.get("onlineMetadata", True) is not False,
                )
                if data.get("addMenu")
                else []
            )
            operations.finish(operation_id, "Accelerated batch transfer complete")
            operations.details(
                operation_id,
                resumable=False,
                completed=completed,
                skipped=skipped,
            )
            return jsonify(
                image=service.summary(target),
                completed=completed,
                skipped=skipped,
                metadata=metadata,
            )
        except EmptyDiskError as exc:
            operations.pause(
                operation_id,
                f"Waiting for a decision on slot {exc.disk['sourceSlot']} · "
                f"{exc.disk['sourceName']}",
            )
            return jsonify(
                partial_response(
                    exc,
                    blankDisk=exc.disk,
                    decisionRequired="skip-or-abort",
                )
            ), 409
        except DestinationExistsError as exc:
            operations.pause(
                operation_id,
                f"Waiting for a decision on existing directory "
                f"{exc.conflict['destination']}",
            )
            return jsonify(
                partial_response(
                    exc,
                    destinationConflict=exc.conflict,
                    decisionRequired="keep-replace-or-abort",
                )
            ), 409
        except OperationCancelled as exc:
            operations.cancelled(operation_id, str(exc))
            return jsonify(partial_response(exc)), 409
        except Exception as exc:
            operations.fail(operation_id, str(exc))
            return jsonify(partial_response(exc)), 400

    @blueprint.post("/api/transfer-image-to-directory")
    @image_mutation("extracting an image to ADFS", target="targetImage")
    def transfer_image_to_directory():
        data = payload()
        source = service.get(data["sourceImage"])
        target = service.get(data["targetImage"])
        create_directory = data.get("createDirectory", True) is not False
        operation_id = data.get("operationId")
        with operations.tracked(
            operation_id, "Preparing image extraction", "Extraction complete"
        ) as progress:
            destination = service.extract_image_to_adfs_directory(
                source,
                target,
                data.get("targetPath", "$"),
                data.get("directoryName"),
                progress,
                create_directory=create_directory,
            )
            service.set_adfs_source_name(
                target,
                destination,
                source.distribution_name or source.name,
            )
            metadata = (
                _metadata_for_directory(
                    service,
                    target,
                    destination,
                )
                if data.get("addMenu")
                else None
            )
        return jsonify(
            image=service.summary(target),
            path=destination,
            metadata=metadata,
        )

    @blueprint.post("/api/images/<image_id>/extract-to-directory")
    @image_mutation("extracting an image")
    def extract_to_directory(image_id):
        target = service.get(image_id)
        upload = request.files.get("image")
        if not upload or not upload.filename:
            raise DiskError("Choose a supported disk or tape image to extract.")
        operation_id = request.form.get("operationId")
        create_directory = request.form.get("createDirectory", "yes") != "no"
        extensions = (
            DFS_EXTENSIONS | MMB_EXTENSIONS | TAPE_EXTENSIONS | ADFS_EXTENSIONS | HFE_EXTENSIONS
        )
        with open_single_upload_image(upload, extensions) as image:
            source = service.create_from_stream(image.filename, image.stream)
            try:
                with operations.tracked(
                    operation_id,
                    "Preparing uploaded image extraction",
                    "Extraction complete",
                ) as progress:
                    destination = service.extract_image_to_adfs_directory(
                        source,
                        target,
                        request.form.get("targetPath", "$"),
                        request.form.get("directoryName"),
                        progress,
                        create_directory=create_directory,
                    )
                    service.set_adfs_source_name(
                        target,
                        destination,
                        best_distribution_filename(image.metadata_names),
                    )
                    metadata = (
                        _metadata_for_directory(service, target, destination)
                        if request.form.get("addMenu") == "yes"
                        else None
                    )
            finally:
                service.discard_session(source)
        return jsonify(
            image=service.summary(target),
            path=destination,
            metadata=metadata,
        )

    @blueprint.get("/api/images/<image_id>/file")
    def get_file(image_id):
        session = service.get(image_id)
        inner = request.args["path"]
        path = service.export_file(
            session,
            optional_int(request.args.get("slot")),
            inner,
            optional_int(request.args.get("side")),
        )
        name = inner.rsplit(".", 1)[-1] or "file"
        bundle = request.args.get("bundle") == "metadata"
        download_path = path
        download_name = name
        mimetype = "application/octet-stream"
        cleanup = [path]
        if bundle:
            try:
                metadata = service.file_metadata(
                    session,
                    optional_int(request.args.get("slot")),
                    inner,
                    optional_int(request.args.get("side")),
                )
                with tempfile.NamedTemporaryFile(
                    dir=work_dir,
                    prefix="file-export-",
                    suffix=".zip",
                    delete=False,
                ) as archive_temp:
                    archive_path = Path(archive_temp.name)
                cleanup.append(archive_path)
                inf = (
                    f"$.{name} {metadata['load']:08X} {metadata['execute']:08X} "
                    f"{metadata['length']:08X}{' Locked' if metadata['access'] & 8 else ''}\n"
                )
                with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.write(path, name)
                    archive.writestr(f"{name}.inf", inf)
                download_path = archive_path
                download_name = f"{name}-with-metadata.zip"
                mimetype = "application/zip"
            except Exception:
                for item in cleanup:
                    item.unlink(missing_ok=True)
                raise
        response = send_file(
            download_path,
            as_attachment=True,
            download_name=download_name,
            mimetype=mimetype,
            conditional=True,
        )
        def remove_exports() -> None:
            for item in cleanup:
                item.unlink(missing_ok=True)

        response.call_on_close(remove_exports)
        return response

    return blueprint
