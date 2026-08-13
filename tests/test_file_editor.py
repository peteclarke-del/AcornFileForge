from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from oaknut.basic import detokenise, tokenise

from app.content_kind import analyse_content, metadata_kind
from app.disk_service import DiskService
from app.file_editor import (
    _format_basic_listing,
    _printable_strings,
    _renumber_tokenised,
    disassemble_file,
    disassemble_file_data,
    inspect_editable_file,
    normalise_basic_source,
    pack_basic_lines,
    prepare_basic_source,
    save_editor_text,
    save_editor_text_as,
    search_image_files,
    update_file_properties,
    verify_basic_source,
    write_file_range,
)
from tests.uef_fixture import minimal_uef


class FileEditorTests(unittest.TestCase):
    def service_with_file(self, content: bytes, metadata: dict | None = None):
        folder = tempfile.TemporaryDirectory()
        source = Path(folder.name) / "exported"
        source.write_bytes(content)
        service = Mock()

        def export(*_args):
            copy = Path(folder.name) / f"copy-{service.export_file.call_count}"
            copy.write_bytes(source.read_bytes())
            return copy

        service.export_file.side_effect = export
        service.file_metadata.return_value = metadata or {"load": 0x1900, "execute": 0x1900, "length": len(content)}
        service.editor_project.return_value = {}
        return folder, service

    def test_detects_and_decodes_tokenised_basic(self):
        program = tokenise('10 PRINT "HELLO"\n20 GOTO 10')
        folder, service = self.service_with_file(program)
        try:
            report = inspect_editable_file(service, SimpleNamespace(target_hardware="bbc", hfe_read_only=False, kind="dfs"), "$.GAME", None, None)
        finally:
            folder.cleanup()
        self.assertEqual(report["view"], "basic")
        self.assertTrue(report["editable"])
        self.assertIn('10 PRINT "HELLO"', report["text"])

    def test_listing_classifier_recognises_content_before_the_editor_opens_it(self):
        self.assertEqual(analyse_content(tokenise('10 PRINT "HELLO"'), "$.PROGRAM")[0], "basic")
        self.assertEqual(analyse_content(b"*DIR GAMES\rCHAIN \"MENU\"\r", "$.COMMANDS")[0], "script")
        self.assertEqual(analyse_content(b"A readable document\r", "$.NOTES")[0], "text")
        self.assertEqual(analyse_content(bytes.fromhex("A90020F4FF60"), "$.CODE")[0], "binary")
        self.assertEqual(analyse_content(minimal_uef(), "$.TAPE")[0], "container")

    def test_listing_classifier_uses_acorn_filetypes_without_reading_content(self):
        self.assertEqual(metadata_kind("PROGRAM", 0xFFB), "basic")
        self.assertEqual(metadata_kind("COMMANDS", 0xFEB), "script")
        self.assertEqual(metadata_kind("README", None), "text")

    def test_image_search_traverses_adfs_directories_and_reports_source_lines(self):
        service = Mock()
        service.list_directory.side_effect = lambda _session, path, _slot, _side: {
            "entries": (
                [{"name": "Games", "path": "$.Games", "type": "dir", "length": 0}]
                if path == "$" else
                [{"name": "!BOOT", "path": "$.Games.!BOOT", "type": "file", "length": 31}]
            )
        }
        service.read_file.return_value = b'*BASIC\rCHAIN "ARCADIANS"\r'
        report = search_image_files(
            service, SimpleNamespace(kind="adfs"), "arcadians", None, None, "$",
        )
        self.assertEqual(report["filesConsidered"], 1)
        self.assertEqual(report["results"][0]["path"], "$.Games.!BOOT")
        self.assertEqual(report["results"][0]["matches"][0]["line"], 2)

    def test_image_search_can_scan_every_populated_mmb_slot(self):
        service = Mock()
        service.list_slots.return_value = [
            {"slot": 0, "name": "ARCADIANS", "formatted": True},
            {"slot": 1, "name": "EMPTY", "formatted": False},
            {"slot": 2, "name": "REPTON", "formatted": True},
        ]
        service.list_dfs_catalogue_files.side_effect = lambda _session, slot, _side: [
            {"name": "!BOOT", "path": "$.!BOOT", "length": 20, "side": 0},
        ]
        service.read_file.side_effect = lambda _session, slot, _path, _side: (
            b'CHAIN "ARCADIANS"\r' if slot == 0 else b'CHAIN "REPTON"\r'
        )
        report = search_image_files(
            service, SimpleNamespace(kind="mmb"), "repton", None, None, "$", True,
        )
        self.assertTrue(report["allSlots"])
        self.assertEqual(report["filesConsidered"], 2)
        self.assertEqual(report["results"][0]["slot"], 2)
        self.assertEqual(report["results"][0]["diskTitle"], "REPTON")

    def test_basic_listing_always_has_a_space_after_the_line_number(self):
        self.assertEqual(
            _format_basic_listing('10PRINT "HELLO"\n20 GOTO 10\n30\tEND'),
            '10 PRINT "HELLO"\n20 GOTO 10\n30 END',
        )

    def test_basic_v_extended_tokens_open_read_only(self):
        program = bytes.fromhex("0d000a06c88e0dff")  # 10 CASE
        folder, service = self.service_with_file(program)
        try:
            report = inspect_editable_file(service, SimpleNamespace(target_hardware="risc-os", hfe_read_only=False, kind="adfs"), "$.PROGRAM", None, None)
        finally:
            folder.cleanup()
        self.assertEqual(report["view"], "basic")
        self.assertEqual(report["basic"]["dialect"], "BBC BASIC V")
        self.assertFalse(report["editable"])
        self.assertIn("CASE", report["text"])

    def test_boot_and_other_command_files_open_as_unnumbered_scripts(self):
        script = b'*BASIC\rPAGE=&E00\r*DIR GAMES\rCHAIN "MENU"\r'
        folder, service = self.service_with_file(script)
        try:
            report = inspect_editable_file(service, SimpleNamespace(hfe_read_only=False, kind="dfs"), "$.!BOOT", None, None)
        finally:
            folder.cleanup()
        self.assertEqual(report["view"], "script")
        self.assertTrue(report["editable"])
        self.assertFalse(report["tokenisedBasic"])
        self.assertEqual([item["action"] for item in report["script"]["commands"]], ["BASIC", "PAGE", "DIR", "CHAIN"])
        self.assertEqual(report["text"].splitlines()[0], "*BASIC")

        folder, service = self.service_with_file(b"*FX 200,3\r*RUN GAME\r")
        try:
            other = inspect_editable_file(service, SimpleNamespace(hfe_read_only=False, kind="dfs"), "$.COMMANDS", None, None)
        finally:
            folder.cleanup()
        self.assertEqual(other["view"], "script")

    def test_extensionless_uef_opens_as_a_browsable_container(self):
        folder, service = self.service_with_file(minimal_uef())
        try:
            report = inspect_editable_file(
                service,
                SimpleNamespace(target_hardware="electron", hfe_read_only=False, kind="adfs"),
                "$.UEF.THRUST", None, None,
            )
        finally:
            folder.cleanup()
        self.assertEqual(report["view"], "container")
        self.assertEqual(report["containerKind"], "uef")
        self.assertTrue(report["readOnly"])
        self.assertFalse(report["editable"])

    def test_renumber_updates_encoded_targets_not_string_contents(self):
        program = tokenise('10 GOTO 30\n20 PRINT "30"\n30 END')
        listing = detokenise(_renumber_tokenised(program, 100, 20))
        self.assertIn("100 GOTO 140", listing)
        self.assertIn('120 PRINT "30"', listing)
        self.assertIn("140 END", listing)

    def test_prepare_basic_renumbers_newly_edited_listing(self):
        result = prepare_basic_source('10 PRINT "A"\n15 GOSUB 10\n20 END', 1000, 10)
        self.assertEqual(result["lineCount"], 3)
        self.assertIn("1010 GOSUB 1000", result["text"])

    def test_normalise_basic_source_validates_and_formats_pasted_lines(self):
        result = normalise_basic_source('100PRINT "PASTED"\n110GOTO 100')
        self.assertEqual(result["lineCount"], 2)
        self.assertEqual(result["text"], '100 PRINT "PASTED"\n110 GOTO 100')

    def test_basic_verification_proves_token_round_trip_and_maps_lines(self):
        result = verify_basic_source('10 PRINT "HELLO"\n20 GOTO 10', '10 PRINT "OLD"')
        self.assertTrue(result["roundTripExact"])
        self.assertEqual(result["lineCount"], 2)
        self.assertEqual(result["destinations"], [10])
        self.assertEqual([row["line"] for row in result["lineRanges"]], [10, 20])
        self.assertTrue(result["diff"])

    def test_project_regions_override_code_and_apply_bookmarks(self):
        data = bytes.fromhex("A94120EEFF60") + b"HELLO"
        report = __import__("app.file_editor", fromlist=["disassemble_file_data"]).disassemble_file_data(
            data, {"load": 0x8000, "execute": 0x8000}, SimpleNamespace(target_hardware="bbc"),
            "$.CODE", project={
                "symbols": {"32768": "start_here"},
                "regions": [{"start": 6, "end": 11, "kind": "text", "name": "message", "width": 8}],
                "bookmarks": [{"offset": 0, "name": "entry", "note": "Reviewed entry"}],
                "comments": {"0": "User annotation"},
            },
        )
        self.assertEqual(report["rows"][0]["label"], "start_here")
        self.assertIn("Reviewed entry", report["rows"][0]["comment"])
        self.assertIn("User annotation", report["rows"][0]["comment"])
        message = next(row for row in report["rows"] if row.get("regionKind") == "text")
        self.assertEqual(message["label"], "message")
        self.assertEqual(message["mnemonic"], "EQUS")

    def test_68000_project_words_use_the_processor_byte_order(self):
        report = disassemble_file_data(
            bytes.fromhex("12344E75"), {"load": 0x8000, "execute": 0x8000},
            SimpleNamespace(target_hardware="archimedes"), "$.CODE", architecture="m68k",
            project={"regions": [{"start": 0, "end": 2, "kind": "words", "width": 8}]},
        )
        word = next(row for row in report["rows"] if row.get("regionKind") == "words")
        self.assertEqual(word["operand"], "&1234")

    def test_pack_basic_lines_uses_tokenised_line_capacity(self):
        statements = ['PRINT "A"'] * 80
        result = pack_basic_lines([statements, ["A=1", "B=2", "PRINT A+B"]])
        self.assertGreater(len(result["groups"][0]), 1)
        self.assertEqual(sum(result["groups"][0]), 80)
        self.assertEqual(result["groups"][1], [3])

    def test_binary_file_gets_annotated_6502_disassembly(self):
        folder, service = self.service_with_file(bytes.fromhex("20F4FFD0FB60"), {"load": 0x8000, "execute": 0x8000, "length": 6})
        try:
            report = disassemble_file(service, SimpleNamespace(target_hardware="bbc"), "$.CODE", None, None)
        finally:
            folder.cleanup()
        self.assertEqual(report["architecture"], "6502")
        self.assertIn("OSBYTE: the reason code in A could not be proved", report["rows"][0]["comment"])
        self.assertGreater(report["reachableInstructions"], 0)

    def test_printable_strings_require_human_looking_words(self):
        data = b"!!!!1234___\0Hello world!\0AB\0LOAD GAME\0hJJJJ)\0A1$%\0"
        strings = _printable_strings(data, 0x8000)
        self.assertEqual([item["text"] for item in strings], ["Hello world!", "LOAD GAME"])
        self.assertEqual(strings[0]["address"], 0x8000 + data.index(b"Hello"))

    def test_file_disassembly_marks_entry_point_and_readable_text(self):
        data = bytes.fromhex("4C0680") + b"ABC" + b"Hello world\0"
        folder, service = self.service_with_file(data, {"load": 0x8000, "execute": 0x8000, "length": len(data)})
        try:
            report = disassemble_file(service, SimpleNamespace(target_hardware="bbc"), "$.CODE", None, None)
        finally:
            folder.cleanup()
        self.assertEqual(report["rows"][0]["label"], "program_entry_8000")
        self.assertIn("File execution entry point", report["rows"][0]["comment"])
        text_row = next(row for row in report["rows"] if "Readable text begins here" in row["comment"])
        self.assertEqual(text_row["mnemonic"], "EQUS")
        self.assertEqual(text_row["operand"], '"ABC"')
        self.assertTrue(text_row["label"].startswith("text_abchello_world_"))
        self.assertIn("Hello world", text_row["comment"])
        target_row = next(row for row in report["rows"] if row["address"] == 0x8006)
        self.assertEqual(target_row["mnemonic"], "EQUS")
        self.assertEqual(target_row["operand"], '"Hello world"')
        self.assertEqual(target_row["label"], "text_hello_world_8006")
        self.assertEqual(report["rows"][0]["operand"], "text_hello_world_8006")

    def test_disassembly_assigns_semantic_routine_and_flow_labels(self):
        # Entry calls a small character-output routine. Its backwards branch is
        # separately labelled as a loop rather than an opaque loc_ address.
        data = bytes.fromhex("20078060EAEAEAA203A94120EEFFCAD0F860")
        folder, service = self.service_with_file(
            data, {"load": 0x8000, "execute": 0x8000, "length": len(data)}
        )
        try:
            report = disassemble_file(
                service, SimpleNamespace(target_hardware="bbc"), "$.CODE", None, None
            )
        finally:
            folder.cleanup()
        routine = next(row for row in report["rows"] if row["address"] == 0x8007)
        self.assertEqual(routine["label"], "write_text_8007")
        call = next(row for row in report["rows"] if row["address"] == 0x8000)
        self.assertEqual(call["operand"], "write_text_8007")
        self.assertIn("write_text_8007", call["comment"])
        loop = next(row for row in report["rows"] if row["address"] == 0x8009)
        self.assertEqual(loop["label"], "loop_8009")

    def test_basic_save_retokenises_and_preserves_acorn_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root / "work")
            session = service.create_blank("ssd", "EDITOR")
            source = root / "PROGRAM"
            source.write_bytes(tokenise('10 PRINT "OLD"'))
            service.put(session, None, "$.PROGRAM", source, "0x1900", "0x1900", None)
            service.set_access(session, None, ["$.PROGRAM"], writable=False)
            before = inspect_editable_file(service, session, "$.PROGRAM", None, None)

            save_editor_text(
                service, session, "$.PROGRAM", None, None,
                '10 PRINT "NEW"\n20 GOTO 10', True, before["sha256"],
            )

            self.assertIn('10 PRINT "NEW"', detokenise(service.read_file(session, None, "$.PROGRAM")))
            metadata = service.file_metadata(session, None, "$.PROGRAM")
            self.assertEqual(metadata["load"] & 0xFFFF, 0x1900)
            self.assertEqual(metadata["execute"] & 0xFFFF, 0x1900)
            self.assertTrue(metadata["access"] & 0x08)

    def test_basic_save_preserves_a_trailing_binary_payload(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root / "work")
            session = service.create_blank("ssd", "EDITOR")
            payload = bytes.fromhex("A90020EEFF60") + b"PAYLOAD\x00"
            source = root / "PROGRAM"
            source.write_bytes(tokenise('10 PRINT "OLD"') + payload)
            service.put(session, None, "$.PROGRAM", source, "0x1900", "0x1900", None)
            before = inspect_editable_file(service, session, "$.PROGRAM", None, None)

            self.assertTrue(before["editable"])
            self.assertTrue(before["basic"]["compound"])
            self.assertEqual(before["basic"]["trailingBytes"], len(payload))
            save_editor_text(
                service, session, "$.PROGRAM", None, None,
                '10 PRINT "NEW"\n20 END', True, before["sha256"],
            )

            stored = service.read_file(session, None, "$.PROGRAM")
            self.assertTrue(stored.endswith(payload))
            self.assertIn('10 PRINT "NEW"', detokenise(stored[:-len(payload)]))

    def test_save_as_creates_a_sibling_with_content_and_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root / "work")
            session = service.create_blank("ssd", "EDITOR")
            source = root / "PROGRAM"
            source.write_bytes(tokenise('10 PRINT "OLD"'))
            service.put(session, None, "$.PROGRAM", source, "0x1900", "0x1900", None)
            service.set_access(session, None, ["$.PROGRAM"], writable=False)
            before = inspect_editable_file(service, session, "$.PROGRAM", None, None)

            _image, saved_path = save_editor_text_as(
                service, session, "$.PROGRAM", None, None, "COPY",
                '10 PRINT "NEW"', True, before["sha256"],
            )

            self.assertEqual(saved_path, "$.COPY")
            self.assertIn('10 PRINT "NEW"', detokenise(service.read_file(session, None, "$.COPY")))
            metadata = service.file_metadata(session, None, "$.COPY")
            self.assertEqual(metadata["load"] & 0xFFFF, 0x1900)
            self.assertEqual(metadata["execute"] & 0xFFFF, 0x1900)
            self.assertTrue(metadata["access"] & 0x08)

    def test_file_hex_write_is_fixed_size_and_stale_guarded(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root / "work")
            session = service.create_blank("ssd", "EDITOR")
            source = root / "CODE"
            source.write_bytes(b"ABCDEF")
            service.put(session, None, "$.CODE", source, "0x8000", "0x8000", None)
            before = inspect_editable_file(service, session, "$.CODE", None, None)

            result = write_file_range(
                service, session, "$.CODE", None, None, before["sha256"],
                [{"offset": 1, "data": "7879"}], True,
            )

            self.assertEqual(result["written"], 2)
            self.assertEqual(service.read_file(session, None, "$.CODE"), b"AxyDEF")

    def test_file_properties_change_metadata_without_changing_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root / "work")
            session = service.create_blank("ssd", "EDITOR")
            source = root / "CODE"
            source.write_bytes(b"UNCHANGED")
            service.put(session, None, "$.CODE", source, "0x1900", "0x1900", None)
            before = inspect_editable_file(service, session, "$.CODE", None, None)

            update_file_properties(
                service, session, "$.CODE", None, None, before["sha256"],
                load="0x3000", execute="0x3003", writable=False,
            )

            self.assertEqual(service.read_file(session, None, "$.CODE"), b"UNCHANGED")
            metadata = service.file_metadata(session, None, "$.CODE")
            self.assertEqual(metadata["load"] & 0xFFFF, 0x3000)
            self.assertEqual(metadata["execute"] & 0xFFFF, 0x3003)
            self.assertTrue(metadata["access"] & 0x08)


if __name__ == "__main__":
    unittest.main()
