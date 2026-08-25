from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from app.disk_service import DiskService
from tests.generated_media import add_test_file, generated_media_matrix


class GeneratedMediaMatrixTests(unittest.TestCase):
    def test_every_core_format_is_generated_and_reopened_without_private_samples(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root / "work")
            media = generated_media_matrix(service)

            self.assertEqual(
                {item.format for item in media},
                {
                    "ssd", "dsd", "adfs-s", "adfs-m", "adfs-l", "adfs-d",
                    "adfs-e", "adfs-e-plus", "adfs-f", "adfs-f-plus", "adfs-g",
                    "adfs-g-plus", "mmb", "beebscsi", "rom", "romfs", "hfe", "uef",
                },
            )
            for item in media:
                self.assertTrue(item.session.path.is_file(), item.format)
                self.assertGreater(item.session.path.stat().st_size, 0, item.format)
                reopened = DiskService(root / "work").get(item.session.id)
                summary = service.summary(reopened)
                self.assertEqual(summary["id"], item.session.id)
                if reopened.kind == "mmb":
                    self.assertEqual(len(service.list_slots(reopened)), 511, item.format)
                else:
                    listing = service.browse_directory(reopened, "$", None)
                    self.assertIn("entries", listing, item.format)
                    self.assertEqual(listing["path"], "$", item.format)

    def test_generated_writable_filesystems_accept_and_return_known_content(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root / "work")
            for item in generated_media_matrix(service):
                if item.session.kind not in {"dfs", "adfs", "romfs"}:
                    continue
                path = "TEST" if item.session.kind == "romfs" else "$.TEST"
                add_test_file(service, item.session, root, path=path)
                self.assertEqual(
                    service.read_file(item.session, None, path),
                    b"Acorn File Forge generated fixture\r",
                    item.format,
                )

    def test_generated_mmb_uses_511_visible_empty_slots(self):
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(Path(folder) / "work")
            session = service.create_blank("mmb", "MATRIX")
            slots = service.list_slots(session)
            self.assertEqual(len(slots), 511)
            self.assertTrue(all(row["empty"] for row in slots))

    def test_filecore_variants_expose_their_real_directory_capabilities(self):
        expected = {
            "adfs-s": ("S", 10, 47),
            "adfs-m": ("M", 10, 47),
            "adfs-l": ("L", 10, 47),
            "adfs-d": ("D", 10, 77),
            "adfs-e": ("E", 10, 77),
            "adfs-e-plus": ("E+", 255, None),
            "adfs-f": ("F", 10, 77),
            "adfs-f-plus": ("F+", 255, None),
            "adfs-g": ("G", 10, 77),
            "adfs-g-plus": ("G+", 255, None),
        }
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(Path(folder) / "work")
            media = {item.format: item.session for item in generated_media_matrix(service)}
            for format_name, (label, name_limit, entry_limit) in expected.items():
                capabilities = service.summary(media[format_name])["filesystemCapabilities"]
                self.assertEqual(capabilities["format"], label, format_name)
                self.assertEqual(capabilities["nameLimit"], name_limit, format_name)
                self.assertEqual(capabilities["directoryEntryLimit"], entry_limit, format_name)

    def test_big_directories_round_trip_long_filenames_and_validate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root / "work")
            session = service.create_blank("adfs-e-plus", "BIGDIR")
            long_name = "A descriptive FileCore filename longer than ten characters"
            add_test_file(service, session, root, path=f"$.{long_name}")
            self.assertEqual(
                service.read_file(session, None, f"$.{long_name}"),
                b"Acorn File Forge generated fixture\r",
            )
            self.assertEqual(service.validate(session, None), "No structural errors found")

    def test_hdf_offset_layout_is_edited_without_moving_disc_address_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root / "work")
            source = service.create_blank("adfs-f", "OFFSETHDF")
            raw = source.path.read_bytes()
            hdf = raw[-0x200:] + raw[:-0x200]
            session = service.create_from_stream(
                "HardDisc4.hdf",
                io.BytesIO(hdf),
                target_hardware="risc-os",
            )
            payload = root / "offset-payload"
            payload.write_bytes(b"HDF offset preserved")
            service.put(session, None, "$.OFFSET", payload, "0x8000", "0x8000", None)

            self.assertEqual(service.read_file(session, None, "$.OFFSET"), b"HDF offset preserved")
            self.assertEqual(service.validate(session, None), "No structural errors found")
            self.assertEqual(session.path.read_bytes()[:0x200], hdf[:0x200])

    def test_generated_romfs_session_survives_service_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder) / "work"
            session = DiskService(work).create_blank("romfs", "RECOVER")
            restored = DiskService(work).get(session.id)
            self.assertEqual(restored.kind, "romfs")
            self.assertEqual(restored.name, session.name)


if __name__ == "__main__":
    unittest.main()
