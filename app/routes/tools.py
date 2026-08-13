from __future__ import annotations

import json
import hashlib
import os
import shlex
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, Response, jsonify, request

from ..analysis_service import (
    build_manifest,
    dependency_report,
    duplicate_report,
    health_report,
    manifest_csv,
    menu_test_report,
    preflight_report,
)
from ..disk_service import DiskError, DiskService
from ..file_editor import (
    disassemble_file,
    inspect_editable_file,
    normalise_basic_source,
    pack_basic_lines,
    prepare_basic_source,
    replace_file_bytes,
    save_editor_text,
    save_editor_text_as,
    search_image_files,
    update_file_properties,
    verify_basic_source,
)
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
        return jsonify(inspect_editable_file(
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

    @blueprint.get("/api/images/<image_id>/inspect/search")
    def search_inspected_files(image_id):
        session = service.get(image_id)
        return jsonify(search_image_files(
            service, session, str(request.args.get("query") or ""),
            optional_int(request.args.get("slot")), optional_int(request.args.get("side")),
            str(request.args.get("root") or "$"),
            str(request.args.get("allSlots") or "false").lower() in {"1", "true", "yes"},
        ))

    @blueprint.put("/api/images/<image_id>/inspect")
    def save_inspected_text(image_id):
        data = payload()
        session = service.get(image_id)
        path = str(data.get("path") or "")
        slot = optional_int(data.get("slot"))
        side = optional_int(data.get("side"))
        current = inspect_editable_file(service, session, path, slot, side)
        if not current["editable"] or current["readOnly"]:
            raise DiskError("This file cannot be edited safely in the current image.")
        if data.get("newName") not in (None, ""):
            image, saved_path = save_editor_text_as(
                service, session, path, slot, side, str(data.get("newName") or ""),
                str(data.get("text") or ""), bool(current["tokenisedBasic"]),
                str(data.get("sha256") or ""),
            )
            return jsonify(
                image=image,
                path=saved_path,
                inspection=inspect_editable_file(service, session, saved_path, slot, side),
            )
        image = save_editor_text(
            service, session, path, slot, side, str(data.get("text") or ""),
            bool(current["tokenisedBasic"]), str(data.get("sha256") or ""),
        )
        return jsonify(image=image, path=path, inspection=inspect_editable_file(service, session, path, slot, side))

    @blueprint.put("/api/images/<image_id>/inspect/properties")
    def save_inspected_properties(image_id):
        data = payload()
        session = service.get(image_id)
        path = str(data.get("path") or "")
        slot = optional_int(data.get("slot"))
        side = optional_int(data.get("side"))
        if not path or session.kind in {"rom", "tape"} or session.hfe_read_only:
            raise DiskError("This file's catalogue properties cannot be changed in the current image.")
        image = update_file_properties(
            service, session, path, slot, side, str(data.get("sha256") or ""),
            load=str(data.get("load") or ""),
            execute=str(data.get("execute") or ""),
            filetype=str(data.get("filetype") or ""),
            writable=bool(data.get("writable", True)),
        )
        return jsonify(image=image, inspection=inspect_editable_file(service, session, path, slot, side))

    @blueprint.post("/api/images/<image_id>/inspect/basic/renumber")
    def renumber_basic(image_id):
        service.get(image_id)
        data = payload()
        try:
            start = int(data.get("start", 10))
            step = int(data.get("step", 10))
        except (TypeError, ValueError) as exc:
            raise DiskError("The BASIC start and step must be whole numbers.") from exc
        return jsonify(prepare_basic_source(str(data.get("text") or ""), start, step))

    @blueprint.post("/api/images/<image_id>/inspect/basic/normalise")
    def normalise_basic(image_id):
        service.get(image_id)
        return jsonify(normalise_basic_source(str(payload().get("text") or "")))

    @blueprint.post("/api/images/<image_id>/inspect/basic/verify")
    def verify_basic(image_id):
        service.get(image_id)
        data = payload()
        return jsonify(verify_basic_source(str(data.get("text") or ""), str(data.get("baseline") or "")))

    @blueprint.get("/api/images/<image_id>/editor-project")
    def editor_project(image_id):
        session = service.get(image_id)
        path = str(request.args.get("path") or "")
        if not path:
            raise DiskError("Choose a file project to open.")
        return jsonify(project=service.editor_project(
            session, path, optional_int(request.args.get("slot")), optional_int(request.args.get("side")),
        ))

    @blueprint.put("/api/images/<image_id>/editor-project")
    def save_editor_project(image_id):
        session = service.get(image_id)
        data = payload()
        path = str(data.get("path") or "")
        if not path:
            raise DiskError("Choose a file project to save.")
        project = service.save_editor_project(
            session, path, optional_int(data.get("slot")), optional_int(data.get("side")),
            dict(data.get("project") or {}),
        )
        return jsonify(project=project)

    @blueprint.get("/api/images/<image_id>/editor-emulator")
    def editor_emulator_status(image_id):
        session = service.get(image_id)
        command = os.environ.get("ACORN_FILE_EMULATOR_COMMAND", "").strip()
        return jsonify(
            available=bool(command and "{file}" in command),
            hardware=session.target_hardware,
            message=(
                "Configured by ACORN_FILE_EMULATOR_COMMAND."
                if command and "{file}" in command
                else "Set ACORN_FILE_EMULATOR_COMMAND with a {file} placeholder to enable direct tests."
            ),
        )

    @blueprint.post("/api/images/<image_id>/editor-emulator")
    def editor_emulator_run(image_id):
        session = service.get(image_id)
        data = payload()
        path = str(data.get("path") or "")
        slot, side = optional_int(data.get("slot")), optional_int(data.get("side"))
        template = os.environ.get("ACORN_FILE_EMULATOR_COMMAND", "").strip()
        if not template or "{file}" not in template:
            raise DiskError("No file emulator command is configured.")
        content = service.read_file(session, slot, path, side)
        metadata = service.file_metadata(session, slot, path, side)
        suffix = f"-{Path(path).name}"
        with tempfile.NamedTemporaryFile(dir=service.work_dir, prefix="emulator-file-", suffix=suffix) as temporary:
            temporary.write(content)
            temporary.flush()
            replacements = {
                "{file}": temporary.name,
                "{image}": str(session.path),
                "{path}": path,
                "{load}": str(metadata.get("load") or 0),
                "{execute}": str(metadata.get("execute") or 0),
            }
            arguments = shlex.split(template)
            for key, value in replacements.items():
                arguments = [part.replace(key, value) for part in arguments]
            try:
                completed = subprocess.run(arguments, capture_output=True, text=True, timeout=60, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise DiskError(f"The emulator test could not complete: {exc}") from exc
        result = {
            "time": datetime.now(timezone.utc).isoformat(),
            "command": arguments[0], "returnCode": completed.returncode,
            "stdout": completed.stdout[-20000:], "stderr": completed.stderr[-20000:],
        }
        project = service.editor_project(session, path, slot, side)
        project["tests"] = [*project.get("tests", []), result][-100:]
        service.save_editor_project(session, path, slot, side, project)
        return jsonify(result=result, project=project)

    @blueprint.get("/api/images/<image_id>/editor-assembler")
    def editor_assembler_status(image_id):
        service.get(image_id)
        command = os.environ.get("ACORN_FILE_ASSEMBLER_COMMAND", "").strip()
        available = bool(command and "{source}" in command and "{output}" in command)
        return jsonify(
            available=available,
            message=(
                "Configured by ACORN_FILE_ASSEMBLER_COMMAND."
                if available
                else "Set ACORN_FILE_ASSEMBLER_COMMAND with {source} and {output} placeholders."
            ),
        )

    @blueprint.post("/api/images/<image_id>/editor-assembler")
    def editor_assembler_run(image_id):
        session = service.get(image_id)
        data = payload()
        path = str(data.get("path") or "")
        slot, side = optional_int(data.get("slot")), optional_int(data.get("side"))
        source = str(data.get("source") or "")
        architecture = str(data.get("architecture") or "6502").casefold()
        origin = str(data.get("origin") or "0")
        template = os.environ.get("ACORN_FILE_ASSEMBLER_COMMAND", "").strip()
        if not template or "{source}" not in template or "{output}" not in template:
            raise DiskError("No compatible external assembler command is configured.")
        if len(source.encode("utf-8")) > 4 * 1024 * 1024:
            raise DiskError("Assembly source is limited to 4 MiB per operation.")
        current = service.read_file(session, slot, path, side)
        expected = str(data.get("sha256") or "")
        if hashlib.sha256(current).hexdigest() != expected:
            raise DiskError("The binary changed after the disassembly opened. Reopen it before assembling.")
        with tempfile.TemporaryDirectory(dir=service.work_dir, prefix="assemble-file-") as folder:
            source_path = Path(folder) / "source.asm"
            output_path = Path(folder) / "output.bin"
            source_path.write_text(source, encoding="utf-8")
            replacements = {
                "{source}": str(source_path), "{output}": str(output_path),
                "{origin}": origin, "{architecture}": architecture,
            }
            arguments = shlex.split(template)
            for key, value in replacements.items():
                arguments = [part.replace(key, value) for part in arguments]
            try:
                completed = subprocess.run(arguments, capture_output=True, text=True, timeout=60, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise DiskError(f"The assembler could not complete: {exc}") from exc
            if completed.returncode or not output_path.is_file():
                detail = (completed.stderr or completed.stdout or "No output file was produced.")[-20000:]
                raise DiskError(f"The assembler rejected the source: {detail}")
            assembled = output_path.read_bytes()
        if not assembled or len(assembled) > 16 * 1024 * 1024:
            raise DiskError("The assembler output is empty or exceeds the safe 16 MiB limit.")
        changed = sum(left != right for left, right in zip(current, assembled)) + abs(len(current) - len(assembled))
        image = replace_file_bytes(service, session, path, slot, side, assembled, expected)
        return jsonify(
            image=image,
            result={
                "size": len(assembled), "changedBytes": changed,
                "sha256": hashlib.sha256(assembled).hexdigest(),
                "stdout": completed.stdout[-20000:], "stderr": completed.stderr[-20000:],
            },
        )

    @blueprint.get("/api/images/<image_id>/editor-debugger")
    def editor_debugger_status(image_id):
        session = service.get(image_id)
        command = os.environ.get("ACORN_FILE_DEBUGGER_COMMAND", "").strip()
        return jsonify(
            available=bool(command and "{file}" in command),
            hardware=session.target_hardware,
            message=(
                "Configured by ACORN_FILE_DEBUGGER_COMMAND. The adapter may use {action}, {breakpoint} and {expression}."
                if command and "{file}" in command
                else "Set ACORN_FILE_DEBUGGER_COMMAND with a {file} placeholder."
            ),
            actions=["launch", "continue", "step", "next", "registers", "memory", "stop"],
        )

    @blueprint.post("/api/images/<image_id>/editor-debugger")
    def editor_debugger_run(image_id):
        session = service.get(image_id)
        data = payload()
        path = str(data.get("path") or "")
        slot, side = optional_int(data.get("slot")), optional_int(data.get("side"))
        template = os.environ.get("ACORN_FILE_DEBUGGER_COMMAND", "").strip()
        if not template or "{file}" not in template:
            raise DiskError("No external debugger command is configured.")
        content = service.read_file(session, slot, path, side)
        metadata = service.file_metadata(session, slot, path, side)
        action = str(data.get("action") or "launch").strip().lower()
        if action not in {"launch", "continue", "step", "next", "registers", "memory", "stop"}:
            raise DiskError("Choose a supported debugger action.")
        expression = str(data.get("expression") or "").strip()[:500]
        with tempfile.NamedTemporaryFile(dir=service.work_dir, prefix="debug-file-", suffix=f"-{Path(path).name}") as temporary:
            temporary.write(content)
            temporary.flush()
            replacements = {
                "{file}": temporary.name, "{image}": str(session.path), "{path}": path,
                "{load}": str(metadata.get("load") or 0), "{execute}": str(metadata.get("execute") or 0),
                "{breakpoint}": str(data.get("breakpoint") or metadata.get("execute") or 0),
                "{architecture}": str(data.get("architecture") or "6502"),
                "{action}": action, "{expression}": expression,
            }
            arguments = shlex.split(template)
            for key, value in replacements.items():
                arguments = [part.replace(key, value) for part in arguments]
            try:
                completed = subprocess.run(arguments, capture_output=True, text=True, timeout=120, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise DiskError(f"The debugger session could not complete: {exc}") from exc
        result = {
            "time": datetime.now(timezone.utc).isoformat(), "command": arguments[0],
            "returnCode": completed.returncode, "stdout": completed.stdout[-50000:],
            "stderr": completed.stderr[-50000:], "breakpoint": replacements["{breakpoint}"],
            "action": action, "expression": expression,
        }
        project = service.editor_project(session, path, slot, side)
        project["tests"] = [*project.get("tests", []), {**result, "kind": "debugger"}][-100:]
        service.save_editor_project(session, path, slot, side, project)
        return jsonify(result=result, project=project)

    @blueprint.post("/api/images/<image_id>/inspect/basic/pack")
    def pack_basic(image_id):
        service.get(image_id)
        data = payload()
        runs = data.get("runs")
        if not isinstance(runs, list):
            raise DiskError("BASIC packing requires a list of safe statement runs.")
        return jsonify(pack_basic_lines(runs))

    @blueprint.get("/api/images/<image_id>/disassembly")
    def inspect_disassembly(image_id):
        session = service.get(image_id)
        path = str(request.args.get("path") or "")
        if not path:
            raise DiskError("Choose a file to disassemble.")
        try:
            origin = int(str(request.args.get("origin")), 0) if request.args.get("origin") not in (None, "") else None
            start = int(str(request.args.get("start") or "0"), 0)
            length = int(str(request.args.get("length")), 0) if request.args.get("length") not in (None, "") else None
        except ValueError as exc:
            raise DiskError("Origin, offset and length must be valid decimal or 0x-prefixed numbers.") from exc
        return jsonify(disassemble_file(
            service, session, path, optional_int(request.args.get("slot")),
            optional_int(request.args.get("side")), str(request.args.get("architecture") or "auto"),
            origin, start, length,
        ))

    return blueprint
