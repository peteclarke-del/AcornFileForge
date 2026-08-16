# Oaknut FileCore integration

Acorn File Forge uses the released Oaknut 12.14.1 packages. No local Oaknut
patch is applied at build time.

Oaknut 12.14.1 incorporates the writable classic E/F work and supplies one
content-driven ADFS implementation for the full standard floppy family:

| Format | Capacity | Allocation map | Directory layout | Filename limit | Entries per directory |
| --- | ---: | --- | --- | ---: | ---: |
| S | 160 KiB | Old | Old | 10 | 47 |
| M | 320 KiB | Old | Old | 10 | 47 |
| L | 640 KiB | Old | Old | 10 | 47 |
| D | 800 KiB | Old | New | 10 | 77 |
| E | 800 KiB | New, one zone | New | 10 | 77 |
| E+ | 800 KiB | New, one zone | Big | 255 | Capacity-dependent |
| F | 1.6 MiB | New, four zones | New | 10 | 77 |
| F+ | 1.6 MiB | New, four zones | Big | 255 | Capacity-dependent |
| G | 3.2 MiB | New, eight zones | New | 10 | 77 |
| G+ | 3.2 MiB | New, eight zones | Big | 255 | Capacity-dependent |

The app creates every format in that table, identifies existing media from its
on-disc structures, traverses nested directories, preserves Acorn metadata,
reports free space, compacts allocation and runs Oaknut's structural validator.
The pane receives the detected filename and directory limits. Bulk planners
therefore group files only when the mounted directory layout requires it.

New-map hard disks are also content-detected. This includes raw FileCore images
and RPCEmu or Arculator HDF/HD4 layouts whose logical disc address zero begins
at the 0x200-byte emulator offset. A New-map DAT can be edited without a DSC
because its allocation structures describe the filesystem extent. A classic
BeebSCSI old-map DAT still requires its matching DSC geometry file for safe
hardware-compatible editing and saving.

## Dependency boundary

`requirements.txt` pins `oaknut-disc`, `oaknut-adfs` and `oaknut-romfs` to the
same 12.14.1 release. The Docker dependency stage imports the public ADFS format
constants for D through G+ and fails the build if that released capability is
missing. Application code does not carry or apply a fork of Oaknut.

`app/adfs_capabilities.py` is the small adapter between Oaknut's generic mount
surface and pane-facing constraints. Keeping this in one module prevents
format-specific checks from spreading through transfer and presentation code.

## Verification

The generated-media matrix creates, writes, reads, validates and reopens all
standard ADFS floppy layouts. It also writes a filename longer than ten
characters to an E+ Big directory and checks that the exact name and contents
survive the round trip. Container tests verify the released FileCore capability
at build time.

For upstream implementation details, see the
[Oaknut ADFS documentation](https://github.com/rob-smallshire/oaknut/blob/master/packages/oaknut-adfs/README.md).
