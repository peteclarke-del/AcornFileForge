from __future__ import annotations

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
                {"ssd", "dsd", "adfs-s", "adfs-m", "adfs-l", "mmb", "beebscsi", "rom", "romfs", "hfe", "uef"},
            )
            for item in media:
                self.assertTrue(item.session.path.is_file(), item.format)
                self.assertGreater(item.session.path.stat().st_size, 0, item.format)
                reopened = DiskService(root / "work").get(item.session.id)
                summary = service.summary(reopened)
                self.assertEqual(summary["id"], item.session.id)

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

    def test_generated_romfs_session_survives_service_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder) / "work"
            session = DiskService(work).create_blank("romfs", "RECOVER")
            restored = DiskService(work).get(session.id)
            self.assertEqual(restored.kind, "romfs")
            self.assertEqual(restored.name, session.name)


if __name__ == "__main__":
    unittest.main()
