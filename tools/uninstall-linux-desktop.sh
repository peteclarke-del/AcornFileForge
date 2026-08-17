#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
data_home=${XDG_DATA_HOME:-"$HOME/.local/share"}

rm -f \
    "$data_home/applications/uk.co.acornfileforge.AcornFileForge.desktop" \
    "$data_home/icons/hicolor/scalable/apps/uk.co.acornfileforge.AcornFileForge.svg" \
    "$data_home/mime/packages/uk.co.acornfileforge.AcornFileForge.xml"
rm -rf "$project_root/.venv-desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$data_home/applications"
fi
if command -v update-mime-database >/dev/null 2>&1; then
    update-mime-database "$data_home/mime"
fi
echo "Acorn File Forge desktop was removed. Working images under the XDG data directory were retained."
