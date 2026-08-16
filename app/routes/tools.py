from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from copy import copy
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, Response, after_this_request, jsonify, request, send_file
from .effects import image_mutation, request_effect

from ..analysis_service import (
    build_manifest,
    dependency_report,
    duplicate_report,
    health_report,
    manifest_csv,
    menu_test_report,
    preflight_report,
    workspace_metadata_records,
)
from ..checksum import sha256_bytes
from ..disk_service import DiskError, DiskService
from ..emulator_config import configured_emulator, emulator_command, emulator_status
from ..hardware_profiles import normalise_hardware_profile
from ..image_diff import compare_images
from ..image_patch import apply_patch_archive, inspect_patch_archive, write_patch_archive
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
    encode_editor_replacement,
)
from ..operations import OperationRegistry
from ..menu.adfs import audit_adfs_menu_pages
from ..menu.mmb import (
    audit_mmb_menu_pages,
    edit_mmb_menu_entries,
    installed_mmb_menu,
    parse_mmb_menu_data,
)
from .common import optional_int, payload


def run_emulator_process(arguments: list[str], cwd: str, timeout: int):
    """Keep managed-emulator execution separate from filesystem subprocesses."""
    return subprocess.run(
        arguments, cwd=cwd, capture_output=True, text=True,
        timeout=timeout, check=False,
    )


def clean_emulator_output(output: str) -> str:
    """Remove expected headless audio and X-server shutdown diagnostics."""
    ignored_prefixes = (
        "ALSA lib ",
        "X connection to ",
    )
    return "\n".join(
        line for line in str(output or "").splitlines()
        if not line.startswith(ignored_prefixes)
    ).strip()


@contextmanager
def uploaded_patch_path(work_dir: Path):
    """Retain one uploaded patch only for the duration of its request."""
    upload = request.files.get("patch")
    if not upload or not upload.filename:
        raise DiskError("Choose an Acorn File Forge patch ZIP.")
    with tempfile.NamedTemporaryFile(
        dir=work_dir, prefix="uploaded-patch-", suffix=".zip", delete=False,
    ) as temporary:
        upload.save(temporary)
        patch_path = Path(temporary.name)
    try:
        yield patch_path
    finally:
        patch_path.unlink(missing_ok=True)


class InteractiveEmulator:
    """Own the single browser-visible emulator display exposed by noVNC."""

    def __init__(self):
        self.lock = threading.RLock()
        self.process = None
        self.xvfb = None
        self.vnc = None
        self.media_context = None

    @staticmethod
    def _terminate(process):
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()

    def _stop_locked(self):
        process, vnc, xvfb, media = self.process, self.vnc, self.xvfb, self.media_context
        self.process = self.vnc = self.xvfb = self.media_context = None
        self._terminate(process)
        self._terminate(vnc)
        self._terminate(xvfb)
        if media:
            media.__exit__(None, None, None)

    def stop(self):
        with self.lock:
            self._stop_locked()

    def start(self, media_context, *, debug: bool):
        with self.lock:
            self._stop_locked()
            launch, media = media_context.__enter__()
            try:
                arguments, cwd = emulator_command(launch, media, debug=debug, interactive=True)
                self.xvfb = subprocess.Popen(
                    ["Xvfb", ":99", "-screen", "0", "1280x960x24", "-ac", "-nolisten", "tcp"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                time.sleep(0.3)
                self.vnc = subprocess.Popen(
                    ["x11vnc", "-display", ":99", "-rfbport", "5900", "-nopw", "-forever", "-shared", "-quiet"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                self.process = subprocess.Popen(
                    arguments, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True,
                )
                self.media_context = media_context
            except Exception:
                self._terminate(self.vnc)
                self._terminate(self.xvfb)
                self.process = self.vnc = self.xvfb = None
                media_context.__exit__(None, None, None)
                raise
            process = self.process
            threading.Thread(target=self._reap, args=(process,), daemon=True).start()
            return arguments, launch

    def _reap(self, process):
        process.communicate()
        with self.lock:
            if self.process is process:
                vnc, xvfb, media = self.vnc, self.xvfb, self.media_context
                self.process = self.vnc = self.xvfb = self.media_context = None
                self._terminate(vnc)
                self._terminate(xvfb)
                if media:
                    media.__exit__(None, None, None)


INTERACTIVE_EMULATOR = InteractiveEmulator()


def create_tools_blueprint(
    service: DiskService,
    operations: OperationRegistry,
) -> Blueprint:
    blueprint = Blueprint("tools", __name__)

    def requested_emulator_session(session, data: dict):
        """Apply the browser's effective Workbench profile without mutating the image."""
        requested = data.get("hardwareProfile")
        if not isinstance(requested, dict) or not requested:
            return session
        try:
            profile = normalise_hardware_profile(requested)
        except ValueError as exc:
            raise DiskError(f"The selected Workbench profile is invalid: {exc}") from exc
        configured = copy(session)
        configured.hardware_profile = profile
        configured.target_hardware = str(profile.get("targetHardware") or session.target_hardware)
        return configured

    def status_request_data() -> dict:
        encoded = str(request.args.get("hardwareProfile") or "")
        if not encoded:
            return {}
        try:
            profile = json.loads(encoded)
        except json.JSONDecodeError as exc:
            raise DiskError("The Workbench profile sent to the emulator is invalid.") from exc
        return {"hardwareProfile": profile}

    def record_editor_run(
        session,
        path,
        slot,
        side,
        result: dict,
        *,
        kind: str | None = None,
    ) -> dict:
        """Append one bounded emulator result to the file's shared project history."""
        project = service.editor_project(session, path, slot, side)
        stored = {**result, "kind": kind} if kind else result
        project["tests"] = [*project.get("tests", []), stored][-100:]
        return service.save_editor_project(session, path, slot, side, project)

    @contextmanager
    def isolated_basic_media(session, configured, data: dict):
        path = str(data.get("path") or "")
        slot, side = optional_int(data.get("slot")), optional_int(data.get("side"))
        if not path:
            raise DiskError("Choose a BASIC file to run.")
        inspection = inspect_editable_file(service, session, path, slot, side)
        if not inspection.get("tokenisedBasic"):
            raise DiskError("Only a recognised tokenised BBC BASIC program can be run in isolation.")
        original = service.read_file(session, slot, path, side)
        source = data.get("source")
        content = encode_editor_replacement(original, str(source), True) if isinstance(source, str) else original
        profile = configured.hardware_profile or {}
        machine = str(profile.get("machine") or "bbc-b")
        if machine == "archimedes":
            raise DiskError("Isolated BASIC test disks currently target 8-bit BBC and Electron systems, not RISC OS BASIC V.")
        filing_system = str(profile.get("filingSystem") or "dfs").lower()
        disk_format = "adfs-s" if machine == "electron" and "adfs" in filing_system else "ssd"
        scratch = service.create_blank(disk_format, "EDITOR", target_hardware=str(configured.target_hardware or "auto"))
        page_text = str(profile.get("page") or ("E00" if machine == "electron" else "1900")).strip().upper().removeprefix("&").removeprefix("0X")
        try:
            page = int(page_text, 16)
        except ValueError:
            page = 0xE00 if machine == "electron" else 0x1900
        try:
            with tempfile.NamedTemporaryFile(dir=service.work_dir, prefix="editor-basic-", delete=False) as program_file:
                program_file.write(content)
                program_path = Path(program_file.name)
            with tempfile.NamedTemporaryFile(dir=service.work_dir, prefix="editor-boot-", delete=False) as boot_file:
                boot_file.write(f'BASIC\rPAGE=&{page:X}\rCHAIN "PROGRAM"\r'.encode("latin-1"))
                boot_path = Path(boot_file.name)
            try:
                service.put(scratch, None, "$.PROGRAM", program_path, hex(page), hex(page), None)
                service.put(scratch, None, "$.!BOOT", boot_path, "0", "0", None)
                service._run(["opt", str(scratch.path), "3"])
            finally:
                program_path.unlink(missing_ok=True)
                boot_path.unlink(missing_ok=True)
            yield scratch.path
        finally:
            service.discard_session(scratch)

    @contextmanager
    def mmb_slot_media(session, slot: int):
        """Expose one formatted MMB slot as temporary emulator-safe SSD media."""
        if session.kind != "mmb":
            raise DiskError("A disk-slot launch requires an MMB image.")
        data, _name = service.slot_download(session, slot)
        temporary = tempfile.NamedTemporaryFile(
            dir=service.work_dir, prefix=f"mmb-slot-{slot:03d}-", suffix=".ssd", delete=False,
        )
        path = Path(temporary.name)
        try:
            with temporary:
                temporary.write(data)
            yield path
        finally:
            path.unlink(missing_ok=True)

    def selected_media_probe(session, configured, slot: int | None, *, debug: bool = False):
        """Build a command for a target without extracting or changing its bytes."""
        if getattr(session, "kind", "") == "mmb":
            if slot is None:
                raise ValueError(
                    "The bundled emulators cannot attach an MMB container directly. "
                    "Select a formatted slot to mount its DFS disk. Whole-MMB execution "
                    "requires an MMFS-capable SD-card emulator adapter."
                )
            slots = service.list_slots(session)
            if slot < 0 or slot >= len(slots) or not slots[slot].get("formatted"):
                raise ValueError("Select one formatted MMB disk slot to run.")
            return emulator_command(configured, Path(f"selected-slot-{slot:03d}.ssd"), debug=debug)
        return emulator_command(configured, configured.path, debug=debug)

    def launch_media(session, configured, data: dict):
        mode = str(data.get("mode") or "parent-auto")
        if mode == "isolated-basic":
            source = isolated_basic_media(session, configured, data)

            @contextmanager
            def isolated():
                with source as media:
                    yield configured, media

            return isolated()
        if mode not in {"parent-auto", "parent-mount", "slot-auto", "slot-mount"}:
            raise DiskError("Choose how the emulator should receive the selected file or its parent image.")
        slot = optional_int(data.get("slot"))
        launch = copy(configured)
        launch.hardware_profile = dict(configured.hardware_profile or {})
        launch.hardware_profile["emulatorBoot"] = "boot" if mode.endswith("auto") else "catalogue"

        if getattr(session, "kind", "") == "mmb":
            if slot is None:
                raise DiskError(
                    "Whole-MMB mounting is not supported by the selected managed emulator. "
                    "Select one formatted slot to mount its DFS disk instead."
                )

            @contextmanager
            def slot_media():
                with mmb_slot_media(session, slot) as media:
                    yield launch, media

            return slot_media()

        @contextmanager
        def parent_media():
            yield launch, launch.path

        return parent_media()

    @blueprint.post("/api/images/<image_id>/preflight")
    @request_effect("read-only", "building an import preflight report")
    def preflight(image_id):
        return jsonify(preflight_report(service, service.get(image_id), payload()))

    @blueprint.get("/api/images/<image_id>/health")
    def health(image_id):
        operation_id = request.args.get("operationId")
        with operations.tracked(
            operation_id,
            "Preparing image health checks",
            "Image health check complete",
        ) as progress:
            report = health_report(service, service.get(image_id), progress)
            return jsonify(report)

    @blueprint.post("/api/images/<image_id>/health/repair")
    @image_mutation("applying a safe image-health repair")
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

    @blueprint.get("/api/images/<image_id>/adfs-installations/audit")
    def audit_adfs_installations(image_id):
        session = service.get(image_id)
        operation_id = request.args.get("operationId")
        root = str(request.args.get("root") or "$")
        with operations.tracked(
            operation_id,
            "Finding installed ADFS software",
            "Installed ADFS software audit complete",
        ) as progress:
            result = service.audit_adfs_installations(session, root, progress)
            return jsonify(result)

    @blueprint.post("/api/images/<image_id>/adfs-installations/repair")
    @image_mutation("repairing installed ADFS software")
    def repair_adfs_installations(image_id):
        session = service.get(image_id)
        data = payload()
        operation_id = data.get("operationId")
        directories = data.get("directories")
        if not isinstance(directories, list):
            raise DiskError("Choose the installed disk directories to repair.")
        with operations.tracked(
            operation_id,
            "Rechecking proposed ADFS repairs",
            "Installed ADFS software repair complete",
        ) as progress:
            result = service.repair_adfs_installations(session, directories, progress)
            return jsonify(image=service.summary(session), repair=result)

    @blueprint.get("/api/images/<image_id>/manifest")
    def manifest(image_id):
        session = service.get(image_id)
        operation_id = request.args.get("operationId")
        with operations.tracked(
            operation_id,
            "Cataloguing image contents",
            "Collection manifest ready",
        ) as progress:
            report = build_manifest(service, session, progress)
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

    @blueprint.post("/api/images/<image_id>/compare")
    @request_effect("read-only", "comparing logical image contents")
    def compare_image(image_id):
        data = payload()
        operation_id = data.get("operationId")
        other_image_id = str(data.get("otherImage") or "").strip()
        if not other_image_id:
            raise DiskError("Choose another open image to compare.")
        if other_image_id == image_id:
            raise DiskError("Choose two different open images to compare.")
        with operations.tracked(
            operation_id,
            "Cataloguing images for comparison",
            "Image comparison complete",
        ) as progress:
            return jsonify(compare_images(
                service,
                service.get(image_id),
                service.get(other_image_id),
                progress,
            ))

    @blueprint.get("/api/images/<image_id>/patch")
    def create_image_patch(image_id):
        operation_id = request.args.get("operationId")
        other_image_id = str(request.args.get("otherImage") or "").strip()
        return _create_patch_download(image_id, other_image_id, operation_id, None)

    @blueprint.post("/api/images/<image_id>/patch/build")
    @request_effect("read-only", "building a selective guarded image patch")
    def create_selective_image_patch(image_id):
        data = payload()
        selected_keys = data.get("selectedKeys")
        if not isinstance(selected_keys, list):
            raise DiskError("A selective patch requires a reviewed list of change keys.")
        return _create_patch_download(
            image_id,
            str(data.get("otherImage") or "").strip(),
            str(data.get("operationId") or "").strip() or None,
            [str(key) for key in selected_keys],
        )

    def _create_patch_download(image_id, other_image_id, operation_id, selected_keys):
        if not other_image_id or other_image_id == image_id:
            raise DiskError("Choose a different open image as the patch candidate.")
        base, candidate = service.get(image_id), service.get(other_image_id)
        with tempfile.NamedTemporaryFile(
            dir=service.work_dir, prefix="image-patch-", suffix=".affpatch.zip", delete=False,
        ) as temporary:
            patch_path = Path(temporary.name)
        try:
            with operations.tracked(
                operation_id,
                "Cataloguing images for a guarded patch",
                "Guarded patch archive ready",
            ) as progress:
                write_patch_archive(
                    service, base, candidate, patch_path, progress,
                    selected_keys=selected_keys,
                )
        except Exception:
            patch_path.unlink(missing_ok=True)
            raise

        @after_this_request
        def remove_patch(response):
            patch_path.unlink(missing_ok=True)
            return response

        return send_file(
            patch_path,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"{Path(base.name).stem}-to-{Path(candidate.name).stem}.affpatch.zip",
        )

    @blueprint.post("/api/images/<image_id>/patch")
    @image_mutation("applying a guarded image patch")
    def apply_image_patch(image_id):
        operation_id = request.form.get("operationId")
        with operations.tracked(
            operation_id,
            "Verifying the guarded patch",
            "Guarded patch applied and verified",
        ) as progress, uploaded_patch_path(service.work_dir) as patch_path:
            result = apply_patch_archive(service, service.get(image_id), patch_path, progress)
        return jsonify(image=service.summary(service.get(image_id)), patch=result)

    @blueprint.post("/api/images/<image_id>/patch/inspect")
    @request_effect("read-only", "inspecting a guarded image patch")
    def inspect_image_patch(image_id):
        operation_id = request.form.get("operationId")
        with operations.tracked(
            operation_id,
            "Inspecting the guarded patch",
            "Patch preflight complete",
        ) as progress, uploaded_patch_path(service.work_dir) as patch_path:
            result = inspect_patch_archive(service, service.get(image_id), patch_path, progress)
        return jsonify(patch=result)

    @blueprint.post("/api/images/<image_id>/manifest/apply")
    @image_mutation("applying reviewed menu metadata")
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
        operation_id = request.args.get("operationId")
        with operations.tracked(
            operation_id,
            "Hashing image contents for duplicate analysis",
            "Duplicate analysis complete",
        ) as progress:
            return jsonify(duplicate_report(service, service.get(image_id), progress))

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
        operation_id = request.args.get("operationId")
        with operations.tracked(
            operation_id,
            "Indexing launcher dependencies",
            "Dependency analysis complete",
        ) as progress:
            return jsonify(dependency_report(
                service,
                session,
                path,
                optional_int(request.args.get("slot")),
                optional_int(request.args.get("side")),
                progress,
            ))

    @blueprint.get("/api/images/<image_id>/inspect/search")
    def search_inspected_files(image_id):
        session = service.get(image_id)
        operation_id = request.args.get("operationId")
        with operations.tracked(
            operation_id,
            "Searching image catalogue and file content",
            "Workspace image search complete",
        ) as progress:
            return jsonify(search_image_files(
                service, session, str(request.args.get("query") or ""),
                optional_int(request.args.get("slot")), optional_int(request.args.get("side")),
                str(request.args.get("root") or "$"),
                str(request.args.get("allSlots") or "false").lower() in {"1", "true", "yes"},
                progress,
                workspace_metadata_records(service, session),
            ))

    @blueprint.put("/api/images/<image_id>/inspect")
    @image_mutation("editing a BASIC or text file")
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
    @image_mutation("editing file properties")
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
    @request_effect("read-only", "previewing a BASIC renumber operation")
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
    @request_effect("read-only", "normalising BASIC source for review")
    def normalise_basic(image_id):
        service.get(image_id)
        return jsonify(normalise_basic_source(str(payload().get("text") or "")))

    @blueprint.post("/api/images/<image_id>/inspect/basic/verify")
    @request_effect("read-only", "verifying BASIC source")
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
    @image_mutation("editing image project metadata")
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
        configured = requested_emulator_session(session, status_request_data())
        status = emulator_status(configured)
        parent_mountable = False
        parent_message = ""
        slot = optional_int(request.args.get("slot"))
        try:
            command, _cwd = selected_media_probe(session, configured, slot)
            status["command"] = " ".join(command)
            parent_mountable = True
        except ValueError as exc:
            status["command"] = ""
            parent_message = str(exc)
        is_basic = str(request.args.get("basic") or "false").lower() in {"1", "true", "yes"}
        isolated_basic = bool(is_basic and status["machine"] != "archimedes" and status["available"])
        if not parent_mountable and not isolated_basic:
            status["available"] = False
            status["message"] = parent_message or status["message"]
        return jsonify(
            **status, hardware=configured.target_hardware,
            parentMountable=parent_mountable, parentMessage=parent_message,
            isolatedBasic=isolated_basic,
            mediaTarget=("mmb-slot" if getattr(session, "kind", "") == "mmb" and slot is not None else "image"),
            targetLabel=(f"MMB slot {slot}" if getattr(session, "kind", "") == "mmb" and slot is not None else getattr(session, "name", "Current image")),
        )

    @blueprint.post("/api/images/<image_id>/editor-emulator")
    @request_effect("external", "launching an editor document in an emulator")
    def editor_emulator_run(image_id):
        session = service.get(image_id)
        data = payload()
        configured = requested_emulator_session(session, data)
        path = str(data.get("path") or "")
        slot, side = optional_int(data.get("slot")), optional_int(data.get("side"))
        if bool(data.get("interactive")):
            try:
                arguments, launch = INTERACTIVE_EMULATOR.start(
                    launch_media(session, configured, data), debug=False,
                )
            except (ValueError, OSError, subprocess.SubprocessError) as exc:
                raise DiskError(f"The browser-visible emulator could not start: {exc}") from exc
            emulator = configured_emulator(launch)
            result = {
                "time": datetime.now(timezone.utc).isoformat(), "command": arguments[0],
                "returnCode": 0, "bounded": False, "interactive": True,
                "emulator": emulator.label, "machine": str(launch.hardware_profile.get("machine") or ""),
                "launchMode": str(data.get("mode") or "parent-auto"),
                "summary": f"{emulator.label} is running in the browser display.",
                "stdout": "", "stderr": "", "viewerPort": 8668,
            }
            project = record_editor_run(session, path, slot, side, result)
            return jsonify(result=result, project=project)
        try:
            with launch_media(session, configured, data) as (launch, media):
                arguments, cwd = emulator_command(launch, media)
                completed = run_emulator_process(arguments, cwd, 30)
        except ValueError as exc:
            raise DiskError(str(exc)) from exc
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DiskError(f"The managed emulator test could not complete: {exc}") from exc
        bounded = completed.returncode == 124
        emulator = configured_emulator(configured)
        mode = str(data.get("mode") or "parent-auto")
        result = {
            "time": datetime.now(timezone.utc).isoformat(),
            "command": arguments[0], "returnCode": 0 if bounded else completed.returncode,
            "bounded": bounded,
            "emulator": emulator.label, "machine": str(configured.hardware_profile.get("machine") or ""),
            "launchMode": mode,
            "summary": (
                f"{emulator.label} completed its expected managed test window."
                if bounded else f"{emulator.label} exited with return code {completed.returncode}."
            ),
            "stdout": clean_emulator_output(completed.stdout)[-20000:],
            "stderr": clean_emulator_output(completed.stderr)[-20000:],
        }
        project = record_editor_run(session, path, slot, side, result)
        return jsonify(result=result, project=project)

    @blueprint.delete("/api/images/<image_id>/editor-emulator")
    @request_effect("external", "stopping the managed emulator")
    def editor_emulator_stop(image_id):
        service.get(image_id)
        INTERACTIVE_EMULATOR.stop()
        return jsonify(stopped=True)

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
    @request_effect("external", "assembling an editor document")
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
        if sha256_bytes(current) != expected:
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
                "sha256": sha256_bytes(assembled),
                "stdout": completed.stdout[-20000:], "stderr": completed.stderr[-20000:],
            },
        )

    @blueprint.get("/api/images/<image_id>/editor-debugger")
    def editor_debugger_status(image_id):
        session = service.get(image_id)
        configured = requested_emulator_session(session, status_request_data())
        status = emulator_status(configured)
        parent_mountable = False
        parent_message = ""
        slot = optional_int(request.args.get("slot"))
        try:
            command, _cwd = selected_media_probe(session, configured, slot, debug=True)
            parent_mountable = True
        except ValueError as exc:
            command = []
            parent_message = str(exc)
        is_basic = str(request.args.get("basic") or "false").lower() in {"1", "true", "yes"}
        isolated_basic = bool(is_basic and status["machine"] != "archimedes" and status["available"])
        available = bool(status["available"] and (parent_mountable or isolated_basic))
        return jsonify(
            available=available,
            hardware=configured.target_hardware,
            command=" ".join(command), configuredBy="managed workbench profile",
            message=(f"{status['label']} provides the managed debugger for this target." if available else parent_message or status["message"]),
            label=status["label"], machine=status["machine"],
            parentMountable=parent_mountable, parentMessage=parent_message,
            isolatedBasic=isolated_basic, actions=["launch"] if available else [],
            mediaTarget=("mmb-slot" if getattr(session, "kind", "") == "mmb" and slot is not None else "image"),
            targetLabel=(f"MMB slot {slot}" if getattr(session, "kind", "") == "mmb" and slot is not None else getattr(session, "name", "Current image")),
        )

    @blueprint.post("/api/images/<image_id>/editor-debugger")
    @request_effect("external", "running the managed debugger")
    def editor_debugger_run(image_id):
        session = service.get(image_id)
        data = payload()
        configured = requested_emulator_session(session, data)
        path = str(data.get("path") or "")
        slot, side = optional_int(data.get("slot")), optional_int(data.get("side"))
        action = str(data.get("action") or "launch").strip().lower()
        if action != "launch":
            raise DiskError("Start the managed debugger before using its native step, register and memory controls.")
        expression = str(data.get("expression") or "").strip()[:500]
        if bool(data.get("interactive")):
            try:
                arguments, launch = INTERACTIVE_EMULATOR.start(
                    launch_media(session, configured, data), debug=True,
                )
            except (ValueError, OSError, subprocess.SubprocessError) as exc:
                raise DiskError(f"The browser-visible debugger could not start: {exc}") from exc
            emulator = configured_emulator(launch)
            result = {
                "time": datetime.now(timezone.utc).isoformat(), "command": arguments[0],
                "returnCode": 0, "bounded": False, "interactive": True,
                "emulator": emulator.label, "machine": str(launch.hardware_profile.get("machine") or ""),
                "launchMode": str(data.get("mode") or "parent-auto"),
                "summary": f"{emulator.label} debugger is running in the browser display.",
                "stdout": "", "stderr": "", "viewerPort": 8668,
                "breakpoint": str(data.get("breakpoint") or ""), "action": action,
                "expression": expression, "kind": "debugger",
            }
            project = record_editor_run(session, path, slot, side, result)
            return jsonify(result=result, project=project)
        try:
            with launch_media(session, configured, data) as (launch, media):
                arguments, cwd = emulator_command(launch, media, debug=True)
                completed = run_emulator_process(arguments, cwd, 120)
        except ValueError as exc:
            raise DiskError(str(exc)) from exc
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DiskError(f"The managed debugger session could not complete: {exc}") from exc
        bounded = completed.returncode == 124
        emulator = configured_emulator(configured)
        mode = str(data.get("mode") or "parent-auto")
        result = {
            "time": datetime.now(timezone.utc).isoformat(), "command": arguments[0],
            "returnCode": 0 if bounded else completed.returncode, "bounded": bounded,
            "emulator": emulator.label, "machine": str(configured.hardware_profile.get("machine") or ""),
            "launchMode": mode,
            "summary": (
                f"{emulator.label} completed its expected managed debugger window."
                if bounded else f"{emulator.label} debugger exited with return code {completed.returncode}."
            ),
            "stdout": clean_emulator_output(completed.stdout)[-50000:],
            "stderr": clean_emulator_output(completed.stderr)[-50000:], "breakpoint": str(data.get("breakpoint") or ""),
            "action": action, "expression": expression,
        }
        project = record_editor_run(
            session, path, slot, side, result, kind="debugger"
        )
        return jsonify(result=result, project=project)

    @blueprint.post("/api/images/<image_id>/inspect/basic/pack")
    @request_effect("read-only", "previewing packed BASIC source")
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
