from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.streaming_zip import stream_stored_zip


class StreamingZipTests(unittest.TestCase):
    def test_streamed_archive_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "scsi0.dat"
            descriptor = root / "scsi0.dsc"
            image.write_bytes((b"ACORN" * 300_000) + b"end")
            descriptor.write_bytes(b"geometry")

            chunks = list(
                stream_stored_zip(
                    (
                        (image, f"BeebSCSI0/{image.name}"),
                        (descriptor, f"BeebSCSI0/{descriptor.name}"),
                    )
                )
            )

            self.assertGreater(len(chunks), 1)
            with zipfile.ZipFile(io.BytesIO(b"".join(chunks))) as archive:
                self.assertEqual(
                    archive.read(f"BeebSCSI0/{image.name}"),
                    image.read_bytes(),
                )
                self.assertEqual(
                    archive.read(f"BeebSCSI0/{descriptor.name}"),
                    b"geometry",
                )


if __name__ == "__main__":
    unittest.main()
