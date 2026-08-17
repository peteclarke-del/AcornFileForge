from __future__ import annotations

import re
import unittest
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]


def published_text_files() -> list[Path]:
    files = [ROOT / "README.md", ROOT / "firmware" / "README.md"]
    files.extend(sorted((ROOT / "docs").rglob("*.md")))
    files.extend(
        [
            ROOT / "app" / "static" / "help.js",
            ROOT / "app" / "readme_service.py",
            ROOT / "app" / "deployment_service.py",
            ROOT / "app" / "workflow_recipe.py",
        ]
    )
    return files


class DocumentationTests(unittest.TestCase):
    def test_published_documentation_has_no_em_dashes(self) -> None:
        offenders = [
            str(path.relative_to(ROOT))
            for path in published_text_files()
            if "\N{EM DASH}" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual([], offenders)

    def test_markdown_local_links_resolve(self) -> None:
        missing: list[str] = []
        link_pattern = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")

        for source in published_text_files():
            if source.suffix != ".md":
                continue
            for raw_target in link_pattern.findall(source.read_text(encoding="utf-8")):
                target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
                target = unquote(target.split("#", 1)[0])
                if not target or "://" in target or target.startswith(("mailto:", "/")):
                    continue
                if not (source.parent / target).resolve().exists():
                    missing.append(f"{source.relative_to(ROOT)} -> {raw_target}")

        self.assertEqual([], missing)

    def test_current_status_names_completed_safety_work(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for required in ("same-length member edits", "whole-MMB", "exact-hash guarded patches"):
            self.assertIn(required, readme)

    def test_obsolete_pane_limit_does_not_return(self) -> None:
        combined = "\n".join(
            path.read_text(encoding="utf-8").lower() for path in published_text_files()
        )
        self.assertNotIn("one to three panes", combined)
        self.assertNotIn("maximum of three panes", combined)


if __name__ == "__main__":
    unittest.main()
