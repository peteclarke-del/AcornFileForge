import io
import tempfile
import unittest
from pathlib import Path

from app.disk_service import DiskError, DiskService


class RomfsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.service = DiskService(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def _host_file(self, data=b"HELLO", name="host-file"):
        path = Path(self.temporary.name) / name
        path.write_bytes(data)
        return path

    def test_create_16k_romfs_has_standard_identity_and_capacity(self):
        session = self.service.create_blank(
            "romfs", "TOOLS", target_hardware="bbc-master",
            options={"geometry": "16k", "version": 7, "copyright": "(C) Test"},
        )
        self.assertEqual(session.kind, "romfs")
        self.assertEqual(session.path.stat().st_size, 16 * 1024)
        self.assertEqual(session.target_hardware, "bbc-master")
        details = self.service.romfs_details(session)
        self.assertEqual(details["title"], "TOOLS")
        self.assertEqual(details["version"], 7)
        self.assertEqual(details["copyright"], "(C) Test")
        self.assertFalse(details["readOnly"])
        self.assertGreater(details["capacity"]["free"], 0)
        self.assertIn("Valid ROMFS", self.service.validate(session, None))

    def test_opened_romfs_is_detected_before_raw_rom(self):
        created = self.service.create_blank("romfs", "FILES")
        reopened = self.service.create_from_stream(
            "files.rom", io.BytesIO(created.path.read_bytes())
        )
        self.assertEqual(reopened.kind, "romfs")
        self.assertIsNotNone(self.service.summary(reopened)["romfs"])

    def test_files_can_be_added_read_renamed_protected_and_deleted(self):
        session = self.service.create_blank("romfs", "FILES")
        self.service.put(
            session, None, "PROGRAM", self._host_file(b"DATA"),
            "0x1900", "0x1900", None,
        )
        row = self.service.list_directory(session, "$", None)["entries"][0]
        self.assertEqual(row["name"], "PROGRAM")
        self.assertEqual(row["load"], 0x1900)
        self.assertEqual(row["exec"], 0x1900)
        self.assertEqual(self.service.read_file(session, None, "PROGRAM"), b"DATA")

        metadata = self.service.set_file_addresses(
            session, None, "PROGRAM", "&FFFF3000", "0xFFFF8023",
        )
        self.assertEqual(metadata["load"], 0xFFFF3000)
        self.assertEqual(metadata["execute"], 0xFFFF8023)
        updated = self.service.list_directory(session, "$", None)["entries"][0]
        self.assertEqual(updated["load"], 0xFFFF3000)
        self.assertEqual(updated["exec"], 0xFFFF8023)
        self.assertEqual(self.service.read_file(session, None, "PROGRAM"), b"DATA")

        self.service.set_access(session, None, ["PROGRAM"], False)
        self.assertTrue(self.service.list_directory(session, "$", None)["entries"][0]["runOnly"])
        self.service.mutate(session, None, ["mv", "{image}:PROGRAM", "NEW.NAME"])
        self.assertEqual(self.service.list_directory(session, "$", None)["entries"][0]["name"], "NEW.NAME")
        self.service.mutate(session, None, ["rm", "--force", "{image}:NEW.NAME"])
        self.assertEqual(self.service.list_directory(session, "$", None)["entries"], [])

    def test_properties_rebuild_header_and_catalogue(self):
        session = self.service.create_blank("romfs", "OLD")
        self.service.set_romfs_properties(
            session, title="NEW", version=42, copyright_text="(C) Acorn",
        )
        details = self.service.romfs_details(session)
        self.assertEqual(details["title"], "NEW")
        self.assertEqual(details["version"], 42)
        self.assertEqual(details["copyright"], "(C) Acorn")
        self.assertIn("all block CRCs passed", self.service.validate(session, None))

    def test_failed_property_or_batch_write_restores_exact_rom(self):
        session = self.service.create_blank("romfs", "SAFE", options={"geometry": "8k"})
        original = session.path.read_bytes()
        with self.assertRaises(DiskError):
            self.service.set_romfs_properties(
                session, title="CHANGED", version=2,
                copyright_text="(C) " + "far too long " * 30,
            )
        self.assertEqual(session.path.read_bytes(), original)
        self.assertEqual(self.service.romfs_details(session)["title"], "SAFE")

        first = self._host_file(b"A" * 5000, "first")
        second = self._host_file(b"B" * 5000, "second")
        with self.assertRaises(DiskError):
            self.service.put_host_tree(
                session, None, "$",
                [
                    {"targetPath": "FIRST", "hostPath": first},
                    {"targetPath": "SECOND", "hostPath": second},
                ],
                preserve_directories=False,
            )
        self.assertEqual(session.path.read_bytes(), original)

    def test_romfs_name_and_shape_restrictions_are_explicit(self):
        session = self.service.create_blank("romfs", "FILES", options={"geometry": "8k"})
        self.assertEqual(session.path.stat().st_size, 8 * 1024)
        self.assertEqual(self.service.validate_leaf_name(session, "A.B/C"), "A.B/C")
        with self.assertRaisesRegex(DiskError, "at most 10"):
            self.service.validate_leaf_name(session, "ELEVENCHARS")
        with self.assertRaisesRegex(DiskError, "flat"):
            self.service.put_host_tree(
                session, None, "$", [{"targetPath": "folder/file", "hostPath": self._host_file()}],
                preserve_directories=True,
            )
        with self.assertRaisesRegex(DiskError, "does not need compaction"):
            self.service.compact(session, None)


if __name__ == "__main__":
    unittest.main()
