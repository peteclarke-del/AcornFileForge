# Linux desktop application

The Linux desktop edition gives Acorn File Forge a normal application window,
file chooser, application-menu entry and Acorn image file associations. It
uses the same workbench and backend as the Docker edition, so format support,
editors, validation, recipes, checkpoints and save packages stay in step.

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
for the current user. It does not use `sudo` and does not modify the Docker
installation.

Launch **Acorn File Forge** from the desktop application menu, run
`tools/acorn-file-forge-desktop`, or open a registered SSD, DSD, MMB, ADFS,
BeebSCSI, UEF, HFE or ROM image from the file manager. DAT and DSC partners are
matched automatically when they share a basename.

The native chooser is a quick-open path and uses automatic target detection.
Use **File → Open image** inside the workbench when an ambiguous ADFS image
needs an explicit target profile or when several ROM components must be
combined with a particular byte layout.

## Desktop behaviour

- The application starts a private random-port service on `127.0.0.1` and
  closes it with the GTK application.
- A launch token protects every private service request. It is removed from
  the visible WebView address immediately after startup.
- Native path selection avoids uploading through a browser request, but the
  selected source is still copied to a safe working session before editing.
- Working sessions are stored under the XDG data directory and recover just as
  browser-owned sessions do.
- Save image produces the same timestamped ZIP and technical README. WebKitGTK
  writes it to the user's normal Downloads directory.
- Run and Debug use native emulator windows. The Docker edition continues to
  use its browser-visible noVNC display.
- Supported floppy images and one selected MMB slot can be written through a
  locally installed Greaseweazle. Choose **Tools → Write physical floppy** or
  right-click the image title. The workflow includes drive selection,
  destructive confirmation, tracked progress, cancellation and verification.

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
