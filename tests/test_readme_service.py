from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.disk_service import MMB_HEADER_SIZE, MMB_SLOT_SIZE, DiskService, ImageSession
from app.readme_service import build_download_readme, timestamped_archive_name


class ReadmeServiceTests(unittest.TestCase):
    def test_archive_name_uses_image_stem_and_timestamp(self) -> None:
        generated = datetime(2026, 8, 1, 14, 5, 9, tzinfo=timezone.utc)

        self.assertEqual(
            timestamped_archive_name("Games.Library.mmb", generated),
            "Games.Library-20260801-140509.zip",
        )

    def test_mmb_readme_lists_formatted_and_empty_slots(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "library.mmb"
            header = bytearray(MMB_HEADER_SIZE)
            header[16:28] = b"MENU DISK   "
            header[31] = 0x0F
            header[32 + 15] = 0xF0
            path.write_bytes(bytes(header) + bytes(MMB_SLOT_SIZE * 2))
            session = ImageSession("a" * 32, path.name, "mmb", path)

            readme = build_download_readme(
                DiskService(folder),
                session,
                path,
                datetime(2026, 8, 1, tzinfo=timezone.utc),
            )

            self.assertIn("### Slot 000: MENU DISK", readme)
            self.assertIn("Access: **read/write**", readme)
            self.assertIn("### Slot 001: empty", readme)
            self.assertIn("### Slot 510: unavailable", readme)
            self.assertIn("Image SHA-256:", readme)


if __name__ == "__main__":
    unittest.main()
