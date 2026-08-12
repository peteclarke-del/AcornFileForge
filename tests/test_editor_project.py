from __future__ import annotations

import unittest

from app.editor_project import EDITOR_PROJECT_FORMAT, editor_project_key, normalise_editor_project


class EditorProjectTests(unittest.TestCase):
    def test_key_separates_slot_side_and_path(self):
        self.assertEqual(editor_project_key("$.GAME", 12, 1), "12|1|$.GAME")
        self.assertNotEqual(editor_project_key("$.GAME", 12, 0), editor_project_key("$.GAME", 12, 1))

    def test_normalisation_rejects_bad_regions_and_cleans_symbols(self):
        project = normalise_editor_project({
            "notes": "Research",
            "symbols": {"0x8000": "start here", "bad": "ignored"},
            "regions": [
                {"start": "0x10", "end": "0x20", "kind": "text", "name": "Message"},
                {"start": 20, "end": 10, "kind": "bytes"},
                {"start": 0, "end": 4, "kind": "unknown"},
            ],
            "bookmarks": [{"offset": "0x12", "name": "Entry", "note": "Check this"}],
        })
        self.assertEqual(project["format"], EDITOR_PROJECT_FORMAT)
        self.assertEqual(project["symbols"], {"32768": "start_here"})
        self.assertEqual(project["regions"], [{"start": 16, "end": 32, "kind": "text", "name": "Message", "width": 8}])
        self.assertEqual(project["bookmarks"][0]["offset"], 18)


if __name__ == "__main__":
    unittest.main()
