from __future__ import annotations

from types import SimpleNamespace
import unittest

from app.analysis_service import preflight_report
from app.disk_service import DiskService
from app.filename_policy import target_name_policy


class FilenamePolicyTests(unittest.TestCase):
    def test_romfs_preflight_and_mutation_share_the_ten_character_policy(self):
        session = SimpleNamespace(
            kind="romfs", name="files.rom", hardware_profile={}, adfs_capabilities={}
        )
        report = preflight_report(None, session, {
            "targetKind": "romfs",
            "changes": [{"name": "ABCDEFGHIJK", "nameIsLeaf": True}],
        })

        self.assertEqual(report["items"][0]["targetName"], "ABCDEFGHIJ")
        with self.assertRaisesRegex(Exception, "at most 10"):
            DiskService.validate_leaf_name(session, "ABCDEFGHIJK")

    def test_romfs_period_is_not_rewritten_by_preflight(self):
        session = SimpleNamespace(
            kind="romfs", name="files.rom", hardware_profile={}, adfs_capabilities={}
        )
        report = preflight_report(None, session, {
            "targetKind": "romfs",
            "changes": [{"name": "A.B", "nameIsLeaf": True}],
        })

        self.assertEqual(report["items"][0]["targetName"], "A.B")
        self.assertEqual(DiskService.validate_leaf_name(session, "A.B"), "A.B")

    def test_adfs_allocator_preserves_legal_spaces_and_resolves_collisions(self):
        policy = target_name_policy("adfs", name_limit=10)

        self.assertEqual(policy.allocate("Elite II", []), "Elite II")
        self.assertEqual(policy.allocate("Elite II", ["elite ii"]), "Elite II1")

    def test_acorn_names_reject_unrepresentable_and_edge_whitespace(self):
        policy = target_name_policy("adfs", name_limit=10)

        with self.assertRaisesRegex(Exception, "Latin-1"):
            policy.validate("Elite🙂")
        with self.assertRaisesRegex(Exception, "start or end"):
            policy.validate(" Elite")
        self.assertEqual(policy.normalise("Café"), "Café")

    def test_short_name_allocator_never_exceeds_its_limit(self):
        policy = target_name_policy("adfs", name_limit=1)
        used = ["A", *"123456789"]

        allocated = policy.allocate("A", used)

        self.assertEqual(len(allocated), 1)
        self.assertNotIn(allocated.casefold(), {name.casefold() for name in used})

    def test_preflight_only_reports_collisions_within_the_same_parent(self):
        session = SimpleNamespace(
            kind="adfs", name="files.adf", hardware_profile={},
            adfs_capabilities={"nameLimit": 10},
        )
        changes = [
            {"name": "README", "nameIsLeaf": True, "parent": "$.ONE"},
            {"name": "README", "nameIsLeaf": True, "parent": "$.TWO"},
        ]

        report = preflight_report(None, session, {"changes": changes})

        self.assertTrue(report["canProceed"])

    def test_mmb_disk_preflight_uses_catalogue_title_limit(self):
        session = SimpleNamespace(
            kind="mmb", name="games.mmb", hardware_profile={}, adfs_capabilities={}
        )

        report = preflight_report(None, session, {
            "targetKind": "mmb",
            "changes": [
                {"name": "TWELVECHARS1", "nameIsLeaf": True, "type": "disk image"}
            ],
        })

        self.assertEqual(report["items"][0]["targetName"], "TWELVECHARS1")


if __name__ == "__main__":
    unittest.main()
