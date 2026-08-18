# Linux desktop application

The Linux desktop edition gives Acorn File Forge a normal application window,
file chooser, application-menu entry and Acorn image file associations. It
uses the same workbench and backend as the Docker edition, so format support,
editors, validation, recipes, checkpoints, deployment packages and save
packages stay in step.

## Requirements

Use a current Debian or Ubuntu desktop with Python 3.12 or a compatible Python
3 release. Install the native libraries first:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-gi \
  gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-webkit-6.0 \
  shared-mime-info desktop-file-utils build-essential python3-dev
```

Package names can differ on Fedora, Arch and other distributions. The required
GObject namespaces are GTK 4, Adwaita 1 and WebKit 6.0.
Build tools are required because Capstone may need to compile on ARM systems
where PyPI does not provide a matching wheel.

## Install from a checkout

```bash
git clone https://github.com/peteclarke-del/AcornFileForge.git
cd AcornFileForge
tools/install-linux-desktop.sh
```

The installer creates `.venv-desktop` in the checkout, installs the Python
application dependencies there and registers the launcher, icon and MIME types
for the current user. The application-menu entry uses the stable
`~/.local/bin/acorn-file-forge` launcher, which points back to this checkout.
This avoids malformed desktop commands when the checkout path contains spaces.
It does not use `sudo` and does not modify the Docker installation.

When installation is started from a sandboxed IDE terminal, such as the Snap
build of Visual Studio Code, the script ignores that application's private
`XDG_DATA_HOME` and registers with the real user desktop under
`~/.local/share`. Any stale Acorn File Forge entry left in the IDE's private
data directory is removed.
The launcher resolves its real file after following the symbolic link, so it
still finds the checkout and virtual environment. It also removes Snap-private
GTK module paths when started from an IDE terminal, preventing incompatible
Snap libraries from being loaded into the native application.

Some Ubuntu installations deny the unprivileged user namespace that
WebKitGTK's Bubblewrap process normally creates. The launcher enables WebKit's
fallback mode so the application does not disappear before drawing its first
window. This fallback is deliberately limited to the desktop host, whose
WebView loads only the authenticated service bound to `127.0.0.1`; it does not
change the Docker/browser edition.

Launch **Acorn File Forge** from the desktop application menu, run
`~/.local/bin/acorn-file-forge`, or open a registered SSD, DSD, MMB, ADFS,
BeebSCSI, UEF, HFE or ROM image from the file manager. DAT and DSC partners are
matched automatically when they share a basename.

The folder button in the native header, **File → Open image** in a pane and
<kbd>Ctrl</kbd>+<kbd>O</kbd> all use the GTK file chooser. This keeps local media
off the browser upload path. The chooser uses automatic target detection; use
the Workbench hardware profile to describe the intended machine before making
target-specific changes.

You can also drag image files from the Linux file manager onto a workbench
pane. The first image targets the pane under the pointer and further images use
successive empty panes. DAT and DSC partners are paired before opening, so a
matching pair creates one BeebSCSI session. The GTK drop controller uses the
same trusted local-path adapter as the native chooser and does not upload image
bytes through WebKit.

## Desktop behaviour

- The application starts a private random-port service on `127.0.0.1` and
  closes it with the GTK application.
- A launch token protects every private service request. It is removed from
  the visible WebView address immediately after startup.
- Native path selection avoids uploading through a browser request. The source
  is cloned by the filesystem when supported, otherwise it is sparse-copied to
  a safe working session before editing. A 512 MiB BeebSCSI DAT therefore does
  not need to be uploaded, spooled and copied a second time.
- Opening a DAT validates its DSC pairing, geometry and root FileCore metadata.
  The expensive full-image sparse optimisation is deferred until Save, where
  the existing progress dialog describes directory repair, checksum and final
  validation stages.
- Working sessions are stored under the XDG data directory and recover just as
  browser-owned sessions do.
- Save image produces the same timestamped ZIP and technical README. WebKitGTK
  writes it to the user's normal Downloads directory.
- **Tools → Build hardware deployment** uses the same isolated snapshot and
  target layouts as Docker. The finished Gotek, MMFS, BeebSCSI, Pi1MHz or RISC
  OS ZIP is written through WebKitGTK to the normal Downloads directory.
- Run and Debug use native emulator windows. The Docker edition continues to
  use its browser-visible noVNC display.
- Supported floppy images and one selected MMB slot can be written through a
  locally installed Greaseweazle. Choose **Tools → Write physical floppy** or
  right-click the image title. The workflow includes drive selection,
  destructive confirmation, tracked progress, cancellation and verification.
- GTK and Libadwaita own the title bar, window controls, application menu,
  keyboard shortcuts, file chooser and symbolic header icons. The embedded
  workbench inherits the desktop font, follows the system light or dark setting
  until a user theme is chosen, and uses flatter desktop-sized controls. Its
  BBC-inspired media colours remain consistent with the browser edition.

### Why a large DAT used to pause at 24 percent

The old pane chooser was an HTML upload control. Its percentage measured the
transfer from WebKit into the loopback Flask request, not ADFS parsing. A large
DAT was then spooled by Werkzeug, copied into the private session and scanned
again for zero ranges. On a 512 MiB BeebSCSI image that meant several complete
passes over the file before the root directory appeared.

The native chooser now passes the selected local path through the authenticated
desktop-only API and creates the private working copy directly. On filesystems
with copy-on-write reflinks this is effectively immediate. Other filesystems
perform one sparse copy, so removable media and network mounts can still take
time, but the redundant loopback upload and eager zero scan are gone.

There is intentionally no parallel GTK implementation of panes or editors.
That would double the maintenance burden and allow filesystem safety fixes to
drift. The detailed rules are in the
[platform contract](PLATFORM-CONTRACT.md).

## Greaseweazle physical disks

Greaseweazle is optional and is not installed automatically. Install the
official tools and Linux udev rules, then confirm `gw info` works in the same
desktop session that launches Acorn File Forge. SSD, DSD and sector-based ADFS
floppies are written with automatic read-back verification. HFE can be written,
but its raw bitcell representation does not support automatic verification.

The complete safety and troubleshooting workflow is in the
[physical floppy guide](PHYSICAL-FLOPPY-GUIDE.md).

## Emulator paths

The native application can use existing emulator installations. Export the
applicable variables before launching when they are not under `/opt`:

```bash
export ACORN_ELKULATOR_ROOT="$HOME/Applications/elkulator"
export ACORN_BEM_ROOT="$HOME/Applications/b-em"
export ACORN_MAME_EXECUTABLE=/usr/games/mame
export ACORN_MAME_ROM_PATH="$HOME/.local/share/mame/roms"
tools/acorn-file-forge-desktop
```

The Workbench profile still selects the machine, additions and emulator. A
missing executable or firmware set is reported before launch.

## Update and remove

Pull the new source and rerun the installer after dependency changes:

```bash
git pull --ff-only
tools/install-linux-desktop.sh
```

Rerunning the installer also repairs an application entry that points to an
older or moved checkout and refreshes the desktop, MIME and icon databases.

Remove the launcher and private environment with:

```bash
tools/uninstall-linux-desktop.sh
```

The uninstaller deliberately retains working sessions under the XDG data
directory. Remove that directory only after saving any images you need.

## Developer smoke test

Run the shared parity tests whenever composition or routes change:

```bash
python -m unittest tests.test_platform_contract
node --check app/static/app.js
```

Then launch the desktop host and verify opening from GTK, opening from a file
manager, recovery after restart, a complete image download and a native
emulator launch. Web browser regressions remain mandatory because the frontend
is shared.

## Troubleshooting application-menu launch

Rerun `tools/install-linux-desktop.sh` after pulling an update. If the icon is
present but no window appears, run `~/.local/bin/acorn-file-forge` in a terminal
to retain startup diagnostics. Older installations may report `bwrap: setting
up uid map: Permission denied`; rerunning the current installer refreshes the
launcher with the WebKitGTK fallback described above.

The application entry is
`~/.local/share/applications/uk.co.acornfileforge.AcornFileForge.desktop`.
`desktop-file-validate` should report no errors for it. A checkout may live in
a path containing spaces because the desktop entry calls the stable launcher
under `~/.local/bin`, not the checkout path directly.
