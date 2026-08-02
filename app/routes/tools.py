from __future__ import annotations

import json
import tempfile
from pathlib import Path

from flask import Blueprint, Response, jsonify, request

from ..analysis_service import (
    build_manifest,
    dependency_report,
    duplicate_report,
    health_report,
    inspect_file,
    manifest_csv,
    menu_test_report,
    preflight_report,
)
from ..disk_service import DiskError, DiskService
from ..operations import OperationCancelled, OperationRegistry
from ..menu_service import (
    audit_adfs_menu_pages,
    audit_mmb_menu_pages,
    edit_mmb_menu_entries,
    installed_mmb_menu,
    parse_mmb_menu_data,
)
from .common import optional_int, payload


def create_tools_blueprint(
    service: DiskService,
    work_dir: Path,
    operations: OperationRegistry,
) -> Blueprint:
    blueprint = Blueprint("tools", __name__)

    @blueprint.post("/api/images/<image_id>/preflight")
    def preflight(image_id):
        return jsonify(preflight_report(service, service.get(image_id), payload()))

    @blueprint.get("/api/images/<image_id>/health")
    def health(image_id):
        operation_id = request.args.get("operationId")
        if operation_id:
            operations.start(operation_id, "Preparing image health checks")
        try:
            report = health_report(
                service,
                service.get(image_id),
                lambda message, current=None, total=None: operations.update(
                    operation_id, message, current, total
                ),
            )
            operations.finish(operation_id, "Image health check complete")
            return jsonify(report)
        except OperationCancelled as exc:
            operations.cancelled(operation_id, str(exc))
            raise
        except Exception as exc:
            operations.fail(operation_id, str(exc))
            raise

    @blueprint.post("/api/images/<image_id>/health/repair")
    def repair_health(image_id):
        data = payload()
        session = service.get(image_id)
        if data.get("action") == "adfs-menu-page-audit" and session.kind == "adfs":
            result = audit_adfs_menu_pages(service, session, str(data.get("root") or "$"))
            return jsonify(image=service.summary(session), report=health_report(service, session), repair=result)
        if data.get("action") != "menu-page-audit" or session.kind != "mmb":
            raise DiskError("That health repair is not available for this image.")
        result = audit_mmb_menu_pages(service, session)
        return jsonify(image=service.summary(session), report=health_report(service, session), repair=result)

    @blueprint.get("/api/images/<image_id>/manifest")
    def manifest(image_id):
        session = service.get(image_id)
        report = build_manifest(service, session)
        output_format = request.args.get("format", "json").lower()
        if output_format == "csv":
            body = manifest_csv(report)
            suffix = "csv"
            mimetype = "text/csv"
        else:
            body = json.dumps(report, indent=2, ensure_ascii=False)
            suffix = "json"
            mimetype = "application/json"
        stem = Path(session.name).stem
        return Response(
            body,
            mimetype=mimetype,
            headers={"Content-Disposition": f'attachment; filename="{stem}-manifest.{suffix}"'},
        )

    @blueprint.post("/api/images/<image_id>/manifest/apply")
    def apply_manifest(image_id):
        session = service.get(image_id)
        if session.kind != "mmb":
            raise DiskError("Reviewed menu manifests can currently be applied only to MMB images.")
        document = request.get_json(silent=True) or {}
        entries = document.get("menuEntries")
        if not isinstance(entries, list):
            entries = next(
                (
                    menu.get("entries")
                    for menu in document.get("menus", [])
                    if isinstance(menu, dict) and isinstance(menu.get("entries"), list)
                ),
                None,
            )
        if not isinstance(entries, list):
            raise DiskError("The manifest must contain editable menu entries.")
        menu_slot, menu_type = installed_mmb_menu(service, session)
        if menu_slot is None or menu_type not in {"universal", "universal-4r", "spi-game-menu"}:
            raise DiskError("No editable Universal or SPI menu is installed.")
        data_file = "$.EGAMDAT" if menu_type == "universal-4r" else "$.GAMDATA"
        expected = parse_mmb_menu_data(service.read_file(session, menu_slot, data_file), menu_type)
        result = edit_mmb_menu_entries(service, session, entries, expected)
        return jsonify(image=service.summary(session), **result)

    @blueprint.get("/api/images/<image_id>/duplicates")
    def duplicates(image_id):
        return jsonify(duplicate_report(service, service.get(image_id)))

    @blueprint.get("/api/images/<image_id>/menu-tests")
    def menu_tests(image_id):
        return jsonify(menu_test_report(
            service,
            service.get(image_id),
            request.args.get("root"),
        ))

    @blueprint.get("/api/images/<image_id>/inspect")
    def inspect(image_id):
        session = service.get(image_id)
        path = request.args.get("path", "")
        if not path:
            raise DiskError("Choose a file to inspect.")
        return jsonify(inspect_file(
            service,
            session,
            path,
            optional_int(request.args.get("slot")),
            optional_int(request.args.get("side")),
        ))

    @blueprint.get("/api/images/<image_id>/dependencies")
    def dependencies(image_id):
        session = service.get(image_id)
        path = request.args.get("path", "")
        if not path:
            raise DiskError("Choose a launcher to inspect.")
        return jsonify(dependency_report(
            service,
            session,
            path,
            optional_int(request.args.get("slot")),
            optional_int(request.args.get("side")),
        ))

    @blueprint.put("/api/images/<image_id>/inspect")
    def save_inspected_text(image_id):
        data = payload()
        session = service.get(image_id)
        path = str(data.get("path") or "")
        slot = optional_int(data.get("slot"))
        side = optional_int(data.get("side"))
        current = inspect_file(service, session, path, slot, side)
        if not current["editable"] or current["tokenisedBasic"]:
            raise DiskError("Only small plain-text files can be edited directly. Tokenised BASIC remains protected.")
        text = str(data.get("text") or "").replace("\r\n", "\n").replace("\n", "\r")
        encoded = text.encode("latin-1", "strict")
        parent, leaf = path.rsplit(".", 1)
        row = next(
            (item for item in service.list_directory(session, parent, slot, side)["entries"] if str(item.get("name", "")).casefold() == leaf.casefold()),
            None,
        )
        if row is None:
            raise DiskError("The file changed while the inspector was open. Refresh and try again.")
        with tempfile.NamedTemporaryFile(dir=work_dir, prefix="inspect-edit-", delete=False) as temporary:
            temporary.write(encoded)
            temporary_path = Path(temporary.name)
        try:
            service.mutate(session, slot, ["rm", "--force", "{image}:" + path], side)
            service.put(
                session,
                slot,
                path,
                temporary_path,
                str(row.get("loadHex") or row.get("load") or ""),
                str(row.get("executeHex") or row.get("exec") or ""),
                row.get("filetype"),
                side,
            )
        finally:
            temporary_path.unlink(missing_ok=True)
        return jsonify(image=service.summary(session), inspection=inspect_file(service, session, path, slot, side))

    return blueprint
