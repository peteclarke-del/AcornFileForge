from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from app.disk_service import DiskError, DiskService, ImageSession
from app.hex_service import compare_data, raw_image_range, search_raw_image, write_raw_image


class HexServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.service = DiskService(self.root / "work")
        self.path = self.root / "image.ssd"
        self.path.write_bytes(bytes(range(256)) + b"Disc catalogue" + bytes(range(256)))
        self.session = ImageSession("a" * 32, self.path.name, "dfs", self.path)

    def tearDown(self):
        self.temporary.cleanup()

    def test_reads_a_bounded_range_without_loading_the_complete_image(self):
        result = raw_image_range(self.session, 250, 16)

        self.assertEqual(result["offset"], 250)
        self.assertEqual(result["length"], 16)
        self.assertEqual(bytes.fromhex(result["data"]), self.path.read_bytes()[250:266])
        self.assertEqual(result["size"], self.path.stat().st_size)

    def test_searches_hex_and_text_in_both_directions(self):
        text = search_raw_image(self.session, "Disc", "text", 0, "forward", False)
        backward = search_raw_image(
            self.session, "44 69 73 63", "hex", self.path.stat().st_size - 1, "backward", False
        )

        self.assertEqual(text["offset"], 256)
        self.assertEqual(backward["offset"], 256)

        wrapped = search_raw_image(self.session, "Disc", "text", -1, "backward", True)
        self.assertEqual(wrapped["offset"], 256)
        self.assertTrue(wrapped["wrapped"])
        wrapped_forward = search_raw_image(self.session, "Disc catalogue", "text", 300, "forward", True)
        self.assertEqual(wrapped_forward["offset"], 256)
        self.assertTrue(wrapped_forward["wrapped"])

    def test_raw_write_requires_confirmation_and_current_version(self):
        version = raw_image_range(self.session, 0, 16)["version"]

        with self.assertRaisesRegex(DiskError, "confirmation"):
            write_raw_image(
                self.service, self.session, version, [{"offset": 4, "data": "AABB"}], False
            )
        with self.assertRaisesRegex(DiskError, "changed after"):
            write_raw_image(
                self.service, self.session, "stale", [{"offset": 4, "data": "AABB"}], True
            )

    def test_raw_write_is_fixed_size_and_invalidates_derived_state(self):
        version = raw_image_range(self.session, 0, 16)["version"]
        cached = self.root / "slot.ssd"
        cached.write_bytes(b"cached")
        self.session.slot_cache[3] = cached
        self.session.menu_scanned = True
        self.session.menu_entries = [{"title": "Old"}]

        result = write_raw_image(
            self.service,
            self.session,
            version,
            [{"offset": 4, "data": "AABB"}, {"offset": 10, "data": "CC"}],
            True,
        )

        self.assertEqual(result["written"], 3)
        self.assertEqual(self.path.read_bytes()[4:6], b"\xAA\xBB")
        self.assertEqual(self.path.stat().st_size, 256 + len(b"Disc catalogue") + 256)
        self.assertFalse(cached.exists())
        self.assertEqual(self.session.slot_cache, {})
        self.assertFalse(self.session.menu_scanned)
        self.assertIsNone(self.session.menu_entries)
        self.assertTrue(self.session.dirty)

    def test_raw_write_rejects_overlapping_or_extending_changes(self):
        version = raw_image_range(self.session, 0, 16)["version"]
        with self.assertRaisesRegex(DiskError, "overlap"):
            write_raw_image(
                self.service,
                self.session,
                version,
                [{"offset": 4, "data": "AABB"}, {"offset": 5, "data": "CC"}],
                True,
            )
        with self.assertRaisesRegex(DiskError, "boundary"):
            write_raw_image(
                self.service,
                self.session,
                version,
                [{"offset": self.path.stat().st_size, "data": "00"}],
                True,
            )

    def test_binary_comparison_reports_ranges_offsets_and_size(self):
        source = b"abcdefghi"
        candidate = b"abXXefgYY-extra"

        report = compare_data(source, BytesIO(candidate), len(candidate))

        self.assertEqual(report["count"], 10)
        self.assertEqual(report["differences"], [2, 3, 7, 8])
        self.assertEqual(report["ranges"], [[2, 3], [7, 8]])
        self.assertEqual(report["sourceSize"], len(source))
        self.assertEqual(report["candidateSize"], len(candidate))


if __name__ == "__main__":
    unittest.main()
