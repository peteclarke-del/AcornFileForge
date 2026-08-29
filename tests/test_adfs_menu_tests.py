from __future__ import annotations

import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

from app.adfs_menu_discovery import MENU_FILES
from app.menu_records import serialise_menu
from app.menu_service import (
    test_installed_adfs_menu_entries as installed_adfs_menu_entries,
)


class _Entry:
    def __init__(self, name: str, path: str, is_dir: bool) -> None:
        self.name = name
        self.path = path
        self.is_dir = is_dir


class _FakeMount:
    """The smallest mount that lets the ADFS menu tester run end to end."""

    def __init__(self, files: dict[str, bytes], directories: dict[str, list[_Entry]]) -> None:
        self._files = files
        self._directories = directories

    def iter_entries(self, path: str):
        return list(self._directories.get(path, []))

    def read_bytes(self, path: str) -> bytes:
        return self._files[path]

    def exists(self, path: str) -> bool:
        return path in self._files or path in self._directories

    def stat(self, path: str):
        return SimpleNamespace(is_dir=path in self._directories, size=len(self._files.get(path, b"")))

    def acorn_meta(self, _path: str):
        return SimpleNamespace(load_address=0x1900, exec_address=0x8023)


def _service_for(mount: _FakeMount) -> Mock:
    service = Mock()

    @contextmanager
    def adfs_mount(_session):
        yield mount

    service.adfs_mount.side_effect = adfs_mount
    return service


class AdfsMenuLauncherTests(unittest.TestCase):
    """Regression cover for a path the analysis tests had entirely mocked out.

    ``test_installed_adfs_menu_entries`` referenced an undefined name, so every
    call raised ``NameError`` as soon as the mount opened. The analysis-service
    test patched this function out, so nothing executed its body.
    """

    def test_a_non_adfs_session_returns_no_menus_without_mounting(self) -> None:
        service = Mock()
        session = SimpleNamespace(kind="dfs")
        roots, tests = installed_adfs_menu_entries(service, session)
        self.assertEqual((roots, tests), ([], []))
        service.adfs_mount.assert_not_called()

    def test_an_adfs_image_without_a_menu_directory_reports_no_roots(self) -> None:
        mount = _FakeMount(files={}, directories={"$": []})
        session = SimpleNamespace(kind="adfs", adfs_menu_roots=None)
        roots, tests = installed_adfs_menu_entries(
            _service_for(mount), session, root="$"
        )
        self.assertEqual(roots, [])
        self.assertEqual(tests, [])

    def test_an_installed_menu_is_opened_and_its_entries_are_tested(self) -> None:
        """Executing the real body proves the mounted view is constructible."""
        menu, _index = serialise_menu(
            [{
                "title": "ELITE",
                "publisher": "Acornsoft",
                "filename": "ELITE",
                "diskTitle": "$.GAMES",
                "action": "E",
                "page": "1900",
                "system": "H",
            }],
            system="H",
        )
        directories = {
            "$": [
                *(_Entry(name, f"$.{name}", False) for name in sorted(MENU_FILES)),
                _Entry("GAMES", "$.GAMES", True),
            ],
            "$.GAMES": [_Entry("ELITE", "$.GAMES.ELITE", False)],
        }
        mount = _FakeMount({"$.GAMDATA": menu, "$.GAMES.ELITE": b"\x0d"}, directories)
        service = _service_for(mount)
        service.list_directory.return_value = {
            "entries": [
                {"name": "ELITE", "type": "file", "load": 0x1900, "exec": 0x8023, "size": 1}
            ]
        }
        session = SimpleNamespace(kind="adfs", adfs_menu_roots=None)

        roots, tests = installed_adfs_menu_entries(service, session, root="$")

        self.assertEqual(roots, ["$"])
        self.assertEqual(len(tests), 1)
        self.assertEqual(tests[0]["launcher"], "ELITE")
        self.assertEqual(tests[0]["menuRoot"], "$")
        self.assertIn("passed", tests[0])

    def test_progress_is_reported_while_entries_are_checked(self) -> None:
        menu, _index = serialise_menu(
            [{
                "title": "GAME",
                "publisher": "Acornsoft",
                "filename": "GAME",
                "diskTitle": "$.GAMES",
                "action": "E",
                "page": "1900",
                "system": "H",
            }],
            system="H",
        )
        directories = {
            "$": [_Entry(name, f"$.{name}", False) for name in sorted(MENU_FILES)],
        }
        mount = _FakeMount({"$.GAMDATA": menu}, directories)
        service = _service_for(mount)
        service.list_directory.return_value = {"entries": []}
        session = SimpleNamespace(kind="adfs", adfs_menu_roots=None)
        seen: list[str] = []

        installed_adfs_menu_entries(
            service,
            session,
            root="$",
            progress=lambda message, _current=None, _total=None: seen.append(message),
        )

        self.assertTrue(any("menu entry" in message for message in seen))


if __name__ == "__main__":
    unittest.main()
