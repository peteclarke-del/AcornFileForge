# Writing physical floppy disks

The native Linux edition of Acorn File Forge can send an open floppy image to
a Greaseweazle drive. The browser and Docker editions deliberately cannot
access host USB hardware. Image editing remains shared between both editions;
only the final hardware adapter is desktop-specific.

## Supported images

| Image | Write | Automatic verification |
| --- | ---: | ---: |
| DFS SSD and DSD | Yes | Yes |
| ADFS ADF, ADS, ADM and ADL floppy images | Yes | Yes |
| HFE | Yes | No |
| One formatted disk selected in an MMB | Yes, as an extracted SSD snapshot | Yes |
| MMB container, DAT/DSC, HDF and other hard disks | No | Not applicable |

Greaseweazle describes HFE as raw bitcell data, so it cannot perform its usual
sector read-back verification. Acorn File Forge calls this out before and after
the write. Test an HFE-derived physical disk on suitable hardware before
depending on it.

Opening, creating and saving the HFE itself uses the HxCFloppyEmulator
command-line converter (`hxcfe`) bundled with Acorn File Forge. That conversion
stage is separate from the optional Greaseweazle hardware write. See the
[HFE and HxCFE guide](HFE-HXC-GUIDE.md) for the supported track-container
workflow and its byte-comparison save check.

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
5. Select **Write and verify**. HFE instead says **finish unverified**.
6. Keep the device connected while cylinder, head and verification progress is
   shown. **Abort operation** terminates Greaseweazle, but the disk in the
   drive must then be treated as incomplete and rewritten.
7. Keep the disk only after the completion dialog reports verification. For
   HFE, test it separately because automatic verification is unavailable.

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
package. It owns supported suffixes, drive validation, discovery, stable
snapshots, subprocess control, progress parsing and verification policy. It has
no Flask, GTK or Nautilus dependency, so the companion `nautilus-acornfs`
project can consume the same module rather than maintaining a second hardware
implementation.
