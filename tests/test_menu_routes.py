import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from flask import Flask

from app.routes.menus import create_menus_blueprint


class MenuRouteTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.service = Mock()
        self.session = Mock(kind="mmb", lock=threading.RLock())
        self.service.get.return_value = self.session
        self.service.summary.return_value = {"id": "a" * 32, "kind": "mmb"}
        self.service.list_slots.return_value = [
            {"slot": 0, "name": "MENU", "formatted": True},
            {"slot": 42, "name": "COMPILATION", "formatted": True},
        ]
        self.entries = [
            {"title": "Game One", "diskTitle": "COMPILATION"},
            {"title": "Game Two", "diskTitle": "COMPILATION"},
            {"title": "Other", "diskTitle": "OTHER"},
        ]
        app = Flask(__name__)
        app.register_blueprint(create_menus_blueprint(self.service, self.temporary.name))
        self.client = app.test_client()

    def tearDown(self):
        self.temporary.cleanup()

    @patch("app.routes.menus.edit_mmb_menu_entries")
    @patch("app.routes.menus.find_menu_slot", return_value=0)
    def test_duplicate_cleanup_ejects_multi_game_disk_and_removes_all_its_records(self, _menu_slot, edit_entries):
        edit_entries.return_value = {"menuSlot": 0, "entries": 1}

        response = self.client.post(
            "/api/images/test/mmb-menu/duplicate-cleanup",
            json={"expectedEntries": self.entries, "removeIndexes": [0], "ejectSlots": [42]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["removedRecords"], 2)
        edit_entries.assert_called_once_with(
            self.service,
            self.session,
            [self.entries[2]],
            self.entries,
        )
        self.service.clear_slots.assert_called_once_with(self.session, [42])

    @patch("app.routes.menus.edit_mmb_menu_entries")
    @patch("app.routes.menus.find_menu_slot", return_value=0)
    def test_duplicate_cleanup_keeps_disk_and_removes_only_selected_record(self, _menu_slot, edit_entries):
        edit_entries.return_value = {"menuSlot": 0, "entries": 2}

        response = self.client.post(
            "/api/images/test/mmb-menu/duplicate-cleanup",
            json={"expectedEntries": self.entries, "removeIndexes": [0], "ejectSlots": []},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["removedRecords"], 1)
        edit_entries.assert_called_once_with(
            self.service,
            self.session,
            self.entries[1:],
            self.entries,
        )
        self.service.clear_slots.assert_not_called()


if __name__ == "__main__":
    unittest.main()
