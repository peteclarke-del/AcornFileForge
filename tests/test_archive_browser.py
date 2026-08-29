import gzip
import io
import struct
import tarfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

from app.archive_browser import (
    ArchiveError,
    MAX_ENTRIES,
    archive_member_editable,
    list_archive,
    preview_archive_member_replacement,
    read_archive_member_details,
    replace_archive_member,
)
from tests.uef_fixture import minimal_uef
from app.uef import uef_project

try:
    from flask import Flask, jsonify
    from app.disk_service import DiskError
    from app.operations import OperationRegistry
    from app.routes.files import create_files_blueprint
    from app.routes.hex_editor import create_hex_editor_blueprint
    from app.routes.tools import create_tools_blueprint
except ModuleNotFoundError:  # Flask is installed in the production image.
    Flask = None


def read_archive_member(data: bytes, filename: str, member_name: str) -> bytes:
    """Read one member's bytes, discarding the metadata the tests do not assert."""
    return read_archive_member_details(data, filename, member_name)[0]


class ArchiveBrowserTests(unittest.TestCase):
    def test_zip_is_presented_as_a_safe_hierarchy(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("Games/Arcadians/!BOOT", b"*BASIC\r")
            archive.writestr("Games/README", b"Games collection")
        root = list_archive(stream.getvalue(), "collection.zip")
        self.assertEqual(root["entries"], [{
            "name": "Games", "type": "dir", "length": 0,
            "attr": "RO", "archiveEntry": True,
        }])
        games = list_archive(stream.getvalue(), "collection.zip", "Games")
        self.assertEqual([row["name"] for row in games["entries"]], ["Arcadians", "README"])
        self.assertEqual(games["entries"][1]["contentKind"], "text")
        boot = list_archive(stream.getvalue(), "collection.zip", "Games/Arcadians")
        self.assertEqual(boot["entries"][0]["contentKind"], "script")
        self.assertEqual(read_archive_member(stream.getvalue(), "collection.zip", "Games/README"), b"Games collection")

    def test_companion_inf_and_spark_metadata_are_exposed_by_archive_members(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("Games/PROGRAM", b"payload")
            archive.writestr("Games/PROGRAM.inf", b"R.PROGRAM FFFF1900 FFFF8023 00000007 Locked\n")
        listing = list_archive(stream.getvalue(), "collection.zip", "Games")
        program = next(row for row in listing["entries"] if row["name"] == "PROGRAM")
        self.assertEqual(program["load"], 0xFFFF1900)
        self.assertEqual(program["exec"], 0xFFFF8023)
        _content, metadata = read_archive_member_details(
            stream.getvalue(), "collection.zip", "Games/PROGRAM",
        )
        self.assertTrue(metadata["metadataAvailable"])
        self.assertEqual(metadata["load"], 0xFFFF1900)

    def test_companion_inf_accepts_locked_without_a_length_field(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("PROGRAM", b"payload")
            archive.writestr("PROGRAM.inf", b"$.PROGRAM FF1900 FF8023 Locked\n")
        _content, metadata = read_archive_member_details(
            stream.getvalue(), "collection.zip", "PROGRAM",
        )
        self.assertEqual(metadata["access"], 0x08)

    def test_tar_and_standalone_gzip_are_supported(self):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            info = tarfile.TarInfo("Docs/Manual")
            info.size = 6
            archive.addfile(info, io.BytesIO(b"Manual"))
        self.assertEqual(read_archive_member(stream.getvalue(), "docs.tar", "Docs/Manual"), b"Manual")
        compressed = gzip.compress(b"10 PRINT \"HELLO\"\r")
        listing = list_archive(compressed, "HELLO.bas.gz")
        self.assertEqual(listing["entries"][0]["name"], "HELLO.bas")
        self.assertEqual(read_archive_member(compressed, "HELLO.bas.gz", "HELLO.bas"), b"10 PRINT \"HELLO\"\r")

    def test_editable_archives_are_rebuilt_with_only_the_selected_member_changed(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.comment = b"kept"
            archive.writestr("Docs/README", b"Old")
            archive.writestr("Docs/OTHER", b"Untouched")
        rebuilt = replace_archive_member(stream.getvalue(), "docs.zip", "Docs/README", b"New text")
        self.assertTrue(archive_member_editable(rebuilt, "docs.zip"))
        with zipfile.ZipFile(io.BytesIO(rebuilt)) as archive:
            self.assertEqual(archive.comment, b"kept")
            self.assertEqual(archive.read("Docs/README"), b"New text")
            self.assertEqual(archive.read("Docs/OTHER"), b"Untouched")

        compressed = gzip.compress(b"Before")
        rebuilt = replace_archive_member(compressed, "README.gz", "README", b"After")
        self.assertEqual(gzip.decompress(rebuilt), b"After")

    def test_uef_member_replacement_requires_same_length_and_preserves_tape_structure(self):
        data = minimal_uef()
        self.assertTrue(archive_member_editable(data, "tape.uef", "THRUST"))
        with self.assertRaisesRegex(ArchiveError, "requires exactly 18 bytes"):
            replace_archive_member(data, "tape.uef", "THRUST", b"replacement")
        replacement = b'10 PRINT "REPTON"\r'
        self.assertEqual(len(replacement), len(b'10 PRINT "THRUST"\r'))
        preview = preview_archive_member_replacement(data, "tape.uef", "THRUST", replacement)
        self.assertTrue(preview["sameLength"])
        self.assertTrue(preview["chunkOrderPreserved"])
        self.assertEqual(len(preview["changedBlocks"]), 1)
        rebuilt = replace_archive_member(data, "tape.uef", "THRUST", replacement)
        self.assertEqual(read_archive_member(rebuilt, "tape.uef", "THRUST"), replacement)

    def test_uef_rebuild_preserves_unknown_chunks_and_split_standard_data(self):
        source = minimal_uef()
        chunk_id, length = struct.unpack_from("<HI", source, 12)
        body = source[18:18 + length]
        unknown = b"private control bytes"
        split = 17
        data = (
            source[:12]
            + struct.pack("<HI", 0x0F10, len(unknown)) + unknown
            + struct.pack("<HI", chunk_id, split) + body[:split]
            + struct.pack("<HI", chunk_id, len(body) - split) + body[split:]
        )
        replacement = b'10 PRINT "REPTON"\r'
        preview = preview_archive_member_replacement(data, "split.uef", "THRUST", replacement)
        self.assertEqual([row["id"] for row in preview["chunks"]], ["&0F10", "&0100", "&0100"])
        self.assertFalse(preview["chunks"][0]["changed"])
        rebuilt = replace_archive_member(data, "split.uef", "THRUST", replacement)
        self.assertIn(struct.pack("<HI", 0x0F10, len(unknown)) + unknown, rebuilt)
        self.assertEqual(read_archive_member(rebuilt, "split.uef", "THRUST"), replacement)

    def test_compressed_uef_rebuild_remains_compressed_and_readable(self):
        data = gzip.compress(minimal_uef(), mtime=123)
        replacement = b'10 PRINT "REPTON"\r'
        rebuilt = replace_archive_member(data, "tape.uef", "THRUST", replacement)
        self.assertTrue(rebuilt.startswith(b"\x1f\x8b"))
        self.assertEqual(read_archive_member(rebuilt, "tape.uef", "THRUST"), replacement)

    def test_uef_project_lists_physical_chunks_and_safe_member_policy(self):
        project = uef_project(minimal_uef())
        self.assertEqual(project["schema"], "acorn-file-forge/uef-project/v1")
        self.assertEqual(project["chunks"][0]["kind"], "Implicit start/stop-bit data")
        self.assertEqual(project["files"][0]["name"], "THRUST")
        self.assertTrue(project["files"][0]["editable"])

    def test_unsafe_parent_members_are_rejected(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("../escape", b"bad")
        with self.assertRaises(ArchiveError):
            list_archive(stream.getvalue(), "unsafe.zip")

    def test_oversized_archive_inventory_is_rejected_before_member_reads(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            for index in range(MAX_ENTRIES + 1):
                archive.writestr(f"empty-{index}", b"")
        with self.assertRaisesRegex(ArchiveError, "more than"):
            list_archive(stream.getvalue(), "too-many.zip")

    def test_raw_and_compressed_uef_are_browsable_tape_containers(self):
        raw = minimal_uef()
        for data, filename in ((raw, "THRUST"), (gzip.compress(raw), "THRUST")):
            listing = list_archive(data, filename)
            self.assertEqual(listing["archiveKind"], "uef")
            self.assertIn("tape container", listing["description"])
            self.assertEqual(listing["entries"][0]["name"], "THRUST")
            self.assertEqual(listing["entries"][0]["load"], 0x1900)
            self.assertEqual(listing["entries"][0]["exec"], 0x1900)
            self.assertTrue(listing["entries"][0]["complete"])
            self.assertEqual(listing["entries"][0]["contentKind"], "text")
            self.assertEqual(read_archive_member(data, filename, "THRUST"), b'10 PRINT "THRUST"\r')

    @unittest.skipIf(Flask is None, "Flask is installed in the production image")
    def test_archive_routes_mark_browse_and_download_members(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("Games/README", b"Games collection")
            archive.writestr("Games/!BOOT", b"*BASIC\rPAGE=&E00\r")
            archive.writestr("Games/CODE", bytes.fromhex("A90020F4FF60"))

        class Service:
            session = SimpleNamespace(
                kind="adfs", target_hardware="bbc", hardware_profile={}, hfe_read_only=False,
            )
            written = None

            def get(self, _image_id):
                return self.session

            def browse_directory(self, *_args):
                return {"entries": [{"name": "games.zip", "type": "file", "length": len(stream.getvalue())}]}

            def file_metadata(self, *_args):
                return {"length": len(stream.getvalue())}

            def read_file(self, *_args):
                return stream.getvalue()

            def validate_leaf_name(self, _session, name, _slot=None):
                if not name or len(name) > 10:
                    raise DiskError("Invalid ADFS filename.")
                return name

            def list_directory(self, *_args):
                return {"entries": []}

            def put(self, _session, _slot, destination, host_path, load, execute, filetype, side):
                self.written = (destination, host_path.read_bytes(), load, execute, filetype, side)

            def summary(self, _session):
                return {"id": "test", "kind": "adfs"}

        service = Service()
        app = Flask(__name__)
        app.register_blueprint(create_files_blueprint(service, Path("/tmp"), OperationRegistry()))
        app.register_blueprint(create_hex_editor_blueprint(service))
        app.register_blueprint(create_tools_blueprint(service, OperationRegistry()))
        app.register_error_handler(DiskError, lambda error: (jsonify(error=str(error)), 400))
        client = app.test_client()
        tree = client.get("/api/images/test/tree?path=$").get_json()
        self.assertTrue(tree["entries"][0]["archive"])
        listing = client.get("/api/images/test/archive/tree?path=$.games.zip&name=games.zip").get_json()
        self.assertEqual(listing["entries"][0]["name"], "Games")
        member = client.get("/api/images/test/archive/file?path=$.games.zip&name=games.zip&member=Games/README")
        self.assertEqual(member.data, b"Games collection")
        inspected = client.get(
            "/api/images/test/archive/inspect?path=$.games.zip&name=games.zip&member=Games/!BOOT"
        ).get_json()
        self.assertEqual(inspected["view"], "script")
        self.assertFalse(inspected["readOnly"])
        self.assertTrue(inspected["archiveEditable"])
        self.assertIn("PAGE=&E00", inspected["text"])
        disassembly = client.get(
            "/api/images/test/archive/disassembly?path=$.games.zip&name=games.zip"
            "&member=Games/CODE&architecture=6502&origin=0x8000"
        ).get_json()
        self.assertEqual(disassembly["architecture"], "6502")
        self.assertEqual(disassembly["origin"], 0x8000)
        cheat_report = client.get(
            "/api/images/test/cheat-candidates?path=$.games.zip&name=games.zip"
            "&member=Games/CODE"
        ).get_json()
        self.assertEqual(cheat_report["path"], "Games/CODE")
        self.assertEqual(cheat_report["kind"], "6502")
        hex_page = client.get(
            "/api/images/test/archive-hex?path=$.games.zip&name=games.zip"
            "&member=Games/CODE&offset=0&length=16"
        ).get_json()
        self.assertEqual(hex_page["data"], "A90020F4FF60")
        self.assertTrue(hex_page["readOnly"])
        found = client.get(
            "/api/images/test/archive-hex/search?path=$.games.zip&name=games.zip"
            "&member=Games/CODE&query=20F4FF&mode=hex&start=0"
        ).get_json()
        self.assertEqual(found["offset"], 2)
        created = client.post("/api/images/test/empty-file", json={
            "destination": "$.Games", "name": "NEWFILE",
            "load": "00000000", "execute": "00000000",
        })
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.get_json()["path"], "$.Games.NEWFILE")
        # Addresses typed by a person are normalised to the engine's explicit
        # hexadecimal form, so no unprefixed value can be read as decimal.
        self.assertEqual(service.written[:5], ("$.Games.NEWFILE", b"", "0x0", "0x0", None))


if __name__ == "__main__":
    unittest.main()
