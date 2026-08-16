from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
from pathlib import Path

from app.checksum import sha256_bytes, sha256_path, sha256_stream


class SparseChecksumTests(unittest.TestCase):
    def test_in_memory_hash_matches_hashlib(self) -> None:
        data = b"Acorn File Forge"
        self.assertEqual(sha256_bytes(data), hashlib.sha256(data).hexdigest())

    def test_stream_hash_matches_hashlib_without_loading_a_path(self) -> None:
        data = (b"Acorn File Forge patch payload" * 1024) + b"!"
        self.assertEqual(sha256_stream(io.BytesIO(data)), hashlib.sha256(data).hexdigest())

    def test_sparse_file_hash_matches_ordinary_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sparse.dat"
            with path.open("wb") as image:
                image.write(b"ADFS")
                image.seek(16 * 1024 * 1024)
                image.write(b"catalogue")

            expected = hashlib.sha256(path.read_bytes()).hexdigest()

            self.assertEqual(sha256_path(path), expected)


if __name__ == "__main__":
    unittest.main()
