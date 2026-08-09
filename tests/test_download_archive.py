from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from app.disk_service import MMB_ENTRY_SIZE, MMB_HEADER_SIZE, MMB_SLOT_SIZE, DiskError, DiskService, ImageSession
from app.download_archive import build_download_archive, prepared_download


class DownloadArchiveTests(unittest.TestCase):
    @staticmethod
    def _mmb_session(root: Path) -> tuple[DiskService, ImageSession]:
        path = root / "games.mmb"
        header = bytearray(MMB_HEADER_SIZE)
        for slot in range(2):
            header[16 + slot * MMB_ENTRY_SIZE + 15] = 0xF0
        path.write_bytes(bytes(header) + bytes(MMB_SLOT_SIZE * 2))
        service = DiskService(root / "work")
        return service, ImageSession("a" * 32, path.name, "mmb", path, dirty=True)

    def test_prepare_builds_complete_archive_before_reporting_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service, session = self._mmb_session(Path(directory))
            progress = []

            archive_path, archive_name = build_download_archive(
                service,
                session,
                lambda message, current=None, total=None: progress.append(
                    (message, current, total)
                ),
            )

            self.assertTrue(archive_path.is_file())
            self.assertTrue(archive_name.startswith("games-"))
            self.assertEqual(progress[-1], (
                "The complete ZIP is ready to download", 100, 100,
            ))
            self.assertTrue(any(current and current >= 40 for _message, current, _total in progress))
            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual(archive.namelist(), ["README.md", "games.mmb"])
                self.assertEqual(archive.read("games.mmb"), session.path.read_bytes())

            self.assertEqual(prepared_download(session), (archive_path, archive_name))

    def test_prepared_archive_is_rejected_after_the_image_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service, session = self._mmb_session(Path(directory))
            build_download_archive(service, session)

            with session.path.open("r+b") as image:
                image.seek(MMB_HEADER_SIZE)
                image.write(b"changed")

            with self.assertRaisesRegex(DiskError, "changed afterward"):
                prepared_download(session)

    def test_sparse_beebscsi_archive_is_compressed_and_byte_exact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "scsi0.dat"
            descriptor = root / "scsi0.dsc"
            with image.open("wb") as output:
                output.write(b"ADFS")
                output.seek(32 * 1024 * 1024 - 1)
                output.write(b"\0")
            descriptor.write_bytes(b"geometry")
            service = DiskService(root / "work")
            service._optimise_sparse_file(image)
            service.prepare_download = lambda session, progress=None: image
            session = ImageSession(
                "b" * 32,
                image.name,
                "adfs",
                image,
                descriptor_name=descriptor.name,
                descriptor_path=descriptor,
            )

            def write_readme(_service, _session, _path, _generated, **_checksums):
                readme = root / "download-README.md"
                readme.write_text("test", encoding="utf-8")
                return readme

            with patch("app.download_archive.write_download_readme", write_readme):
                archive_path, _archive_name = build_download_archive(service, session)

            self.assertLess(archive_path.stat().st_size, 200_000)
            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual(
                    archive.read("BeebSCSI0/scsi0.dat"),
                    image.read_bytes(),
                )


if __name__ == "__main__":
    unittest.main()
