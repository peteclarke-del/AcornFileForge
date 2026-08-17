#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$project_root/tools/linux-xdg-paths.sh"
inherited_data_home=${XDG_DATA_HOME:-}
data_home=$(acorn_host_data_home)
host_data_dirs=${XDG_DATA_DIRS_VSCODE_SNAP_ORIG:-${XDG_DATA_DIRS:-/usr/local/share:/usr/share}}
registered_launcher="$HOME/.local/bin/acorn-file-forge"

rm -f \
    "$data_home/applications/uk.co.acornfileforge.AcornFileForge.desktop" \
    "$data_home/icons/hicolor/scalable/apps/uk.co.acornfileforge.AcornFileForge.svg" \
    "$data_home/mime/packages/uk.co.acornfileforge.AcornFileForge.xml"
if [ -L "$registered_launcher" ]; then
    rm -f "$registered_launcher"
fi
case "$inherited_data_home" in
    "$HOME"/snap/*)
        rm -f \
            "$inherited_data_home/applications/uk.co.acornfileforge.AcornFileForge.desktop" \
            "$inherited_data_home/icons/hicolor/scalable/apps/uk.co.acornfileforge.AcornFileForge.svg" \
            "$inherited_data_home/mime/packages/uk.co.acornfileforge.AcornFileForge.xml"
        ;;
esac
rm -rf "$project_root/.venv-desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
    XDG_DATA_HOME="$data_home" XDG_DATA_DIRS="$host_data_dirs" \
        update-desktop-database "$data_home/applications"
fi
if command -v update-mime-database >/dev/null 2>&1; then
    XDG_DATA_HOME="$data_home" XDG_DATA_DIRS="$host_data_dirs" \
        update-mime-database "$data_home/mime"
fi
echo "Acorn File Forge desktop was removed. Working images under the XDG data directory were retained."
