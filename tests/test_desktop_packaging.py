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

        self.assertIn('launcher_path=$(readlink -f -- "$0")', launcher)
        self.assertIn("GDK_PIXBUF_MODULEDIR", launcher)
        self.assertIn("GSETTINGS_SCHEMA_DIR", launcher)
        self.assertIn('"$HOME"/snap/*', launcher)

    def test_launcher_handles_restricted_webkit_user_namespaces(self) -> None:
        launcher = (ROOT / "tools/acorn-file-forge-desktop").read_text(encoding="utf-8")
        desktop_host = (ROOT / "desktop/__main__.py").read_text(encoding="utf-8")

        self.assertIn("WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS=1", launcher)
        self.assertIn("authenticated, loopback-only", launcher)
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


if __name__ == "__main__":
    unittest.main()
