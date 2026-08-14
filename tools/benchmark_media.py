#!/usr/bin/env python3
"""Repeatable generated-image performance benchmarks for release checks."""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path

from app.disk_service import DiskService
from app.download_archive import build_download_archive
from app.menu.adfs import create_adfs_menu


def measure(name: str, callback, repeats: int = 3) -> dict:
    timings = []
    for _attempt in range(repeats):
        started = time.perf_counter()
        callback()
        timings.append(time.perf_counter() - started)
    return {
        "name": name,
        "runs": repeats,
        "minimumSeconds": min(timings),
        "medianSeconds": statistics.median(timings),
        "maximumSeconds": max(timings),
    }


def run(profile: str = "quick") -> dict:
    repeats = 2 if profile == "quick" else 5
    file_count = 20 if profile == "quick" else 100
    with tempfile.TemporaryDirectory(prefix="acorn-forge-benchmark-") as folder:
        root = Path(folder)
        service = DiskService(root / "work")
        mmb = service.create_blank("mmb", "BENCHMARK")
        ssd = service.create_blank("ssd", "BENCH")
        adfs = service.create_blank("adfs-hard", "BENCH", "20MB")
        beebscsi = service.create_blank("beebscsi", "BENCHSCSI", "20MB", "beebscsi-bbc")
        files = []
        for number in range(file_count):
            path = root / f"FILE{number:04d}"
            path.write_bytes((f"generated-{number}\r".encode("ascii")) * 16)
            group = number // 40 + 1
            files.append({"targetPath": f"PACK{group}/FILE{number:04d}", "hostPath": path})
        for number in range(min(20, file_count)):
            service.put(ssd, None, f"$.F{number:02d}", Path(files[number]["hostPath"]), "0x1900", "0x1900", None)
        service.put_host_tree(adfs, None, "$", files, preserve_directories=True)
        service.make_directory(beebscsi, "$.GAMES")
        service.make_directory(adfs, "$.MENU")
        menu_entries = [
            {
                "title": f"Generated title {number + 1}",
                "publisher": "Acorn File Forge",
                "diskTitle": "BENCH",
                "filename": "FILE0000",
                "directory": f"$.PACK{number // 40 + 1}",
                "action": "CHAIN",
                "page": "1900",
            }
            for number in range(file_count)
        ]
        template_dir = Path(__file__).resolve().parents[1] / "app" / "assets" / "menu_templates"
        create_adfs_menu(service, adfs, "$.MENU", menu_entries, template_dir)

        results = [
            measure("mmb-list-511-slots", lambda: service.list_slots(mmb), repeats),
            measure("dfs-list-20-files", lambda: service.browse_directory(ssd, "$", None), repeats),
            measure("adfs-list-generated-tree", lambda: service.browse_directory(adfs, "$.PACK1", None), repeats),
            measure(
                f"adfs-bulk-import-{file_count}-files",
                lambda: _bulk_adfs_import(service, files),
                repeats,
            ),
            measure(
                f"adfs-menu-rebuild-{file_count}-entries",
                lambda: create_adfs_menu(service, adfs, "$.MENU", menu_entries, template_dir),
                repeats,
            ),
            measure("beebscsi-root-list", lambda: service.browse_directory(beebscsi, "$", None), repeats),
            measure("beebscsi-checkpoint", lambda: _checkpoint_round_trip(service, beebscsi), repeats),
            measure(
                "beebscsi-save-archive",
                lambda: build_download_archive(service, beebscsi),
                1 if profile == "quick" else 2,
            ),
        ]
        return {
            "schema": 1,
            "profile": profile,
            "generatedFiles": file_count,
            "benchmarks": results,
        }


def _checkpoint_round_trip(service: DiskService, session) -> None:
    token = service.begin_automatic_checkpoint(session, "benchmark")
    service.finish_automatic_checkpoint(session, token)


def _bulk_adfs_import(service: DiskService, files: list[dict]) -> None:
    target = service.create_blank("adfs-hard", "IMPORT", "20MB")
    try:
        service.put_host_tree(target, None, "$", files, preserve_directories=True)
    finally:
        service.discard_session(target)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("quick", "full"), default="quick")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    result = run(arguments.profile)
    rendered = json.dumps(result, indent=2)
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
