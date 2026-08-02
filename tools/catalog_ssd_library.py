#!/usr/bin/env python3
"""Catalogue a publisher-organised SSD library using Acorn File Forge itself."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

from app.disk_service import DiskService, ImageSession
from app.menu_interpreter import decode_basic


def display_publisher(folder: str) -> str:
    """Uppercase the first character of each word without destroying acronyms."""
    return " ".join(word[:1].upper() + word[1:] for word in folder.split())


def basic_text(data: bytes) -> str:
    lines = decode_basic(data)
    return "\n".join(line.text for line in lines) if lines else ""


def ssdmenu_games(text: str) -> list[dict]:
    games = []
    for title, filename, page, action in re.findall(
        r'\bDATA\s*"([^"]+)"\s*,\s*"([^"]*)"\s*,\s*&?([0-9A-F]+)\s*,\s*"([^"]*)"',
        text,
        re.IGNORECASE,
    ):
        if title.strip().upper() == "FINISH":
            continue
        games.append(
            {
                "title": re.sub(r"-(?:E00|1900|1D00)$", "", title.strip(), flags=re.I),
                "internalFile": filename.strip(),
                "internalPage": page.upper(),
                "internalAction": action.strip().upper(),
            }
        )
    return games


def haven_games(text: str) -> list[dict]:
    match = re.search(
        r"REM\s+Game Data\s*\n(.*?)(?:\nREM\s+(?:Documentation|Reviews|Solutions) Data|\Z)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return []
    rows = []
    for line in match.group(1).splitlines():
        data = re.match(r"\s*DATA\s+(.+?)\s*,\s*(\$?\.[^,\s]+)\s*$", line, re.I)
        if data and not data.group(1).strip().isdigit():
            rows.append(
                {
                    "title": data.group(1).strip().strip('"'),
                    "internalFile": data.group(2).strip().strip('"'),
                }
            )
    return rows


def catalogue(source: Path) -> list[dict]:
    service = DiskService("/tmp/acorn-catalog-work")
    rows = []
    publishers = sorted((path for path in source.iterdir() if path.is_dir()), key=lambda path: path.name.casefold())
    slot = 3
    for publisher_dir in publishers:
        for image in sorted(publisher_dir.glob("*.[sS][sS][dD]"), key=lambda path: path.name.casefold()):
            with tempfile.TemporaryDirectory(prefix="aff-ssd-") as temporary:
                exported = Path(temporary)
                try:
                    subprocess.run(
                        ["disc", "export", "--meta-format", "none", str(image), str(exported)],
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                    )
                    root = exported / "$"
                    files = {
                        path.name: path.read_bytes()
                        for path in root.iterdir()
                        if path.is_file()
                    } if root.is_dir() else {}
                except subprocess.CalledProcessError:
                    session = ImageSession("0" * 32, image.name, "dfs", image)
                    listing = service.list_directory(session, "$", None)
                    files = {
                        str(entry["name"]): service.read_file(
                            session,
                            None,
                            f'$.{entry["name"]}',
                        )
                        for entry in listing["entries"]
                        if entry.get("type") not in {"dir", "directory"}
                    }
            program_text = {name: basic_text(data) for name, data in files.items()}
            ssdmenu_name = next((name for name in program_text if name.upper() == "SSDMENU"), "")
            haven_name = next((name for name in program_text if name.upper() == "HAVEN"), "")
            boot_name = next((name for name in files if name.upper() == "!BOOT"), "")
            boot = files.get(boot_name, b"")
            if ssdmenu_name:
                chosen = ("CHAIN", ssdmenu_name)
            elif boot_name and boot:
                chosen = ("EXEC", boot_name)
            else:
                chosen = ("", "")
            games = ssdmenu_games(program_text.get(ssdmenu_name, ""))
            source_kind = "SSDMENU" if games else ""
            if not games:
                games = haven_games(program_text.get(haven_name, ""))
                source_kind = "HAVEN" if games else ""
            rows.append(
                {
                    "slot": slot,
                    "publisher": display_publisher(publisher_dir.name),
                    "source": str(image),
                    "sourceName": image.name,
                    "diskTitle": service._dfs_title(image.read_bytes()) or image.stem,
                    "launcher": {
                        "action": chosen[0],
                        "filename": chosen[1],
                    },
                    "boot": boot.decode("latin-1", "replace"),
                    "gamesSource": source_kind,
                    "games": games,
                    "catalogue": [
                        {"name": name, "length": len(data)}
                        for name, data in sorted(files.items(), key=lambda item: item[0].casefold())
                    ],
                }
            )
            slot += 1
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rows = catalogue(args.source)
    output = json.dumps(rows, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
