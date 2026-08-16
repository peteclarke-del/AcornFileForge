from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.errors import DiskError
from app.image_diff import manifest_fingerprint
from app.image_patch import PATCH_FORMAT, _catalogue_address, apply_patch_archive, write_patch_archive


def manifest(identity: str, records: list[dict]) -> dict:
    return {
        "image": {"id": identity, "name": f"{identity}.ssd", "kind": "dfs"},
        "records": records,
        "menus": [],
    }


class PatchService:
    def __init__(self, work_dir: Path):
        self.work_dir = work_dir

    @staticmethod
    def read_file(_session, _slot, path, _side):
        return {"$.NEW": b"new bytes", "$.CHANGED": b"changed bytes"}[path]


class ImagePatchTests(unittest.TestCase):
    def test_numeric_manifest_addresses_are_rendered_as_hexadecimal(self) -> None:
        self.assertEqual(_catalogue_address(1900), "76C")
        self.assertEqual(_catalogue_address("00001900"), "00001900")

    def test_patch_archive_embeds_only_added_and_changed_payloads(self) -> None:
        base = manifest("base", [
            {"recordType": "file", "path": "$.CHANGED", "size": 3, "sha256": "old"},
            {"recordType": "file", "path": "$.REMOVED", "size": 4, "sha256": "gone"},
        ])
        candidate = manifest("candidate", [
            {"recordType": "file", "path": "$.CHANGED", "size": 13, "sha256": "changed"},
            {"recordType": "file", "path": "$.NEW", "size": 9, "sha256": "new"},
        ])
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "change.affpatch.zip"
            service = PatchService(Path(folder))
            sessions = [SimpleNamespace(kind="dfs"), SimpleNamespace(kind="dfs")]
            with patch("app.image_patch.build_manifest", side_effect=[base, candidate]):
                document = write_patch_archive(service, *sessions, destination)
            self.assertEqual(document["format"], PATCH_FORMAT)
            self.assertEqual(document["summary"]["total"], 3)
            with zipfile.ZipFile(destination) as archive:
                self.assertEqual(
                    sorted(name for name in archive.namelist() if name.startswith("payloads/")),
                    ["payloads/00000000.bin", "payloads/00000001.bin"],
                )
                stored = json.loads(archive.read("patch.json"))
                self.assertEqual(len(stored["operations"]), 3)
                self.assertEqual(stored["candidateRecords"], candidate["records"])
                self.assertEqual(stored["layout"], {"kind": "dfs", "doubleSided": False})

    def test_wrong_base_fingerprint_is_rejected_before_mutation(self) -> None:
        current = manifest("current", [{"recordType": "file", "path": "$.A", "sha256": "a", "size": 1}])
        document = {
            "format": PATCH_FORMAT,
            "version": 1,
            "kind": "dfs",
            "baseFingerprint": "0" * 64,
            "candidateFingerprint": manifest_fingerprint(current),
            "operations": [],
        }
        with tempfile.TemporaryDirectory() as folder:
            archive_path = Path(folder) / "wrong.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("patch.json", json.dumps(document))
            service = PatchService(Path(folder))
            with patch("app.image_patch.build_manifest", return_value=current):
                with self.assertRaisesRegex(DiskError, "exact base revision"):
                    apply_patch_archive(service, SimpleNamespace(kind="dfs"), archive_path)

    def test_patch_creation_rejects_different_dfs_side_layouts(self) -> None:
        base = manifest("base", [])
        candidate = manifest("candidate", [])
        base["image"]["doubleSided"] = False
        candidate["image"]["doubleSided"] = True
        with tempfile.TemporaryDirectory() as folder:
            with patch("app.image_patch.build_manifest", side_effect=[base, candidate]):
                with self.assertRaisesRegex(DiskError, "matching DFS side layouts"):
                    write_patch_archive(
                        PatchService(Path(folder)),
                        SimpleNamespace(kind="dfs"),
                        SimpleNamespace(kind="dfs"),
                        Path(folder) / "wrong-layout.zip",
                    )


if __name__ == "__main__":
    unittest.main()
