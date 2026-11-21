"""Identify the Acorn format of a disk from a short flux probe.

A probe reads cylinders 0 and 2 of both heads as raw flux once, then decodes
that capture offline against each Acorn encoding. FM with ten 256-byte
sectors is DFS, MFM with sixteen 256-byte sectors is old-map ADFS, and MFM
with 1024-byte sectors is ADFS D/E (five per track) or F (ten, high density).
Track 0 then holds the catalogue or map that says how many tracks and sides
the disk uses. Cylinder 2 shows whether a 40-track disk sits in an 80-track
drive: its sector headers then say cylinder 1.

The decisions are pure functions of ``gw`` output and decoded bytes, so they
are tested without hardware.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from .formats import (
    DISK_FORMATS,
    DiskFormat,
    adfs_old_map_sectors,
    dfs_format,
    dfs_sector_count,
)

PROBE_TRACKS = "c=0,2:h=0-1"

# Each candidate encoding, the 80-cylinder gw definition that decodes it and
# the size of one track in the decoded image.
@dataclass(frozen=True)
class Encoding:
    key: str
    gw_format: str
    track_bytes: int
    label: str


ENCODINGS = (
    Encoding("dfs", "acorn.dfs.ds80", 10 * 256, "FM, ten 256-byte sectors (DFS)"),
    Encoding("adfs-old", "acorn.adfs.640", 16 * 256, "MFM, sixteen 256-byte sectors (ADFS S/M/L)"),
    Encoding("adfs-800", "acorn.adfs.800", 5 * 1024, "MFM, five 1024-byte sectors (ADFS D/E)"),
    Encoding("adfs-1600", "acorn.adfs.1600", 10 * 1024, "MFM high density, ten 1024-byte sectors (ADFS F)"),
)

_TRACK_RESULT = re.compile(r"^T(\d+)\.(\d+):.*\((\d+)/(\d+) sectors\)")
_UNEXPECTED = re.compile(r"^T(\d+)\.(\d+):.*unexpected sector C:(\d+)", re.I)
_SECTOR_TOTAL = re.compile(r"Found (\d+) sectors of (\d+)")


@dataclass(frozen=True)
class TrackDecode:
    """What one encoding found on the probed tracks."""

    good: dict[tuple[int, int], tuple[int, int]] = field(default_factory=dict)
    foreign_cylinders: dict[tuple[int, int], frozenset[int]] = field(default_factory=dict)

    def complete(self, cylinder: int, head: int) -> bool:
        found, total = self.good.get((cylinder, head), (0, 0))
        return total > 0 and found == total

    def sectors_found(self) -> int:
        return sum(found for found, _total in self.good.values())

    def headers_seen(self) -> bool:
        """True when any sector header was seen, even a non-matching one."""
        return self.sectors_found() > 0 or any(self.foreign_cylinders.values())


def parse_decode(output: str | list[str]) -> TrackDecode:
    """Collect the per-track sector results a gw read or convert printed."""
    lines = output.splitlines() if isinstance(output, str) else output
    good: dict[tuple[int, int], tuple[int, int]] = {}
    foreign: dict[tuple[int, int], set[int]] = {}
    for line in lines:
        text = line.strip()
        match = _TRACK_RESULT.match(text)
        if match:
            cylinder, head, found, total = map(int, match.groups())
            good[(cylinder, head)] = (found, total)
            continue
        match = _UNEXPECTED.match(text)
        if match:
            cylinder, head, header = map(int, match.groups())
            foreign.setdefault((cylinder, head), set()).add(header)
    return TrackDecode(good, {key: frozenset(value) for key, value in foreign.items()})


def parse_sector_total(output: str | list[str]) -> tuple[int, int] | None:
    """Return gw's final "Found N sectors of M" tally, when it printed one."""
    lines = output.splitlines() if isinstance(output, str) else output
    for line in reversed(lines):
        match = _SECTOR_TOTAL.search(line)
        if match:
            return int(match.group(1)), int(match.group(2))
    return None


@dataclass(frozen=True)
class Detection:
    """The outcome of probing one disk.

    ``status`` is ``formatted`` when one layout was identified,
    ``unrecognised`` when sectors exist but the layout is ambiguous or not
    Acorn, and ``unformatted`` when no sector header was found at all.
    """

    status: str
    disk_format: DiskFormat | None
    step: int | None
    detail: str
    candidates: tuple[str, ...] = ()
    encoding: str | None = None

    def public(self) -> dict:
        return {
            "status": self.status,
            "format": self.disk_format.public() if self.disk_format else None,
            "step": self.step,
            "detail": self.detail,
            "candidates": list(self.candidates),
            "encoding": self.encoding,
        }


def double_step_needed(decode: TrackDecode) -> bool | None:
    """Say whether physical cylinder 2 held the disk's cylinder 1.

    ``None`` means cylinder 2 gave no evidence either way.
    """
    if decode.complete(2, 0):
        return False
    if 1 in decode.foreign_cylinders.get((2, 0), frozenset()):
        return True
    return None


def classify(
    decodes: dict[str, TrackDecode],
    track_zero: dict[str, tuple[bytes, bytes]],
) -> Detection:
    """Choose a layout from each encoding's decode of the probe.

    ``track_zero`` maps an encoding key to the decoded bytes of cylinder 0,
    head 0 and head 1.
    """
    matches = [item for item in ENCODINGS if decodes.get(item.key, TrackDecode()).complete(0, 0)]
    if not matches:
        if any(item.headers_seen() for item in decodes.values()):
            return Detection(
                "unrecognised",
                None,
                None,
                "Sectors were found, but track 0 does not match any Acorn floppy layout.",
                tuple(DISK_FORMATS),
            )
        return Detection(
            "unformatted",
            None,
            None,
            "No sector headers were found. The disk appears to be blank or unformatted.",
        )
    encoding = matches[0]
    decode = decodes[encoding.key]
    head0, head1 = track_zero.get(encoding.key, (b"", b""))
    double_sided = decode.complete(0, 1)

    if encoding.key == "dfs":
        found = dfs_format(dfs_sector_count(head0), double_sided)
        side = "double" if double_sided else "single"
        if found is None:
            return _unrecognised(
                encoding,
                "The disk is DFS-encoded but its catalogue does not give a track count.",
                (f"dfs-40{'-ds' if double_sided else ''}", f"dfs-80{'-ds' if double_sided else ''}"),
            )
        detail = f"DFS catalogue on track 0 reports a {found.cylinders}-track, {side}-sided disk."
    elif encoding.key == "adfs-old":
        sectors = adfs_old_map_sectors(head0)
        by_size = {640: "adfs-s", 1280: "adfs-m", 2560: "adfs-l"}
        identifier = by_size.get(sectors or 0) or ("adfs-l" if double_sided else None)
        if identifier is None:
            return _unrecognised(
                encoding,
                "The disk is old-map ADFS encoded but its free-space map does not give a size.",
                ("adfs-s", "adfs-m", "adfs-l"),
            )
        found = DISK_FORMATS[identifier]
        detail = f"ADFS free-space map reports {found.label}."
    else:
        found = DISK_FORMATS[encoding.key]
        detail = f"Track 0 holds {encoding.label}."

    step = 1
    if found.forty_track:
        needed = double_step_needed(decode)
        # Most Greaseweazle setups use an 80-track drive, so a 40-track disk
        # without cylinder-2 evidence is assumed to need double stepping.
        step = 1 if needed is False else 2
        detail += (
            " The drive is double-stepping this 40-track disk."
            if step == 2
            else " The drive reads this 40-track disk at single step."
        )
    return Detection("formatted", found, step, detail, (found.identifier,), encoding.key)


def _unrecognised(encoding: Encoding, detail: str, candidates: tuple[str, ...]) -> Detection:
    return Detection("unrecognised", None, None, detail, candidates, encoding.key)


def track_zero_bytes(image: bytes, encoding: Encoding) -> tuple[bytes, bytes]:
    """Split cylinder 0 of a decoded, track-interleaved image into its heads."""
    size = encoding.track_bytes
    return image[:size], image[size:2 * size]
