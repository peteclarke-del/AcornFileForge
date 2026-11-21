"""Drive panes: Acorn layouts, disk detection, formatting and write-back.

The format and detection tests are pure. The round-trip tests drive the real
``gw`` through ``tests/fake_gw.py``, which treats a flux file as the disk in
the drive. They run when ``ACORN_TEST_GW`` names a working gw, or one is on
PATH, and are skipped otherwise.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask, jsonify

from acorn_greaseweazle import (
    DISK_FORMATS,
    DiskFormatError,
    GreaseweazleClient,
    classify,
    disk_format,
    format_for_image,
    parse_decode,
    parse_sector_total,
)
from acorn_greaseweazle.detect import TrackDecode
from app.disk_service import DiskError, DiskService
from app.operations import OperationRegistry
from app.physical_drive import physical_drive_summary
from app.routes.desktop import create_desktop_blueprint
from tests.test_greaseweazle import _Process

ROOT = Path(__file__).resolve().parent.parent


def _dfs_catalogue(sectors: int) -> bytes:
    track = bytearray(2560)
    track[0x106] = sectors >> 8
    track[0x107] = sectors & 0xFF
    return bytes(track)


def _adfs_map(sectors: int) -> bytes:
    track = bytearray(4096)
    track[0xFC:0xFF] = sectors.to_bytes(3, "little")
    return bytes(track)


class DiskFormatTests(unittest.TestCase):
    def _image(self, folder: str, name: str, data: bytes) -> Path:
        path = Path(folder) / name
        path.write_bytes(data)
        return path

    def test_every_layout_names_an_acorn_gw_definition(self) -> None:
        for layout in DISK_FORMATS.values():
            with self.subTest(layout=layout.identifier):
                self.assertTrue(layout.gw_format.startswith("acorn."))

    def test_short_capture_names_still_select_a_layout(self) -> None:
        self.assertEqual(disk_format("ssd").identifier, "dfs-80")
        self.assertEqual(disk_format("ADL").identifier, "adfs-l")
        with self.assertRaises(DiskFormatError):
            disk_format("amiga")

    def test_a_truncated_40_track_dfs_image_takes_its_size_from_the_catalogue(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = self._image(folder, "game.ssd", _dfs_catalogue(400) + bytes(5000))
            self.assertEqual(format_for_image(path).identifier, "dfs-40")
            path = self._image(folder, "big.dsd", _dfs_catalogue(800) + bytes(9000))
            self.assertEqual(format_for_image(path).identifier, "dfs-80-ds")

    def test_adf_images_are_identified_by_size(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(format_for_image(self._image(folder, "e.adf", bytes(819_200))).identifier, "adfs-800")
            self.assertEqual(format_for_image(self._image(folder, "f.adf", bytes(1_638_400))).identifier, "adfs-1600")
            with self.assertRaisesRegex(DiskFormatError, "not an ADFS floppy size"):
                format_for_image(self._image(folder, "odd.adf", bytes(1000)))

    def test_flux_images_need_no_layout(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(format_for_image(self._image(folder, "disk.scp", b"SCP")))


def _decode(*tracks: tuple[int, int, int, int], foreign: dict | None = None) -> TrackDecode:
    return TrackDecode(
        {(cylinder, head): (found, total) for cylinder, head, found, total in tracks},
        {key: frozenset(value) for key, value in (foreign or {}).items()},
    )


class DetectionTests(unittest.TestCase):
    def test_gw_track_results_are_parsed(self) -> None:
        decode = parse_decode(
            "T0.0: IBM FM (10/10 sectors) from Raw Flux (56788 flux in 400.00ms)\n"
            "T0.1: IBM MFM (3/16 sectors) from Raw Flux (9 flux in 400.00ms)\n"
            "T2.0: Ignoring unexpected sector C:1 H:0 R:0 N:1\n"
        )
        self.assertTrue(decode.complete(0, 0))
        self.assertFalse(decode.complete(0, 1))
        self.assertEqual(decode.foreign_cylinders[(2, 0)], frozenset({1}))
        self.assertEqual(parse_sector_total("x\nFound 395 sectors of 400 (98%)\n"), (395, 400))

    def test_a_double_sided_80_track_dfs_disk(self) -> None:
        result = classify(
            {"dfs": _decode((0, 0, 10, 10), (0, 1, 10, 10), (2, 0, 10, 10))},
            {"dfs": (_dfs_catalogue(800), _dfs_catalogue(800))},
        )
        self.assertEqual((result.status, result.disk_format.identifier, result.step), ("formatted", "dfs-80-ds", 1))

    def test_a_40_track_dfs_disk_in_an_80_track_drive_double_steps(self) -> None:
        result = classify(
            {"dfs": _decode((0, 0, 10, 10), (2, 0, 0, 10), foreign={(2, 0): {1}})},
            {"dfs": (_dfs_catalogue(400), b"")},
        )
        self.assertEqual((result.disk_format.identifier, result.step), ("dfs-40", 2))

    def test_a_40_track_disk_in_a_40_track_drive_single_steps(self) -> None:
        result = classify(
            {"dfs": _decode((0, 0, 10, 10), (2, 0, 10, 10))},
            {"dfs": (_dfs_catalogue(400), b"")},
        )
        self.assertEqual(result.step, 1)

    def test_old_map_adfs_sizes_come_from_the_free_space_map(self) -> None:
        for sectors, expected in ((640, "adfs-s"), (1280, "adfs-m"), (2560, "adfs-l")):
            with self.subTest(expected=expected):
                result = classify(
                    {"adfs-old": _decode((0, 0, 16, 16), (2, 0, 16, 16))},
                    {"adfs-old": (_adfs_map(sectors), b"")},
                )
                self.assertEqual(result.disk_format.identifier, expected)

    def test_1024_byte_sector_disks_are_identified_by_encoding(self) -> None:
        self.assertEqual(
            classify({"adfs-800": _decode((0, 0, 5, 5))}, {}).disk_format.identifier, "adfs-800"
        )
        self.assertEqual(
            classify({"adfs-1600": _decode((0, 0, 10, 10))}, {}).disk_format.identifier, "adfs-1600"
        )

    def test_a_disk_with_no_sector_headers_is_unformatted(self) -> None:
        result = classify({"dfs": _decode((0, 0, 0, 10)), "adfs-old": _decode((0, 0, 0, 16))}, {})
        self.assertEqual(result.status, "unformatted")
        self.assertIsNone(result.disk_format)

    def test_a_disk_with_foreign_sectors_asks_for_the_format(self) -> None:
        result = classify({"dfs": _decode((0, 0, 0, 10), foreign={(0, 0): {7}})}, {})
        self.assertEqual(result.status, "unrecognised")
        self.assertEqual(set(result.candidates), set(DISK_FORMATS))

    def test_a_dfs_disk_without_a_track_count_offers_both_dfs_layouts(self) -> None:
        result = classify({"dfs": _decode((0, 0, 10, 10))}, {"dfs": (_dfs_catalogue(0), b"")})
        self.assertEqual(result.status, "unrecognised")
        self.assertEqual(result.candidates, ("dfs-40", "dfs-80"))


class CommandLineTests(unittest.TestCase):
    """gw must never be left to guess a layout from a file suffix."""

    @patch("acorn_greaseweazle.client.subprocess.Popen")
    @patch("acorn_greaseweazle.client.subprocess.run")
    def test_a_write_names_its_layout_and_pads_a_truncated_image(self, run, popen) -> None:
        run.return_value = subprocess.CompletedProcess(["gw"], 0, "Device: Greaseweazle")
        seen = {}

        def started(command, **_kwargs):
            seen["command"] = command
            seen["size"] = Path(command[-1]).stat().st_size
            return _Process("T0.0: Writing\nAll tracks verified\n")

        popen.side_effect = started
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "game.ssd"
            image.write_bytes(_dfs_catalogue(400) + bytes(2560))
            result = GreaseweazleClient("gw").write(image, "A", step=2)
            self.assertEqual(image.stat().st_size, 5120, "the source image is left alone")
            self.assertEqual([item.name for item in Path(folder).iterdir()], ["game.ssd"])
        self.assertIn("--format=acorn.dfs.ss", seen["command"])
        self.assertIn("--tracks=step=2", seen["command"])
        self.assertEqual(seen["size"], DISK_FORMATS["dfs-40"].size)
        self.assertEqual((result.disk_format, result.step), ("dfs-40", 2))

    @patch("acorn_greaseweazle.client.subprocess.Popen")
    @patch("acorn_greaseweazle.client.subprocess.run")
    def test_an_adf_read_names_its_layout(self, run, popen) -> None:
        run.return_value = subprocess.CompletedProcess(["gw"], 0, "Device: Greaseweazle")

        def started(command, **_kwargs):
            Path(command[-1]).write_bytes(bytes(819_200))
            started.command = command
            return _Process("Found 800 sectors of 800 (100%)\n")

        popen.side_effect = started
        with tempfile.TemporaryDirectory() as folder:
            result = GreaseweazleClient("gw").read(
                Path(folder) / "disk.adf", "A", disk_format=DISK_FORMATS["adfs-800"]
            )
        self.assertIn("--format=acorn.adfs.800", started.command)
        self.assertEqual((result.sectors_found, result.missing_sectors), (800, 0))


def _working_gw() -> str | None:
    candidate = os.environ.get("ACORN_TEST_GW") or shutil.which("gw")
    if not candidate:
        return None
    try:
        probe = subprocess.run(
            [candidate, "convert", "--help"], capture_output=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return candidate if probe.returncode == 0 else None


REAL_GW = _working_gw()


@unittest.skipUnless(REAL_GW and shutil.which("disc"), "needs a working gw and the disc engine")
class DrivePaneRoundTripTests(unittest.TestCase):
    """Open, edit and write back through the routes, against a simulated drive."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        folder = Path(self.temporary.name)
        self.disk = folder / "drive.scp"
        wrapper = folder / "gw"
        wrapper.write_text(
            "#!/bin/sh\n"
            f'FAKE_GW_REAL="{REAL_GW}" FAKE_GW_DISK="{self.disk}" '
            f'exec "{sys.executable}" "{ROOT / "tests" / "fake_gw.py"}" "$@"\n'
        )
        wrapper.chmod(0o755)
        self.service = DiskService(folder / "work")
        app = Flask(__name__)
        patcher = patch(
            "app.routes.desktop.GreaseweazleClient",
            side_effect=lambda *a, **k: GreaseweazleClient(str(wrapper)),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        app.register_blueprint(create_desktop_blueprint(self.service, OperationRegistry()))

        @app.errorhandler(DiskError)
        def _disk_error(error):
            return jsonify(error=str(error)), 400

        self.client = app.test_client()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _post(self, url: str, **body):
        response = self.client.post(url, json=body)
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def _probe(self) -> dict:
        return self._post("/api/desktop/drive/probe", drive="A")["detection"]

    def test_a_blank_disk_is_offered_for_formatting_and_only_formatted_on_request(self) -> None:
        self.assertEqual(self._probe()["status"], "unformatted")
        blank = self.disk.read_bytes()
        refused = self.client.post(
            "/api/desktop/drive/format", json={"drive": "A", "format": "adfs-l", "step": 1}
        )
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(self.disk.read_bytes(), blank, "nothing is written without confirmation")
        image = self._post(
            "/api/desktop/drive/format", drive="A", format="adfs-l", step=1, title="Blank", confirm=True
        )["image"]
        self.assertEqual(image["physicalDrive"]["format"]["id"], "adfs-l")
        self.assertFalse(image["physicalDrive"]["unwritten"])
        detection = self._probe()
        self.assertEqual((detection["status"], detection["format"]["id"]), ("formatted", "adfs-l"))

    def test_edits_stay_in_the_pane_until_written(self) -> None:
        for layout in ("dfs-80", "dfs-40-ds", "adfs-m", "adfs-800"):
            with self.subTest(layout=layout):
                self.disk.unlink(missing_ok=True)
                self._post("/api/desktop/drive/format", drive="A", format=layout, step=1, title="T", confirm=True)
                detection = self._probe()
                self.assertEqual(detection["format"]["id"], layout)
                image = self._post(
                    "/api/desktop/drive/open", drive="A", format=layout, step=detection["step"]
                )["image"]
                session = self.service.get(image["id"])
                before = self.disk.read_bytes()
                session.path.write_bytes(_patched(session.path.read_bytes()))
                self.assertTrue(physical_drive_summary(session)["unwritten"])
                self.assertEqual(self.disk.read_bytes(), before, "editing never touches the disk")
                written = self._post(f"/api/desktop/images/{image['id']}/drive/write")
                self.assertTrue(written["result"]["verified"])
                self.assertFalse(written["image"]["physicalDrive"]["unwritten"])
                again = self._post("/api/desktop/drive/open", drive="A", format=layout, step=detection["step"])
                reread = self.service.get(again["image"]["id"]).path.read_bytes()
                self.assertEqual(reread[: session.path.stat().st_size], session.path.read_bytes())


def _patched(data: bytes) -> bytes:
    """Change a byte well past the catalogue so the image differs from the disk."""
    changed = bytearray(data)
    changed[3000] ^= 0xFF
    return bytes(changed)


if __name__ == "__main__":
    unittest.main()
