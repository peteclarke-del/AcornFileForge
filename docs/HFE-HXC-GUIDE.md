# HFE and HxCFE guide

Acorn File Forge uses the official HxCFloppyEmulator command-line converter,
normally invoked as `hxcfe`, to open, create and save HFE floppy images. HFE is
a track and bit-cell container. DFS and ADFS are the filing systems stored in
the sectors represented by those tracks.

![Creating an HFE-wrapped Acorn floppy](images/hfe-create.png)

## What is included

The Docker image and native Debian/Ubuntu packages contain an
architecture-native HxCFE executable, `libhxcfe.so` and `libusbhxcfe.so`. The
build is made from the revision pinned in `tools/build-hxc-runtime.sh`. Users of
an official Acorn File Forge image or package do not need to install a separate
HxC package.

The native package keeps HxCFE private to the application:

```text
/opt/acorn-file-forge/native/bin/hxcfe
/opt/acorn-file-forge/native/lib/libhxcfe.so
/opt/acorn-file-forge/native/lib/libusbhxcfe.so
/opt/acorn-file-forge/native/share/licenses/HxCFloppyEmulator-COPYING
```

The application launcher supplies the private library path. Running the binary
directly for diagnosis therefore requires:

```bash
LD_LIBRARY_PATH=/opt/acorn-file-forge/native/lib \
  /opt/acorn-file-forge/native/bin/hxcfe -help
```

The Docker image installs the same executable and libraries under
`/usr/local/bin` and `/usr/local/lib`.

## Open an HFE image

1. Select **Open image** or drag an `.hfe` file onto a pane.
2. Acorn File Forge validates the HFE signature, revision, track count and side
   count before invoking HxCFE.
3. HxCFE reports the track structure and decodes the sector stream to a private
   working image.
4. Acorn File Forge identifies the decoded filesystem as DFS or ADFS and opens
   it with the applicable catalogue and filename rules.
5. Read the warning at the top of the pane. It states the HFE version, track
   count, side count, bitrate and whether the image is editable.

The original HFE is retained unchanged throughout the session. Filesystem edits
are made to decoded working sectors, not directly to the selected host file.

## Editable and read-only images

An ordinary HFE v1 image is editable when HxCFE decodes a clean sector image
and the contained DFS or ADFS geometry is supported. File editing, access
changes, compaction and cross-image transfers then follow the rules of the
decoded filesystem.

Acorn File Forge opens these images read-only:

- HFE v2 or v3 images
- images for which HxCFE reports bad sectors
- images using weak bits, variable timing, protection data or another track
  feature that cannot be represented safely by a sector filesystem editor

Read-only HFE images can still be browsed, analysed and used as a source for
file extraction. This prevents an ordinary catalogue edit from silently
destroying non-sector data.

## Create a new HFE image

Choose **File → New → New Image**, then select one of these formats:

- HFE DFS single-sided, equivalent to a 200 KiB SSD
- HFE DFS double-sided, equivalent to a 400 KiB DSD
- HFE ADFS S, 160 KiB
- HFE ADFS M, 320 KiB
- HFE ADFS L, 640 KiB

Acorn File Forge first creates the corresponding formatted sector image, then
asks HxCFE to encode it as HFE. The new pane behaves as DFS or ADFS while its
format badge remains HFE.

## Save an edited HFE image

Saving is deliberately stricter than ordinary sector-image export:

1. Acorn File Forge asks HxCFE to encode the edited sectors as a new HFE, using
   the original HFE as a track-layout reference where applicable.
2. It asks HxCFE to decode the candidate output again.
3. It compares the complete decoded result with the private working sectors.
4. A byte mismatch blocks the download and leaves the original HFE untouched.
5. A successful result is included in the normal timestamped save package with
   its generated technical README.

The progress dialog remains open while encoding and verification run. Do not
close the application until it reports that the package is ready.

## Transfers and physical disks

A DFS-formatted HFE can be inserted into an MMB slot. MMB stores DFS sectors,
not track timing, so weak-bit and protection information cannot be carried into
the slot. Acorn File Forge reports that loss before copying.

An HFE containing DFS or ADFS can be copied into another writable filesystem by
extracting its files. Load and execution addresses are retained where the
destination format supports them.

Greaseweazle can write HFE track data to a physical floppy. Its normal sector
read-back verification is not available for HFE, so the application reports an
unverified write and requires the disk to be tested on suitable hardware. See
the [physical floppy guide](PHYSICAL-FLOPPY-GUIDE.md).

## Troubleshooting

### “The HFE conversion engine is not installed”

Official 1.0.0 Docker images and native packages bundle HxCFE. If this error
appears, confirm that the package is current and that all runtime files are
present:

```bash
dpkg-query -W acorn-file-forge
test -x /opt/acorn-file-forge/native/bin/hxcfe
test -f /opt/acorn-file-forge/native/lib/libhxcfe.so
test -f /opt/acorn-file-forge/native/lib/libusbhxcfe.so
```

Reinstall the matching Debian or Ubuntu package if a file is absent. A source
checkout does not create this private runtime until
`tools/build-linux-package.sh` is run. The Docker build constructs it
automatically.

### HxCFE cannot load its libraries

Use the Acorn File Forge launcher rather than invoking the private binary. For
a direct diagnostic invocation, supply `LD_LIBRARY_PATH` as shown above.

### The image opens read-only

Read the pane warning. HFE v2/v3, bad-sector and advanced track layouts are
protected intentionally. Copy readable files to a new SSD, DSD, ADFS or clean
HFE v1 image instead of forcing a lossy rewrite.

### Conversion times out or saving fails verification

Keep the original image. Check available temporary disk space and application
logs, then retry once. A verification failure means the re-encoded sectors did
not exactly match the edited filesystem, so Acorn File Forge correctly withheld
the output.

## Build and licence boundary

`tools/build-hxc-runtime.sh` is the single build path used by Docker and native
packages. It checks out the pinned upstream revision, builds the HxCFE command
line target, stages the executable and shared libraries, installs the upstream
GPL-3.0 licence and executes a runtime smoke test. This avoids different HxCFE
implementations drifting between the web and desktop editions.

The exact pinned revision and redistribution boundary are recorded in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).
