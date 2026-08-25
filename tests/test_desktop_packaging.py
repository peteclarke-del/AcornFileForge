from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DesktopPackagingTests(unittest.TestCase):
    def test_desktop_entry_uses_a_validated_stable_launcher(self) -> None:
        template = (
            ROOT / "packaging/linux/uk.co.acornfileforge.AcornFileForge.desktop.in"
        ).read_text(encoding="utf-8")
        installer = (ROOT / "tools/install-linux-desktop.sh").read_text(encoding="utf-8")

        self.assertIn("Exec=@EXEC@ %F", template)
        self.assertIn("TryExec=@TRY_EXEC@", template)
        self.assertIn('registered_launcher="$user_bin/acorn-file-forge"', installer)
        self.assertIn('ln -sfn "$launcher" "$registered_launcher"', installer)
        self.assertIn('desktop-file-validate "$desktop_file"', installer)

    def test_launcher_resolves_symlink_and_removes_snap_gtk_paths(self) -> None:
        launcher = (ROOT / "tools/acorn-file-forge-desktop").read_text(encoding="utf-8")
        environment = (ROOT / "tools/linux-desktop-environment.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn('launcher_path=$(readlink -f -- "$0")', launcher)
        self.assertIn("linux-desktop-environment.sh", launcher)
        self.assertIn("GDK_PIXBUF_MODULEDIR", environment)
        self.assertIn("GSETTINGS_SCHEMA_DIR", environment)
        self.assertIn('"$HOME"/snap/*', environment)

    def test_launcher_handles_restricted_webkit_user_namespaces(self) -> None:
        launcher = (ROOT / "tools/acorn-file-forge-desktop").read_text(encoding="utf-8")
        environment = (ROOT / "tools/linux-desktop-environment.sh").read_text(
            encoding="utf-8"
        )
        desktop_host = (ROOT / "desktop/__main__.py").read_text(encoding="utf-8")

        self.assertIn("linux-desktop-environment.sh", launcher)
        self.assertIn("WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS=1", environment)
        self.assertIn("apparmor_restrict_unprivileged_userns", environment)
        self.assertIn("ACORN_FILE_FORGE_DISABLE_WEBKIT_SANDBOX", environment)
        self.assertIn('self.webview.connect("decide-policy", self._navigation_policy)', desktop_host)
        self.assertIn("Gio.AppInfo.launch_default_for_uri", desktop_host)

    def test_native_host_owns_file_chooser_bridge_and_gtk_chrome(self) -> None:
        desktop_host = (ROOT / "desktop/__main__.py").read_text(encoding="utf-8")
        frontend = (ROOT / "app/static/app.js").read_text(encoding="utf-8")

        self.assertIn('register_script_message_handler("acornDesktop")', desktop_host)
        self.assertIn("user_content_manager=self.content_manager", desktop_host)
        self.assertIn('Gtk.Button.new_from_icon_name("document-open-symbolic")', desktop_host)
        self.assertIn('icon_name="open-menu-symbolic"', desktop_host)
        self.assertIn("applyNativeAppearance", frontend)
        self.assertIn("open-images:${index}", frontend)
        self.assertIn("self.chooser_targets[chooser]", desktop_host)
        self.assertNotIn("self.chooser_targets[id(chooser)]", desktop_host)
        self.assertIn("chooserOpened(preferredIndex", frontend)
        self.assertIn("evaluate_javascript_finish", desktop_host)
        self.assertIn("Gtk.DropTarget.new", desktop_host)
        self.assertIn("Gdk.FileList", desktop_host)
        self.assertIn("_native_files_dropped", desktop_host)
        self.assertIn("paneAtPoint(x, y)", frontend)

    def test_installer_rejects_snap_private_xdg_data_home(self) -> None:
        paths = (ROOT / "tools/linux-xdg-paths.sh").read_text(encoding="utf-8")
        installer = (ROOT / "tools/install-linux-desktop.sh").read_text(encoding="utf-8")

        self.assertIn('"$HOME"/snap/*', paths)
        self.assertIn('"$HOME/.local/share"', paths)
        self.assertIn("XDG_DATA_DIRS_VSCODE_SNAP_ORIG", installer)
        self.assertIn("inherited_data_home", installer)

    def test_debian_package_reuses_shared_application_and_desktop_environment(self) -> None:
        builder = (ROOT / "tools/build-linux-package.sh").read_text(encoding="utf-8")
        launcher = (ROOT / "packaging/linux/acorn-file-forge").read_text(
            encoding="utf-8"
        )

        for shared_source in (
            '"$project_root/acorn_greaseweazle"',
            '"$project_root/app"',
            '"$project_root/desktop"',
        ):
            self.assertIn(shared_source, builder)
        self.assertIn("linux-desktop-environment.sh", launcher)
        self.assertIn('PYTHONPATH="$project_root/vendor:$project_root', launcher)
        self.assertIn('PATH="$project_root/native/bin:', launcher)
        self.assertIn('LD_LIBRARY_PATH="$project_root/native/lib', launcher)
        self.assertIn("tools/build-hxc-runtime.sh", builder)
        self.assertIn("dpkg-deb --build --root-owner-group", builder)
        self.assertNotIn("firmware", builder)
        self.assertIn("ACORN_PACKAGE_REVISION", builder)
        self.assertIn("ACORN_PACKAGE_TARGET", builder)
        self.assertIn("X-Acorn-Target", builder)

    def test_debian_package_registers_desktop_mime_appstream_and_manual(self) -> None:
        builder = (ROOT / "tools/build-linux-package.sh").read_text(encoding="utf-8")
        postinst = (ROOT / "packaging/linux/postinst").read_text(encoding="utf-8")
        postrm = (ROOT / "packaging/linux/postrm").read_text(encoding="utf-8")
        metainfo = (
            ROOT / "packaging/linux/uk.co.acornfileforge.AcornFileForge.metainfo.xml"
        ).read_text(encoding="utf-8")

        for required in (
            "uk.co.acornfileforge.AcornFileForge.desktop",
            "uk.co.acornfileforge.AcornFileForge.xml",
            "uk.co.acornfileforge.AcornFileForge.metainfo.xml",
            "acorn-file-forge.1.gz",
        ):
            self.assertIn(required, builder)
        self.assertIn("<id>uk.co.acornfileforge.AcornFileForge</id>", metainfo)
        for maintainer_script in (postinst, postrm):
            self.assertIn("gtk4-update-icon-cache", maintainer_script)
            self.assertIn("gtk-update-icon-cache", maintainer_script)

    def test_debian_dependency_lock_contains_every_application_requirement(self) -> None:
        application = {
            line.strip().lower()
            for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }
        package_lock = {
            line.strip().lower()
            for line in (
                ROOT / "packaging/linux/requirements-debian.txt"
            ).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }

        self.assertTrue(application.issubset(package_lock))

    def test_stable_release_builds_debian_and_ubuntu_for_supported_architectures(self) -> None:
        workflow = (ROOT / ".github/workflows/release.yml").read_text(
            encoding="utf-8"
        )
        self.assertEqual("1.0.0", (ROOT / "VERSION").read_text(encoding="utf-8").strip())
        for required in (
            "debian:trixie-slim",
            "ubuntu:24.04",
            "linux/amd64",
            "linux/arm64",
            "linux/arm/v7",
            "--verify-tag",
            "SHA256SUMS",
        ):
            self.assertIn(required, workflow)
        self.assertIn("tools/build-source-archive.sh", workflow)
        self.assertIn('cd "$stage/opt/acorn-file-forge"', workflow)
        self.assertTrue((ROOT / "docs/releases/1.0.0.md").is_file())


if __name__ == "__main__":
    unittest.main()
