#!/usr/bin/env python3
"""Decode BASIC programs from SSDs unresolved by catalog_ssd_library.py."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from app.menu_interpreter import decode_basic


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("catalogue", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    catalogue = json.loads(args.catalogue.read_text(encoding="utf-8"))
    results = []
    for item in catalogue:
        if item.get("games"):
            continue
        image = Path(item["source"])
        programs = {}
        with tempfile.TemporaryDirectory(prefix="aff-menu-") as temporary:
            exported = Path(temporary)
            result = subprocess.run(
                ["disc", "export", "--meta-format", "none", str(image), str(exported)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            root = exported / "$"
            if result.returncode == 0 and root.is_dir():
                for path in root.iterdir():
                    if not path.is_file():
                        continue
                    lines = decode_basic(path.read_bytes())
                    if lines:
                        programs[path.name] = "\n".join(line.text for line in lines)
        results.append(
            {
                "slot": item["slot"],
                "publisher": item["publisher"],
                "sourceName": item["sourceName"],
                "diskTitle": item["diskTitle"],
                "boot": item["boot"],
                "programs": programs,
            }
        )
    args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
