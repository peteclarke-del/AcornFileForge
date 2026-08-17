from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.deployment_service import (
    DEPLOYMENT_FORMAT,
    available_deployment_targets,
    build_deployment_archive,
    deployment_plan,
)
from app.disk_service import DiskError, DiskService
from app.image_session import ImageSession


class DeploymentDiskService(DiskService):
    """Exercise deployment packaging without requiring the Oaknut CLI."""

    def summary(self, session):
        return {
            "revision": f"{session.path.stat().st_size}:{session.path.stat().st_mtime_ns}",
            "hardDisk": False,
        }

    def prepare_download(self, session, progress=None):
        return session.path


def floppy_session(service: DiskService, name: str) -> ImageSession:
    path = service.work_dir / f"{name}.ssd"
    path.write_bytes(bytes(200 * 1024))
    return ImageSession("a" * 32, path.name, "dfs", path)


class DeploymentServiceTests(unittest.TestCase):
    def test_gotek_plan_uses_a_finalised_snapshot_without_mutating_source(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            service = DeploymentDiskService(Path(folder) / "work")
            session = floppy_session(service, "ARCADIANS")
            original = session.path.read_bytes()
            revision = service.summary(session)["revision"]

            plan = deployment_plan(service, session, {
                "target": "gotek",
                "gotekMode": "native",
            })

            self.assertEqual(plan["format"], DEPLOYMENT_FORMAT)
            self.assertEqual(plan["source"]["revision"], revision)
            self.assertEqual(plan["entries"][0]["path"], "GOTEK-USB/ARCADIANS.ssd")
            self.assertTrue(plan["canProceed"])
            self.assertEqual(session.path.read_bytes(), original)
            self.assertEqual(service.summary(session)["revision"], revision)

    def test_indexed_gotek_package_contains_config_manifest_and_readme(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            service = DeploymentDiskService(Path(folder) / "work")
            session = floppy_session(service, "GAME")
            output = Path(folder) / "deployment.zip"
            plan = deployment_plan(service, session, {
                "target": "gotek", "gotekMode": "indexed", "startIndex": 12,
            })

            built = build_deployment_archive(service, session, {
                "target": "gotek",
                "gotekMode": "indexed",
                "startIndex": 12,
                "expectedRevision": plan["source"]["revision"],
            }, output)

            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
                manifest = json.loads(archive.read("Deployment/manifest.json"))
                config = archive.read("GOTEK-USB/FF.CFG").decode("ascii")
                readme = archive.read("README.md").decode("utf-8")
            self.assertIn("GOTEK-USB/DSKA0012_GAME.ssd", names)
            self.assertIn("Deployment/compatibility-report.md", names)
            self.assertIn("nav-mode = indexed", config)
            self.assertEqual(manifest["target"], "gotek")
            self.assertEqual(built["source"]["revision"], plan["source"]["revision"])
            self.assertIn("## Recovery", readme)

    def test_package_rejects_a_revision_changed_after_review(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            service = DeploymentDiskService(Path(folder) / "work")
            session = floppy_session(service, "GAME")
            output = Path(folder) / "deployment.zip"

            with self.assertRaisesRegex(DiskError, "changed after deployment review"):
                build_deployment_archive(service, session, {
                    "target": "gotek",
                    "gotekMode": "native",
                    "expectedRevision": "stale",
                }, output)

    def test_targets_explain_why_an_image_is_not_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            service = DeploymentDiskService(Path(folder) / "work")
            session = floppy_session(service, "GAME")
            targets = {row["id"]: row for row in available_deployment_targets(service, session)}

            self.assertTrue(targets["gotek"]["available"])
            self.assertFalse(targets["mmfs"]["available"])
            self.assertIn("MMB", targets["mmfs"]["reason"])


if __name__ == "__main__":
    unittest.main()
