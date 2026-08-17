#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
venv="$project_root/.venv-desktop"
data_home=${XDG_DATA_HOME:-"$HOME/.local/share"}
applications="$data_home/applications"
icons="$data_home/icons/hicolor/scalable/apps"
mime_packages="$data_home/mime/packages"
desktop_file="$applications/uk.co.acornfileforge.AcornFileForge.desktop"
launcher="$project_root/tools/acorn-file-forge-desktop"

if ! command -v make >/dev/null 2>&1 || ! command -v cc >/dev/null 2>&1; then
    echo "Native build tools are missing. On Ubuntu or Debian install build-essential and python3-dev." >&2
    exit 2
fi

python3 - <<'PY'
try:
    import gi
    gi.require_version("Adw", "1")
    gi.require_version("Gtk", "4.0")
    gi.require_version("WebKit", "6.0")
    from gi.repository import Adw, Gtk, WebKit  # noqa: F401
except (ImportError, ValueError) as exc:
    raise SystemExit(
        "GTK desktop dependencies are missing. On Ubuntu or Debian install: "
        "python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-webkit-6.0"
    ) from exc
PY

python3 -m venv --system-site-packages "$venv"
"$venv/bin/python" -m pip install --upgrade pip
"$venv/bin/python" -m pip install -r "$project_root/requirements.txt"

mkdir -p "$applications" "$icons" "$mime_packages"
cp "$project_root/app/static/favicon.svg" \
    "$icons/uk.co.acornfileforge.AcornFileForge.svg"
cp "$project_root/packaging/linux/uk.co.acornfileforge.AcornFileForge.xml" \
    "$mime_packages/uk.co.acornfileforge.AcornFileForge.xml"
sed \
    -e "s|@EXEC@|$launcher|g" \
    "$project_root/packaging/linux/uk.co.acornfileforge.AcornFileForge.desktop.in" \
    > "$desktop_file"
chmod 755 "$launcher"
chmod 644 "$desktop_file" \
    "$icons/uk.co.acornfileforge.AcornFileForge.svg" \
    "$mime_packages/uk.co.acornfileforge.AcornFileForge.xml"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$applications"
fi
if command -v gtk4-update-icon-cache >/dev/null 2>&1; then
    gtk4-update-icon-cache -f -t "$data_home/icons/hicolor" >/dev/null 2>&1 || true
fi
if command -v update-mime-database >/dev/null 2>&1; then
    update-mime-database "$data_home/mime"
fi

echo "Acorn File Forge desktop is installed for this user."
echo "Launch it from the application menu or run: $launcher"
