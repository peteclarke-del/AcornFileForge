"""Converting floppy images between DFS and ADFS through the real engine."""

from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

from app.disk_service import DiskError, DiskService
from app.filesystem_conversion import conversion_targets, convert, plan_conversion


@unittest.skipUnless(shutil.which("disc"), "needs the disc engine")
class FilesystemConversionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.service = DiskService(self.root / "work")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _file(self, data: bytes) -> Path:
        path = self.root / f"payload-{len(list(self.root.iterdir()))}.bin"
        path.write_bytes(data)
        return path

    def _put(self, session, path: str, data: bytes, load="1900", execute="8023", side=None) -> None:
        self.service.put(session, None, path, self._file(data), f"0x{load}", f"0x{execute}", None, side)

    def _dfs_files(self, session, side=None) -> dict[str, dict]:
        return {row["path"]: row for row in self.service.list_dfs_catalogue_files(session, None, side)}

    def test_dfs_to_adfs_keeps_data_addresses_letters_and_boot(self) -> None:
        source = self.service.create_blank("ssd", "GAMES")
        self._put(source, "$.!BOOT", b"*RUN ELITE\r", "0", "0")
        self._put(source, "$.ELITE", bytes(range(256)) * 9, "FFFF1900", "FFFF8023")
        self._put(source, "G.CHUCKIE", b"chuckie" * 40)
        self.service._run(["opt", str(source.path), "3"])
        self.service.set_access(source, None, ["$.ELITE"], False)

        targets = {item["id"] for item in conversion_targets(source)}
        self.assertEqual(targets, {"adfs-s", "adfs-m", "adfs-l", "adfs-800", "adfs-1600"})
        converted, plan = convert(self.service, source, "adfs-m")

        self.assertEqual(converted.kind, "adfs")
        self.assertTrue(converted.name.endswith(".adm"))
        self.assertEqual(plan.dropped, [])
        self.assertEqual(self.service.read_file(converted, None, "$.ELITE"), bytes(range(256)) * 9)
        self.assertEqual(self.service.read_file(converted, None, "$.G.CHUCKIE"), b"chuckie" * 40)
        root = {row["name"]: row for row in self.service.list_directory(converted, "$", None)["entries"]}
        self.assertEqual(root["ELITE"]["load"] & 0xFFFF, 0x1900)
        self.assertEqual(root["ELITE"]["exec"] & 0xFFFF, 0x8023)
        self.assertIn("L", root["ELITE"]["attr"].split("/")[0])
        self.assertEqual(root["G"]["type"], "dir")
        self.assertTrue(str(self.service._run(["opt", str(converted.path)])).startswith("3"))
        self.assertEqual(self._dfs_files(source).keys(), {"$.!BOOT", "$.ELITE", "G.CHUCKIE"}, "source is unchanged")

    def test_adfs_to_dfs_flattens_and_shortens_names(self) -> None:
        source = self.service.create_blank("adfs-l", "Utils")
        self.service.make_directory(source, "$.Games")
        self.service.make_directory(source, "$.Games.Arcade")
        self._put(source, "$.Readme", b"hello\r")
        self._put(source, "$.Games.Revs", b"revs" * 100)
        self._put(source, "$.Games.Arcade.Planetoid", b"p" * 300)

        plan = plan_conversion(self.service, source, "dfs-80")
        self.assertEqual(plan.dropped, [])
        self.assertIn("flattened", " ".join(plan.notes))
        converted, _plan = convert(self.service, source, "dfs-80")

        files = self._dfs_files(converted)
        self.assertEqual(set(files), {"$.Readme", "G.Revs", "G.Planeto"})
        self.assertEqual(self.service.read_file(converted, None, "G.Planeto"), b"p" * 300)
        self.assertTrue(converted.name.endswith(".ssd"))

    def test_a_dfs_target_reports_files_that_do_not_fit_before_creating_anything(self) -> None:
        source = self.service.create_blank("adfs-l", "Many")
        for number in range(35):
            self._put(source, f"$.F{number}", b"x")
        sessions_before = set(self.service.sessions)

        plan = plan_conversion(self.service, source, "dfs-40")
        self.assertEqual(len(plan.files), 31)
        self.assertEqual(len(plan.dropped), 4)
        self.assertIn("31 files", plan.dropped[0]["reason"])
        with self.assertRaisesRegex(DiskError, "will not fit"):
            convert(self.service, source, "dfs-40")
        self.assertEqual(set(self.service.sessions), sessions_before)

        converted, _plan = convert(self.service, source, "dfs-40", accept_losses=True)
        self.assertEqual(len(self._dfs_files(converted)), 31)

    def test_a_double_sided_dfs_target_uses_its_second_side(self) -> None:
        source = self.service.create_blank("adfs-l", "Many")
        for number in range(40):
            self._put(source, f"$.F{number}", b"x")
        converted, plan = convert(self.service, source, "dfs-80-ds")
        self.assertEqual(plan.dropped, [])
        self.assertEqual(len(self._dfs_files(converted, 0)), 31)
        self.assertEqual(len(self._dfs_files(converted, 2)), 9)

    def test_names_that_collide_once_shortened_stay_distinct(self) -> None:
        source = self.service.create_blank("adfs-l", "Names")
        self._put(source, "$.Planetoid1", b"one")
        self._put(source, "$.Planetoid2", b"two")
        converted, plan = convert(self.service, source, "dfs-80")
        files = self._dfs_files(converted)
        self.assertEqual(len(files), 2)
        self.assertEqual(sorted(self.service.read_file(converted, None, path) for path in files), [b"one", b"two"])
        self.assertEqual(len(plan.renamed), 2)

    def test_both_sides_of_a_dsd_reach_adfs(self) -> None:
        source = self.service.create_blank("dsd", "Two")
        self._put(source, "$.FRONT", b"front", side=0)
        self._put(source, "$.FRONT", b"back", side=2)
        converted, plan = convert(self.service, source, "adfs-l")
        self.assertEqual(self.service.read_file(converted, None, "$.FRONT"), b"front")
        self.assertEqual(self.service.read_file(converted, None, "$.SIDE2.FRONT"), b"back")
        self.assertIn("$.SIDE2", " ".join(plan.notes))

    def test_same_filesystem_targets_are_refused(self) -> None:
        source = self.service.create_blank("ssd", "D")
        with self.assertRaisesRegex(DiskError, "other filesystem"):
            plan_conversion(self.service, source, "dfs-80")


if __name__ == "__main__":
    unittest.main()
