from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.analysis_service import (
    duplicate_report,
    health_report,
    inspect_file,
    menu_test_report,
    preflight_report,
)
from app.disk_service import DiskError, DiskService, ImageSession, MMB_HEADER_SIZE, MMB_SLOT_SIZE
from app.operations import OperationCancelled


class AnalysisServiceTests(unittest.TestCase):
    def test_preflight_reports_target_truncation_and_collision(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "disk.adl"
            path.write_bytes(b"image")
            session = ImageSession("a" * 32, path.name, "adfs", path)

            report = preflight_report(
                DiskService(folder),
                session,
                {"operation": "copy", "changes": [{"name": "LONG-FILENAME"}, {"name": "LONG-FILENOTE"}]},
            )

            self.assertFalse(report["canProceed"])
            self.assertTrue(any("becomes" in item["message"] for item in report["issues"]))
            self.assertTrue(any("clashes" in item["message"] for item in report["issues"]))

    def test_inspector_decodes_plain_text_loader_commands(self) -> None:
        service = Mock()
        temporary = tempfile.NamedTemporaryFile(delete=False)
        temporary.write(b'*DIR Games\rCHAIN "MENU"\r')
        temporary.close()
        service.export_file.return_value = Path(temporary.name)
        session = Mock()

        try:
            report = inspect_file(service, session, "$.!BOOT", None, None)
        finally:
            Path(temporary.name).unlink(missing_ok=True)

        self.assertEqual(report["view"], "text")
        self.assertTrue(report["editable"])
        self.assertEqual([item["action"] for item in report["commands"]], ["DIR", "CHAIN"])

    def test_duplicate_finder_hashes_identical_mmb_slots(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "twins.mmb"
            header = bytearray(MMB_HEADER_SIZE)
            for slot, title in ((0, b"FIRST       "), (1, b"SECOND      ")):
                header[16 + slot * 16 : 28 + slot * 16] = title
                header[31 + slot * 16] = 0x0F
            path.write_bytes(bytes(header) + bytes(MMB_SLOT_SIZE * 2))
            session = ImageSession("b" * 32, path.name, "mmb", path)

            report = duplicate_report(DiskService(folder), session)

            self.assertEqual(len(report["exact"]), 1)
            self.assertEqual({item["slot"] for item in report["exact"][0]}, {0, 1})

    @patch("app.analysis_service.build_manifest")
    def test_mmb_duplicate_finder_matches_games_across_different_disk_titles(self, manifest) -> None:
        manifest.return_value = {
            "records": [
                {"recordType": "slot", "slot": 10, "diskTitle": "ALPHA DISK", "formatted": True, "sha256": "slot-a", "fileCount": 1},
                {"recordType": "slot", "slot": 20, "diskTitle": "BETA DISK", "formatted": True, "sha256": "slot-b", "fileCount": 1},
                {"recordType": "file", "slot": 10, "diskTitle": "ALPHA DISK", "path": "$.GAME", "size": 4096, "load": "001900", "execute": "001900", "sha256": "game-bytes"},
                {"recordType": "file", "slot": 20, "diskTitle": "BETA DISK", "path": "$.GAME", "size": 4096, "load": "001900", "execute": "001900", "sha256": "game-bytes"},
            ],
            "menus": [{"type": "universal", "entries": [
                {"title": "Repton 2", "publisher": "Superior", "diskTitle": "ALPHA DISK", "filename": "GAME", "action": "", "page": "E00"},
                {"title": "REPTON-2", "publisher": "Superior", "diskTitle": "BETA DISK", "filename": "GAME", "action": "", "page": "E00"},
            ]}],
        }

        report = duplicate_report(Mock(), Mock(kind="mmb"))

        self.assertEqual(len(report["gameDuplicates"]), 1)
        self.assertEqual({item["diskTitle"] for item in report["gameDuplicates"][0]}, {"ALPHA DISK", "BETA DISK"})
        self.assertEqual([[item["slot"] for item in group] for group in report["contentMatches"]], [[10, 20]])

    @patch("app.analysis_service.test_installed_adfs_menu_entries")
    def test_adfs_menu_runner_reports_proven_page_mismatch(self, test_entries) -> None:
        session = Mock(kind="adfs")
        test_entries.return_value = (["$.Games"], [{
            "index": 0, "menuRoot": "$.Games", "title": "Example",
            "diskTitle": "$.Games.Example", "launcher": "!BOOT",
            "action": "EXEC", "page": "1900", "passed": False,
            "problems": ["PAGE should be &E00"],
            "evidence": "!BOOT sets PAGE=&E00",
        }])

        report = menu_test_report(Mock(), session)

        self.assertEqual(report["failed"], 1)
        self.assertEqual(report["menuRoots"], ["$.Games"])
        self.assertIn("PAGE should be &E00", report["tests"][0]["problems"])

    def test_health_check_reports_progress_and_honours_abort(self) -> None:
        service = Mock()
        session = Mock(kind="dfs", descriptor_path=None, tape=None, warnings=[])

        def abort(_message, _current, _total):
            raise OperationCancelled("Stopped safely")

        with self.assertRaises(OperationCancelled):
            health_report(service, session, abort)

    @patch("app.analysis_service.menu_test_report")
    def test_mmb_health_itemises_failed_menu_records(self, menu_report) -> None:
        service = Mock()
        service.list_slots.return_value = [{
            "slot": 42, "name": "BROKEN", "formatted": True,
            "invalid": False, "writable": True,
        }]
        menu_report.return_value = {
            "passed": 0,
            "failed": 1,
            "tests": [{
                "index": 6,
                "menuSlot": 0,
                "menuType": "universal",
                "title": "Example Game",
                "diskTitle": "MISSING",
                "slots": [],
                "launcher": "!BOOT",
                "action": "EXEC",
                "page": "E00",
                "passed": False,
                "problems": ["No formatted slot has the required disk title"],
                "evidence": "disk missing",
            }],
        }
        session = Mock(
            kind="mmb", descriptor_path=None, tape=None, warnings=[],
            hardware_profile=None,
        )

        report = health_report(service, session)

        menu_check = next(item for item in report["checks"] if item["name"] == "Menu records")
        self.assertEqual(menu_check["findings"][0]["record"], 7)
        self.assertEqual(menu_check["findings"][0]["menuSlot"], 0)
        self.assertEqual(menu_check["findings"][0]["title"], "Example Game")
        self.assertIn("required disk title", menu_check["findings"][0]["problems"][0])

    @patch("app.analysis_service.installed_mmb_menus")
    def test_mmb_menu_test_itemises_unreadable_menu_database(self, installed_menus) -> None:
        installed_menus.return_value = [{"slot": 3, "type": "universal"}]
        service = Mock()
        service.list_slots.return_value = []
        service.read_file.side_effect = DiskError("catalogue is truncated")
        session = Mock(kind="mmb")

        report = menu_test_report(service, session)

        self.assertEqual(report["failed"], 1)
        self.assertEqual(report["tests"][0]["menuSlot"], 3)
        self.assertEqual(report["tests"][0]["launcher"], "$.GAMDATA")
        self.assertIn("catalogue is truncated", report["tests"][0]["problems"][0])


if __name__ == "__main__":
    unittest.main()
