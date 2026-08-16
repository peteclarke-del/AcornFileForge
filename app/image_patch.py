from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path

from .analysis_service import build_manifest
from .checksum import sha256_bytes
from .disk_service import DiskError
from .image_diff import compare_manifests, manifest_fingerprint
from .menu_service import delete_adfs_items


PATCH_FORMAT = "acorn-file-forge-image-patch"
PATCH_VERSION = 1
MAX_OPERATIONS = 100_000


def _layout_signature(manifest: dict) -> dict:
    """Return the physical traits that can change how logical paths are addressed."""
    image = manifest.get("image", {})
    signature = {"kind": image.get("kind")}
    if image.get("kind") == "dfs":
        signature["doubleSided"] = bool(image.get("doubleSided"))
    elif image.get("kind") == "rom":
        signature["bankSize"] = (image.get("rom") or {}).get("bankSize")
    return signature


def _patch_changes(kind: str, comparison: dict):
    for action in ("removed", "added", "modified", "metadata"):
        for change in comparison["changes"][action]:
            row = change.get("after") or change.get("before") or {}
            record_type = row.get("recordType")
            if kind == "mmb" and record_type != "slot":
                continue
            if kind == "rom" and record_type != "rom-bank":
                continue
            yield action, change, row


def _candidate_bytes(service, session, row: dict) -> bytes:
    if session.kind == "mmb":
        return service._slot_path(session, int(row["slot"])).read_bytes()
    if session.kind == "rom":
        exported = service.export_file(session, None, str(row["path"]))
        try:
            return exported.read_bytes()
        finally:
            exported.unlink(missing_ok=True)
    return service.read_file(
        session,
        int(row["slot"]) if row.get("slot") is not None else None,
        str(row["path"]),
        int(row["side"]) if row.get("side") is not None else None,
    )


def write_patch_archive(service, base_session, candidate_session, destination: Path) -> dict:
    base = build_manifest(service, base_session)
    candidate = build_manifest(service, candidate_session)
    comparison = compare_manifests(base, candidate)
    if not comparison["sameFormat"]:
        raise DiskError("Patch sets require two images from the same filesystem family.")
    if _layout_signature(base) != _layout_signature(candidate):
        raise DiskError("Patch sets require matching DFS side layouts or ROM bank sizes.")
    if base_session.kind == "tape":
        raise DiskError("UEF tape images are read-only and cannot receive patch sets.")

    operations = []
    payloads: list[tuple[str, bytes]] = []
    for action, change, row in _patch_changes(base_session.kind, comparison):
        operation = {
            "action": action,
            "key": change["key"],
            "before": change.get("before"),
            "after": change.get("after"),
            "changedFields": change.get("changedFields", []),
        }
        needs_payload = (
            action in {"added", "modified"}
            and row.get("recordType") != "directory"
            and not (base_session.kind == "mmb" and not row.get("formatted"))
        )
        if needs_payload:
            content = _candidate_bytes(service, candidate_session, row)
            payload_name = f"payloads/{len(payloads):08d}.bin"
            operation["payload"] = payload_name
            operation["payloadSha256"] = sha256_bytes(content)
            payloads.append((payload_name, content))
        operations.append(operation)
    if len(operations) > MAX_OPERATIONS:
        raise DiskError(f"Patch sets are limited to {MAX_OPERATIONS:,} logical operations.")

    document = {
        "format": PATCH_FORMAT,
        "version": PATCH_VERSION,
        "kind": base_session.kind,
        "base": comparison["base"],
        "candidate": comparison["candidate"],
        "baseFingerprint": comparison["baseFingerprint"],
        "candidateFingerprint": comparison["candidateFingerprint"],
        "layout": _layout_signature(base),
        "candidateRecords": candidate.get("records", []),
        "summary": comparison["summary"],
        "operations": operations,
    }
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        archive.writestr("patch.json", json.dumps(document, indent=2, ensure_ascii=False))
        for name, content in payloads:
            archive.writestr(name, content)
    return document


def _remove_filesystem_record(service, session, row: dict) -> None:
    path = str(row["path"])
    if session.kind == "adfs":
        delete_adfs_items(service, session, [path])
        return
    arguments = ["rm", "--force"]
    if row.get("recordType") == "directory":
        arguments.append("--recursive")
    arguments.append("{image}:" + path)
    service.mutate(
        session,
        int(row["slot"]) if row.get("slot") is not None else None,
        arguments,
        int(row["side"]) if row.get("side") is not None else None,
    )


def _catalogue_address(value) -> str:
    """Convert manifest addresses to the hexadecimal text expected by metadata edits."""
    if isinstance(value, int):
        return f"{value:X}"
    return str(value or "0")


def _apply_access(service, session, row: dict) -> None:
    path = str(row["path"])
    slot = int(row["slot"]) if row.get("slot") is not None else None
    side = int(row["side"]) if row.get("side") is not None else None
    attributes = str(row.get("attributes") or "")
    if attributes:
        normalised = attributes.upper()
        writable = "RUN" not in normalised if session.kind == "romfs" else "L" not in normalised
        service.set_access(session, slot, [path], writable, side)


def _apply_metadata(service, session, row: dict) -> None:
    if row.get("recordType") == "directory":
        _apply_access(service, session, row)
        return
    service.set_file_addresses(
        session,
        int(row["slot"]) if row.get("slot") is not None else None,
        str(row["path"]),
        _catalogue_address(row.get("load")),
        _catalogue_address(row.get("execute")),
        int(row["side"]) if row.get("side") is not None else None,
    )
    _apply_access(service, session, row)


def _apply_normal_patch(service, session, operations: list[dict], archive: zipfile.ZipFile) -> None:
    removal_actions = {"removed", "modified"} if session.kind == "dfs" else {"removed"}
    removals = [item for item in operations if item["action"] in removal_actions]
    removals.sort(key=lambda item: (item["before"].get("recordType") == "directory", -str(item["before"].get("path") or "").count(".")))
    for operation in removals:
        _remove_filesystem_record(service, session, operation["before"])

    additions = [item for item in operations if item["action"] in {"added", "modified"}]
    additions.sort(key=lambda item: (item["after"].get("recordType") != "directory", str(item["after"].get("path") or "").count(".")))
    for operation in additions:
        row = operation["after"]
        if row.get("recordType") == "directory":
            if session.kind != "adfs":
                raise DiskError("This patch contains a directory for a flat filesystem.")
            service.make_directory(session, str(row["path"]))
            _apply_access(service, session, row)
            continue
        content = archive.read(operation["payload"])
        if sha256_bytes(content) != operation["payloadSha256"]:
            raise DiskError(f"Patch payload {operation['payload']} failed its SHA-256 check.")
        with tempfile.NamedTemporaryFile(dir=service.work_dir, prefix="patch-file-", delete=False) as temporary:
            temporary.write(content)
            temporary_path = Path(temporary.name)
        try:
            service.put(
                session,
                int(row["slot"]) if row.get("slot") is not None else None,
                str(row["path"]), temporary_path,
                str(row.get("load") or "") or None,
                str(row.get("execute") or "") or None,
                None,
                int(row["side"]) if row.get("side") is not None else None,
            )
        finally:
            temporary_path.unlink(missing_ok=True)
        # put() already writes the candidate load and execution addresses. A
        # second metadata pass is both redundant and ambiguous for numeric DFS
        # manifest values, so only reproduce the access bits here.
        _apply_access(service, session, row)

    for operation in (item for item in operations if item["action"] == "metadata"):
        _apply_metadata(service, session, operation["after"])


def _apply_mmb_patch(service, session, operations: list[dict], archive: zipfile.ZipFile) -> None:
    for operation in operations:
        row = operation.get("after") or operation.get("before") or {}
        slot = int(row["slot"])
        if operation["action"] == "removed":
            service.clear_slot(session, slot)
            continue
        if operation["action"] in {"added", "modified"}:
            if not row.get("formatted"):
                service.clear_slot(session, slot)
                continue
            content = archive.read(operation["payload"])
            if sha256_bytes(content) != operation["payloadSha256"]:
                raise DiskError(f"Patch payload {operation['payload']} failed its SHA-256 check.")
            service.insert_slot_bytes(session, slot, content, "patch.ssd", str(row.get("diskTitle") or ""))
        if row.get("formatted"):
            service.rename_slot(session, slot, str(row.get("diskTitle") or "UNTITLED"))
            service.protect_slot(session, slot, bool(row.get("writable", True)))
            source_name = str(row.get("sourceName") or "")
            if source_name:
                service.set_slot_source_name(session, [slot], source_name)
            else:
                session.slot_source_names.pop(slot, None)
                service._persist_session(session)


def _apply_rom_patch(service, session, operations: list[dict], archive: zipfile.ZipFile) -> None:
    removed_banks = []
    for operation in operations:
        row = operation.get("after") or operation.get("before") or {}
        bank = int(row["bank"])
        if operation["action"] == "removed":
            removed_banks.append(bank)
        elif operation["action"] in {"added", "modified"}:
            content = archive.read(operation["payload"])
            if sha256_bytes(content) != operation["payloadSha256"]:
                raise DiskError(f"Patch payload {operation['payload']} failed its SHA-256 check.")
            service.put_rom_bank(session, content, bank)
    if removed_banks:
        current_count = session.path.stat().st_size // session.rom_bank_size
        expected = list(range(current_count - len(removed_banks), current_count))
        if sorted(removed_banks) != expected:
            raise DiskError("A ROM patch can remove only contiguous banks from the end of an image.")
        with session.lock, session.path.open("r+b") as image:
            image.truncate((current_count - len(removed_banks)) * session.rom_bank_size)
        session.dirty = True
        service._persist_session(session)


def apply_patch_archive(service, session, archive_path: Path) -> dict:
    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
            if len(names) > MAX_OPERATIONS + 1 or "patch.json" not in names:
                raise DiskError("This is not a valid Acorn File Forge patch archive.")
            if any(name.startswith("/") or ".." in Path(name).parts for name in names):
                raise DiskError("The patch archive contains an unsafe member path.")
            document = json.loads(archive.read("patch.json"))
            if document.get("format") != PATCH_FORMAT or document.get("version") != PATCH_VERSION:
                raise DiskError("This patch format or version is not supported.")
            if document.get("kind") != session.kind:
                raise DiskError(f"This patch targets {document.get('kind')}, not the open {session.kind} image.")
            operations = document.get("operations")
            if not isinstance(operations, list) or len(operations) > MAX_OPERATIONS:
                raise DiskError("The patch operation list is invalid or too large.")
            current = build_manifest(service, session)
            if document.get("layout") and _layout_signature(current) != document.get("layout"):
                raise DiskError("This patch targets a different DFS side layout or ROM bank size.")
            if manifest_fingerprint(current) != document.get("baseFingerprint"):
                raise DiskError("The open image does not match this patch's exact base revision.")
            if session.kind == "mmb":
                _apply_mmb_patch(service, session, operations, archive)
            elif session.kind == "rom":
                _apply_rom_patch(service, session, operations, archive)
            elif session.kind == "tape":
                raise DiskError("UEF tape images are read-only and cannot receive patch sets.")
            else:
                _apply_normal_patch(service, session, operations, archive)
    except zipfile.BadZipFile as exc:
        raise DiskError("The selected patch is not a readable ZIP archive.") from exc
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DiskError(f"The patch document is incomplete or invalid: {exc}") from exc

    result = build_manifest(service, session)
    actual = manifest_fingerprint(result)
    if actual != document.get("candidateFingerprint"):
        expected_records = document.get("candidateRecords")
        detail = ""
        if isinstance(expected_records, list):
            verification = compare_manifests(
                {"image": document.get("candidate", {}), "records": expected_records},
                result,
            )
            for category in ("added", "removed", "modified", "metadata"):
                if not verification["changes"][category]:
                    continue
                mismatch = verification["changes"][category][0]
                row = mismatch.get("after") or mismatch.get("before") or {}
                fields = mismatch.get("changedFields") or []
                label = row.get("path") or row.get("diskTitle") or mismatch.get("key")
                detail = f" First mismatch: {label} ({category}{': ' + ', '.join(fields) if fields else ''})."
                break
        raise DiskError(
            "The patch operations completed, but the resulting logical fingerprint did not match the candidate image."
            + detail
        )
    return {"operations": len(operations), "fingerprint": actual, "summary": document.get("summary", {})}
