from __future__ import annotations

import ast
import unittest
from pathlib import Path

from app import oaknut_internals


APP_ROOT = Path(__file__).resolve().parent.parent / "app"
ADAPTER = APP_ROOT / "oaknut_internals.py"


def _private_oaknut_imports(source: Path) -> list[str]:
    """Return private Oaknut names imported by one module."""
    tree = ast.parse(source.read_text(encoding="utf-8"))
    borrowed: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        if node.module != "oaknut" and not node.module.startswith("oaknut."):
            continue
        borrowed.extend(
            alias.name for alias in node.names if alias.name.startswith("_")
        )
    return borrowed


class OaknutAdapterTests(unittest.TestCase):
    """The borrowed private API must stay real, named, and contained."""

    def test_every_borrowed_symbol_exists_in_the_pinned_release(self) -> None:
        """An Oaknut upgrade that drops a private name fails here, not in front of a user."""
        from oaknut.disc import cli

        for name in oaknut_internals.BORROWED_SYMBOLS:
            with self.subTest(symbol=name):
                self.assertTrue(
                    hasattr(cli, name),
                    f"oaknut.disc.cli no longer provides {name}; the pinned "
                    "version has changed and app/oaknut_internals.py needs review",
                )

    def test_every_borrowed_symbol_is_callable(self) -> None:
        from oaknut.disc import cli

        for name in oaknut_internals.BORROWED_SYMBOLS:
            with self.subTest(symbol=name):
                self.assertTrue(callable(getattr(cli, name)))

    def test_public_names_are_bound_to_the_borrowed_symbols(self) -> None:
        from oaknut.disc import cli

        expected = {
            "file_copy_item": "_file_item",
            "collect_copy_items": "_collect_copy_items",
            "in_storage_order": "_in_global_storage_order",
            "ensure_directory_chain": "_ensure_dir_chain",
            "write_copy_item": "_write_copy_item",
            "walk_post_order": "_walk_post_order_mount",
            "natural_name_key": "_natural_name_key",
        }
        for public, private in expected.items():
            with self.subTest(name=public):
                self.assertIs(
                    getattr(oaknut_internals, public),
                    getattr(cli, private),
                )

    def test_the_declared_symbol_list_matches_what_is_re_exported(self) -> None:
        """BORROWED_SYMBOLS is the contract the upgrade check reads; keep it honest."""
        self.assertEqual(
            sorted(oaknut_internals.BORROWED_SYMBOLS),
            sorted(_private_oaknut_imports(ADAPTER)),
        )

    def test_no_other_module_reaches_into_the_private_oaknut_api(self) -> None:
        """Borrowing private names is contained to one reviewed module."""
        offenders: dict[str, list[str]] = {}
        for source in sorted(APP_ROOT.rglob("*.py")):
            if source == ADAPTER:
                continue
            borrowed = _private_oaknut_imports(source)
            if borrowed:
                offenders[str(source.relative_to(APP_ROOT.parent))] = borrowed
        self.assertEqual(
            offenders,
            {},
            "private Oaknut symbols must be imported through "
            "app/oaknut_internals.py so an upgrade has one place to review",
        )

    def test_the_adapter_exports_only_public_names(self) -> None:
        for name in oaknut_internals.__all__:
            with self.subTest(name=name):
                self.assertFalse(name.startswith("_"))
                self.assertTrue(hasattr(oaknut_internals, name))


if __name__ == "__main__":
    unittest.main()
