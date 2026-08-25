"""Build validated, non-mutating hardware deployment packages."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
import zipfile
from contextlib import contextmanager
from copy import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable

from .analysis_service import preflight_report
from .checksum import sha256_bytes, sha256_path
from .errors import DiskError
from .version import application_version


DEPLOYMENT_FORMAT = "acorn-file-forge-hardware-deployment"
DEPLOYMENT_VERSION = 1
FAT32_FILE_LIMIT = 4 * 1024 * 1024 * 1024 - 1


TARGETS = (
    {
        "id": "gotek",
        "label": "Gotek / FlashFloppy USB",
        "description": "Floppy images in native or indexed FlashFloppy layout.",
    },
    {
        "id": "mmfs",
        "label": "MMFS SD card",
        "description": "An MMB installed as BEEB.MMB in the FAT root.",
    },
    {
        "id": "beebscsi",
        "label": "BeebSCSI SD card",
        "description": "A matched DAT and DSC pair below BeebSCSI0.",
    },
    {
        "id": "pi1mhz",
        "label": "Pi1MHz SD card",
        "description": "MMFS or BeebSCSI media in the paths used by Pi1MHz.",
    },
    {
        "id": "risc-os",
        "label": "RISC OS / Archimedes host",
        "description": "A FileCore image and companion metadata for deployment or emulation.",
    },
)


@dataclass(frozen=True)
class DeploymentEntry:
    path: str
    role: str
    source: Path | None = None
    data: bytes | None = None

    @property
    def size(self) -> int:
        return len(self.data) if self.data is not None else int(self.source.stat().st_size)

    def digest(self, progress: Callable[[int, int], None] | None = None) -> str:
        if self.data is not None:
            return sha256_bytes(self.data)
        return sha256_path(self.source, progress)


def _safe_leaf(value: str, fallback: str = "DISK") -> str:
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", str(value or "")).strip(" ._")
    return stem or fallback


def _entry(path: str, role: str, *, source: Path | None = None, data: bytes | str | None = None) -> DeploymentEntry:
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise DiskError(f"The deployment path is unsafe: {path}")
    encoded = data.encode("utf-8") if isinstance(data, str) else data
    if (source is None) == (encoded is None):
        raise DiskError("A deployment entry must have exactly one source.")
    return DeploymentEntry(str(pure), role, source=source, data=encoded)


def available_deployment_targets(service, session) -> list[dict]:
    suffix = session.path.suffix.casefold()
    summary = service.summary(session)
    floppy = session.kind in {"dfs", "adfs"} and not bool(summary.get("hardDisk"))
    paired_dat = bool(session.descriptor_path and suffix == ".dat")
    support = {
        "gotek": session.kind == "mmb" or floppy or suffix == ".hfe",
        "mmfs": session.kind == "mmb",
        "beebscsi": paired_dat,
        "pi1mhz": session.kind == "mmb" or paired_dat,
        "risc-os": session.kind == "adfs" and not paired_dat,
    }
    reasons = {
        "gotek": "Open a floppy image or MMB collection.",
        "mmfs": "MMFS deployment requires an MMB image.",
        "beebscsi": "BeebSCSI deployment requires a matched DAT and DSC pair.",
        "pi1mhz": "Pi1MHz deployment currently accepts an MMB or matched BeebSCSI pair.",
        "risc-os": "RISC OS deployment requires a FileCore ADFS, HDF or RAW image.",
    }
    return [
        {**target, "available": support[target["id"]], "reason": "" if support[target["id"]] else reasons[target["id"]]}
        for target in TARGETS
    ]


def _copy_sparse(
    source: Path,
    destination: Path,
    progress: Callable[[int, int], None] | None = None,
) -> None:
    """Copy an image without materialising zero-filled DAT extents."""
    block_size = 4 * 1024 * 1024
    size = source.stat().st_size
    copied = 0
    with source.open("rb") as reader, destination.open("wb") as writer:
        while chunk := reader.read(block_size):
            if chunk.strip(b"\0"):
                writer.write(chunk)
            else:
                writer.seek(len(chunk), os.SEEK_CUR)
            copied += len(chunk)
            if progress:
                progress(copied, size)
        writer.truncate(size)
    shutil.copystat(source, destination)


@contextmanager
def prepared_snapshot(service, session, progress: Callable | None = None):
    """Yield a hardware-finalised session copy and leave the live session untouched."""
    with tempfile.TemporaryDirectory(dir=service.work_dir, prefix="deployment-snapshot-") as folder:
        root = Path(folder)
        configured = copy(session)
        configured.path = root / session.path.name
        _copy_sparse(
            session.path,
            configured.path,
            (lambda current, total: progress("Copying an isolated image snapshot", current, total))
            if progress else None,
        )
        if session.descriptor_path:
            configured.descriptor_path = root / session.descriptor_path.name
            shutil.copy2(session.descriptor_path, configured.descriptor_path)
        configured.lock = threading.RLock()
        configured.slot_cache = {}
        configured.finalised_mtime_ns = None
        service.prepare_download(configured, progress)
        yield configured


def _gotek_entries(service, session, options: dict) -> list[DeploymentEntry]:
    mode = str(options.get("gotekMode") or "native").strip().lower()
    if mode not in {"native", "indexed"}:
        raise DiskError("Choose Native or Indexed Gotek navigation.")
    try:
        start = int(options.get("startIndex") or 0)
    except (TypeError, ValueError) as exc:
        raise DiskError("The first Gotek index must be a number from 0 to 9999.") from exc
    if start < 0 or start > 9999:
        raise DiskError("The first Gotek index must be between 0 and 9999.")
    images: list[tuple[str, bytes | None, Path | None]] = []
    if session.kind == "mmb":
        for slot in service.list_slots(session):
            if not slot.get("formatted"):
                continue
            data, filename = service.slot_download(session, int(slot["slot"]))
            images.append((f"{int(slot['slot']):03d}-{_safe_leaf(filename)}", data, None))
    else:
        source = service.prepare_download(session)
        images.append((_safe_leaf(source.name), None, source))
    if not images:
        raise DiskError("The MMB contains no formatted disks to deploy.")
    if start + len(images) > 10_000:
        raise DiskError("The selected Gotek index range exceeds DSKA9999.")
    entries = []
    for offset, (name, data, source) in enumerate(images):
        leaf = name
        if mode == "indexed":
            suffix = Path(name).suffix or ".ssd"
            leaf = f"DSKA{start + offset:04d}_{_safe_leaf(Path(name).stem)}{suffix.lower()}"
        entries.append(_entry(f"GOTEK-USB/{leaf}", "floppy image", source=source, data=data))
    if mode == "indexed":
        entries.append(_entry(
            "GOTEK-USB/FF.CFG",
            "FlashFloppy configuration",
            data="nav-mode = indexed\nindexed-prefix = DSKA\n",
        ))
    return entries


def _media_entries(service, session, target: str) -> list[DeploymentEntry]:
    if target == "mmfs":
        return [_entry("SD-CARD/BEEB.MMB", "MMFS disk collection", source=session.path)]
    if target in {"beebscsi", "pi1mhz"} and session.descriptor_path:
        source = service.prepare_download(session)
        return [
            _entry("SD-CARD/BeebSCSI0/scsi0.dat", "BeebSCSI data image", source=source),
            _entry("SD-CARD/BeebSCSI0/scsi0.dsc", "BeebSCSI geometry descriptor", source=session.descriptor_path),
        ]
    if target == "pi1mhz" and session.kind == "mmb":
        return [_entry("SD-CARD/BEEB.MMB", "Pi1MHz MMFS disk collection", source=session.path)]
    if target == "risc-os":
        source = service.prepare_download(session)
        entries = [_entry(f"RISC-OS-HOST/Images/{_safe_leaf(source.name)}", "FileCore image", source=source)]
        if session.descriptor_path:
            entries.append(_entry(
                f"RISC-OS-HOST/Images/{_safe_leaf(session.descriptor_path.name)}",
                "companion descriptor",
                source=session.descriptor_path,
            ))
        return entries
    raise DiskError("The open image is not compatible with that deployment target.")


def _profile_findings(session, target: str) -> list[dict]:
    profile = session.hardware_profile or {}
    addons = {str(value) for value in profile.get("addons") or []}
    findings = []
    def warn(message: str) -> None:
        findings.append({"severity": "warning", "message": message})
    if not profile:
        warn("No hardware profile is applied; machine-specific checks are limited.")
    if target == "mmfs" and not ({"mmfs"} & addons or str(profile.get("mmfsBuild") or "none") != "none"):
        warn("The selected hardware profile does not declare an MMFS interface or build.")
    if target == "beebscsi" and "beebscsi" not in addons and session.target_hardware != "beebscsi":
        warn("The selected hardware profile does not declare BeebSCSI storage.")
    if target == "pi1mhz":
        if str(profile.get("emulator") or "") != "elkulator-pi1mhz":
            warn("The profile does not explicitly select the Pi1MHz-aware Elkulator integration.")
        if profile.get("machine") == "electron" and "electron-ap5" not in addons:
            warn("An Electron needs an AP5 or another compatible 1 MHz bus interface for Pi1MHz.")
    if target == "risc-os" and profile.get("machine") not in {"archimedes", None, ""}:
        warn("The applied profile is not an Archimedes or RISC OS machine.")
    return findings


def _instructions(session, target: str, options: dict) -> list[str]:
    instructions = {
        "gotek": [
            "Format the USB device with a filesystem supported by the installed Gotek firmware.",
            "Copy the contents of GOTEK-USB to the root of the USB device.",
            "Keep FF.CFG with the indexed images when Indexed mode was selected.",
            "Insert the USB device, select a disk, catalogue it and verify a read before enabling writes.",
        ],
        "mmfs": [
            "Back up the existing SD card before replacing its disk collection.",
            "Copy SD-CARD/BEEB.MMB to the FAT root as BEEB.MMB.",
            "Use an MMFS ROM build and PAGE value compatible with the selected machine profile.",
            "Boot MMFS, catalogue two known slots and test a read before writing to the collection.",
        ],
        "beebscsi": [
            "Back up the existing SD card and preserve any other SCSI target directories.",
            "Copy SD-CARD/BeebSCSI0 to the SD-card root without renaming scsi0.dat or scsi0.dsc.",
            "Start with the intended ADFS ROM and target hardware, then catalogue the root and several subdirectories.",
            "After the first write, reboot and repeat the directory checks before relying on the image.",
        ],
        "pi1mhz": [
            "Start from a working Pi1MHz SD card and preserve its kernel, firmware and Pi1MHz.cfg.",
            "Merge the contents of SD-CARD into the existing FAT root; do not replace unrelated Pi1MHz files.",
            "For MMFS, keep BEEB.MMB in the root. For BeebSCSI, keep the pair below BeebSCSI0.",
            "Boot the configured machine without a Tube first, verify storage, then repeat with optional expansions.",
        ],
        "risc-os": [
            "Back up the destination emulator or storage media before installing the image.",
            "Copy the image from RISC-OS-HOST/Images to the location expected by the emulator, podule or storage adapter.",
            "Attach it using the geometry and interface appropriate to the selected RISC OS target.",
            "Run the filing-system free-space and directory checks before allowing applications to write.",
        ],
    }
    return instructions[target]


def _deployment_plan(service, session, payload: dict, progress: Callable | None = None) -> tuple[dict, list[DeploymentEntry]]:
    report = progress or (lambda _message, _current=None, _total=None: None)
    target = str(payload.get("target") or "").strip().lower()
    availability = {item["id"]: item for item in available_deployment_targets(service, session)}
    if target not in availability:
        raise DiskError("Choose a supported deployment target.")
    if not availability[target]["available"]:
        raise DiskError(availability[target]["reason"])
    report("Planning target paths and filenames", 0, 4)
    entries = _gotek_entries(service, session, payload) if target == "gotek" else _media_entries(service, session, target)
    paths = [entry.path.casefold() for entry in entries]
    if len(paths) != len(set(paths)):
        raise DiskError("The deployment would create two files with the same target path.")
    report("Checking capacity and target profile", 1, 4)
    issues = _profile_findings(session, target)
    for entry in entries:
        if entry.size > FAT32_FILE_LIMIT and target in {"gotek", "mmfs", "beebscsi", "pi1mhz"}:
            issues.append({
                "severity": "error",
                "message": f"{entry.path} exceeds the FAT32 single-file limit.",
            })
    report("Hashing deployment files", 2, 4)
    total_bytes = sum(entry.size for entry in entries)
    hashed = 0
    manifest_entries = []
    for entry in entries:
        digest = entry.digest(
            lambda current, _total, entry=entry, completed=hashed: report(
                f"Hashing {entry.path}", completed + current, total_bytes,
            )
        )
        manifest_entries.append({
            "path": entry.path,
            "role": entry.role,
            "size": entry.size,
            "sha256": digest,
        })
        hashed += entry.size
        report(f"Hashed {entry.path}", hashed, total_bytes)
    summary = service.summary(session)
    compatibility = preflight_report(service, session, {
        "operation": f"deploy-{target}",
        "sourceKind": session.kind,
        "targetKind": "host",
        "changes": [
            {
                "name": PurePosixPath(entry.path).name,
                "nameIsLeaf": True,
                "parent": str(PurePosixPath(entry.path).parent),
                "source": session.name,
                "type": entry.role,
            }
            for entry in entries
        ],
    })
    issues.extend(compatibility["issues"])
    plan = {
        "format": DEPLOYMENT_FORMAT,
        "version": DEPLOYMENT_VERSION,
        "applicationVersion": application_version(),
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target": target,
        "targetLabel": availability[target]["label"],
        "source": {
            "image": session.name,
            "kind": session.kind,
            "revision": summary["revision"],
            "hardwareProfile": session.hardware_profile or {},
        },
        "entries": manifest_entries,
        "issues": issues,
        "canProceed": not any(item["severity"] == "error" for item in issues),
        "instructions": _instructions(session, target, payload),
        "compatibilityReport": compatibility,
    }
    report("Deployment plan validated", 4, 4)
    return plan, entries


def deployment_plan(service, session, payload: dict, progress: Callable | None = None) -> dict:
    """Build an exact plan from a disposable, hardware-finalised snapshot."""
    with prepared_snapshot(service, session, progress) as snapshot:
        plan, _entries = _deployment_plan(service, snapshot, payload, progress)
    # The revision protects the real session, not the disposable snapshot.
    plan["source"]["revision"] = service.summary(session)["revision"]
    return plan


def deployment_readme(plan: dict) -> str:
    lines = [
        f"# {plan['targetLabel']} deployment",
        "",
        f"Created by Acorn File Forge {plan['applicationVersion']}.",
        f"Source image: `{plan['source']['image']}`",
        f"Source revision: `{plan['source']['revision']}`",
        "",
        "## Installation",
        "",
    ]
    lines.extend(f"{index}. {step}" for index, step in enumerate(plan["instructions"], 1))
    lines.extend(["", "## Files", ""])
    lines.extend(
        f"- `{entry['path']}`: {entry['role']}, {entry['size']:,} bytes, SHA-256 `{entry['sha256']}`"
        for entry in plan["entries"]
    )
    lines.extend(["", "## Validation findings", ""])
    lines.extend(
        f"- {item['severity'].upper()}: {item['message']}" for item in plan["issues"]
    )
    if not plan["issues"]:
        lines.append("- No target-layout problems were detected.")
    lines.extend([
        "",
        "## Recovery",
        "",
        "Keep the previous working media unchanged until the new deployment has passed its read, write and reboot checks. Restore that backup if any check fails.",
        "",
    ])
    return "\n".join(lines)


def build_deployment_archive(service, session, payload: dict, output: Path, progress: Callable | None = None) -> dict:
    report = progress or (lambda _message, _current=None, _total=None: None)
    expected = str(payload.get("expectedRevision") or "")
    live_revision = service.summary(session)["revision"]
    if expected and expected != live_revision:
        raise DiskError("The image changed after deployment review. Build a new plan before downloading.")
    with prepared_snapshot(service, session, report) as snapshot:
        plan, entries = _deployment_plan(service, snapshot, payload, report)
        plan["source"]["revision"] = live_revision
        if not plan["canProceed"]:
            raise DiskError("The deployment plan contains blocking findings.")
        total = sum(entry.size for entry in entries)
        written = 0
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
            for entry in entries:
                report(f"Adding {entry.path}", written, total)
                if entry.data is not None:
                    archive.writestr(entry.path, entry.data)
                    written += len(entry.data)
                else:
                    with entry.source.open("rb") as source, archive.open(entry.path, "w", force_zip64=True) as target:
                        while chunk := source.read(4 * 1024 * 1024):
                            target.write(chunk)
                            written += len(chunk)
                            report(f"Adding {entry.path}", written, total)
                report(f"Added {entry.path}", written, total)
            archive.writestr("README.md", deployment_readme(plan))
            archive.writestr("Deployment/manifest.json", json.dumps(plan, indent=2, ensure_ascii=False) + "\n")
            archive.writestr("Deployment/compatibility-report.md", plan["compatibilityReport"]["markdown"])
    report("Deployment package complete", total, total)
    return plan


__all__ = [
    "DEPLOYMENT_FORMAT",
    "DEPLOYMENT_VERSION",
    "available_deployment_targets",
    "build_deployment_archive",
    "deployment_plan",
    "deployment_readme",
]
