from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.image_diff import compare_images, compare_manifests, manifest_fingerprint, record_key


def manifest(name: str, kind: str, records: list[dict]) -> dict:
    return {"image": {"id": name, "name": name, "kind": kind}, "records": records, "menus": []}


class ImageDiffTests(unittest.TestCase):
    def test_record_keys_include_slot_side_and_bank_context(self) -> None:
        self.assertEqual(record_key({"recordType": "slot", "slot": 12}), "slot:12")
        self.assertEqual(
            record_key({"recordType": "file", "slot": 12, "path": "$.Game"}),
            "slot:12:file:$.game",
        )
        self.assertEqual(
            record_key({"recordType": "file", "side": 2, "path": "$.Game"}),
            "side:2:file:$.game",
        )
        self.assertEqual(
            record_key({"recordType": "rom-bank", "bank": 3, "path": "bank:3"}),
            "bank:3:rom-bank:bank:3",
        )

    def test_fingerprint_ignores_record_order_and_session_identity(self) -> None:
        records = [
            {"recordType": "file", "path": "$.A", "sha256": "a", "size": 1},
            {"recordType": "file", "path": "$.B", "sha256": "b", "size": 2},
        ]
        first = manifest("first", "adfs", records)
        second = manifest("second", "adfs", list(reversed(records)))
        self.assertEqual(manifest_fingerprint(first), manifest_fingerprint(second))

    def test_compare_classifies_content_and_metadata_changes(self) -> None:
        base = manifest("old", "dfs", [
            {"recordType": "file", "path": "$.SAME", "sha256": "1", "size": 10, "load": "1900"},
            {"recordType": "file", "path": "$.CONTENT", "sha256": "2", "size": 20},
            {"recordType": "file", "path": "$.META", "sha256": "3", "size": 30, "execute": "1900"},
            {"recordType": "file", "path": "$.REMOVED", "sha256": "4", "size": 40},
        ])
        candidate = manifest("new", "dfs", [
            {"recordType": "file", "path": "$.SAME", "sha256": "1", "size": 10, "load": "1900"},
            {"recordType": "file", "path": "$.CONTENT", "sha256": "changed", "size": 20},
            {"recordType": "file", "path": "$.META", "sha256": "3", "size": 30, "execute": "1D00"},
            {"recordType": "file", "path": "$.ADDED", "sha256": "5", "size": 50},
        ])

        report = compare_manifests(base, candidate)

        self.assertEqual(report["summary"], {
            "added": 1, "removed": 1, "modified": 1, "metadata": 1, "total": 4,
        })
        self.assertEqual(report["changes"]["modified"][0]["changedFields"], ["sha256"])
        self.assertEqual(report["changes"]["metadata"][0]["changedFields"], ["execute"])
        self.assertTrue(report["sameFormat"])

    def test_directory_allocation_changes_are_derived_not_logical_changes(self) -> None:
        base = manifest("old", "adfs", [
            {"recordType": "directory", "path": "$.Games", "size": 2048, "fileCount": 1, "attributes": "WR/"},
        ])
        candidate = manifest("new", "adfs", [
            {"recordType": "directory", "path": "$.Games", "size": 4096, "fileCount": 12, "attributes": "WR/"},
        ])
        self.assertEqual(compare_manifests(base, candidate)["summary"]["total"], 0)
        self.assertEqual(manifest_fingerprint(base), manifest_fingerprint(candidate))

    def test_image_comparison_reports_each_catalogue_phase(self) -> None:
        base = manifest("old", "dfs", [])
        candidate = manifest("new", "dfs", [])
        updates = []
        sessions = [
            SimpleNamespace(kind="dfs", name="old.ssd"),
            SimpleNamespace(kind="dfs", name="new.ssd"),
        ]

        with patch("app.image_diff.build_manifest", side_effect=[base, candidate]) as builder:
            report = compare_images(None, *sessions, lambda *values: updates.append(values))

        self.assertEqual(report["summary"]["total"], 0)
        self.assertEqual(builder.call_count, 2)
        self.assertTrue(all(call.args[2] is not None for call in builder.call_args_list))
        self.assertEqual(updates[-1], ("Comparing logical contents and metadata", 2, 2))


if __name__ == "__main__":
    unittest.main()
