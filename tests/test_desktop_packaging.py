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

    def test_installer_rejects_snap_private_xdg_data_home(self) -> None:
        paths = (ROOT / "tools/linux-xdg-paths.sh").read_text(encoding="utf-8")
        installer = (ROOT / "tools/install-linux-desktop.sh").read_text(encoding="utf-8")

        self.assertIn('"$HOME"/snap/*', paths)
        self.assertIn('"$HOME/.local/share"', paths)
        self.assertIn("XDG_DATA_DIRS_VSCODE_SNAP_ORIG", installer)
        self.assertIn("inherited_data_home", installer)


if __name__ == "__main__":
    unittest.main()
