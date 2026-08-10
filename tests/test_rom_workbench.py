import json
import tempfile
import unittest
from pathlib import Path

from app.rom_workbench import (
    RomWorkbenchError, apply_patch, audit_rom, bank_map, build_data_archive,
    build_sideways_rom, compare_roms, disassemble_6502, hardware_export,
    identify_rom, make_patch, normalise_project,
    make_selective_patch, disassemble_capstone, Cs,
)


class RomWorkbenchTests(unittest.TestCase):
    def test_disassembly_labels_mos_calls_and_branches(self):
        data = bytes.fromhex("20F4FFD0FB60")
        report = disassemble_6502(data, origin=0x8000)
        self.assertEqual(report["rows"][0]["comment"], "OSBYTE")
        self.assertEqual(report["rows"][1]["target"], 0x8000)
        self.assertEqual(report["rows"][2]["mnemonic"], "RTS")

    def test_unknown_opcode_is_data_not_invented_code(self):
        row = disassemble_6502(b"\x02", origin=0x8000)["rows"][0]
        self.assertEqual((row["mnemonic"], row["operand"]), ("EQUB", "&02"))

    @unittest.skipIf(Cs is None, "Capstone is installed in the production image")
    def test_arm_and_68000_disassembly_use_correct_byte_order(self):
        arm = disassemble_capstone(bytes.fromhex("0000A0E31EFF2FE1"), architecture="arm", length=8)
        self.assertEqual([row["mnemonic"] for row in arm["rows"]], ["MOV", "BX"])
        m68k = disassemble_capstone(bytes.fromhex("4E714E75"), architecture="m68k", length=4)
        self.assertEqual([row["mnemonic"] for row in m68k["rows"]], ["NOP", "RTS"])

    def test_comparison_and_patch_are_checksum_guarded(self):
        left, right = b"hello ROM", b"hello rom!"
        report = compare_roms(left, right)
        self.assertGreater(report["changedBytes"], 0)
        patch = make_patch(left, right)
        self.assertEqual(apply_patch(left, patch), right)
        with self.assertRaises(RomWorkbenchError):
            apply_patch(b"wrong", patch)

    def test_selective_patch_contains_only_chosen_ranges(self):
        left, right = b"ABC-DEF-GHI", b"AbC-DEF-GhI"
        report = compare_roms(left, right)
        self.assertEqual(len(report["ranges"]), 2)
        patch = make_selective_patch(left, right, [1])
        self.assertEqual(apply_patch(left, patch), b"ABC-DEF-GhI")

    def test_bank_map_finds_duplicates(self):
        data = b"A" * 256 + b"B" * 256 + b"A" * 256
        report = bank_map(data, 256)
        self.assertEqual(report["banks"][0]["duplicates"], [2])
        self.assertEqual(report["banks"][2]["duplicates"], [0])

    def test_builder_creates_safe_service_rom_header(self):
        data = build_sideways_rom("Workshop", [{"name": "MENU", "syntax": "<file>"}])
        report = audit_rom(data, 16384)
        self.assertTrue(report["healthy"])
        self.assertEqual(data[0x80], 0x60)
        self.assertIn(b"AFFCOMMANDS\0MENU\0<file>\0", data)

    def test_data_archive_refuses_overflow(self):
        image = build_data_archive("Archive", [("ONE", b"abc")])
        self.assertIn(b"AFFROMFS1", image)
        with self.assertRaises(RomWorkbenchError):
            build_data_archive("Full", [("BIG", b"X" * 20000)])

    def test_hardware_export_can_mirror_swap_and_split(self):
        result = hardware_export(b"\x01\x02", device_size=8, mirror=True, lanes=2, byte_swap=True)
        self.assertEqual(result["components"], [b"\x02" * 4, b"\x01" * 4])

    def test_hardware_export_can_swap_words_and_address_lines(self):
        words = hardware_export(bytes(range(8)), device_size=8, word_swap=True)
        self.assertEqual(words["components"][0], bytes((2, 3, 0, 1, 6, 7, 4, 5)))
        addresses = hardware_export(bytes(range(8)), device_size=8, address_swaps=[(0, 1)])
        self.assertEqual(addresses["components"][0], bytes((0, 2, 1, 3, 4, 6, 5, 7)))

    def test_identification_catalogue_and_mirror_hint(self):
        data = b"AB" * 16
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "catalogue.json"
            digest = __import__("hashlib").sha256(data).hexdigest()
            path.write_text(json.dumps({"roms": [{"sha256": digest, "title": "Known"}]}))
            result = identify_rom(data, path)
        self.assertTrue(result["matched"])
        self.assertTrue(any("mirrored" in row for row in result["transformations"]))

    def test_project_metadata_is_bounded(self):
        project = normalise_project({"notes": "x" * 30000, "symbols": {"32768": "start"}})
        self.assertEqual(len(project["notes"]), 20000)
        self.assertEqual(project["symbols"]["32768"], "start")


if __name__ == "__main__":
    unittest.main()
