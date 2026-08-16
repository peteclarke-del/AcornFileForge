from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.analysis_service import (
    build_manifest,
    dependency_report,
    duplicate_report,
    health_report,
    inspect_file,
    menu_test_report,
    workspace_metadata_records,
    preflight_report,
)
from app.disk_service import DiskError, DiskService, ImageSession, MMB_HEADER_SIZE, MMB_SLOT_SIZE
from app.operations import OperationCancelled


class AnalysisServiceTests(unittest.TestCase):
    @patch("app.analysis_service.parse_mmb_menu_data")
    @patch("app.analysis_service.installed_mmb_menus")
    def test_workspace_metadata_exposes_mmb_menu_publishers_and_launchers(
        self, installed, parse_menu,
    ) -> None:
        installed.return_value = [{"slot": 0, "type": "universal"}]
        parse_menu.return_value = [{
            "title": "Arcadians", "publisher": "Acornsoft",
            "diskTitle": "ARCADIANS", "filename": "SSDMENU",
            "action": "CHAIN", "page": "E00",
        }]
        service = Mock()
        service.list_slots.return_value = [
            {"slot": 20, "formatted": True, "name": "ARCADIANS"},
        ]
        service.read_file.return_value = b"menu"

        records = workspace_metadata_records(service, Mock(kind="mmb", editor_projects={}))

        self.assertEqual(records[0]["slot"], 20)
        self.assertEqual(records[0]["fileName"], "SSDMENU")
        self.assertEqual(records[0]["searchFields"]["publisher"], "Acornsoft")

    def test_workspace_metadata_exposes_rom_symbols_regions_and_editor_comments(self) -> None:
        session = Mock(
            kind="rom",
            name="TOOLS.rom",
            rom_project={
                "identity": {"title": "Development Tools"},
                "symbols": {"32768": "service_entry"},
                "regions": [{"start": "&8000", "end": "&80FF", "name": "Dispatch table"}],
            },
            editor_projects={
                "-|-|bank:0": {
                    "notes": "Reverse engineering notes",
                    "symbols": {"&8010": "command_dispatch"},
                    "comments": {"32": "Command parser"},
                },
            },
        )

        records = workspace_metadata_records(Mock(), session)

        self.assertTrue(any(row.get("resultType") == "rom-symbol" for row in records))
        self.assertTrue(any(row.get("resultType") == "rom-region" for row in records))
        comment = next(row for row in records if row.get("resultType") == "project-comment")
        self.assertEqual(comment["offset"], 32)
        self.assertEqual(comment["fileName"], "bank:0")
        saved_symbol = next(row for row in records if row.get("resultType") == "project-symbol")
        self.assertEqual(saved_symbol["offset"], 0x8010)

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
            self.assertEqual(report["format"], "acorn-file-forge-compatibility-report")
            self.assertEqual(report["version"], 1)
            self.assertEqual(report["items"][0]["sourceName"], "LONG-FILENAME")
            self.assertEqual(report["items"][0]["targetName"], "LONG-FILEN")
            self.assertTrue(any("becomes" in item["message"] for item in report["issues"]))
            self.assertTrue(any("clashes" in item["message"] for item in report["issues"]))
            self.assertIn("# Acorn File Forge compatibility report", report["markdown"])

    def test_preflight_records_per_item_directory_and_filetype_losses(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "disk.ssd"
            path.write_bytes(b"image")
            session = ImageSession("b" * 32, path.name, "dfs", path)

            report = preflight_report(
                DiskService(folder),
                session,
                {
                    "operation": "copy",
                    "sourceKind": "adfs",
                    "targetKind": "dfs",
                    "changes": [{"name": "Games", "type": "directory", "filetype": "FF8"}],
                },
            )

            self.assertFalse(report["canProceed"])
            self.assertEqual(len(report["items"][0]["losses"]), 2)
            self.assertIn("hierarchical directory", report["items"][0]["losses"][0])
            self.assertIn("RISC OS filetype", report["items"][0]["losses"][1])

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

    @patch("app.analysis_service.build_manifest")
    def test_duplicate_finder_forwards_progress_to_manifest_build(self, manifest) -> None:
        manifest.return_value = {"records": [], "menus": []}
        progress = Mock()

        duplicate_report(Mock(), Mock(kind="dfs"), progress)

        self.assertIs(manifest.call_args.args[2], progress)

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

    @patch("app.analysis_service.sha256_path")
    def test_manifest_checksum_does_not_swallow_cancellation(self, checksum) -> None:
        service = Mock()
        service.list_directory.return_value = {
            "entries": [{"name": "GAME", "type": "file", "length": 1}],
        }
        temporary = tempfile.NamedTemporaryFile(delete=False)
        temporary.write(b"x")
        temporary.close()
        service.export_file.return_value = Path(temporary.name)
        session = Mock(kind="adfs")

        def cancel_during_checksum(_path, progress):
            progress(1, 1)

        def progress(message, _current, _total):
            if message.startswith("Checksumming"):
                raise OperationCancelled("Stopped safely")

        checksum.side_effect = cancel_during_checksum
        try:
            with self.assertRaises(OperationCancelled):
                build_manifest(service, session, progress)
        finally:
            Path(temporary.name).unlink(missing_ok=True)

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

    def test_dependency_scan_honours_cancellation_during_catalogue_walk(self) -> None:
        service = Mock()
        temporary = tempfile.NamedTemporaryFile(delete=False)
        temporary.write(b'CHAIN "GAME"\r')
        temporary.close()
        service.export_file.return_value = Path(temporary.name)
        service.list_directory.return_value = {"entries": []}
        session = Mock(kind="adfs")

        def abort(message, _current, _total):
            if message.startswith("Reading directory"):
                raise OperationCancelled("Stopped safely")

        try:
            with self.assertRaises(OperationCancelled):
                dependency_report(service, session, "$.!BOOT", None, None, abort)
        finally:
            Path(temporary.name).unlink(missing_ok=True)

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
