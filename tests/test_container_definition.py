from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ContainerDefinitionTests(unittest.TestCase):
    def test_python_native_dependencies_are_built_outside_runtime_image(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        builder = dockerfile.index("FROM python:3.12-slim-trixie AS python-deps")
        runtime = dockerfile.rindex("FROM python:3.12-slim-trixie")
        self.assertLess(builder, runtime)
        self.assertIn("build-essential", dockerfile[builder:runtime])
        self.assertIn("--root=/python-install", dockerfile[builder:runtime])
        self.assertIn("Staged Capstone ARM, M68K and MOS65XX support is available", dockerfile[builder:runtime])
        runtime_definition = dockerfile[runtime:]
        self.assertIn("COPY --from=python-deps /python-install/usr/local /usr/local", runtime_definition)
        self.assertNotIn("/wheels", runtime_definition)
        self.assertNotIn("build-essential", runtime_definition)

    def test_runtime_dependencies_use_trixie_package_names(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        runtime = dockerfile.rindex("FROM python:3.12-slim-trixie")
        runtime_definition = dockerfile[runtime:]
        self.assertIn("liballegro4.4t64", runtime_definition)
        self.assertNotIn("liballegro4.4 ", runtime_definition)

    def test_public_clone_instructions_do_not_require_a_github_key(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("git clone https://github.com/peteclarke-del/AcornFileForge.git", readme)


if __name__ == "__main__":
    unittest.main()
