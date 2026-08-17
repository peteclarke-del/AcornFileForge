from __future__ import annotations

import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from acorn_greaseweazle import (
    GreaseweazleClient,
    GreaseweazleError,
    ProbeResult,
    WriteResult,
    image_format,
    stable_snapshot,
)

try:
    from flask import Flask, jsonify
    from app.disk_service import DiskError
    from app.image_session import ImageSession
    from app.routes.desktop import create_desktop_blueprint
except ModuleNotFoundError:
    Flask = create_desktop_blueprint = None


class _Process:
    def __init__(self, output: str, return_code: int = 0) -> None:
        self.stdout = io.StringIO(output)
        self.return_code = return_code
        self.terminated = False

    def wait(self, timeout=None):
        return self.return_code

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.terminated = True


class GreaseweazleTests(unittest.TestCase):
    def test_supported_formats_apply_correct_verification_policy(self) -> None:
        self.assertTrue(image_format("game.ssd").automatic_verification)
        self.assertTrue(image_format("utilities.ADL").automatic_verification)
        self.assertFalse(image_format("preserved.hfe").automatic_verification)
        with self.assertRaisesRegex(GreaseweazleError, "not a floppy image"):
            image_format("scsi0.dat")

    def test_snapshot_has_stable_bytes_and_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "game.ssd"
            source.write_bytes(b"original")
            with stable_snapshot(source, temporary) as snapshot:
                source.write_bytes(b"changed")
                self.assertEqual(snapshot.read_bytes(), b"original")
                snapshot_path = snapshot
            self.assertFalse(snapshot_path.exists())

    @patch("acorn_greaseweazle.client.subprocess.Popen")
    @patch("acorn_greaseweazle.client.subprocess.run")
    def test_sector_image_requires_and_reports_verification(self, run, popen) -> None:
        run.return_value = subprocess.CompletedProcess(["gw", "info"], 0, "Device: Greaseweazle")
        popen.return_value = _Process(
            "Writing c=0-1:h=0-1\nT0.0: Written and verified\nT0.1: Written and verified\n"
            "T1.0: Written and verified\nT1.1: Written and verified\nAll tracks verified\n"
        )
        progress = Mock()
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "game.ssd"
            image.write_bytes(b"disk")
            result = GreaseweazleClient("/usr/bin/gw").write(image, "A", progress)

        self.assertTrue(result.verified)
        self.assertTrue(result.verification_supported)
        self.assertEqual(result.tracks_written, 4)
        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0][:3], ["/usr/bin/gw", "write", "--drive=A"])

    @patch("acorn_greaseweazle.client.subprocess.Popen")
    @patch("acorn_greaseweazle.client.subprocess.run")
    def test_hfe_can_complete_with_explicitly_unavailable_verification(self, run, popen) -> None:
        run.return_value = subprocess.CompletedProcess(["gw", "info"], 0, "Device ready")
        popen.return_value = _Process("Writing c=0-0:h=0-0\nT0.0: Written\n")
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "preserved.hfe"
            image.write_bytes(b"hfe")
            result = GreaseweazleClient("/usr/bin/gw").write(image, "0")

        self.assertFalse(result.verified)
        self.assertFalse(result.verification_supported)

    @patch("acorn_greaseweazle.client.subprocess.Popen")
    @patch("acorn_greaseweazle.client.subprocess.run")
    def test_missing_sector_verification_is_a_failure(self, run, popen) -> None:
        run.return_value = subprocess.CompletedProcess(["gw", "info"], 0, "Device ready")
        popen.return_value = _Process("Writing c=0-0:h=0-0\nT0.0: Written\n")
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "game.ssd"
            image.write_bytes(b"disk")
            with self.assertRaisesRegex(GreaseweazleError, "without confirming"):
                GreaseweazleClient("/usr/bin/gw").write(image, "A")

    @patch("acorn_greaseweazle.client.subprocess.Popen")
    @patch("acorn_greaseweazle.client.subprocess.run")
    def test_cancellation_terminates_the_active_hardware_command(self, run, popen) -> None:
        run.return_value = subprocess.CompletedProcess(["gw", "info"], 0, "Device ready")
        process = _Process("Writing c=0-79:h=0-1\nT0.0: Written and verified\n")
        popen.return_value = process
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "game.ssd"
            image.write_bytes(b"disk")

            reports = 0

            def cancel(_message, _current=None, _total=None):
                nonlocal reports
                reports += 1
                if reports > 1:
                    raise RuntimeError("cancel requested")

            with self.assertRaisesRegex(RuntimeError, "cancel requested"):
                GreaseweazleClient("/usr/bin/gw").write(image, "A", cancel)

        self.assertTrue(process.terminated)

    def test_drive_identifier_cannot_be_used_as_command_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "game.ssd"
            image.write_bytes(b"disk")
            with self.assertRaisesRegex(GreaseweazleError, "Choose Greaseweazle drive"):
                GreaseweazleClient("/usr/bin/gw").write(image, "A; eject")

    def test_probe_explains_missing_command(self) -> None:
        # Isolate PATH discovery so this remains valid on a Greaseweazle machine.
        with patch("acorn_greaseweazle.client.shutil.which", return_value=None):
            result = GreaseweazleClient().probe()
        self.assertFalse(result.available)
        self.assertIn("not installed", result.detail)

    @unittest.skipIf(Flask is None, "Flask is available in the application environment")
    @patch("app.routes.desktop.GreaseweazleClient.probe")
    def test_desktop_status_exposes_drive_and_verification_policy(self, probe) -> None:
        probe.return_value = ProbeResult(True, "/usr/bin/gw", "Device ready")
        headers = {"X-Acorn-Desktop-Token": "d" * 32}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image_path = root / "physical.ssd"
            image_path.write_bytes(b"disk")
            session = ImageSession("image-id", "physical.ssd", "dfs", image_path)
            service = Mock(work_dir=root)
            service.get.return_value = session
            service.summary.return_value = {"hardDisk": False}
            app = Flask(__name__)
            app.register_blueprint(create_desktop_blueprint(service))
            app.register_error_handler(DiskError, lambda error: (jsonify(error=str(error)), 400))
            client = app.test_client()
            response = client.get(
                "/api/desktop/images/image-id/physical-floppy",
                headers=headers,
            )

        self.assertEqual(response.status_code, 200)
        status = response.get_json()
        self.assertTrue(status["available"])
        self.assertTrue(status["media"]["automaticVerification"])
        self.assertEqual([item["id"] for item in status["drives"]], ["A", "B", "0", "1", "2", "3"])

    @unittest.skipIf(Flask is None, "Flask is available in the application environment")
    @patch("app.routes.desktop.GreaseweazleClient.write")
    def test_desktop_write_uses_snapshot_and_reports_result(self, write) -> None:
        write.side_effect = lambda path, drive, progress: WriteResult(
            drive=drive,
            image=Path(path).name,
            verified=True,
            verification_supported=True,
            tracks_written=80,
            output_tail=("All tracks verified",),
        )
        headers = {"X-Acorn-Desktop-Token": "d" * 32}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image_path = root / "physical.ssd"
            image_path.write_bytes(b"disk")
            session = ImageSession("image-id", "physical.ssd", "dfs", image_path)
            service = Mock(work_dir=root)
            service.get.return_value = session
            service.summary.return_value = {"hardDisk": False}
            service.prepare_download.return_value = image_path
            app = Flask(__name__)
            app.register_blueprint(create_desktop_blueprint(service))
            app.register_error_handler(DiskError, lambda error: (jsonify(error=str(error)), 400))
            client = app.test_client()
            response = client.post(
                "/api/desktop/images/image-id/physical-floppy",
                json={"drive": "B"},
                headers=headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["result"]["drive"], "B")
        written_path = Path(write.call_args.args[0])
        self.assertTrue(written_path.name.startswith("acorn-floppy-"))
        self.assertFalse(written_path.exists())


if __name__ == "__main__":
    unittest.main()
