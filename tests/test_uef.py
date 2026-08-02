from __future__ import annotations

import unittest
import zipfile
from pathlib import Path

from app.disk_service import DiskService
from app.uef import (
    basic_unopened_channel_io,
    is_tokenized_basic,
    parse_uef,
    rewrite_basic_loader,
)


ROOT = Path(__file__).resolve().parents[1]


def sample_uef(archive_name: str) -> bytes:
    fixture = ROOT / "samples" / archive_name
    if not fixture.is_file():
        raise unittest.SkipTest(f"Optional UEF fixture is not bundled: {archive_name}")
    with zipfile.ZipFile(fixture) as archive:
        member = next(name for name in archive.namelist() if name.lower().endswith(".uef"))
        return archive.read(member)


class UEFTests(unittest.TestCase):
    def test_detects_cassette_inherited_basic_channel_before_disk_boot(self):
        body = bytes((0xBE,)) + b"#6"
        program = b"\x0D\x00\x0A" + bytes((len(body) + 4,)) + body + b"\x0D\xFF"

        self.assertTrue(basic_unopened_channel_io(program))

    def test_explicit_basic_open_is_not_misreported_as_inherited_channel(self):
        body = bytes((0x8E,)) + b'"DATA":' + bytes((0xBE,)) + b"#A%"
        program = b"\x0D\x00\x0A" + bytes((len(body) + 4,)) + body + b"\x0D\xFF"

        self.assertFalse(basic_unopened_channel_io(program))

    def test_control_character_tape_name_is_inferred_from_previous_file(self):
        contents = parse_uef(sample_uef("Acornsoft Meteors (1983)(Acornsoft)[a].zip"))

        self.assertEqual([item.name for item in contents.files], ["Meteors", "METEOR2", "DStar"])
        self.assertTrue(contents.files[1].inferred_name)
        self.assertEqual(contents.files[1].original_name, "\r")
        self.assertTrue(any("labelled METEOR2" in warning for warning in contents.warnings))

    def test_empty_tape_next_command_is_rewritten_to_final_dfs_name(self):
        contents = parse_uef(sample_uef("Acornsoft Meteors (1983)(Acornsoft)[a].zip"))
        loader = contents.files[0].data

        rewritten, changes = rewrite_basic_loader(
            loader,
            "METEOR2",
            {"Meteors": "METEORS", "METEOR2": "METEOR2"},
        )

        self.assertTrue(is_tokenized_basic(rewritten))
        self.assertIn(b"*/METEOR2", rewritten)
        self.assertNotIn(b"*/\r", rewritten)
        self.assertTrue(any("cassette-next" in change for change in changes))

    def test_existing_explicit_loader_reference_is_preserved(self):
        contents = parse_uef(sample_uef("Acornsoft Meteors (1983)(Acornsoft).zip"))
        loader = contents.files[0].data

        rewritten, changes = rewrite_basic_loader(
            loader,
            "METEOR2",
            {"METEOR2": "METEOR2"},
        )

        self.assertEqual(rewritten, loader)
        self.assertEqual(changes, ())

    def test_empty_chain_is_rewritten_without_losing_trailing_payload(self):
        body = b'\xD7""'
        trailing = b"\x00machine-data-after-basic"
        loader = b"\x0D\x00\x0A" + bytes((len(body) + 4,)) + body + b"\x0D\xFF" + trailing

        rewritten, changes = rewrite_basic_loader(loader, "SECOND", {})

        self.assertIn(b'\xD7"SECOND"', rewritten)
        self.assertTrue(rewritten.endswith(trailing))
        self.assertTrue(is_tokenized_basic(rewritten))
        self.assertTrue(any('CHAIN ""' in change for change in changes))

    def test_chuckulus_dfs_loader_abbreviations_are_made_adfs_safe(self):
        contents = parse_uef((ROOT / "samples" / "Chuckulus-Electron-V1-0.uef").read_bytes())
        chuck = contents.files[1]
        occupied = [
            (item.load & 0xFFFF, (item.load & 0xFFFF) + len(item.data))
            for item in contents.files
        ]

        patched, repairs, warnings = DiskService._expand_adfs_oscli_abbreviations(
            chuck.data,
            chuck.load,
            occupied,
        )

        self.assertEqual(warnings, [])
        self.assertEqual(len(repairs), 2)
        self.assertEqual(patched[len(chuck.data) :], b"RUN EZZZIns\rLOAD EZMC 2000\r")
        self.assertIn(b"\xA2\x00\xA0\x0D\x20\xF7\xFF", patched)
        self.assertIn(b"\xA2\x0C\xA0\x0D\x20\xF7\xFF", patched)
        self.assertLess(chuck.load + len(patched), 0x0E00)

    def test_adfs_boot_script_abbreviations_are_expanded(self):
        source = b"*BASIC\r*FX21\rCLOSE#0:*R.Chuck\r*LO.EZMC 2000\r"

        patched, repairs = DiskService._expand_adfs_text_commands(source)

        self.assertEqual(
            patched,
            b"*BASIC\r*FX21\rCLOSE#0:*RUN Chuck\r*LOAD EZMC 2000\r",
        )
        self.assertEqual(len(repairs), 2)

    def test_loader_repair_follows_boot_target_without_scanning_data_files(self):
        contents = parse_uef((ROOT / "samples" / "Chuckulus-Electron-V1-0.uef").read_bytes())
        chuck = contents.files[1]
        items = [
            {
                "sourceName": "!BOOT",
                "load": 0,
                "data": b"*BASIC\rCLOSE#0:*R.Chuck\r",
            },
            {
                "sourceName": "Chuck",
                "load": chuck.load,
                "data": chuck.data,
            },
            {
                "sourceName": "Review",
                "load": 0x3000,
                "data": b"r. If that sounds difficult, read the manual\r"
                b"l. The game was reviewed in volume 2\r",
            },
        ]

        repairs, warnings = DiskService._repair_adfs_loader_items(items)

        self.assertEqual(warnings, [])
        self.assertEqual(len(repairs), 3)
        self.assertIn(b"RUN Chuck", items[0]["data"])
        self.assertTrue(items[1]["data"].endswith(b"RUN EZZZIns\rLOAD EZMC 2000\r"))
        self.assertNotIn("loaderRepairs", items[2])

    def test_unprovable_boot_target_commands_are_grouped_into_one_warning(self):
        items = [
            {"sourceName": "!BOOT", "load": 0, "data": b"*BASIC\rCH.\"HAVEN\"\r"},
            {
                "sourceName": "HAVEN",
                "load": 0x2000,
                "data": b"R.+FRAK\rR.+PRES5\r",
            },
            {
                "sourceName": "R.+FRAK",
                "load": 0x3000,
                "data": b"r. This ordinary review text must not be scanned\r",
            },
        ]

        repairs, warnings = DiskService._repair_adfs_loader_items(items)

        self.assertEqual(repairs, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("HAVEN: loader contains 2 ambiguous", warnings[0])
        self.assertNotIn("ordinary review", warnings[0])

    def test_relocated_adfs_basic_loader_uses_proven_local_root_file(self):
        body = b"DATA FRAK (Superior),$.SS"
        haven = b"\x0D\x02\x8A" + bytes((len(body) + 4,)) + body + b"\x0D\xFF"
        items = [
            {"sourceName": "!BOOT", "load": 0, "data": b'*BASIC\rCH."HAVEN"\r'},
            {"sourceName": "HAVEN", "load": 0x1D00, "data": haven},
            {"sourceName": "SS", "load": 0x1D00, "data": b"program"},
        ]

        repairs, warnings = DiskService._repair_adfs_loader_items(items)

        self.assertEqual(warnings, [])
        self.assertEqual(len(repairs), 1)
        self.assertIn("HAVEN: changed root path $.SS to SS", repairs[0])
        self.assertIn(b",SS", items[1]["data"])
        self.assertNotIn(b"$.SS", items[1]["data"])
        self.assertTrue(is_tokenized_basic(items[1]["data"]))

    def test_relocated_adfs_basic_loader_preserves_missing_root_file(self):
        body = b'DATA Missing,$.MISSING'
        program = b"\x0D\x00\x0A" + bytes((len(body) + 4,)) + body + b"\x0D\xFF"

        patched, repairs, references = DiskService._rewrite_adfs_basic_root_paths(
            program, {"loader"}
        )

        self.assertEqual(patched, program)
        self.assertEqual(repairs, [])
        self.assertEqual(references, set())


if __name__ == "__main__":
    unittest.main()
