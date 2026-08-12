import gzip
import io
import tarfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

from app.archive_browser import (
    ArchiveError,
    archive_member_editable,
    list_archive,
    read_archive_member,
    replace_archive_member,
)
from tests.uef_fixture import minimal_uef

try:
    from flask import Flask, jsonify
    from app.disk_service import DiskError
    from app.operations import OperationRegistry
    from app.routes.files import create_files_blueprint
    from app.routes.hex_editor import create_hex_editor_blueprint
except ModuleNotFoundError:  # Flask is installed in the production image.
    Flask = None


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

    def test_uef_member_replacement_is_refused_without_rebuilding_tape_timing(self):
        data = minimal_uef()
        self.assertFalse(archive_member_editable(data, "tape.uef"))
        with self.assertRaisesRegex(ArchiveError, "UEF members remain read-only"):
            replace_archive_member(data, "tape.uef", "THRUST", b"replacement")

    def test_unsafe_parent_members_are_rejected(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("../escape", b"bad")
        with self.assertRaises(ArchiveError):
            list_archive(stream.getvalue(), "unsafe.zip")

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
                kind="adfs", target_hardware="bbc", hfe_read_only=False,
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
        self.assertEqual(service.written[:5], ("$.Games.NEWFILE", b"", "00000000", "00000000", None))


if __name__ == "__main__":
    unittest.main()
