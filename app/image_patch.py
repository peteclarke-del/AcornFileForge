from __future__ import annotations

import json
import re
import shutil
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path

from .analysis_service import build_manifest
from .checksum import sha256_path, sha256_stream
from .disk_service import DiskError
from .image_diff import compare_manifests, manifest_fingerprint, record_key
from .menu_service import delete_adfs_items


PATCH_FORMAT = "acorn-file-forge-image-patch"
PATCH_VERSION = 1
MAX_OPERATIONS = 100_000
MAX_PATCH_UNCOMPRESSED_BYTES = 9 * 1024 * 1024 * 1024
MAX_PATCH_DOCUMENT_BYTES = 64 * 1024 * 1024
PATCH_ACTIONS = frozenset({"added", "removed", "modified", "metadata"})
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


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


def _payload_required(kind: str, operation: dict) -> bool:
    row = operation.get("after") or operation.get("before") or {}
    return (
        operation.get("action") in {"added", "modified"}
        and row.get("recordType") != "directory"
        and not (kind == "mmb" and not row.get("formatted"))
    )


def _member_sha256(archive: zipfile.ZipFile, name: str) -> str:
    with archive.open(name) as source:
        return sha256_stream(source)


def _extract_payload(archive: zipfile.ZipFile, name: str, work_dir: Path) -> Path:
    """Stream one already-verified member to disk without retaining it in RAM."""
    with tempfile.NamedTemporaryFile(dir=work_dir, prefix="patch-file-", delete=False) as temporary:
        with archive.open(name) as source:
            shutil.copyfileobj(source, temporary, length=8 * 1024 * 1024)
        return Path(temporary.name)


def _read_patch_document(archive: zipfile.ZipFile) -> dict:
    names = archive.namelist()
    if len(names) > MAX_OPERATIONS + 1 or "patch.json" not in names:
        raise DiskError("This is not a valid Acorn File Forge patch archive.")
    if len(names) != len(set(names)):
        raise DiskError("The patch archive contains duplicate member names.")
    if any(name.startswith("/") or ".." in Path(name).parts for name in names):
        raise DiskError("The patch archive contains an unsafe member path.")
    if sum(item.file_size for item in archive.infolist()) > MAX_PATCH_UNCOMPRESSED_BYTES:
        raise DiskError("The expanded patch archive exceeds the 9 GiB safety limit.")
    if archive.getinfo("patch.json").file_size > MAX_PATCH_DOCUMENT_BYTES:
        raise DiskError("The patch operation document exceeds the 64 MiB safety limit.")
    document = json.loads(archive.read("patch.json"))
    if document.get("format") != PATCH_FORMAT or document.get("version") != PATCH_VERSION:
        raise DiskError("This patch format or version is not supported.")
    operations = document.get("operations")
    if not isinstance(operations, list) or len(operations) > MAX_OPERATIONS:
        raise DiskError("The patch operation list is invalid or too large.")
    for field in ("baseFingerprint", "candidateFingerprint"):
        fingerprint = str(document.get(field) or "").lower()
        if not SHA256_PATTERN.fullmatch(fingerprint):
            raise DiskError(f"The patch has an invalid {field}.")
        document[field] = fingerprint
    expected_payloads = set()
    for index, operation in enumerate(operations, start=1):
        if not isinstance(operation, dict) or operation.get("action") not in PATCH_ACTIONS:
            raise DiskError(f"Patch operation {index} has an invalid action.")
        if not isinstance(operation.get("after") or operation.get("before"), dict):
            raise DiskError(f"Patch operation {index} has no logical record.")
        if not _payload_required(str(document.get("kind") or ""), operation):
            continue
        name = str(operation.get("payload") or "")
        checksum = str(operation.get("payloadSha256") or "").lower()
        if not name.startswith("payloads/") or name not in names:
            raise DiskError(f"Patch operation {index} is missing its payload.")
        if not SHA256_PATTERN.fullmatch(checksum):
            raise DiskError(f"Patch operation {index} has an invalid payload checksum.")
        operation["payloadSha256"] = checksum
        expected_payloads.add(name)
    unexpected = set(names) - {"patch.json"} - expected_payloads
    if unexpected:
        raise DiskError(f"The patch archive contains an unexpected member: {sorted(unexpected)[0]}.")
    return document


def _validate_operation_plan(kind: str, document: dict, current: dict) -> None:
    """Prove that the advertised operations are the canonical candidate diff."""
    candidate_records = document.get("candidateRecords")
    if not isinstance(candidate_records, list) or not all(
        isinstance(record, dict) for record in candidate_records
    ):
        raise DiskError("The patch has no verifiable candidate manifest.")
    candidate_keys = [record_key(record) for record in candidate_records]
    if len(candidate_keys) != len(set(candidate_keys)):
        raise DiskError("The patch candidate manifest contains duplicate logical records.")
    candidate = {"image": document.get("candidate", {}), "records": candidate_records}
    if manifest_fingerprint(candidate) != document["candidateFingerprint"]:
        raise DiskError("The patch candidate manifest does not match its fingerprint.")
    comparison = compare_manifests(current, candidate)
    expected = [
        {
            "action": action,
            "key": change["key"],
            "before": change.get("before"),
            "after": change.get("after"),
            "changedFields": change.get("changedFields", []),
        }
        for action, change, _row in _patch_changes(kind, comparison)
    ]
    actual = [
        {
            "action": operation.get("action"),
            "key": operation.get("key"),
            "before": operation.get("before"),
            "after": operation.get("after"),
            "changedFields": operation.get("changedFields", []),
        }
        for operation in document["operations"]
    ]
    if actual != expected:
        raise DiskError("The patch operation plan does not match its base and candidate manifests.")
    if document.get("summary") != comparison["summary"]:
        raise DiskError("The patch change summary does not match its operation plan.")


def _preflight_patch(service, session, archive: zipfile.ZipFile) -> tuple[dict, dict]:
    document = _read_patch_document(archive)
    if document.get("kind") != session.kind:
        raise DiskError(f"This patch targets {document.get('kind')}, not the open {session.kind} image.")
    current = build_manifest(service, session)
    if document.get("layout") and _layout_signature(current) != document.get("layout"):
        raise DiskError("This patch targets a different DFS side layout or ROM bank size.")
    if manifest_fingerprint(current) != document.get("baseFingerprint"):
        raise DiskError("The open image does not match this patch's exact base revision.")
    _validate_operation_plan(session.kind, document, current)
    for index, operation in enumerate(document["operations"], start=1):
        if not _payload_required(session.kind, operation):
            continue
        if _member_sha256(archive, operation["payload"]) != operation["payloadSha256"]:
            raise DiskError(f"Patch payload for operation {index} failed its SHA-256 check.")
    return document, current


def inspect_patch_archive(service, session, archive_path: Path) -> dict:
    """Verify a patch completely without changing the open image."""
    try:
        with zipfile.ZipFile(archive_path) as archive:
            document, _current = _preflight_patch(service, session, archive)
            payload_names = {
                operation["payload"]
                for operation in document["operations"]
                if _payload_required(session.kind, operation)
            }
            payload_bytes = sum(archive.getinfo(name).file_size for name in payload_names)
    except zipfile.BadZipFile as exc:
        raise DiskError("The selected patch is not a readable ZIP archive.") from exc
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DiskError(f"The patch document is incomplete or invalid: {exc}") from exc
    return {
        "compatible": True,
        "base": document.get("base", {}),
        "candidate": document.get("candidate", {}),
        "summary": document.get("summary", {}),
        "operationCount": len(document["operations"]),
        "payloadCount": len(payload_names),
        "payloadBytes": payload_bytes,
        "operations": document["operations"][:200],
        "truncated": len(document["operations"]) > 200,
    }


@contextmanager
def _candidate_payload_path(service, session, row: dict):
    """Expose one candidate payload as a path and clean generated exports."""
    if session.kind == "mmb":
        yield service._slot_path(session, int(row["slot"]))
        return
    exported = service.export_file(
        session,
        int(row["slot"]) if row.get("slot") is not None else None,
        str(row["path"]),
        int(row["side"]) if row.get("side") is not None else None,
    )
    try:
        yield exported
    finally:
        exported.unlink(missing_ok=True)


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

    operation_count = sum(1 for _item in _patch_changes(base_session.kind, comparison))
    if operation_count > MAX_OPERATIONS:
        raise DiskError(f"Patch sets are limited to {MAX_OPERATIONS:,} logical operations.")
    operations = []
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        payload_count = 0
        for action, change, row in _patch_changes(base_session.kind, comparison):
            operation = {
                "action": action,
                "key": change["key"],
                "before": change.get("before"),
                "after": change.get("after"),
                "changedFields": change.get("changedFields", []),
            }
            if _payload_required(base_session.kind, operation):
                payload_name = f"payloads/{payload_count:08d}.bin"
                with _candidate_payload_path(service, candidate_session, row) as source:
                    checksum = sha256_path(source)
                    expected = str(row.get("sha256") or "").lower()
                    if SHA256_PATTERN.fullmatch(expected) and checksum != expected:
                        raise DiskError(
                            f"{row.get('path') or row.get('diskTitle') or operation['key']} "
                            "changed while the patch was being built. Compare the images again."
                        )
                    archive.write(source, payload_name)
                operation["payload"] = payload_name
                operation["payloadSha256"] = checksum
                payload_count += 1
            operations.append(operation)
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
        archive.writestr("patch.json", json.dumps(document, indent=2, ensure_ascii=False))
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
        temporary_path = _extract_payload(archive, operation["payload"], service.work_dir)
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
            document, _current = _preflight_patch(service, session, archive)
            operations = document["operations"]
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
