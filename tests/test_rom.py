import io
import tempfile
import unittest
import zipfile

from app.disk_service import DiskError, DiskService
from app.download_archive import build_download_archive
from app.rom import (
    inspect_bank,
    make_sideways_template,
    parse_risc_os_extension_header,
    parse_sideways_header,
)


class RomTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.service = DiskService(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_standard_header_is_parsed(self):
        header = parse_sideways_header(make_sideways_template(16 * 1024, "Test ROM"))
        self.assertIsNotNone(header)
        self.assertEqual(header.title, "Test ROM")
        self.assertEqual(header.roles, "language + service")
        self.assertEqual(header.language_entry, 0x8080)
        self.assertEqual(header.processor, "6502 BASIC")
        self.assertGreater(header.metadata_end, 9)

    def test_decoded_bank_exposes_regions_entry_points_and_strings(self):
        row = inspect_bank(
            make_sideways_template(16 * 1024, "Visible ROM"),
            0,
            include_contents=True,
        )
        self.assertEqual(row["structures"][0]["kind"], "header")
        self.assertEqual(
            [item["address"] for item in row["structures"] if item["kind"] == "entry"],
            [0x8080, 0x8080],
        )
        self.assertIn("Visible ROM", [item["text"] for item in row["strings"]])

    def test_sideways_header_role_bits_follow_the_acorn_definition(self):
        language = bytearray(make_sideways_template(16 * 1024, "Language"))
        language[6] = 0x40
        self.assertEqual(parse_sideways_header(language).roles, "language")
        service = bytearray(language)
        service[6] = 0x80
        self.assertEqual(parse_sideways_header(service).roles, "service")

    def test_header_without_standard_copyright_marker_is_not_guessed(self):
        image = bytearray(make_sideways_template(16 * 1024, "Not a ROM"))
        marker = image[7]
        image[marker + 1 : marker + 4] = b"ABC"
        self.assertIsNone(parse_sideways_header(image))

    def test_header_role_and_vector_disagreement_is_reported(self):
        image = bytearray(make_sideways_template(16 * 1024, "Mismatch"))
        image[6] = 0x40
        row = inspect_bank(image, 0, include_contents=True)
        self.assertTrue(any("service-ROM flag" in warning for warning in row["warnings"]))

    def test_structurally_valid_risc_os_module_candidate_is_decoded(self):
        image = bytearray(256)
        image[4:8] = (44).to_bytes(4, "little")
        image[16:20] = (64).to_bytes(4, "little")
        image[64:75] = b"TestModule\0"
        row = inspect_bank(
            image,
            0,
            erase_byte=0xFF,
            include_contents=True,
            include_risc_os_modules=True,
        )
        self.assertEqual(row["modules"][0]["title"], "TestModule")
        self.assertEqual(row["modules"][0]["initialise"], 44)

    def test_risc_os_declared_star_command_is_listed(self):
        image = bytearray(256)
        image[4:8] = (44).to_bytes(4, "little")
        image[16:20] = (64).to_bytes(4, "little")
        image[24:28] = (80).to_bytes(4, "little")
        image[64:75] = b"TestModule\0"
        image[80:85] = b"Hello"
        image[85] = 0
        image[88:92] = (128).to_bytes(4, "little")
        image[92:96] = (1 | (2 << 16)).to_bytes(4, "little")
        image[96:100] = (144).to_bytes(4, "little")
        image[100:104] = (176).to_bytes(4, "little")
        image[144:158] = b"Bad parameters\0"
        image[176:197] = b"Displays a greeting.\0"
        row = inspect_bank(
            image,
            0,
            include_contents=True,
            include_risc_os_modules=True,
        )
        command = row["starCommands"][0]
        self.assertEqual(command["display"], "*Hello")
        self.assertEqual(command["confidence"], "declared")
        self.assertEqual(command["minimumParameters"], 1)
        self.assertEqual(command["maximumParameters"], 2)
        self.assertEqual(command["helpText"], "Displays a greeting.")
        self.assertEqual(command["helpSource"], "Declared RISC OS command help")

    def test_bbc_tokenised_star_command_table_is_recovered_as_candidates(self):
        image = bytearray(make_sideways_template(16 * 1024, "Commands"))
        image[0x100:0x103] = b"\xDD\xF0\x81"
        image[0x1F0:0x1F6] = b"HELP\x81\xFF"
        table = b"MENU\x81ROMS\x82SRLOAD\x83SRSAVE\x84"
        image[0x200 : 0x200 + len(table)] = table
        row = inspect_bank(image, 0, include_contents=True)
        commands = {item["display"]: item for item in row["starCommands"]}
        self.assertEqual(commands["*MENU"]["confidence"], "strong candidate")
        self.assertIn("*SRSAVE", commands)

    def test_bbc_token_command_syntax_is_reconstructed_by_dispatch_token(self):
        image = bytearray(make_sideways_template(16 * 1024, "Syntax commands"))
        image[0x100:0x103] = b"\xDD\x00\x82"
        table = b"BUILD\x84LOADROM\x90RLOAD\x90ROMS\x8E\xFF<file>\r<file> <rom>\r\r"
        image[0x200 : 0x200 + len(table)] = table
        commands = {item["display"]: item for item in inspect_bank(image, 0, include_contents=True)["starCommands"]}
        self.assertEqual(commands["*BUILD"]["syntax"], "<file>")
        self.assertEqual(commands["*LOADROM"]["syntax"], "<file> <rom>")
        self.assertEqual(commands["*RLOAD"]["syntax"], "<file> <rom>")
        self.assertEqual(commands["*ROMS"]["helpText"], "*ROMS")

    def test_bbc_token_table_excludes_help_groups_and_crosses_group_divider(self):
        image = bytearray(make_sideways_template(16 * 1024, "Grouped commands"))
        image[0x100:0x103] = b"\xDD\xF0\x81"
        image[0x1F0:0x1F6] = b"HELP\x81\xFF"
        table = b"SRAM\x82UTILS\x83\xFFBUILD\x84DUMP\x85\x80LIST\x86TYPE\x87"
        image[0x200 : 0x200 + len(table)] = table
        row = inspect_bank(image, 0, include_contents=True)
        commands = {item["display"] for item in row["starCommands"]}
        self.assertEqual(commands, {"*BUILD", "*DUMP", "*LIST", "*TYPE"})

    def test_bbc_address_dispatch_command_table_is_recovered(self):
        image = bytearray(make_sideways_template(16 * 1024, "Address commands"))
        image[0x100:0x103] = b"\xDD\x00\x82"  # CMP &8200,X proves the table reference.
        table = b"MENU\x80\xFFROMS\x81\x0FSOUND\x82\x1F"
        image[0x200 : 0x200 + len(table)] = table
        row = inspect_bank(image, 0, include_contents=True)
        commands = {item["display"]: item for item in row["starCommands"]}
        self.assertEqual(set(commands), {"*MENU", "*ROMS", "*SOUND"})
        self.assertEqual(commands["*MENU"]["handlerAddress"], 0x8100)

    def test_bbc_three_byte_address_dispatch_metadata_is_skipped(self):
        image = bytearray(make_sideways_template(16 * 1024, "Address metadata"))
        image[0x100:0x103] = b"\xBD\x00\x82"  # LDA &8200,X proves the table reference.
        table = b"ACCESS\x90\x00\x16BACK\x91\x00\x00BYE\x92\x00\x20DIR\x93\x00\x10"
        image[0x200 : 0x200 + len(table)] = table
        row = inspect_bank(image, 0, include_contents=True)
        self.assertEqual(
            {item["display"] for item in row["starCommands"]},
            {"*ACCESS", "*BACK", "*BYE", "*DIR"},
        )

    def test_bbc_address_dispatch_help_fragments_are_reconstructed(self):
        image = bytearray(make_sideways_template(16 * 1024, "Address help"))
        image[0x100:0x103] = b"\xBD\x00\x82"
        image[0x110:0x113] = b"\xBD\x80\x81"
        image[0x180:0x183] = bytes((0x10, 0x20, 0x30))
        image[0x310] = 0
        image[0x320:0x327] = b"<file>\0"
        image[0x330:0x334] = b"(I)\0"
        table = b"LOAD\x90\x00\x12SAVE\x91\x00\x10ROMS\x92\x00\x00"
        image[0x200 : 0x200 + len(table)] = table
        commands = {item["display"]: item for item in inspect_bank(image, 0, include_contents=True)["starCommands"]}
        self.assertEqual(commands["*LOAD"]["helpText"], "*LOAD <file> (I)")
        self.assertEqual(commands["*SAVE"]["helpText"], "*SAVE <file>")
        self.assertEqual(commands["*ROMS"]["helpText"], "*ROMS")

    def test_literal_shared_help_is_attached_only_to_a_proven_command(self):
        image = bytearray(make_sideways_template(16 * 1024, "Shared help"))
        image[0x100:0x103] = b"\xDD\x00\x82"
        table = b"MENU\x80\xFFROMS\x81\x0FSOUND\x82\x1F"
        image[0x200 : 0x200 + len(table)] = table
        image[0x300:0x32F] = b"  *MENU   (Shows the menu)\r*FAKE Not a command\r"
        commands = {item["display"]: item for item in inspect_bank(image, 0, include_contents=True)["starCommands"]}
        self.assertEqual(commands["*MENU"]["helpText"], "*MENU (Shows the menu)")
        self.assertNotIn("*FAKE", commands)

    def test_explicit_star_command_text_is_not_reported_as_a_provided_command(self):
        image = bytearray(make_sideways_template(16 * 1024, "Text command"))
        image[0x200:0x20A] = b"Try *MENU\0"
        row = inspect_bank(image, 0, include_contents=True)
        self.assertNotIn("*MENU", {item["display"] for item in row["starCommands"]})

    def test_risc_os_extension_rom_trailer_and_checksum_are_recognised(self):
        image = bytearray(64 * 1024)
        image[-16:-12] = len(image).to_bytes(4, "little")
        checksum = sum(
            int.from_bytes(image[offset : offset + 4], "little")
            for offset in range(0, len(image) - 12, 4)
        ) & 0xFFFFFFFF
        image[-12:-8] = checksum.to_bytes(4, "little")
        image[-8:] = b"ExtnROM0"
        header = parse_risc_os_extension_header(image)
        self.assertIsNotNone(header)
        self.assertTrue(header.checksum_valid)

    def test_256k_image_is_listed_as_sixteen_16k_banks(self):
        session = self.service.create_blank(
            "rom",
            "Banked",
            options={
                "totalSize": 256 * 1024,
                "bankSize": 16 * 1024,
                "template": "sideways",
            },
        )
        rows = self.service.list_rom_banks(session)
        self.assertEqual(len(rows), 16)
        self.assertEqual(rows[0]["name"], "Banked")
        self.assertTrue(all(row["empty"] for row in rows[1:]))
        self.assertEqual(rows[0]["strings"], [])
        self.assertEqual(rows[1]["matchingBanks"], list(range(2, 16)))
        decoded = self.service.inspect_rom_bank(session, 0)
        self.assertIn("Banked", [item["text"] for item in decoded["strings"]])
        self.assertEqual(decoded["fileOffset"], 0)
        self.assertGreater(decoded["programmedBytes"], 0)
        self.assertGreater(decoded["programmedPercent"], 0)
        self.assertEqual(len(decoded["diagnostics"]["sha256"]), 64)
        self.assertEqual(decoded["diagnostics"]["usedStart"], 0)

    def test_opened_rom_layout_survives_recovery(self):
        session = self.service.create_from_stream(
            "chips.rom",
            io.BytesIO(bytes(range(256)) * 128),
            rom_options={
                "platform": "archimedes",
                "layout": "byte-interleaved-4",
                "componentNames": ["ic24.rom", "ic25.rom", "ic26.rom", "ic27.rom"],
            },
        )
        restored = DiskService(self.temporary.name)._restore_session(session.id)
        self.assertEqual(restored.rom_layout, "byte-interleaved-4")
        self.assertEqual(restored.rom_component_names[0], "ic24.rom")

    def test_overlapping_bank_move_reads_sources_before_writing(self):
        session = self.service.create_blank(
            "rom", "Move", options={"totalSize": 4 * 1024, "bankSize": 1024}
        )
        for bank, value in enumerate((1, 2, 3, 4)):
            self.service.put_rom_bank(session, bytes((value,)) * 1024, bank)
        self.service.move_rom_banks(session, [0, 1, 2], 1)
        self.assertEqual(self.service.rom_bank_bytes(session, "bank:1")[:1], b"\x01")
        self.assertEqual(self.service.rom_bank_bytes(session, "bank:2")[:1], b"\x02")
        self.assertEqual(self.service.rom_bank_bytes(session, "bank:3")[:1], b"\x03")
        self.assertTrue(self.service.list_rom_banks(session)[0]["empty"])

    def test_bank_import_rejects_implicit_truncation(self):
        session = self.service.create_blank(
            "rom", "Small", options={"totalSize": 4096, "bankSize": 4096}
        )
        with self.assertRaisesRegex(DiskError, "does not fit"):
            self.service.put_rom_bank(session, b"x" * 4097)

    def test_interleaved_component_export_restores_chip_order(self):
        logical = bytes((0, 10, 20, 30, 1, 11, 21, 31))
        session = self.service.create_from_stream(
            "set.rom",
            io.BytesIO(logical),
            rom_options={
                "layout": "byte-interleaved-4",
                "componentNames": ["a.rom", "b.rom", "c.rom", "d.rom"],
            },
        )
        exports = self.service.rom_component_exports(session)
        self.assertEqual(
            [path.read_bytes() for path, _name in exports],
            [b"\x00\x01", b"\x0a\x0b", b"\x14\x15", b"\x1e\x1f"],
        )

    def test_saved_interleaved_rom_contains_readme_and_physical_chips(self):
        session = self.service.create_from_stream(
            "set.rom",
            io.BytesIO(bytes((0, 10, 20, 30, 1, 11, 21, 31))),
            rom_options={
                "platform": "archimedes",
                "layout": "byte-interleaved-4",
                "componentNames": ["ic24.rom", "ic25.rom", "ic26.rom", "ic27.rom"],
            },
        )
        archive_path, _name = build_download_archive(self.service, session)
        with zipfile.ZipFile(archive_path) as archive:
            self.assertIn("set.rom", archive.namelist())
            self.assertIn("README.md", archive.namelist())
            self.assertEqual(archive.read("ROM-components/ic24.rom"), b"\x00\x01")
            readme = archive.read("README.md").decode()
            self.assertIn("byte-interleaved-4", readme)
            self.assertIn("ic24.rom", readme)


if __name__ == "__main__":
    unittest.main()
