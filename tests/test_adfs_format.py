from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.adfs_format import probe_new_map_adfs
from app.disk_service import DiskError, DiskService


class NewMapADFSProbeTests(unittest.TestCase):
    @staticmethod
    def _write_e_image(path: Path, *, duplicate_record: bool = True) -> None:
        size = 800 * 1024
        data = bytearray(size)
        record = bytearray(60)
        record[0:12] = bytes((10, 5, 2, 2, 15, 7, 1, 0, 0, 1, 0x20, 0x05))
        record[12:15] = (0x0203).to_bytes(3, "little")
        record[16:20] = size.to_bytes(4, "little")
        record[20:22] = b"\x52\xbb"
        record[22:32] = b"Test      "
        data[4:64] = record
        if duplicate_record:
            data[1028:1088] = record
        path.write_bytes(data)

    @staticmethod
    def _write_f_image(path: Path) -> None:
        size = 1600 * 1024
        data = bytearray(size)
        record = bytearray(60)
        record[0:12] = bytes((10, 10, 2, 4, 15, 6, 1, 0, 0, 4, 0x40, 0x06))
        record[12:15] = (0x0209).to_bytes(3, "little")
        record[16:20] = size.to_bytes(4, "little")
        record[20:22] = b"\x7c\x06"
        record[22:32] = b"BlankF    "
        data[0xDC0 : 0xDC0 + 60] = record
        common_bits = 1024 * 8 - 0x640
        map_offset = ((common_bits - 60 * 8) + common_bits) * 64
        data[map_offset + 4 : map_offset + 64] = record
        data[map_offset + 4 * 1024 + 4 : map_offset + 4 * 1024 + 64] = record
        path.write_bytes(data)

    def test_recognises_matching_e_format_new_map_records(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "Example.adf"
            self._write_e_image(image)
            detected = probe_new_map_adfs(image)

        self.assertIsNotNone(detected)
        assert detected is not None
        self.assertEqual(detected.format_name, "E")
        self.assertEqual(detected.disc_name, "Test")
        self.assertEqual(detected.sector_size, 1024)

    def test_rejects_a_single_coincidental_disc_record(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "NotADisc.adf"
            self._write_e_image(image, duplicate_record=False)
            self.assertIsNone(probe_new_map_adfs(image))

    def test_recognises_f_record_at_the_middle_zone_map(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "BlankF.adf"
            self._write_f_image(image)
            detected = probe_new_map_adfs(image)

        self.assertIsNotNone(detected)
        assert detected is not None
        self.assertEqual(detected.format_name, "F")
        self.assertEqual(detected.zones, 4)
        self.assertEqual(detected.map_offset, 813056)

    def test_identification_error_names_the_unsupported_format(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image = root / "Example.adf"
            self._write_e_image(image)
            service = DiskService(root / "work")
            calls = []
            service._run_json = lambda args: (
                calls.append(args) or {"reports": {"candidates": {"rows": []}}}
            )

            with self.assertRaisesRegex(DiskError, r"valid ADFS E new-map image.*Oaknut.*without writable"):
                service.identify_kind(image)
            self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
