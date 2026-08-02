from __future__ import annotations

from datetime import datetime
from pathlib import Path

from flask import Blueprint, Response, jsonify, request, send_from_directory

from ..archive_utils import open_disk_image_upload
from ..disk_service import DiskError, DiskService
from ..formats import (
    ADFS_EXTENSIONS,
    DFS_EXTENSIONS,
    HFE_EXTENSIONS,
    MMB_EXTENSIONS,
    TAPE_EXTENSIONS,
)
from ..menu_service import best_distribution_filename
from ..operations import OperationCancelled, OperationRegistry
from ..readme_service import timestamped_archive_name, write_download_readme
from ..streaming_zip import stream_stored_zip
from .common import optional_int, payload


def create_images_blueprint(
    service: DiskService,
    static_dir: Path,
    operations: OperationRegistry,
) -> Blueprint:
    blueprint = Blueprint("images", __name__)

    @blueprint.get("/")
    def index():
        return send_from_directory(static_dir, "index.html")

    @blueprint.get("/api/health")
    def health():
        return jsonify(status="ok", engine="oaknut")

    @blueprint.post("/api/images")
    def open_image():
        image = request.files.get("image")
        if not image or not image.filename:
            raise DiskError("Choose a disk image to open.")
        descriptor_file = request.files.get("descriptor")
        image_extensions = (
            DFS_EXTENSIONS | MMB_EXTENSIONS | TAPE_EXTENSIONS | ADFS_EXTENSIONS | HFE_EXTENSIONS
        )
        with open_disk_image_upload(image, image_extensions) as (
            image_item,
            archived_descriptor,
        ):
            descriptor = None
            if descriptor_file and descriptor_file.filename:
                descriptor = (
                    descriptor_file.filename,
                    descriptor_file.stream,
                )
            elif archived_descriptor is not None:
                descriptor = (
                    archived_descriptor.filename,
                    archived_descriptor.stream,
                )
            session = service.create_from_stream(
                image_item.filename,
                image_item.stream,
                descriptor,
                request.form.get("targetHardware", "auto"),
            )
            service.set_distribution_name(
                session,
                best_distribution_filename(image_item.metadata_names),
            )
        return jsonify(image=service.summary(session))

    @blueprint.post("/api/images/create")
    def create_image():
        data = payload()
        session = service.create_blank(
            data.get("format", "ssd"),
            data.get("title", "BLANK"),
            data.get("capacity"),
            data.get("targetHardware", "auto"),
        )
        return jsonify(image=service.summary(session))

    @blueprint.get("/api/images/<image_id>")
    def image_summary(image_id):
        return jsonify(image=service.summary(service.get(image_id)))

    @blueprint.patch("/api/images/<image_id>")
    def rename_image(image_id):
        data = payload()
        session = service.get(image_id)
        service.rename_session(session, data.get("name", ""))
        return jsonify(image=service.summary(session))

    @blueprint.patch("/api/images/<image_id>/hardware-profile")
    def set_hardware_profile(image_id):
        data = payload()
        session = service.get(image_id)
        allowed = {
            "name", "machine", "filingSystem", "mmfsBuild", "tube",
            "page", "menuType", "notes", "targetHardware", "catalogMachine",
        }
        profile = {
            key: value
            for key, value in data.items()
            if key in allowed and isinstance(value, (str, bool, int, float))
        }
        profile["tube"] = bool(profile.get("tube", False))
        session.hardware_profile = profile
        if session.kind == "adfs" and data.get("targetHardware"):
            session.target_hardware = service._target_hardware(str(data["targetHardware"]))
        service._persist_session(session)
        return jsonify(image=service.summary(session))

    @blueprint.get("/api/images/<image_id>/checkpoints")
    def image_checkpoints(image_id):
        session = service.get(image_id)
        return jsonify(
            image=service.summary(session),
            checkpoints=service.list_checkpoints(session),
        )

    @blueprint.post("/api/images/<image_id>/checkpoints")
    def create_image_checkpoint(image_id):
        data = payload()
        session = service.get(image_id)
        checkpoint = service.create_checkpoint(session, data.get("name", ""))
        return jsonify(
            image=service.summary(session),
            checkpoint=checkpoint,
            checkpoints=service.list_checkpoints(session),
        )

    @blueprint.post("/api/images/<image_id>/checkpoints/<checkpoint_id>/restore")
    def restore_image_checkpoint(image_id, checkpoint_id):
        session = service.get(image_id)
        service.begin_automatic_checkpoint(session, "restoring a named checkpoint")
        checkpoint = service.restore_checkpoint(session, checkpoint_id)
        return jsonify(
            image=service.summary(session),
            checkpoint=checkpoint,
            checkpoints=service.list_checkpoints(session),
        )

    @blueprint.delete("/api/images/<image_id>/checkpoints/<checkpoint_id>")
    def delete_image_checkpoint(image_id, checkpoint_id):
        session = service.get(image_id)
        service.delete_checkpoint(session, checkpoint_id)
        return jsonify(
            image=service.summary(session),
            checkpoints=service.list_checkpoints(session),
        )

    @blueprint.post("/api/images/<image_id>/undo")
    def undo_image_change(image_id):
        session = service.get(image_id)
        checkpoint = service.undo_last_change(session)
        return jsonify(
            image=service.summary(session),
            checkpoint=checkpoint,
            checkpoints=service.list_checkpoints(session),
        )

    @blueprint.get("/api/images/recoverable")
    def recoverable_images():
        return jsonify(images=service.recoverable_sessions())

    @blueprint.post("/api/images/recoverable/claim")
    def claim_recoverable_image():
        data = payload()
        session = service.claim_recovery_key(data.get("recoveryKey", ""))
        return jsonify(image=service.summary(session))

    @blueprint.delete("/api/images/recoverable")
    def clear_recoverable_images():
        data = request.get_json(silent=True) or {}
        image_ids = data.get("imageIds")
        if image_ids is not None and not isinstance(image_ids, list):
            raise DiskError("Choose the sessions to clear.")
        removed = service.clear_recoverable_sessions(image_ids)
        return jsonify(removed=removed)

    @blueprint.delete("/api/images/<image_id>")
    def discard_image(image_id):
        service.discard_session(service.get(image_id))
        return ("", 204)

    @blueprint.get("/api/images/<image_id>/download")
    def download_image(image_id):
        session = service.get(image_id)
        download_path = service.prepare_download(session)
        generated = datetime.now().astimezone()
        readme_path = write_download_readme(service, session, download_path, generated)
        is_beebscsi = bool(session.descriptor_path and session.path.suffix.lower() == ".dat")
        archive_root = "BeebSCSI0/" if is_beebscsi else ""
        files = [(readme_path, "README.md"), (download_path, f"{archive_root}{session.name}")]
        if session.descriptor_path:
            files.append((session.descriptor_path, f"{archive_root}{session.descriptor_name}"))
        return Response(
            stream_stored_zip(tuple(files)),
            mimetype="application/zip",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{timestamped_archive_name(session.name, generated)}"'
                ),
                "X-Accel-Buffering": "no",
            },
        )

    @blueprint.post("/api/images/<image_id>/download/prepare")
    def prepare_image_download(image_id):
        data = payload()
        operation_id = data.get("operationId")
        session = service.get(image_id)
        if operation_id:
            operations.start(operation_id, "Preparing image download")
        try:
            service.prepare_download(
                session,
                lambda message, current=None, total=None: operations.update(
                    operation_id, message, current, total
                ),
            )
            operations.finish(operation_id, "Image download is ready")
            return jsonify(image=service.summary(session), ready=True)
        except OperationCancelled as exc:
            operations.cancelled(operation_id, str(exc))
            raise
        except Exception as exc:
            operations.fail(operation_id, str(exc))
            raise

    @blueprint.post("/api/images/<image_id>/convert")
    def convert_image(image_id):
        data = payload()
        converted, files = service.convert_uef(
            service.get(image_id),
            data.get("format", "ssd"),
        )
        return jsonify(image=service.summary(converted), files=files)

    @blueprint.post("/api/images/<image_id>/compact")
    def compact(image_id):
        data = payload()
        session = service.get(image_id)
        service.compact(session, optional_int(data.get("slot")), data.get("order"))
        return jsonify(
            image=service.summary(session),
            message="Free space compacted successfully",
        )

    return blueprint
