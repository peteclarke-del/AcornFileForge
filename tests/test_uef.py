from __future__ import annotations

import unittest
import zipfile
import tempfile
from pathlib import Path

from app.disk_service import DiskError, DiskService
from app.uef import (
    basic_unopened_channel_io,
    is_tokenized_basic,
    parse_uef,
    rewrite_basic_loader,
)


ROOT = Path(__file__).resolve().parents[1]


def sample_uef(fixture_name: str) -> bytes:
    fixture = ROOT / "samples" / fixture_name
    if not fixture.is_file():
        raise unittest.SkipTest(f"Optional UEF fixture is not bundled: {fixture_name}")
    if fixture.suffix.casefold() == ".uef":
        return fixture.read_bytes()
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
        contents = parse_uef(sample_uef("Chuckulus-Electron-V1-0.uef"))
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

    def test_adfs_directory_path_is_not_expanded_as_a_dfs_command(self):
        source = b"*R.+AP2\r*L.+MANUAL\r"

        patched, repairs = DiskService._expand_adfs_text_commands(
            source, {"r.+ap2", "l.+manual"}
        )

        self.assertEqual(patched, source)
        self.assertEqual(repairs, [])

    def test_binary_adfs_directory_path_is_not_reported_as_ambiguous(self):
        source = b"\xA2\x07\xA0\x20\x20\xF7\xFFR.+AP2\r"

        patched, repairs, warnings = DiskService._expand_adfs_oscli_abbreviations(
            source, 0x2000, [(0x2000, 0x2000 + len(source))], {"r.+ap2"}
        )

        self.assertEqual(patched, source)
        self.assertEqual(repairs, [])
        self.assertEqual(warnings, [])

    def test_legacy_adfs_notices_are_consolidated(self):
        warnings = DiskService._normalise_warnings([
            "Repaired 4 old-ADFS directory sequence fields for 8-bit hardware.",
            "Repaired 10 old-ADFS directory sequence fields for 8-bit hardware.",
            "$.GAMES.QBIX: HAVEN: loader contains 1 ambiguous abbreviated command(s) (R.+AP2)",
            "$.GAMES.QBIX: the selected hardware profile has a Tube second processor enabled.",
            "$.GAMES.ZALAGA: ADFS compatibility change made: LOADER: expanded L. ZALAGA to LOAD ZALAGA.",
        ])

        self.assertEqual(len(warnings), 4)
        self.assertEqual(sum("directory sequence" in item for item in warnings), 1)
        self.assertEqual(sum("Tube second processor" in item for item in warnings), 1)
        self.assertEqual(sum("current path-aware results" in item for item in warnings), 1)
        self.assertTrue(any("ZALAGA" in item for item in warnings))

    def test_loader_repair_follows_boot_target_without_scanning_data_files(self):
        contents = parse_uef(sample_uef("Chuckulus-Electron-V1-0.uef"))
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
                "data": b"\xA9\x00R.+FRAK\r\xA2\x00R.+PRES5\r",
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
        self.assertIn("HAVEN: loader contains 1 ambiguous", warnings[0])
        self.assertIn("R.+PRES5", warnings[0])
        self.assertNotIn("R.+FRAK", warnings[0])
        self.assertNotIn("ordinary review", warnings[0])

    def test_data_driven_second_stage_loader_is_repaired(self):
        boot = b'*BASIC\rCH."HAVEN"\r'
        haven_body = b"DATA 1:DATA ZALAGA (Aardvark),LOADER"
        haven = b"\x0D\x00\x0A" + bytes((len(haven_body) + 4,)) + haven_body + b"\x0D\xFF"
        loader_body = b'*KEY0 "*L. ZALAGA 2000|M"'
        loader = b"\x0D\x00\x0A" + bytes((len(loader_body) + 4,)) + loader_body + b"\x0D\xFF"
        items = [
            {"sourceName": "!BOOT", "load": 0, "data": boot},
            {"sourceName": "HAVEN", "load": 0x1D00, "data": haven},
            {"sourceName": "LOADER", "load": 0x1D00, "data": loader},
            {"sourceName": "ZALAGA", "load": 0x2000, "data": b"machine code"},
        ]

        repairs, warnings = DiskService._repair_adfs_loader_items(items)

        self.assertEqual(warnings, [])
        self.assertTrue(any("LOADER" in repair and "LOAD ZALAGA" in repair for repair in repairs))
        self.assertIn(b"*LOAD ZALAGA 2000", items[2]["data"])

    def test_embedded_root_path_is_retargeted_without_moving_binary(self):
        source = b"\xA9\x00$.DATA\r\x20\xF7\xFF"

        patched, repairs, references = DiskService._rewrite_adfs_binary_root_paths(
            source, {"data"}
        )

        self.assertEqual(len(patched), len(source))
        self.assertIn(b"@.DATA\r", patched)
        self.assertEqual(references, {"data"})
        self.assertEqual(repairs, ["changed root path $.DATA to @.DATA"])

    def test_direct_sector_and_disc_switch_loader_is_warned_not_rewritten(self):
        risks = DiskService._adfs_loader_risks(b'*DISC\rOSWORD &72\r')

        self.assertEqual(len(risks), 2)
        self.assertTrue(any("filing system" in risk for risk in risks))
        self.assertTrue(any("direct sector" in risk for risk in risks))

    def test_adfs_installation_roots_use_provenance_and_avoid_nested_loaders(self):
        roots = DiskService._adfs_installation_roots(
            {
                "$": ["!BOOT", "GAMDATA", "GAMINDX", "PUBDATA", "PUBINDX", "UNIMENU"],
                "$.Games": [],
                "$.Games.FRAK": ["!BOOT", "HAVEN"],
                "$.Games.FRAK.Data": ["LOADER", "FRAK"],
                "$.Games.NOBOOT": ["PROGRAM"],
            },
            {
                "$.Games.FRAK": "HA-FRAK.adf",
                "$.Games.NOBOOT": "NoBoot.adf",
            },
        )

        self.assertEqual(roots, ["$.Games.FRAK", "$.Games.NOBOOT"])

    def test_installed_disk_audit_is_not_offered_for_adfs_floppies(self):
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(folder)
            session = service.create_blank("adfs-l", "FLOPPY")

            with self.assertRaisesRegex(DiskError, "ADFS HDD"):
                service.audit_adfs_installations(session)

    def test_zalaga_adf_install_repairs_its_data_selected_loader(self):
        fixture = ROOT / "samples" / "[ADF]" / "aardvark" / "HA-ZALA.adf"
        if not fixture.is_file():
            raise unittest.SkipTest("Optional Zalaga ADF fixture is not bundled")
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(folder)
            with fixture.open("rb") as stream:
                source = service.create_from_stream(fixture.name, stream)
            target = service.create_blank("adfs-l", "TARGET")

            installed = service.extract_image_to_adfs_directory(
                source, target, "$", "ZALAGA"
            )

            loader = service.read_file(target, None, f"{installed}.LOADER")
            self.assertIn(b"*LOAD ZALAGA 2000", loader)
            self.assertNotIn(b"*L. ZALAGA 2000", loader)

    def test_hdd_installation_audit_lists_and_repairs_zalaga_loader(self):
        fixture = ROOT / "samples" / "[ADF]" / "aardvark" / "HA-ZALA.adf"
        if not fixture.is_file():
            raise unittest.SkipTest("Optional Zalaga ADF fixture is not bundled")
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(folder)
            with fixture.open("rb") as stream:
                source = service.create_from_stream(fixture.name, stream)
            target = service.create_blank("adfs-hard", "TARGET", "4MB")
            service.make_directory(target, "$.ZALAGA")
            service._copy_image_listing_to_adfs(
                source, None, None, target, "$.ZALAGA"
            )
            service.set_adfs_source_name(target, "$.ZALAGA", fixture.name)

            audit = service.audit_adfs_installations(target)

            self.assertEqual(audit["checked"], 1)
            self.assertEqual(audit["repairable"], 1)
            finding = audit["directories"][0]
            self.assertEqual(finding["path"], "$.ZALAGA")
            self.assertEqual(finding["source"], fixture.name)
            self.assertTrue(any("LOAD ZALAGA" in item for item in finding["repairs"]))

            result = service.repair_adfs_installations(target, ["$.ZALAGA"])

            self.assertEqual(result["count"], 1)
            loader = service.read_file(target, None, "$.ZALAGA.LOADER")
            self.assertIn(b"*LOAD ZALAGA 2000", loader)
            self.assertNotIn(b"*L. ZALAGA 2000", loader)

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
