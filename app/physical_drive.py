"""Panes bound to a disk in a Greaseweazle drive.

A drive pane is an ordinary image session whose working file was read from a
physical disk. Every edit stays in that working file; the disk changes only
when the user asks for a write. The binding records the drive, the Acorn
layout and head stepping, and a digest of the bytes the disk was last known
to hold. Comparing that digest with the working file tells the pane whether
it has changes still to write, and undoing back to the disk's contents
correctly reports nothing to write.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Callable

from acorn_greaseweazle import (
    DISK_FORMATS,
    Detection,
    DiskFormat,
    GreaseweazleClient,
    GreaseweazleError,
    disk_format,
)
from acorn_greaseweazle.formats import DiskFormatError

from .checksum import sha256_path
from .errors import DiskError
from .floppy_layouts import create_blank_layout, layout as floppy_layout
from .image_session import ImageSession

Progress = Callable[[str, int | None, int | None], None]

def normalise_physical_drive(value: object) -> dict | None:
    """Accept a stored binding only when every field is still valid."""
    if not isinstance(value, dict):
        return None
    try:
        layout = disk_format(value.get("format"))
    except DiskFormatError:
        return None
    step = int(value.get("step") or 1)
    drive = str(value.get("drive") or "")
    if step not in (1, 2) or not drive.isalnum():
        return None
    return {
        "drive": drive,
        "format": layout.identifier,
        "step": step,
        "diskDigest": str(value.get("diskDigest") or ""),
        "missingSectors": max(0, int(value.get("missingSectors") or 0)),
    }


def physical_drive_summary(session: ImageSession) -> dict | None:
    binding = session.physical_drive
    if not binding:
        return None
    layout = DISK_FORMATS[binding["format"]]
    return {
        "drive": binding["drive"],
        "format": layout.public(),
        "step": binding["step"],
        "missingSectors": binding.get("missingSectors", 0),
        "unwritten": sha256_path(session.path) != binding.get("diskDigest"),
    }


def bind(session: ImageSession, drive: str, layout: DiskFormat, step: int, missing: int = 0) -> None:
    """Record that the working file now matches the disk in ``drive``."""
    session.physical_drive = {
        "drive": drive,
        "format": layout.identifier,
        "step": step,
        "diskDigest": sha256_path(session.path),
        "missingSectors": missing,
    }


@dataclass
class PhysicalDriveService:
    """Probe, open, format and write disks for drive panes."""

    disks: object
    client_factory: Callable[[], GreaseweazleClient] = GreaseweazleClient

    def _client(self) -> GreaseweazleClient:
        return self.client_factory()

    def probe(self, drive: str, progress: Progress | None = None) -> Detection:
        with tempfile.TemporaryDirectory(prefix="acorn-drive-probe-") as folder:
            return self._client().probe_disk(drive, folder, progress)

    def open_disk(
        self,
        drive: str,
        format_id: str,
        step: int,
        progress: Progress | None = None,
    ) -> ImageSession:
        """Read the whole disk into a new pane session."""
        layout = floppy_layout(format_id)
        with tempfile.TemporaryDirectory(prefix="acorn-drive-read-") as folder:
            capture = Path(folder) / f"floppy-drive-{drive.lower()}{layout.suffix}"
            result = self._client().read(capture, drive, progress, disk_format=layout, step=step)
            if result.sectors_found == 0:
                raise GreaseweazleError(
                    f"No {layout.label} sectors could be read. Check the format, or format the disk."
                )
            session = self.disks.create_from_path(capture)
        session.name = f"Drive {drive} ({layout.label}){layout.suffix}"
        bind(session, drive, layout, step, result.missing_sectors)
        session.dirty = False
        if result.missing_sectors:
            session.warnings.append(
                f"{result.missing_sectors} of {result.sectors_total} sectors could not be read "
                "and are filled with zeros. Writing back would make them permanent."
            )
        self.disks._persist_session(session)
        return session

    def format_disk(
        self,
        drive: str,
        format_id: str,
        step: int,
        title: str,
        progress: Progress | None = None,
    ) -> ImageSession:
        """Write a blank filesystem to the disk and open it as a pane.

        This is the only path that writes without a separate write click,
        and it runs only after the user confirms formatting.
        """
        layout = floppy_layout(format_id)
        session = create_blank_layout(self.disks, layout, title)
        self._client().write(session.path, drive, progress, disk_format=layout, step=step)
        session.name = f"Drive {drive} ({layout.label}){layout.suffix}"
        bind(session, drive, layout, step)
        session.dirty = False
        self.disks._persist_session(session)
        return session

    def write_disk(self, session: ImageSession, image: Path, progress: Progress | None = None) -> dict:
        """Write a finalised snapshot of the pane to its bound disk and verify it."""
        binding = session.physical_drive
        if not binding:
            raise DiskError("This pane is not attached to a floppy drive.")
        layout = DISK_FORMATS[binding["format"]]
        if image.stat().st_size > layout.size:
            raise DiskError(f"The image has grown beyond a {layout.label} disk and cannot be written.")
        result = self._client().write(
            image, binding["drive"], progress, disk_format=layout, step=binding["step"]
        )
        bind(session, binding["drive"], layout, binding["step"])
        self.disks._persist_session(session)
        return {"verified": result.verified, "tracksWritten": result.tracks_written}

