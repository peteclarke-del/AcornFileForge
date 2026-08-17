from __future__ import annotations

import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from app.platform_contract import (
    HOST_EXCLUSIVE_ENDPOINTS,
    PLATFORM_CONTRACT_FORMAT,
    PlatformRuntime,
)

try:
    from app.server import create_app
    from app.routes.desktop import _image_pair
    from desktop.runtime import DesktopServer, desktop_paths
except ModuleNotFoundError:  # Flask and Werkzeug are container dependencies.
    create_app = DesktopServer = desktop_paths = _image_pair = None


class PlatformContractTests(unittest.TestCase):
    def test_desktop_runtime_requires_private_token(self) -> None:
        with self.assertRaisesRegex(ValueError, "private launch token"):
            PlatformRuntime("desktop", "short")
        self.assertEqual(PlatformRuntime().public_contract()["host"], "web")

    @unittest.skipIf(create_app is None, "Flask is available in the application container")
    def test_web_and_desktop_route_maps_differ_only_by_declared_adapters(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            web = create_app(work_dir=root / "web")
            desktop = create_app(
                work_dir=root / "desktop",
                platform="desktop",
                desktop_token="d" * 32,
            )

        web_routes = {rule.endpoint for rule in web.url_map.iter_rules()}
        desktop_routes = {rule.endpoint for rule in desktop.url_map.iter_rules()}
        self.assertEqual(web_routes - desktop_routes, HOST_EXCLUSIVE_ENDPOINTS["web"])
        self.assertEqual(
            desktop_routes - web_routes,
            HOST_EXCLUSIVE_ENDPOINTS["desktop"],
        )
        self.assertEqual(web.static_folder, desktop.static_folder)
        self.assertFalse(web.extensions["acorn_interactive_emulator"].native)
        self.assertTrue(desktop.extensions["acorn_interactive_emulator"].native)

    @unittest.skipIf(create_app is None, "Flask is available in the application container")
    def test_desktop_service_rejects_requests_without_launch_token(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = create_app(
                work_dir=Path(temporary),
                platform="desktop",
                desktop_token="d" * 32,
            )
            client = app.test_client()
            denied = client.get("/api/health")
            allowed = client.get(
                "/api/health", headers={"X-Acorn-Desktop-Token": "d" * 32}
            )

        self.assertEqual(denied.status_code, 403)
        self.assertEqual(allowed.status_code, 200)
        contract = allowed.get_json()["platform"]
        self.assertEqual(contract["format"], PLATFORM_CONTRACT_FORMAT)
        self.assertEqual(contract["host"], "desktop")

    @unittest.skipIf(DesktopServer is None, "Flask is available in the application container")
    def test_desktop_server_binds_random_loopback_port(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with DesktopServer(Path(temporary)) as server:
                port = server.port
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    urllib.request.urlopen(
                        f"http://127.0.0.1:{server.port}/api/health", timeout=5
                    )
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.port}/api/health",
                    headers={"X-Acorn-Desktop-Token": server.token},
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    health = json.load(response)

        self.assertEqual(denied.exception.code, 403)
        self.assertGreater(port, 0)
        self.assertEqual(health["platform"]["host"], "desktop")

    @unittest.skipIf(desktop_paths is None, "Desktop runtime dependencies unavailable")
    def test_desktop_paths_follow_xdg_locations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ,
            {
                "XDG_DATA_HOME": f"{temporary}/data",
                "XDG_CONFIG_HOME": f"{temporary}/config",
                "XDG_CACHE_HOME": f"{temporary}/cache",
            },
        ):
            paths = desktop_paths()

        self.assertEqual(paths.work, Path(temporary) / "data/acorn-file-forge/work")
        self.assertEqual(paths.config, Path(temporary) / "config/acorn-file-forge")
        self.assertEqual(paths.cache, Path(temporary) / "cache/acorn-file-forge")

    @unittest.skipIf(desktop_paths is None, "Desktop runtime dependencies unavailable")
    def test_desktop_paths_ignore_an_ide_snap_private_xdg_home(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ,
            {
                "HOME": temporary,
                "XDG_DATA_HOME": f"{temporary}/snap/code/current/.local/share",
                "XDG_CONFIG_HOME": f"{temporary}/snap/code/current/.config",
                "XDG_CACHE_HOME": f"{temporary}/snap/code/current/.cache",
            },
        ):
            paths = desktop_paths()

        self.assertEqual(paths.data, Path(temporary) / ".local/share/acorn-file-forge")
        self.assertEqual(paths.config, Path(temporary) / ".config/acorn-file-forge")
        self.assertEqual(paths.cache, Path(temporary) / ".cache/acorn-file-forge")

    @unittest.skipIf(_image_pair is None, "Flask is available in the application container")
    def test_desktop_open_pairs_dat_and_dsc_from_either_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dat = root / "SCSI0.DAT"
            dsc = root / "scsi0.dsc"
            dat.write_bytes(b"data")
            dsc.write_bytes(b"descriptor")

            from_dat = _image_pair({"path": str(dat)})
            from_dsc = _image_pair({"path": str(dsc)})

        self.assertEqual(from_dat, (dat, dsc))
        self.assertEqual(from_dsc, (dat, dsc))


if __name__ == "__main__":
    unittest.main()
