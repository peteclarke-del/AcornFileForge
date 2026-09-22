from __future__ import annotations

import json
import re
import unittest
from importlib.metadata import PackageNotFoundError, metadata
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]


def pinned_requirements(path: Path) -> dict[str, str]:
    """Map each `name[extra]==version` line of a requirements file to its version.

    Extras are dropped from the key, so `oaknut-romfs[cli]==1.2.3` is
    reported as `oaknut-romfs`.
    """
    pins: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "==" in line:
            name, version = line.split("==", 1)
            pins[name.split("[", 1)[0].lower()] = version
    return pins


def pinned_oaknut_release() -> str:
    """The single Oaknut release the application requires.

    The Oaknut packages are cut together from one repository, so the three the
    application pins must agree before any document can be checked against
    them.
    """
    requirements = pinned_requirements(ROOT / "requirements.txt")
    versions = {
        name: version for name, version in requirements.items() if name.startswith("oaknut-")
    }
    assert len(set(versions.values())) == 1, f"requirements.txt mixes Oaknut releases: {versions}"
    return next(iter(versions.values()))


def published_text_files() -> list[Path]:
    files = [
        ROOT / "README.md",
        ROOT / "CONTRIBUTING.md",
        ROOT / "GOVERNANCE.md",
        ROOT / "SECURITY.md",
        ROOT / "CODE_OF_CONDUCT.md",
        ROOT / "SUPPORT.md",
        ROOT / "THIRD_PARTY_NOTICES.md",
        ROOT / "firmware" / "README.md",
    ]
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

    def test_collection_documentation_covers_both_hosts(self) -> None:
        guide = (ROOT / "docs" / "COLLECTION-GUIDE.md").read_text(encoding="utf-8")
        help_text = (ROOT / "app" / "static" / "help.js").read_text(encoding="utf-8")
        for required in ("IndexedDB", "client-state.json", "mode `0600`"):
            self.assertIn(required, guide)
        self.assertIn("Linux desktop edition", help_text)

    def test_hxcfe_runtime_and_hfe_workflow_are_documented(self) -> None:
        guide = (ROOT / "docs" / "HFE-HXC-GUIDE.md").read_text(encoding="utf-8")
        help_text = (ROOT / "app" / "static" / "help.js").read_text(encoding="utf-8")
        # Track the packaged version rather than a fixed name, so a release
        # bump cannot leave this checking notes for an older release.
        version = (ROOT / "VERSION").read_text(encoding="ascii").strip()
        release = (ROOT / "docs" / "releases" / f"{version}.md").read_text(
            encoding="utf-8"
        )
        for required in (
            "HxCFloppyEmulator",
            "libhxcfe.so",
            "libusbhxcfe.so",
            "byte mismatch blocks the download",
        ):
            self.assertIn(required, guide)
        self.assertIn("HxCFloppyEmulator command-line converter", help_text)
        self.assertIn("bundled HxCFloppyEmulator", release)

    def test_published_dependency_versions_match_manifests(self) -> None:
        requirements = pinned_requirements(ROOT / "requirements.txt")
        package_lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
        notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        self.assertIn(f"| Flask | {requirements['flask']} |", notices)
        self.assertIn(f"| Gunicorn | {requirements['gunicorn']} |", notices)
        self.assertIn(f"| Capstone | {requirements['capstone']} |", notices)
        self.assertIn(f"| Oaknut Disc, ADFS and ROMFS | {pinned_oaknut_release()} |", notices)
        playwright = package_lock["packages"]["node_modules/playwright"]["version"]
        self.assertIn(f"| Playwright | {playwright},", notices)

    def test_oaknut_notice_links_the_repository_oaknut_declares(self) -> None:
        """The notices send readers to the repository Oaknut itself publishes.

        The row once linked a repository that does not exist, and nothing
        noticed because only the version was checked. Oaknut's own package
        metadata is the authority for where its source and licence live.
        """
        try:
            project_urls = metadata("oaknut-disc").get_all("Project-URL") or []
        except PackageNotFoundError:
            self.skipTest("oaknut-disc is not installed")
        repository = dict(url.split(", ", 1) for url in project_urls)["Repository"]
        notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        row = next(line for line in notices.splitlines() if line.startswith("| Oaknut "))
        self.assertIn(f"<{repository}>", row)

    def test_handbooks_name_the_pinned_oaknut_release(self) -> None:
        """Every Oaknut version the documentation quotes is the one installed.

        The FileCore handbook, the main README and the in-app help all tell the
        user which Oaknut release does their editing. A dependency bump touches
        only requirements.txt, so without this check those passages keep naming
        the superseded engine, which is exactly the drift the notices test above
        already catches for the inventory table.
        """
        expected = pinned_oaknut_release()
        pattern = re.compile(r"Oaknut[^\n\d]{0,40}?(\d+\.\d+\.\d+)")
        stale: list[str] = []
        for path in [
            ROOT / "README.md",
            ROOT / "THIRD_PARTY_NOTICES.md",
            ROOT / "app" / "static" / "help.js",
            *sorted((ROOT / "docs").glob("*.md")),
        ]:
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                for version in pattern.findall(line):
                    if version != expected:
                        stale.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
        self.assertEqual(stale, [], "\n".join([f"documents not naming Oaknut {expected}:", *stale]))

    def test_compose_example_publishes_application_and_emulator_ports(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn('      - "8666:8666"', readme)
        self.assertIn('      - "8668:8668"', readme)

    def test_repository_governance_files_define_the_licensing_boundary(self) -> None:
        for relative in (
            "LICENSE",
            "NOTICE",
            "CONTRIBUTING.md",
            "GOVERNANCE.md",
            "SECURITY.md",
            "CODE_OF_CONDUCT.md",
            "SUPPORT.md",
            "THIRD_PARTY_NOTICES.md",
            ".github/ISSUE_TEMPLATE/bug_report.yml",
            ".github/ISSUE_TEMPLATE/feature_request.yml",
            ".github/pull_request_template.md",
            ".github/dependabot.yml",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)

        licence = (ROOT / "LICENSE").read_text(encoding="utf-8")
        notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        self.assertIn("MIT License", licence)
        self.assertIn("not covered by the Acorn File Forge MIT licence", notices)
        self.assertIn("Do not open a public issue", security)


if __name__ == "__main__":
    unittest.main()
