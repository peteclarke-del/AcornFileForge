import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flask import Flask

from app.operations import OperationRegistry
from app.routes.files import create_files_blueprint


class FileRouteTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.service = Mock()
        self.session = SimpleNamespace(kind="dfs")
        self.service.get.return_value = self.session
        self.service.summary.return_value = {"id": "a" * 32, "kind": "dfs"}
        self.service.inner_for.side_effect = lambda _session, path, _side: path
        app = Flask(__name__)
        app.register_blueprint(
            create_files_blueprint(
                self.service,
                Path(self.temporary.name),
                OperationRegistry(),
            )
        )
        self.client = app.test_client()

    def tearDown(self):
        self.temporary.cleanup()

    def test_delete_sends_all_selected_dfs_files_in_one_mutation(self):
        response = self.client.post(
            "/api/images/test/delete",
            json={
                "slot": 7,
                "side": 2,
                "items": [
                    {"path": "$.ONE", "recursive": False},
                    {"path": "$.TWO", "recursive": False},
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.service.mutate.assert_called_once_with(
            self.session,
            7,
            ["rm", "--force", "{image}:$.ONE", "$.TWO"],
            2,
        )
        self.assertEqual(len(response.get_json()["deletedItems"]), 2)

    def test_access_change_sends_all_selected_files_in_one_mutation(self):
        self.service.set_access.return_value = ["$.ONE", "$.TWO"]
        response = self.client.post(
            "/api/images/test/lock",
            json={
                "slot": 3,
                "paths": ["$.ONE", "$.TWO"],
                "unlock": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.service.set_access.assert_called_once_with(
            self.session,
            3,
            ["$.ONE", "$.TWO"],
            True,
            None,
        )

    def test_mkdir_validates_and_creates_an_adfs_directory(self):
        self.session.kind = "adfs"

        response = self.client.post(
            "/api/images/test/mkdir",
            json={"path": "$.Games.NewDir", "side": 2},
        )

        self.assertEqual(response.status_code, 200)
        self.service.validate_leaf_name.assert_called_once_with(
            self.session,
            "NewDir",
        )
        self.service.mutate.assert_called_once_with(
            self.session,
            None,
            ["mkdir", "-p", "{image}:$.Games.NewDir"],
            2,
        )

    def test_dfs_prefix_move_is_sent_as_one_route_operation(self):
        self.service.move_dfs_items.return_value = [{
            "source": "$.HELLO",
            "destination": "F.HELLO",
        }]

        response = self.client.post(
            "/api/images/test/move-dfs",
            json={
                "slot": 4,
                "side": 2,
                "items": [{"source": "$.HELLO", "destination": "F.HELLO"}],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.service.move_dfs_items.assert_called_once_with(
            self.session,
            4,
            [{"source": "$.HELLO", "destination": "F.HELLO"}],
            2,
        )

    @patch("app.routes.files.delete_adfs_items")
    def test_adfs_batch_delete_rewrites_menus_once(self, delete_items):
        self.session.kind = "adfs"
        delete_items.return_value = {
            "deletedItems": [
                {"path": "$.ONE", "isDirectory": False},
                {"path": "$.TWO", "isDirectory": False},
            ],
            "menuEntriesRemoved": 4,
        }

        response = self.client.post(
            "/api/images/test/delete",
            json={"items": [{"path": "$.ONE"}, {"path": "$.TWO"}]},
        )

        self.assertEqual(response.status_code, 200)
        delete_items.assert_called_once_with(
            self.service,
            self.session,
            ["$.ONE", "$.TWO"],
        )
        self.assertEqual(response.get_json()["menuEntriesRemoved"], 4)


if __name__ == "__main__":
    unittest.main()
