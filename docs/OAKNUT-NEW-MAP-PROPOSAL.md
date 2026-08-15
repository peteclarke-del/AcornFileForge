# Oaknut classic FileCore E/F implementation history

Oaknut ADFS 12.14.0 includes complete, writable support for the classic ADFS E
and F floppy formats. Acorn File Forge pins that component and verifies its
new-map classes while building the Docker image. These are the
800 KiB and 1.6 MiB FileCore new-map formats normally encountered as
Archimedes ADF images. They are not old-map ADFS images with larger geometry.

The original proposal is retained in
[`patches/oaknut/0001-add-writable-filecore-e-f-support.patch`](patches/oaknut/0001-add-writable-filecore-e-f-support.patch).
It is useful for reviewing the implementation history or for maintainers of an
older Oaknut 12.13.1 source tree. The Docker build no longer applies either
patch because doing so would overwrite the released implementation.

The adjacent `0001-add-writable-filecore-e-f-runtime.patch` is the historical
wheel-layout version of the same proposal. It is not part of the current build.

## Implemented behaviour

The patch adds:

- content-based E and F detection, including both map copies and exact disc
  geometry;
- ZoneCheck and CrossCheck validation;
- single-zone E and four-zone F map parsing;
- fragmented object and indirect disc-address translation;
- 2 KiB new-format directories with up to 77 entries;
- nested directory traversal, file reads and Acorn metadata;
- file and directory creation, replacement, rename and deletion;
- load and execute addresses, access flags, filetypes and datestamps;
- volume title, directory title and boot-option editing;
- free-space reporting, compaction and filesystem validation;
- fresh E and F image creation; and
- transactional map rebuilding, with both map copies checked before changed
  bytes replace the working image.

An existing image containing defect objects or allocated objects which are not
referenced by the directory tree remains readable, but mutation is refused.
That rule avoids silently discarding structures that the compacting writer
cannot safely reproduce.

## Scope

This patch covers the classic E and F floppy layouts. It does not claim support
for F+, E+, big directories, format-version extensions, very large FileCore
media or proprietary variants. Those formats need separate fixtures and
review. They must not be inferred merely from an ADF suffix.

Old-map S, M, L, D and supported hard-drive layouts continue through Oaknut's
existing implementation. The new code is selected only after a checked
new-map disc record has been found.

## Applying it to an Oaknut checkout

From the root of an Oaknut 12.13.1 checkout:

```bash
git apply /path/to/AcornFileForge/docs/patches/oaknut/0001-add-writable-filecore-e-f-support.patch
uv run pytest packages/oaknut-adfs/tests
```

Acorn File Forge's Dockerfile installs `oaknut-adfs==12.14.0` and checks for the
native E/F implementation. A source installation which uses an older system
Oaknut deliberately reports a specific E/F compatibility error instead of the
misleading generic unrecognised-filesystem message.

## Verification completed

During the original proposal, the Oaknut ADFS test suite passed all 508 tests
with the patch applied. The additional tests covered generated and reopened E/F media, files, nested
directories, metadata, boot options and map validation. Manual checks also
covered:

- the repository's real 800 KiB sample image;
- a published blank 1.6 MiB F image;
- read, write, rename and reopen cycles on disposable copies; and
- public API creation of fresh E and F filesystems.

The implementation follows the FileCore chapter of the RISC OS Programmer's
Reference Manual. Linux's independently implemented ADFS boot-block checksum
was used as a cross-check. Release validation should also catalogue and mutate
test images in Arculator and RPCEmu.

## Maintainer review points

The writer deliberately rebuilds a compact map in memory and validates the
replacement before publishing it. This costs more memory than editing fragment
links in place, but gives a much safer failure boundary for floppy-sized media.
Useful upstream review should focus on map-zone edge cases, nonstandard defect
layouts, shared fragment IDs and whether later FileCore variants should extend
these classes or use separate mounts.
