import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from flask import Flask

from app.routes.mmb import create_mmb_blueprint


class MmbRouteTests(unittest.TestCase):
    def setUp(self):
        self.service = Mock()
        self.source = SimpleNamespace(id="source", kind="mmb", lock=threading.RLock())
        self.target = SimpleNamespace(id="target", kind="mmb", lock=threading.RLock())
        self.service.get.side_effect = lambda image_id: {
            "source": self.source,
            "target": self.target,
        }[image_id]
        self.service.summary.side_effect = lambda session: {
            "id": session.id,
            "kind": "mmb",
        }
        app = Flask(__name__)
        app.register_blueprint(create_mmb_blueprint(self.service))
        self.client = app.test_client()

    @patch("app.routes.mmb._refresh_mmc_desktop")
    @patch("app.routes.mmb.eject_mmb_slots")
    def test_replacing_slots_uses_menu_aware_ejection(self, eject, _refresh):
        self.service.paste_mmb_slots.side_effect = [
            {"pasted": False, "conflicts": [{"slot": 40, "name": "OLD"}]},
            {
                "pasted": True,
                "sourceSlots": [10],
                "targetSlots": [40],
                "conflicts": [],
            },
        ]

        response = self.client.post(
            "/api/images/target/slots/paste",
            json={
                "sourceImage": "source",
                "sourceSlots": [10],
                "targetStart": 40,
                "replace": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        eject.assert_called_once_with(self.service, self.target, [40])
        self.assertEqual(self.service.paste_mmb_slots.call_count, 2)

    @patch("app.routes.mmb._refresh_mmc_desktop")
    @patch("app.routes.mmb.eject_mmb_slots")
    def test_cross_image_cut_copies_before_ejecting_source(self, eject, _refresh):
        checkpoint = {"id": "checkpoint"}
        self.service.begin_automatic_checkpoint.return_value = checkpoint
        self.service.paste_mmb_slots.return_value = {
            "pasted": True,
            "sourceSlots": [10, 12],
            "targetSlots": [40, 42],
            "conflicts": [],
        }

        response = self.client.post(
            "/api/images/target/slots/paste",
            json={
                "sourceImage": "source",
                "sourceSlots": [10, 12],
                "targetStart": 40,
                "cut": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.service.paste_mmb_slots.assert_called_once_with(
            self.source,
            self.target,
            [10, 12],
            40,
            cut=False,
            replace=False,
        )
        eject.assert_called_once_with(self.service, self.source, [10, 12])
        self.service.finish_automatic_checkpoint.assert_called_once_with(
            self.source,
            checkpoint,
        )
        self.assertEqual(_refresh.call_args_list, [
            call(self.service, self.target),
            call(self.service, self.source),
        ])


if __name__ == "__main__":
    unittest.main()
