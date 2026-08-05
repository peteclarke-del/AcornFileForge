from __future__ import annotations

import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

from ..archive_utils import open_single_upload_image
from ..disk_service import (
    DestinationExistsError,
    DiskError,
    DiskService,
    EmptyDiskError,
)
from ..formats import ADFS_EXTENSIONS, DFS_EXTENSIONS, HFE_EXTENSIONS, MMB_EXTENSIONS, TAPE_EXTENSIONS
from ..menu_service import (
    analyse_adfs_directory,
    analyse_disk,
    best_distribution_filename,
    continuation_metadata_from_mmb_menu,
    delete_adfs_items,
    enrich_if_ambiguous,
    enrich_from_distribution_filename,
    metadata_records_from_mmb_menu,
    mmb_metadata_for_adfs,
    move_adfs_items,
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
    def clear_operation_history():
        return jsonify(removed=operations.clear_terminal())

    @blueprint.get("/api/operations/<operation_id>")
    def operation_progress(operation_id):
        return jsonify(operation=operations.get(operation_id))

    @blueprint.post("/api/operations/<operation_id>/cancel")
    def cancel_operation(operation_id):
        return jsonify(operation=operations.cancel(operation_id))

    @blueprint.get("/api/images/<image_id>/tree")
    def tree(image_id):
        return jsonify(
            service.list_directory(
                service.get(image_id),
                request.args.get("path", "$"),
                optional_int(request.args.get("slot")),
                optional_int(request.args.get("side")),
            )
        )

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
    def validate(image_id):
        data = payload()
        return jsonify(
            message=service.validate(
                service.get(image_id),
                optional_int(data.get("slot")),
            )
        )

    @blueprint.post("/api/images/<image_id>/rename")
    def rename(image_id):
        data = payload()
        session = service.get(image_id)
        slot = optional_int(data.get("slot"))
        if session.kind == "mmb" and data.get("slotTitle") is not None:
            service.rename_slot(session, slot, data["slotTitle"])
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
            service.mutate(
                session,
                slot,
                [
                    "mv",
                    "--force" if data.get("overwrite") else "",
                    "{image}:" + data["source"],
                    data["destination"],
                ],
                optional_int(data.get("side")),
            )
            result = {}
        return jsonify(image=service.summary(session), **result)

    @blueprint.post("/api/images/<image_id>/move")
    def move_items(image_id):
        session = service.get(image_id)
        result = move_adfs_items(
            service,
            session,
            payload().get("items", []),
        )
        return jsonify(image=service.summary(session), **result)

    @blueprint.post("/api/images/<image_id>/move-dfs")
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
        if session.kind == "adfs":
            result = delete_adfs_items(
                service,
                session,
                [item["path"] for item in items],
            )
        else:
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
                optional_int(data.get("slot")),
                args,
                optional_int(data.get("side")),
            )
            result = {
                "deletedItems": [
                    {"path": item["path"], "isDirectory": bool(item.get("recursive"))}
                    for item in items
                ]
            }
        return jsonify(image=service.summary(session), **result)

    @blueprint.post("/api/images/<image_id>/mkdir")
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
        service.mutate(
            session,
            optional_int(data.get("slot")),
            ["mkdir", "-p", "{image}:" + path],
            optional_int(data.get("side")),
        )
        return jsonify(image=service.summary(session))

    @blueprint.post("/api/images/<image_id>/lock")
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
    def put_file(image_id):
        upload = request.files.get("file")
        if not upload or not upload.filename:
            raise DiskError("Choose a host file to import.")
        session = service.get(image_id)
        slot = optional_int(request.form.get("slot"))
        name = request.form.get("targetName") or DiskService.safe_filename(upload.filename)
        name = service.validate_leaf_name(session, name, slot)
        destination_dir = request.form.get("destination", "$").rstrip(".")
        if session.kind == "dfs" or (session.kind == "mmb" and slot is not None):
            destination_dir = service.validate_dfs_prefix(destination_dir)
        destination = f"{destination_dir}.{name}"
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

    @blueprint.post("/api/transfer")
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
    def transfer_slot_to_directory():
        data = payload()
        source = service.get(data["sourceImage"])
        target = service.get(data["targetImage"])
        source_slot = int(data["sourceSlot"])
        operation_id = data.get("operationId")
        if operation_id:
            operations.start(operation_id, "Preparing MMB slot transfer")
        try:
            menu_metadata: list[dict] = []
            if data.get("addMenu"):
                operations.update(operation_id, "Checking the MMB Universal Menu")
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
                lambda message, current=None, total=None: operations.update(
                    operation_id,
                    message,
                    current,
                    total,
                ),
            )
            metadata = None
            metadata_entries: list[dict] = []
            if data.get("addMenu"):
                operations.update(operation_id, "Analysing launch files in the copied directory")
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
                        operations.update(operation_id, "Checking the online software archive")
                        metadata = enrich_if_ambiguous(detected)
                    else:
                        metadata = detected
                    metadata_entries = [metadata]
            operations.finish(operation_id, "Transfer complete")
        except OperationCancelled as exc:
            operations.cancelled(operation_id, str(exc))
            raise
        except Exception as exc:
            operations.fail(operation_id, str(exc))
            raise
        return jsonify(
            image=service.summary(target),
            path=destination,
            metadata=metadata,
            metadataEntries=metadata_entries,
        )

    @blueprint.post("/api/transfer-mmb-batch-to-adfs")
    def transfer_mmb_batch_to_adfs():
        data = payload()
        source = service.get(data["sourceImage"])
        target = service.get(data["targetImage"])
        operation_id = data.get("operationId")
        completed: list[dict] = []
        skipped: list[dict] = []
        operations.start(operation_id, "Preparing accelerated MMB batch transfer")
        operations.details(
            operation_id,
            resumable=True,
            endpoint="/api/transfer-mmb-batch-to-adfs",
            request={key: value for key, value in data.items() if key != "operationId"},
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
            metadata = _partial_mmb_metadata(
                service,
                source,
                completed,
                operations,
                operation_id,
                enabled=bool(data.get("addMenu")),
            )
            operations.pause(
                operation_id,
                f"Waiting for a decision on slot {exc.disk['sourceSlot']} · "
                f"{exc.disk['sourceName']}",
            )
            operations.details(operation_id, resumable=True, endpoint="/api/transfer-mmb-batch-to-adfs", request={key: value for key, value in data.items() if key != "operationId"}, completed=completed, skipped=skipped)
            return jsonify(
                error=str(exc),
                image=service.summary(target),
                completed=completed,
                skipped=skipped,
                metadata=metadata,
                blankDisk=exc.disk,
                decisionRequired="skip-or-abort",
            ), 409
        except DestinationExistsError as exc:
            metadata = _partial_mmb_metadata(
                service,
                source,
                completed,
                operations,
                operation_id,
                enabled=bool(data.get("addMenu")),
            )
            operations.pause(
                operation_id,
                f"Waiting for a decision on existing directory "
                f"{exc.conflict['destination']}",
            )
            operations.details(operation_id, resumable=True, endpoint="/api/transfer-mmb-batch-to-adfs", request={key: value for key, value in data.items() if key != "operationId"}, completed=completed, skipped=skipped)
            return jsonify(
                error=str(exc),
                image=service.summary(target),
                completed=completed,
                skipped=skipped,
                metadata=metadata,
                destinationConflict=exc.conflict,
                decisionRequired="keep-replace-or-abort",
            ), 409
        except OperationCancelled as exc:
            metadata = _partial_mmb_metadata(
                service,
                source,
                completed,
                operations,
                operation_id,
                enabled=bool(data.get("addMenu")),
            )
            operations.cancelled(operation_id, str(exc))
            operations.details(operation_id, resumable=True, endpoint="/api/transfer-mmb-batch-to-adfs", request={key: value for key, value in data.items() if key != "operationId"}, completed=completed, skipped=skipped)
            return jsonify(
                error=str(exc),
                image=service.summary(target),
                completed=completed,
                skipped=skipped,
                metadata=metadata,
            ), 409
        except Exception as exc:
            metadata = _partial_mmb_metadata(
                service,
                source,
                completed,
                operations,
                operation_id,
                enabled=bool(data.get("addMenu")),
            )
            operations.fail(operation_id, str(exc))
            operations.details(operation_id, resumable=True, endpoint="/api/transfer-mmb-batch-to-adfs", request={key: value for key, value in data.items() if key != "operationId"}, completed=completed, skipped=skipped)
            return jsonify(
                error=str(exc),
                image=service.summary(target),
                completed=completed,
                skipped=skipped,
                metadata=metadata,
            ), 400

    @blueprint.post("/api/transfer-image-to-directory")
    def transfer_image_to_directory():
        data = payload()
        source = service.get(data["sourceImage"])
        target = service.get(data["targetImage"])
        create_directory = data.get("createDirectory", True) is not False
        operation_id = data.get("operationId")
        if operation_id:
            operations.start(operation_id, "Preparing image extraction")
        try:
            destination = service.extract_image_to_adfs_directory(
                source,
                target,
                data.get("targetPath", "$"),
                data.get("directoryName"),
                lambda message, current=None, total=None: operations.update(
                    operation_id, message, current, total
                ),
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
            operations.finish(operation_id, "Extraction complete")
        except OperationCancelled as exc:
            operations.cancelled(operation_id, str(exc))
            raise
        except Exception as exc:
            operations.fail(operation_id, str(exc))
            raise
        return jsonify(
            image=service.summary(target),
            path=destination,
            metadata=metadata,
        )

    @blueprint.post("/api/images/<image_id>/extract-to-directory")
    def extract_to_directory(image_id):
        target = service.get(image_id)
        upload = request.files.get("image")
        if not upload or not upload.filename:
            raise DiskError("Choose a supported disk or tape image to extract.")
        operation_id = request.form.get("operationId")
        create_directory = request.form.get("createDirectory", "yes") != "no"
        if operation_id:
            operations.start(operation_id, "Preparing uploaded image extraction")
        extensions = (
            DFS_EXTENSIONS | MMB_EXTENSIONS | TAPE_EXTENSIONS | ADFS_EXTENSIONS | HFE_EXTENSIONS
        )
        with open_single_upload_image(upload, extensions) as image:
            source = service.create_from_stream(image.filename, image.stream)
            try:
                destination = service.extract_image_to_adfs_directory(
                    source,
                    target,
                    request.form.get("targetPath", "$"),
                    request.form.get("directoryName"),
                    lambda message, current=None, total=None: operations.update(
                        operation_id, message, current, total
                    ),
                    create_directory=create_directory,
                )
                service.set_adfs_source_name(
                    target,
                    destination,
                    best_distribution_filename(image.metadata_names),
                )
                metadata = (
                    _metadata_for_directory(
                        service,
                        target,
                        destination,
                    )
                    if request.form.get("addMenu") == "yes"
                    else None
                )
                operations.finish(operation_id, "Extraction complete")
            except OperationCancelled as exc:
                operations.cancelled(operation_id, str(exc))
                raise
            except Exception as exc:
                operations.fail(operation_id, str(exc))
                raise
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
        response = send_file(
            path,
            as_attachment=True,
            download_name=name,
            mimetype="application/octet-stream",
            conditional=True,
        )
        response.call_on_close(lambda: path.unlink(missing_ok=True))
        return response

    return blueprint
