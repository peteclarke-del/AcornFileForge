from __future__ import annotations

import unittest

from app.disk_service import DiskService
from app.formats import ADFS_EXTENSIONS


class FormatTests(unittest.TestCase):
    def test_archimedes_and_raw_hard_drive_extensions_are_adfs(self):
        for extension in (".adf", ".hdf", ".hdd", ".img", ".raw", ".bin", ".dsk"):
            with self.subTest(extension=extension):
                self.assertIn(extension, ADFS_EXTENSIONS)
                self.assertEqual(DiskService.detect_kind(f"HardDisc4{extension}"), "adfs")

    def test_extensionless_images_are_content_detected(self):
        self.assertEqual(DiskService.detect_kind("HardDisc4"), "unknown")


if __name__ == "__main__":
    unittest.main()
