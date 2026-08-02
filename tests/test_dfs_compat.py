from pathlib import Path
import unittest

from app.dfs_compat import dfs_catalogue_files, infer_dfs_launch_page, repair_dfs_basic_wildcards
from app.menu_interpreter import decode_basic


ROOT = Path(__file__).resolve().parents[1]


class DFSCompatibilityTests(unittest.TestCase):
    def test_bug_blaster_wildcard_is_replaced_with_exact_catalogue_name(self) -> None:
        source = ROOT / "samples/[SSD]/alligata/AL-BUGCJHHLR.ssd"
        repaired, changes = repair_dfs_basic_wildcards(source.read_bytes())

        self.assertTrue(any("A.BUG3 line 120" in change for change in changes))
        entry = next(item for item in dfs_catalogue_files(repaired) if item.path == "A.BUG3")
        lines = decode_basic(repaired[entry.start : entry.start + entry.length])
        self.assertIsNotNone(lines)
        self.assertIn('CHAIN"BUG?1"', next(line.text for line in lines if line.number == 120))

    def test_repair_is_idempotent(self) -> None:
        source = ROOT / "samples/[SSD]/alligata/AL-BUGCJHHLR.ssd"
        repaired, _changes = repair_dfs_basic_wildcards(source.read_bytes())
        second, changes = repair_dfs_basic_wildcards(repaired)

        self.assertEqual(second, repaired)
        self.assertEqual(changes, [])

    def test_ssdmenu_page_comes_from_its_saved_basic_address(self) -> None:
        source = ROOT / "samples/[SSD]/Acornsoft/ACN-ARCBOXCT.ssd"
        page, evidence = infer_dfs_launch_page(source.read_bytes(), "SSDMENU", "")

        self.assertEqual(page, "1900")
        self.assertIn("tokenised BASIC saved at &1900", evidence)

    def test_exec_boot_page_uses_its_explicit_assignment(self) -> None:
        source = ROOT / "samples/[SSD]/alligata/AL-BUGCJHHLR.ssd"
        page, evidence = infer_dfs_launch_page(source.read_bytes(), "!BOOT", "E")

        self.assertEqual(page, "E00")
        self.assertIn("explicitly sets PAGE=&E00", evidence)

    def test_exec_boot_follows_rooted_chain_to_actual_basic_page(self) -> None:
        source = ROOT / "samples/[SSD]/kansas city/KCS-COMPILE1.ssd"
        page, evidence = infer_dfs_launch_page(source.read_bytes(), "!BOOT", "E")

        self.assertEqual(page, "E00")
        self.assertIn("KANLOAD", evidence)

    def test_lenient_basic_image_still_provides_saved_page(self) -> None:
        source = ROOT / "samples/[SSD]/tynesoft/TY-SUMROLYMP.ssd"
        page, evidence = infer_dfs_launch_page(source.read_bytes(), "LOADER", "")

        self.assertEqual(page, "1900")
        self.assertIn("tokenised BASIC saved at &1900", evidence)

    def test_machine_code_exec_boot_marks_page_as_unused(self) -> None:
        source = ROOT / "samples/[SSD]/Chuckulus-Electron-V1-0.ssd"
        page, evidence = infer_dfs_launch_page(source.read_bytes(), "!BOOT", "E")

        self.assertIsNone(page)
        self.assertIn("PAGE is not used", evidence)


if __name__ == "__main__":
    unittest.main()
