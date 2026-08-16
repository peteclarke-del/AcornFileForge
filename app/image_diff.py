from __future__ import annotations

import json
from typing import Any

from .analysis_service import build_manifest
from .checksum import sha256_bytes


IDENTITY_FIELDS = ("recordType", "slot", "side", "bank", "path")
CONTENT_FIELDS = ("sha256", "size", "formatted", "empty", "fileCount")
IGNORED_FIELDS = frozenset(IDENTITY_FIELDS)
DIRECTORY_DERIVED_FIELDS = frozenset({"size", "fileCount"})


def _normalise(value: Any) -> Any:
    """Return deterministic JSON-compatible values for comparison and hashing."""
    if isinstance(value, dict):
        return {str(key): _normalise(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_normalise(item) for item in value]
    return value


def record_key(record: dict) -> str:
    """Build a stable filesystem-aware identity for one manifest record."""
    record_type = str(record.get("recordType") or "object").casefold()
    path = str(record.get("path") or "").casefold()
    if record.get("slot") is not None:
        slot = int(record["slot"])
        return f"slot:{slot}" if record_type == "slot" else f"slot:{slot}:{record_type}:{path}"
    if record.get("bank") is not None:
        return f"bank:{int(record['bank'])}:{record_type}:{path}"
    side = "" if record.get("side") is None else str(record["side"])
    return f"side:{side}:{record_type}:{path}"


def manifest_fingerprint(manifest: dict) -> str:
    """Hash logical image contents without session IDs, names or dirty state."""
    logical = []
    for record in manifest.get("records", []):
        fingerprint_record = dict(record)
        if fingerprint_record.get("recordType") == "directory":
            for field in DIRECTORY_DERIVED_FIELDS:
                fingerprint_record.pop(field, None)
        logical.append({"key": record_key(record), "record": _normalise(fingerprint_record)})
    logical.sort(key=lambda item: item["key"])
    encoded = json.dumps(logical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256_bytes(encoded.encode("utf-8"))


def _changed_fields(before: dict, after: dict) -> list[str]:
    ignored = IGNORED_FIELDS | (
        DIRECTORY_DERIVED_FIELDS
        if before.get("recordType") == "directory" and after.get("recordType") == "directory"
        else frozenset()
    )
    return sorted(
        key for key in set(before) | set(after)
        if key not in ignored and _normalise(before.get(key)) != _normalise(after.get(key))
    )


def compare_manifests(base: dict, candidate: dict) -> dict:
    """Compare two logical manifests and classify content and metadata changes."""
    left = {record_key(record): record for record in base.get("records", [])}
    right = {record_key(record): record for record in candidate.get("records", [])}
    changes: dict[str, list[dict]] = {"added": [], "removed": [], "modified": [], "metadata": []}

    for key in sorted(left.keys() - right.keys()):
        changes["removed"].append({"key": key, "before": left[key]})
    for key in sorted(right.keys() - left.keys()):
        changes["added"].append({"key": key, "after": right[key]})
    for key in sorted(left.keys() & right.keys()):
        before, after = left[key], right[key]
        fields = _changed_fields(before, after)
        if not fields:
            continue
        change = {"key": key, "before": before, "after": after, "changedFields": fields}
        category = "modified" if any(field in CONTENT_FIELDS for field in fields) else "metadata"
        changes[category].append(change)

    base_image = base.get("image", {})
    candidate_image = candidate.get("image", {})
    summary = {name: len(items) for name, items in changes.items()}
    summary["total"] = sum(summary.values())
    return {
        "base": {"id": base_image.get("id"), "name": base_image.get("name"), "kind": base_image.get("kind")},
        "candidate": {"id": candidate_image.get("id"), "name": candidate_image.get("name"), "kind": candidate_image.get("kind")},
        "baseFingerprint": manifest_fingerprint(base),
        "candidateFingerprint": manifest_fingerprint(candidate),
        "sameFormat": base_image.get("kind") == candidate_image.get("kind"),
        "summary": summary,
        "changes": changes,
    }


def compare_images(service, base_session, candidate_session, progress=None) -> dict:
    if progress:
        progress(
            f"Cataloguing base image {getattr(base_session, 'name', 'base image')}",
            0,
            2,
        )
    base = build_manifest(service, base_session, progress)
    if progress:
        progress(
            f"Cataloguing candidate image {getattr(candidate_session, 'name', 'candidate image')}",
            1,
            2,
        )
    candidate = build_manifest(service, candidate_session, progress)
    if progress:
        progress("Comparing logical contents and metadata", 2, 2)
    return compare_manifests(base, candidate)
