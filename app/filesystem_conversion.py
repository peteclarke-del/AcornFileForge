"""Convert a floppy image between the DFS and ADFS filesystems.

Conversion copies files, not sectors: the source is read file by file and the
files are written into a blank image of the chosen layout, which then opens
as a new pane. The source pane is never changed.

DFS to ADFS keeps the DFS directory letters as ADFS directories, so ``G.ELITE``
becomes ``$.G.ELITE`` and ``$.ELITE`` stays ``$.ELITE``. ADFS to DFS flattens
the tree: files in ``$`` keep their names, and a file in a subdirectory takes
its first directory's initial as its DFS directory letter. ADFS allows longer
names, deeper trees, more files and bigger discs than DFS, so that direction
is checked first. Anything that does not fit is reported, and nothing is
created unless the caller accepts dropping it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import tempfile
from typing import Callable

from acorn_greaseweazle import DISK_FORMATS, DiskFormat

from .errors import DiskError
from .floppy_layouts import (
    DFS_CATALOGUE_SECTORS,
    DFS_FILES_PER_SIDE,
    create_blank_layout,
    is_dfs,
    layout as floppy_layout,
)
from .image_session import ImageSession

Progress = Callable[[str, int | None, int | None], None]

DFS_NAME_LENGTH = 7
ADFS_NAME_LENGTH = 10
_DFS_UNSAFE = re.compile(r'[\s."#*:$&@^|!]')
_DFS_LOCKED = re.compile(r"L", re.I)


@dataclass(frozen=True)
class SourceFile:
    """One file found on the source disc."""

    source_path: str
    directory: str
    name: str
    load: int
    exec_address: int
    length: int
    locked: bool
    side: int | None = None


@dataclass
class ConversionPlan:
    """Where every source file goes, and what will not fit."""

    target: DiskFormat
    files: list[tuple[SourceFile, str]] = field(default_factory=list)
    directories: list[str] = field(default_factory=list)
    renamed: list[dict] = field(default_factory=list)
    dropped: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def public(self) -> dict:
        return {
            "target": self.target.public(),
            "files": len(self.files),
            "renamed": self.renamed,
            "dropped": self.dropped,
            "notes": self.notes,
        }


def conversion_targets(session: ImageSession) -> list[dict]:
    """List the layouts an image can be converted to."""
    if session.kind not in {"dfs", "adfs"} or session.hfe_read_only or session.scp_read_only:
        return []
    other = "adfs" if session.kind == "dfs" else "dfs"
    return [
        item.public()
        for item in DISK_FORMATS.values()
        if (item.identifier.startswith("dfs-") if other == "dfs" else item.identifier.startswith("adfs-"))
    ]


def _number(value: object) -> int:
    if isinstance(value, int):
        return value
    text = str(value or "0").strip()
    try:
        return int(text, 16) if text else 0
    except ValueError:
        return 0


def _source_files(disks, session: ImageSession) -> list[SourceFile]:
    if session.kind == "dfs":
        # A DSD's sides are Acorn drives 0 and 2.
        sides = [0, 2] if session.path.suffix.lower() == ".dsd" else [None]
        found = []
        for side in sides:
            for row in disks.list_dfs_catalogue_files(session, None, side):
                found.append(
                    SourceFile(
                        row["path"],
                        row["prefix"],
                        row["name"],
                        _number(row["load"]),
                        _number(row["exec"]),
                        int(row["length"]),
                        "L" in str(row.get("attr") or ""),
                        side,
                    )
                )
        return found
    found: list[SourceFile] = []

    def walk(directory: str) -> None:
        for row in disks.list_directory(session, directory, None)["entries"]:
            path = f"{directory}.{row['name']}"
            if row["type"] == "dir":
                walk(path)
                continue
            found.append(
                SourceFile(
                    path,
                    directory,
                    row["name"],
                    _number(row["load"]),
                    _number(row["exec"]),
                    int(row["length"]),
                    bool(_DFS_LOCKED.search(str(row.get("attr") or "").split("/")[0])),
                )
            )

    walk("$")
    return found


def _dfs_leaf(name: str) -> str:
    cleaned = _DFS_UNSAFE.sub("", name)[:DFS_NAME_LENGTH]
    return cleaned or "FILE"


def _unique(name: str, used: set[str], length: int) -> str:
    candidate = name
    counter = 1
    while candidate.upper() in used:
        suffix = str(counter)
        candidate = name[: length - len(suffix)] + suffix
        counter += 1
    used.add(candidate.upper())
    return candidate


def plan_conversion(disks, session: ImageSession, target_id: str) -> ConversionPlan:
    """Decide where each file goes without changing anything."""
    target = floppy_layout(target_id)
    if session.kind not in {"dfs", "adfs"}:
        raise DiskError("Only DFS and ADFS floppy images can be converted.")
    if is_dfs(target) == (session.kind == "dfs"):
        raise DiskError("Choose a layout with the other filesystem; the image is already "
                        f"{session.kind.upper()}.")
    plan = ConversionPlan(target)
    files = _source_files(disks, session)
    if is_dfs(target):
        _plan_to_dfs(plan, files)
    else:
        _plan_to_adfs(plan, files)
    return plan


def _plan_to_adfs(plan: ConversionPlan, files: list[SourceFile]) -> None:
    directories: set[str] = set()
    used: dict[str, set[str]] = {}
    capacity = plan.target.size - 7 * 256  # map and root directory
    total = 0
    for item in files:
        # Both sides of a DSD use the same directory letters, so side 2's
        # files go in their own tree rather than colliding with side 1's.
        base = "$.SIDE2" if item.side == 2 else "$"
        parent = base if item.directory == "$" else f"{base}.{item.directory}"
        for needed in (base, parent):
            if needed != "$" and needed not in directories:
                directories.add(needed)
                plan.directories.append(needed)
                capacity -= 5 * 256
        name = _unique(item.name[:ADFS_NAME_LENGTH], used.setdefault(parent, set()), ADFS_NAME_LENGTH)
        sectors = -(-item.length // 256)
        if total + sectors * 256 > capacity:
            plan.dropped.append({"path": item.source_path, "reason": f"no space on a {plan.target.label} disc"})
            continue
        total += sectors * 256
        destination = f"{parent}.{name}"
        if name != item.name:
            plan.renamed.append({"from": item.source_path, "to": destination})
        plan.files.append((item, destination))
    if any(item.side == 2 for item in files):
        plan.notes.append("Files from side 2 of the DSD are in $.SIDE2.")


def _plan_to_dfs(plan: ConversionPlan, files: list[SourceFile]) -> None:
    sides = plan.target.heads
    per_side = plan.target.cylinders * 10 - DFS_CATALOGUE_SECTORS
    side_files = [0] * sides
    side_sectors = [0] * sides
    # DFS names are unique per side and directory letter.
    used: dict[tuple[int, str], set[str]] = {}
    for item in files:
        parts = item.source_path.split(".")
        letter = "$" if len(parts) == 2 else parts[1][:1].upper()
        if not letter.isalnum():
            letter = "$"
        leaf = _dfs_leaf(item.name)
        sectors = -(-item.length // 256)
        side = next(
            (
                index
                for index in range(sides)
                if side_files[index] < DFS_FILES_PER_SIDE and side_sectors[index] + sectors <= per_side
            ),
            None,
        )
        if side is None:
            full = side_files[0] >= DFS_FILES_PER_SIDE
            plan.dropped.append({
                "path": item.source_path,
                "reason": (
                    f"a DFS side holds at most {DFS_FILES_PER_SIDE} files"
                    if full and sectors <= per_side
                    else f"no space on a {plan.target.label} disc"
                ),
            })
            continue
        name = _unique(leaf, used.setdefault((side, letter), set()), DFS_NAME_LENGTH)
        key = f"{letter}.{name}"
        side_files[side] += 1
        side_sectors[side] += sectors
        destination = key if sides == 1 else f"{side * 2}:{key}"
        if name != item.name or len(parts) > 2:
            plan.renamed.append({"from": item.source_path, "to": key + (f" (side {side + 1})" if sides == 2 else "")})
        plan.files.append((item, destination))
    if any(len(item.source_path.split(".")) > 3 for item in files):
        plan.notes.append("DFS has no subdirectories, so nested ADFS paths were flattened.")


def convert(
    disks,
    session: ImageSession,
    target_id: str,
    *,
    accept_losses: bool = False,
    title: str | None = None,
    progress: Progress | None = None,
) -> tuple[ImageSession, ConversionPlan]:
    """Create a new image of ``target_id`` holding the source's files."""
    report = progress or (lambda _message, _current=None, _total=None: None)
    plan = plan_conversion(disks, session, target_id)
    if plan.dropped and not accept_losses:
        raise DiskError(
            f"{len(plan.dropped)} files will not fit on a {plan.target.label} disc. "
            "Review the conversion and accept leaving them out, or choose a larger layout."
        )
    if not plan.files:
        raise DiskError("There are no files to convert.")
    disc_title = (title if title is not None else str(disks.summary(session).get("title") or "")).strip()
    target = create_blank_layout(disks, plan.target, disc_title[: 12 if is_dfs(plan.target) else 10])
    try:
        for directory in plan.directories:
            disks.make_directory(target, directory)
        locked: dict[int | None, list[str]] = {}
        with tempfile.TemporaryDirectory(prefix="acorn-convert-") as folder:
            total = len(plan.files)
            for position, (item, destination) in enumerate(plan.files, start=1):
                report(f"Copying {item.source_path}", position - 1, total)
                data = disks.read_file(session, None, item.source_path, item.side)
                payload = Path(folder) / f"{position}.bin"
                payload.write_bytes(data)
                target_path, side = destination, None
                if is_dfs(plan.target) and plan.target.heads == 2:
                    side_text, target_path = destination.split(":", 1)
                    side = int(side_text)
                disks.put(
                    target,
                    None,
                    target_path,
                    payload,
                    f"0x{item.load & 0xFFFFFFFF:X}",
                    f"0x{item.exec_address & 0xFFFFFFFF:X}",
                    None,
                    side,
                )
                if item.locked:
                    locked.setdefault(side, []).append(target_path)
            for side, paths in locked.items():
                disks.set_access(target, None, paths, False, side)
        disks.carry_boot_option(session, target, "$", include_dfs=True)
        report("Conversion complete", len(plan.files), len(plan.files))
    except Exception:
        disks.discard_session(target)
        raise
    stem = Path(session.name).stem
    disks.rename_session(target, f"{stem}{plan.target.suffix}")
    target.dirty = True
    disks._persist_session(target)
    return target, plan

