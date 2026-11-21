#!/usr/bin/env python3
"""Stand in for a Greaseweazle drive by delegating to the real ``gw convert``.

``read`` decodes the flux file named by ``FAKE_GW_DISK`` as though it were
the disk in the drive, inserting a blank, unformatted disk first if there is
none; ``write`` encodes the image onto that same flux file,
so a later read sees what was written. ``FAKE_GW_REAL`` names the real gw.
Only the integration tests use this, and only when a working gw exists.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def _blank_disk(real: str, disk: Path) -> None:
    """Insert a never-formatted disk: flux with no sector headers on it."""
    zeros = disk.with_suffix(".zeros.img")
    zeros.write_bytes(bytes(1 << 20))
    subprocess.run(
        [real, "convert", "--format=raw.250", "--tracks=c=0-2:h=0-1", str(zeros), str(disk)],
        stdout=subprocess.DEVNULL,
        check=True,
    )
    zeros.unlink()


def main(argv: list[str]) -> int:
    real = os.environ["FAKE_GW_REAL"]
    disk = Path(os.environ["FAKE_GW_DISK"])
    if not argv or argv[0] == "info":
        print("Host Tools: fake\nDevice: simulated drive")
        return 0
    verb, rest = argv[0], argv[1:]
    options = [item for item in rest if item.startswith("--") and not item.startswith(("--drive", "--revs"))]
    files = [item for item in rest if not item.startswith("--")]
    if verb == "read":
        if not disk.exists():
            _blank_disk(real, disk)
        command = [real, "convert", *options, str(disk), files[-1]]
    elif verb == "write":
        temporary = disk.with_suffix(".new.scp")
        command = [real, "convert", *options, files[-1], str(temporary)]
    else:
        # File-only commands such as convert need no drive.
        command = [real, *argv]
    result = subprocess.run(command, check=False)
    if verb == "write" and result.returncode == 0:
        temporary.replace(disk)
        print("All tracks verified")
    return result.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
