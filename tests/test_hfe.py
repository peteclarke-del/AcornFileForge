from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.disk_service import DiskError, DiskService, ImageSession
from app.hfe import HFEError, parse_hfe_header


def header(signature: bytes = b"HXCPICFE", revision: int = 0) -> bytes:
    data = bytearray(512)
    data[:8] = signature
    data[8] = revision
    data[9] = 80
    data[10] = 2
    data[11] = 2
    data[12:14] = (250).to_bytes(2, "little")
    return bytes(data)


class HFETests(unittest.TestCase):
    def test_v1_header_geometry_is_parsed(self) -> None:
        parsed = parse_hfe_header(header())
        self.assertEqual((parsed.version, parsed.tracks, parsed.sides), ("v1", 80, 2))
        self.assertFalse(parsed.advanced)

    def test_v2_and_v3_are_advanced(self) -> None:
        self.assertTrue(parse_hfe_header(header(revision=1)).advanced)
        self.assertEqual(parse_hfe_header(header(b"HXCHFEV3")).version, "v3")

    def test_invalid_signature_is_rejected(self) -> None:
        with self.assertRaisesRegex(HFEError, "valid HFE signature"):
            parse_hfe_header(header(b"NOTANHFE"))

    def test_hfe_extension_uses_container_decoder(self) -> None:
        self.assertEqual(DiskService.detect_kind("disk.hfe"), "hfe")

    def test_advanced_hfe_working_copy_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "decoded.ssd"
            image.write_bytes(b"")
            session = ImageSession(
                "a" * 32,
                "protected.hfe",
                "dfs",
                image,
                hfe_original_path=Path(folder) / "protected.hfe",
                hfe_version="v3",
                hfe_read_only=True,
            )
            with self.assertRaisesRegex(DiskError, "cannot be rewritten safely"):
                DiskService.require_writable_geometry(session)


if __name__ == "__main__":
    unittest.main()
