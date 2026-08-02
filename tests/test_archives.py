from __future__ import annotations

import io
import unittest
import zipfile
from types import SimpleNamespace

from app.archive_utils import iter_upload_images, open_single_upload_image
from app.disk_service import DiskError


def zip_upload(name: str, members: dict[str, bytes]):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for filename, data in members.items():
            archive.writestr(filename, data)
    stream.seek(0)
    return SimpleNamespace(filename=name, stream=stream)


class ArchiveTests(unittest.TestCase):
    def test_mmb_import_expands_every_supported_disk_and_ignores_extras(self):
        upload = zip_upload(
            "Games (1984)(Acornsoft).zip",
            {
                "README.txt": b"notes",
                "disks/Game A.ssd": b"A" * 204800,
                "disks/Game B.dsd": b"B" * 409600,
            },
        )

        items = [
            (item.filename, len(item.stream.read()), item.metadata_names)
            for item in iter_upload_images([upload], {".ssd", ".dsd"})
        ]

        self.assertEqual(
            items,
            [
                (
                    "Game A.ssd",
                    204800,
                    [
                        "disks/Game A.ssd",
                        "Games (1984)(Acornsoft).zip",
                    ],
                ),
                (
                    "Game B.dsd",
                    409600,
                    [
                        "disks/Game B.dsd",
                        "Games (1984)(Acornsoft).zip",
                    ],
                ),
            ],
        )

    def test_single_image_import_explains_a_multi_image_zip(self):
        upload = zip_upload(
            "two.zip",
            {"one.ssd": b"1", "two.ssd": b"2"},
        )

        with self.assertRaisesRegex(DiskError, "contains 2 supported images"):
            with open_single_upload_image(upload, {".ssd"}):
                pass


if __name__ == "__main__":
    unittest.main()
