#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
output_dir=${1:-"$project_root/dist"}
version=$(sed -n '1p' "$project_root/VERSION")
debian_version=$(printf '%s' "$version" | sed 's/-rc\./~rc./')
architecture=$(dpkg --print-architecture)
package_name=acorn-file-forge_${debian_version}_${architecture}.deb
SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-$(git -C "$project_root" log -1 --format=%ct)}
export SOURCE_DATE_EPOCH
build_root=$(mktemp -d)
stage="$build_root/package"
application="$stage/opt/acorn-file-forge"

cleanup() {
    rm -rf -- "$build_root"
}
trap cleanup EXIT HUP INT TERM

for command in dpkg-deb python3; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "$command is required to build the Debian package." >&2
        exit 2
    fi
done

mkdir -p \
    "$application" \
    "$stage/DEBIAN" \
    "$stage/usr/bin" \
    "$stage/usr/share/applications" \
    "$stage/usr/share/doc/acorn-file-forge" \
    "$stage/usr/share/icons/hicolor/scalable/apps" \
    "$stage/usr/share/man/man1" \
    "$stage/usr/share/metainfo" \
    "$stage/usr/share/mime/packages"

cp -a "$project_root/app" "$project_root/desktop" "$application/"
mkdir -p "$application/tools"
cp "$project_root/tools/linux-desktop-environment.sh" "$application/tools/"
cp "$project_root/VERSION" "$application/"

python3 -m pip install \
    --disable-pip-version-check \
    --no-compile \
    --target "$application/vendor" \
    -r "$project_root/packaging/linux/requirements-debian.txt"

cp "$project_root/packaging/linux/acorn-file-forge" "$stage/usr/bin/"
sed \
    -e 's|@EXEC@|/usr/bin/acorn-file-forge|g' \
    -e 's|@TRY_EXEC@|/usr/bin/acorn-file-forge|g' \
    "$project_root/packaging/linux/uk.co.acornfileforge.AcornFileForge.desktop.in" \
    > "$stage/usr/share/applications/uk.co.acornfileforge.AcornFileForge.desktop"
cp "$project_root/app/static/favicon.svg" \
    "$stage/usr/share/icons/hicolor/scalable/apps/uk.co.acornfileforge.AcornFileForge.svg"
cp "$project_root/packaging/linux/uk.co.acornfileforge.AcornFileForge.xml" \
    "$stage/usr/share/mime/packages/"
cp "$project_root/packaging/linux/uk.co.acornfileforge.AcornFileForge.metainfo.xml" \
    "$stage/usr/share/metainfo/"
gzip -n -9 -c "$project_root/packaging/linux/acorn-file-forge.1" \
    > "$stage/usr/share/man/man1/acorn-file-forge.1.gz"

cp \
    "$project_root/README.md" \
    "$project_root/THIRD_PARTY_NOTICES.md" \
    "$stage/usr/share/doc/acorn-file-forge/"
cp "$project_root/LICENSE" "$stage/usr/share/doc/acorn-file-forge/copyright"
cp -a "$project_root/docs" "$stage/usr/share/doc/acorn-file-forge/handbook"

installed_size=$(du -sk "$stage" | awk '{print $1}')
cat > "$stage/DEBIAN/control" <<EOF
Package: acorn-file-forge
Version: $debian_version
Section: utils
Priority: optional
Architecture: $architecture
Installed-Size: $installed_size
Maintainer: Acorn File Forge contributors <peteclarke-del@users.noreply.github.com>
Depends: python3 (>= 3.11), python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1, gir1.2-webkit-6.0, shared-mime-info, desktop-file-utils
Homepage: https://github.com/peteclarke-del/AcornFileForge
Description: Acorn media image workshop
 Browse, edit, validate and convert Acorn BBC, Electron, Archimedes and
 RISC OS disk, tape, ROM and hard-drive images from a native GTK application.
EOF
cp "$project_root/packaging/linux/postinst" "$stage/DEBIAN/postinst"
cp "$project_root/packaging/linux/postrm" "$stage/DEBIAN/postrm"

find "$stage" -type d -exec chmod 755 {} +
find "$stage" -type f -exec chmod 644 {} +
if [ -d "$application/vendor/bin" ]; then
    find "$application/vendor/bin" -type f -exec chmod 755 {} +
fi
chmod 755 \
    "$stage/DEBIAN/postinst" \
    "$stage/DEBIAN/postrm" \
    "$stage/usr/bin/acorn-file-forge"
find "$stage" -exec touch -d "@$SOURCE_DATE_EPOCH" {} +

if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate \
        "$stage/usr/share/applications/uk.co.acornfileforge.AcornFileForge.desktop"
fi
if command -v appstreamcli >/dev/null 2>&1; then
    appstreamcli validate --no-net \
        "$stage/usr/share/metainfo/uk.co.acornfileforge.AcornFileForge.metainfo.xml"
fi

mkdir -p "$output_dir"
dpkg-deb --build --root-owner-group "$stage" "$output_dir/$package_name"
echo "$output_dir/$package_name"
