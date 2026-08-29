"""Shared policy for the flux containers HxCFE can decode and re-encode.

HFE and SCP are different files but the same workflow: decode the flux to raw
sectors, identify the Acorn filesystem inside, prove the sectors re-encode and
decode back byte-for-byte before permitting any edit, and prove it again before
handing the user a saved image.

That policy lived twice in ``disk_service``, once per container, and the two
copies had already drifted: only the HFE save path restored an omitted tail
sector, so saving an edited ADFS-L SCP failed its own verification. Expressing
the rules once here means a container cannot quietly miss a fix made for its
sibling, and lets the geometry rules be unit tested without an HxCFE binary.

Nothing in this module runs a subprocess itself. ``FluxEngine`` is handed the
caller's ``run_hxcfe`` so the disk service keeps ownership of process
execution, error translation and timeouts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .errors import DiskError


SECTOR_SIZE = 256

# The raw sector sizes Acorn floppy geometries produce. A decode is only ever
# padded up to one of these, and only ever by a single trailing sector.
CANONICAL_SIZES: dict[str, frozenset[int]] = {
    "dfs": frozenset({102_400, 204_800, 409_600}),
    "adfs": frozenset({163_840, 327_680, 655_360}),
}

# Filesystems the workbench can browse inside a flux container.
BROWSEABLE_KINDS = frozenset({"dfs", "adfs"})

# HxCFE's raw sector reader, used to decode every container back to sectors.
RAW_DECODER = "RAW_LOADER"

# HxCFE needs an explicit blank-disk layout to encode ADFS S/M/L geometries.
# DFS geometries are inferred correctly from the sector image alone.
_ADFS_FLUX_LAYOUTS = {
    163_840: "ACORN_ADFS_160K",
    327_680: "ACORN_ADFM_320K",
    655_360: "ACORN_ADFL_640K",
}

# Sector-image extensions by decoded geometry.
_ADFS_SECTOR_SUFFIXES = {163_840: ".ads", 327_680: ".adm", 655_360: ".adl"}

# A DFS image larger than one MMB slot must be the double-sided interleave.
_MAX_SINGLE_SIDED_DFS = 204_800


@dataclass(frozen=True)
class FluxContainer:
    """One HxCFE-supported flux container and the words used to describe it."""

    identifier: str
    extension: str
    label: str
    plugin: str
    noun: str
    signature: bytes | None = None

    @property
    def display(self) -> str:
        return self.identifier.upper()


HFE = FluxContainer(
    identifier="hfe",
    extension=".hfe",
    label="HxC HFE flux image (.hfe)",
    plugin="HXC_HFE",
    noun="HFE image",
)

SCP = FluxContainer(
    identifier="scp",
    extension=".scp",
    label="SuperCard Pro flux image (.scp)",
    plugin="SCP_FLUX_STREAM",
    noun="SCP flux capture",
    signature=b"SCP",
)

FLUX_CONTAINERS: dict[str, FluxContainer] = {
    container.identifier: container for container in (HFE, SCP)
}


def sector_image_suffix(kind: str, size: int, sides: int = 1) -> str:
    """Return the canonical sector-image extension for a decoded geometry."""
    if kind == "dfs":
        return ".dsd" if sides == 2 or size > _MAX_SINGLE_SIDED_DFS else ".ssd"
    return _ADFS_SECTOR_SUFFIXES.get(size, ".adf")


def flux_layout_for(kind: str, size: int) -> str | None:
    """Return HxCFE's blank-disk layout hint, or None when it is not needed."""
    if kind != "adfs":
        return None
    return _ADFS_FLUX_LAYOUTS.get(size)


def is_flux_encodable(kind: str, size: int) -> bool:
    """Whether these sectors can be wrapped as flux by HxCFE.

    Any DFS geometry encodes without a layout hint. ADFS encodes only for the
    S, M and L floppy geometries that have a known blank layout; D, E, F and
    hard-disc images have no flux equivalent HxCFE can build.
    """
    return kind == "dfs" or flux_layout_for(kind, size) is not None


def restore_omitted_tail_sector(
    path: Path,
    kind: str,
    expected_size: int | None = None,
) -> bool:
    """Restore one omitted trailing sector from an otherwise complete decode.

    HxCFE's raw writer can omit an unreadable final 256-byte sector while still
    reporting every sector on the final track. An ADFS-L decode then arrives as
    655,104 bytes instead of 655,360 and geometry detection can select a linear
    hard-disc view instead of a floppy.

    Padding is only ever safe at the physical end of a known geometry, so this
    refuses to act unless the file is exactly one sector short of a canonical
    size for ``kind``. It never fills a gap in the middle of an image, and never
    grows a file by more than a single sector.

    Returns True when a sector was appended.
    """
    if not path.is_file():
        return False
    canonical_sizes = CANONICAL_SIZES.get(kind, frozenset())
    if not canonical_sizes:
        return False
    size = path.stat().st_size
    target = expected_size if expected_size in canonical_sizes else None
    if target is None:
        target = next(
            (value for value in canonical_sizes if size + SECTOR_SIZE == value),
            None,
        )
    if target is None or size + SECTOR_SIZE != target:
        return False
    with path.open("ab") as image:
        image.write(bytes(SECTOR_SIZE))
    return True


class FluxEngine:
    """The four HxCFE conversions the workbench needs, in one vocabulary.

    The engine is constructed with the caller's ``run_hxcfe`` callable, which
    takes a list of HxCFE arguments and returns its combined output. Errors are
    raised by that callable as ``DiskError``.
    """

    def __init__(self, run_hxcfe: Callable[[list[str]], str]) -> None:
        self._run_hxcfe = run_hxcfe

    def decode_to_sectors(self, source: Path, output: Path) -> str:
        """Decode any flux container to a raw sector image."""
        return self._run_hxcfe([
            f"-finput:{source}",
            f"-conv:{RAW_DECODER}",
            f"-foutput:{output}",
        ])

    def container_info(self, source: Path) -> str:
        """Return HxCFE's descriptive report for a container."""
        return self._run_hxcfe([f"-finput:{source}", "-infos"])

    def encode_from_sectors(
        self,
        sectors: Path,
        container: FluxContainer,
        output: Path,
        *,
        kind: str,
        reference: Path | None = None,
    ) -> str:
        """Wrap a raw sector image as flux, reusing an original's timing.

        ``reference`` is the container the sectors were decoded from. HxCFE
        uses it to preserve track timing that the sector view cannot express,
        so an edited image stays as close to the capture as possible.
        """
        layout = flux_layout_for(kind, sectors.stat().st_size)
        return self._run_hxcfe([
            f"-finput:{sectors}",
            *([f"-uselayout:{layout}"] if layout else []),
            f"-conv:{container.plugin}",
            f"-foutput:{output}",
            *([f"-reffile:{reference}"] if reference else []),
        ])

    def decodes_back_to(self, container_file: Path, sectors: Path, kind: str) -> bool:
        """Whether a container decodes back to exactly these sectors.

        The decode is normalised for a single omitted tail sector first, using
        the source image's size as the expected geometry, so a container is not
        rejected for the one artefact the workbench knows how to repair.
        """
        check = container_file.parent / f"{container_file.stem}-verify.img"
        check.unlink(missing_ok=True)
        try:
            self.decode_to_sectors(container_file, check)
            restore_omitted_tail_sector(
                check,
                kind,
                expected_size=sectors.stat().st_size,
            )
            return check.is_file() and check.read_bytes() == sectors.read_bytes()
        except DiskError:
            return False
        finally:
            check.unlink(missing_ok=True)

    def encode_and_verify(
        self,
        sectors: Path,
        container: FluxContainer,
        output: Path,
        *,
        kind: str,
        reference: Path | None = None,
        failure_message: str,
    ) -> Path:
        """Encode sectors as flux and refuse to return an inexact container.

        A flux image the workbench cannot decode back to the bytes it started
        from is never handed to the user: it would look like a saved disk while
        silently differing from what they edited.
        """
        output.unlink(missing_ok=True)
        self.encode_from_sectors(
            sectors,
            container,
            output,
            kind=kind,
            reference=reference,
        )
        if not output.is_file() or not output.stat().st_size:
            raise DiskError(
                f"HxCFE did not produce a usable {container.display} image."
            )
        if not self.decodes_back_to(output, sectors, kind):
            output.unlink(missing_ok=True)
            raise DiskError(failure_message)
        return output


__all__ = [
    "BROWSEABLE_KINDS",
    "CANONICAL_SIZES",
    "FLUX_CONTAINERS",
    "HFE",
    "SCP",
    "SECTOR_SIZE",
    "FluxContainer",
    "FluxEngine",
    "flux_layout_for",
    "is_flux_encodable",
    "restore_omitted_tail_sector",
    "sector_image_suffix",
]
