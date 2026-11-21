# Reading and writing physical floppy disks

The native Linux edition of Acorn File Forge can open the disk in a
Greaseweazle drive as a normal pane, write an edited pane back to that disk,
format a blank disk, and send any open floppy image to a drive. The browser and
Docker editions deliberately cannot
access host USB hardware. Image editing remains shared between both editions;
only the final hardware adapter is desktop-specific.

## Supported images

| Image | Write | Read | Automatic verification |
| --- | ---: | ---: | ---: |
| DFS SSD and DSD | Yes | Yes | Yes |
| ADFS ADF, ADS, ADM and ADL floppy images | Yes | Yes | Yes |
| HFE | Yes | Yes | No |
| SCP | Yes | Yes | No |
| One formatted disk selected in an MMB | Yes, as an extracted SSD snapshot | Not applicable | Yes |
| MMB container, DAT/DSC, HDF and other hard disks | No | No | Not applicable |

## Open a disk in a drive

Choose **Open floppy drive** in an empty pane, or **File → Open floppy drive…**,
then pick the Greaseweazle drive. Acorn File Forge reads four tracks (cylinders
0 and 2 of both heads) as raw flux and identifies the disk from them without
writing anything:

| What is found on track 0 | Identified as |
| --- | --- |
| FM, ten 256-byte sectors | DFS. The catalogue gives 40 or 80 tracks, and head 1 shows double-sided |
| MFM, sixteen 256-byte sectors | Old-map ADFS. The free-space map gives S, M or L |
| MFM, five 1024-byte sectors | ADFS D or E (800 KiB) |
| MFM high density, ten 1024-byte sectors | ADFS F (1.6 MiB) |

Cylinder 2 also shows whether a 40-track disk is sitting in an 80-track drive:
its sector headers then say cylinder 1, and the disk is read with double
stepping.

What happens next depends on the disk:

- **Identified.** The whole disk is read with that layout and opens as an
  ordinary pane. Browse, add, rename, delete and undo work as for any image.
- **Not identified.** Sectors were found but match no single layout, or a DFS
  catalogue gives no track count. You are asked to choose the format and the
  head stepping. A wrong choice only produces an unreadable pane; the disk is
  not changed.
- **Unformatted.** No sector headers were found. You are asked whether to
  format the disk, and with which layout and title. Formatting needs the
  confirmation box ticked, and declining writes nothing.

Unreadable sectors do not stop the read. The pane opens with a warning that
gives the count. Their bytes are zero, and writing back would make them
permanent.

### Writing the pane back

A drive pane never writes to the disk on its own. Its header shows the drive
and either **Matches the disk** or **Changes not yet written**, and has a
**Write to disk** button. Writing asks for confirmation, then writes every
track with the layout and stepping the disk was opened with, and verifies by
reading it back. The pane then shows **Matches the disk** again. Undoing
back to the disk's contents also counts as matching, because the comparison
uses the bytes, not an edit counter.

To put a DFS disc's files onto an ADFS floppy, or the reverse, open it, use
**Tools → Convert to ADFS/DFS…** to make a converted pane, then write that
pane with **Write physical floppy…**. See *Converting between DFS and ADFS* in
the README.

Closing a pane with unwritten changes asks first. The disk keeps what it held
before, and the pane's private working copy stays available through
**Recover previous session**.

### Capturing to an image file

The `/api/desktop/physical-floppy/read` route still captures a disk into a new
image without binding it to the drive. A sector capture names one of the
layouts in the table below; `hfe` and `scp` capture bitcells or raw flux.

| Format | Captures | Use when |
| --- | --- | --- |
| `dfs-40`, `dfs-80`, `dfs-40-ds`, `dfs-80-ds` | Decoded DFS sectors | The disk is a standard DFS floppy |
| `adfs-s`, `adfs-m`, `adfs-l`, `adfs-800`, `adfs-1600` | Decoded ADFS sectors | The disk is a standard ADFS floppy |
| `hfe` | Bitcell image | The disk has non-standard tracks worth keeping |
| `scp` | Raw flux | Preservation, copy protection, or a disk that will not decode |

The earlier names `ssd`, `dsd`, `ads`, `adm`, `adl` and `adf` are still
accepted and mean the 80-track DFS and the 800 KiB ADFS layouts. A flux capture keeps everything the drive produced, including tracks no filesystem
decoder accepts, so it is the safer choice for a disk of unknown condition or
one you may only get one chance to read. Pass `revolutions` to capture several
revolutions per track when a disk is marginal.

### Layouts are always explicit

`gw` picks a disk definition from a file's suffix when it is not told one, and
its defaults are wrong for Acorn media: `.adf` means an Amiga disk, and
`.ssd`/`.dsd` mean 40 tracks. Every sector read and write therefore passes
`--format=acorn.…` explicitly. An image being written takes its layout from its
DFS catalogue or ADFS size, and a DFS image truncated after its last used
sector is padded with zeros in a temporary copy, so the original is never
changed.

Greaseweazle describes HFE and SCP as flux or raw bitcell data, so it cannot
perform its usual sector read-back verification. Acorn File Forge calls this
out before and after the write. Test an HFE- or SCP-derived physical disk on suitable hardware before
depending on it.

Opening, creating and saving the HFE itself uses the HxCFloppyEmulator
command-line converter (`hxcfe`) bundled with Acorn File Forge. That conversion
stage is separate from the optional Greaseweazle hardware write. See the
[HFE, SCP and HxCFE guide](HFE-HXC-GUIDE.md) for the supported track-container
workflow and its byte-comparison save check.

## Using a real floppy controller

A host with an actual floppy controller, such as a Raspberry Pi or a PC with a
drive attached, can read and write disks directly through `/dev/fd0` with no
Greaseweazle hardware. Select the drive and the disk's geometry, then read or
write.

This path is not equivalent to Greaseweazle, and the difference decides which
you should use:

- A floppy controller returns **decoded sectors** at whatever geometry the
  kernel has been told the disk uses. Anything the controller cannot decode
  fails rather than being captured.
- Greaseweazle captures **flux**, so it reads a disk whether or not a
  filesystem decoder accepts it.

A PC controller also defaults to 512-byte MFM sectors, while DFS and ADFS S, M
and L use 256-byte sectors and ADFS D and E use 1024. The kernel geometry must
already match the disk, normally set with `setfdprm` from the `fdutils` package
or by using a device node such as `/dev/fd0u800`. Acorn File Forge checks the
captured length against the chosen geometry and refuses a short or mismatched
read, so a disk the controller could not fully decode is never presented as a
complete image.

Use the controller for ordinary, healthy disks in a standard format. Use
Greaseweazle for anything damaged, copy protected, unusual, or that you may
only get one chance to read.

Writing through the controller erases the disk completely and cannot be undone,
so the write is refused until it is explicitly confirmed, and the image size
must match both a known Acorn geometry and the drive.

Supported geometries are DFS 40 and 80 track, single and double sided; and ADFS
S, M, L, D and E.

## Install Greaseweazle

Install the official Greaseweazle host tools so the `gw` command is available
in the desktop session. Follow the project's current installation and Linux
udev instructions:

- <https://github.com/keirf/greaseweazle/wiki/Software-Installation>
- <https://github.com/keirf/greaseweazle/wiki/Supported-Image-Types>

Connect the device and check it outside Acorn File Forge first:

```bash
gw info
```

If `gw info` fails, correct the USB connection, firmware or udev permissions.
Acorn File Forge reports the same diagnostic and does not start a write.

## Write a disk

1. Open a supported image in the native Linux application. At the root of an
   MMB, select exactly one formatted slot.
2. Open **Tools** and choose **Write physical floppy**, or right-click the
   image title or coloured format badge and choose the same command.
3. Select Greaseweazle drive A, B, 0, 1, 2 or 3.
4. Insert the destination disk. Confirm that all existing data on it may be
   overwritten.
5. Select **Write and verify**. HFE and SCP instead say **finish unverified**.
6. Keep the device connected while cylinder, head and verification progress is
   shown. **Abort operation** terminates Greaseweazle, but the disk in the
   drive must then be treated as incomplete and rewritten.
7. Keep the disk only after the completion dialog reports verification. For
   HFE or SCP, test it separately because automatic verification is unavailable.

The current working image is finalised, then copied to a private stable
snapshot before `gw write` starts. Further edits cannot change bytes halfway
through a physical write. The source image and its undo history are never
modified by the hardware operation.

## Safety and failure handling

- Commands are executed as argument arrays without a shell. Drive identifiers
  are restricted to the supported connector values.
- A failed probe never starts the motor or writes a track.
- Sector images are not reported as successful unless Greaseweazle prints its
  complete verification confirmation.
- A verification failure, missing confirmation, timeout, cancellation or
  non-zero exit status says that the physical disk may be incomplete.
- A 30-minute watchdog terminates a stalled command.
- Temporary MMB extractions and write snapshots are removed after success,
  failure or cancellation.

## Shared integration module

The UI-neutral implementation is the top-level `acorn_greaseweazle` Python
package. It owns supported suffixes, the Acorn layout table (`formats.py`), disk
identification (`detect.py`), drive validation, discovery, stable snapshots,
subprocess control, progress parsing and verification policy. The drive pane
binding (`app/physical_drive.py`) is the only part that knows about image
sessions. It has
no Flask, GTK or Nautilus dependency, so the companion `nautilus-acornfs`
project can consume the same module rather than maintaining a second hardware
implementation.

## Testing without a drive

`tests/fake_gw.py` stands in for a drive by passing reads and writes to the
real `gw convert` against a flux file. With no file present, it inserts a
blank, unformatted disk. `tests/test_physical_drive.py` uses it to format,
identify, open, edit and write back DFS and ADFS disks through the real
routes. Those round trips run when a working `gw` is on `PATH` or named by
`ACORN_TEST_GW`, and are skipped otherwise. `tests/browser/drive-pane-regression.cjs`
covers the dialogs in Chromium.

