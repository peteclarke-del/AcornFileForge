# ROM image handbook

This handbook covers the ROM-specific parts of Acorn File Forge. It is intended
for ROM collectors, developers, repairers and anyone preparing images for a
programmer. The main [README](../README.md) remains the complete application
guide. This document goes deeper into ROM interpretation, maintenance and
hardware preparation.

## Safety first

A ROM image is executable machine data. It does not contain a normal DFS or
ADFS catalogue, so names shown by the application are decoded structures and
evidence, not files that can be mounted or extracted.

Before changing a ROM:

1. Keep the original dump outside Acorn File Forge.
2. Create a named checkpoint in **Edit -> Checkpoints**.
3. Record the machine, socket, ROM board, chip type and any link settings under
   **Tools -> ROM Workbench -> Project**.
4. Save and compare checksums before programming a device.
5. Test in an emulator or a spare programmable device before replacing a
   known-good ROM.

A recognised title or valid header proves only that a structure was decoded.
It does not prove that the code is safe for a particular machine, ROM slot,
Tube configuration, bank-switching board or physical device.

## Supported ROM input

The normal image picker recognises `.rom`, `.rom0` through `.rom7`, and `.bin`
files that contain a recognisable Acorn header. Use **Raw format override ->
Acorn ROM** when a headerless binary or unusually named dump is misidentified.

The application supports:

- 8 KiB and 16 KiB BBC, BBC Master and Electron sideways ROMs;
- 32 KiB and larger images divided into configurable logical banks;
- 256 KiB images commonly exposed as sixteen 16 KiB banks;
- a partial final bank, preserved without padding and reported by Image Health;
- BBC-family language, service and combined language/service headers;
- BBC-family 6502, 65C02 and 68000 processor flags;
- RISC OS extension ROM trailers and plausible relocatable module headers;
- two-chip and four-chip byte-interleaved source sets;
- custom byte images where no standard header can be proved.

Logical bank size must be at least 256 bytes and aligned to 256 bytes. The bank
view does not rewrite, pad or reorder bytes merely because its layout settings
change.

## Opening one image or a physical chip set

### One image

1. Choose **Open image** in an empty pane.
2. Select the ROM or BIN.
3. Confirm the platform and byte layout in the ROM summary.
4. Use the raw Acorn ROM override if automatic detection is inappropriate.
5. After opening, choose **Tools -> ROM layout** if the logical bank size,
   erased byte, target family or layout needs correction.

### Two or four physical files

Select two or four equal-sized component files together. The open dialog asks
how they relate:

- **Concatenate** places each selected component after the previous component.
  Use this for files that represent consecutive banks.
- **Byte interleave** reconstructs logical CPU byte order from byte-wide
  physical chips. Two lanes alternate bytes between two chips. Four lanes do
  the same across four chips, which is common in Archimedes and RISC OS ROM
  sets.

Component order matters. Keep the file selection order consistent with the
physical sockets. The saved ZIP records that order and contains reconstructed
files in `ROM-components`.

## Reading the ROM pane

![ROM bank inventory showing address, identity, purpose and utilisation](../app/static/help/rom-pane.png)

The pane is a bank inventory. At normal width it has four columns. In a narrow
or multi-pane layout, each bank becomes a two-column information card.

| Field | Meaning |
| --- | --- |
| Bank | Zero-based logical bank number using the current bank size. |
| File address | Byte offset in the complete saved image. It is not a CPU address. |
| Mapped address | Conventional CPU window for the chosen target. A normal BBC-family 16 KiB sideways bank maps to `&8000-&BFFF`. |
| Identity | Header title or a clear `Empty bank` or raw-data description. |
| Version and copyright | Strings decoded from a valid BBC-family header. |
| Purpose | Language, service, combined, RISC OS extension, raw or erased. |
| Processor | Processor declared by the header, such as 6502 BASIC, 65C02 or 68000. |
| Entry points | Proven language and service vectors in mapped address form. |
| Programmed | Bytes that differ from the configured erased value. |
| Percentage | Programmed bytes divided by actual bank length. This is not filesystem free space. |
| Duplicate result | Other banks with byte-identical content, or `Unique bank contents`. |
| SHA-256 | A shortened fingerprint. Point at it for the complete value. |

The guidance strip provides the shortest route to the next level:

- select the information icon to decode the bank;
- double-click the row to open its first byte in the hex editor;
- use **Tools -> ROM Workbench** for code, revision and hardware work;
- use **Tools -> ROM layout** to change interpretation without rewriting data.

## Decoded bank information

![Decoded ROM information with fingerprints, header and star-command evidence](../app/static/help/rom-decoder.png)

The information dialog deliberately begins on its heading. Opening it does not
select or expand the first command. Tab moves to the first interactive control.

### Fingerprints and byte statistics

The bank report includes:

- its exact byte range in the complete image;
- SHA-256 and CRC-32 fingerprints;
- Shannon entropy from 0 to 8 bits per byte;
- the number of distinct byte values;
- counts of configured erased bytes, zero bytes and `&FF` bytes;
- the first and last non-erased offset;
- printable-byte count;
- byte-identical logical banks.

These values are diagnostics. High entropy can suggest compressed, encrypted or
dense code, but it is not a copy-protection detector. Printable strings can
suggest commands, messages or build data, but string boundaries are not files.

### BBC-family header

For a valid sideways-ROM header the decoder reports title, version string,
version byte, copyright, ROM type byte, role flags, processor, language entry,
service entry and extra feature bits. It checks the declared role flags against
the entry vectors and reports contradictions to Image Health.

Rename is available only when the existing allocated title field can be changed
safely. It does not move machine code or enlarge the header.

### Star commands and help

RISC OS modules have a standard command keyword table, so structurally valid
entries are labelled **Declared**. The decoder can show parameter limits,
configuration or status keywords and module ownership.

BBC, Master and Electron service ROMs do not share one universal command
catalogue. The scanner therefore accepts only coherent evidence:

- token-dispatch tables with a valid command run and token use;
- address-dispatch tables with valid in-ROM handlers and an indexed 6502 code
  reference;
- declared RISC OS module command tables.

Printable `*NAME` text alone is rejected. This avoids listing examples, help
headings, error messages and accidental machine-code strings as commands.

The `?` control opens the help available for a command. Its source label tells
you whether the text was declared by a RISC OS module, reconstructed from a
BBC command syntax table, or recovered from a shared BBC `*HELP` topic. Hover
or keyboard focus shows the tooltip. Selecting it pins the tooltip; Escape
closes pinned help. **Table** and **Handler** open the relevant bytes in a hex
editor inside the decoder. Closing that editor returns to the same dialog and
scroll position.

![Pinned help reconstructed from a ROM command syntax table](../app/static/help/rom-command-help.png)

No listed commands does not prove that a ROM has none. A ROM can construct
names dynamically, recognise abbreviations directly in code or use an unknown
table layout. Test `*HELP` on suitable hardware and inspect the service entry
when the static evidence is inconclusive.

### RISC OS structures

For Archimedes targets, the decoder looks for standard relocatable-module
header offsets, bounded title and help strings, entry facilities, command
tables and SWI information. A candidate remains labelled as plausible until
an enclosing extension-ROM structure proves its role.

A standard `ExtnROM0` trailer supplies a declared image size and checksum. Image
Health compares the stored and calculated checksums and offers repair only when
the standard structure is proven.

## ROM Workbench

Open **Tools -> ROM Workbench** for maintenance and development. Its tabs share
the same working ROM and project metadata. Closing the Workbench does not save
the image to the host; use the pane save control for that.

### Overview

![ROM Workbench Overview with bank map, identity and audit result](../app/static/help/rom-workbench-overview.png)

Overview shows bank count, bank size, exact catalogue identity and health. The
bank map relates logical bank, file offset, decoded title, type and duplicate
banks. On an interleaved image it also describes physical byte lanes.

Audit findings can offer two narrowly defined repairs:

- align BBC header role flags with proven language and service vectors;
- rebuild the checksum of a standard RISC OS extension-ROM trailer.

Each repair creates an automatic undo checkpoint. The app does not offer a
guess-based repair for unrecognised headers or ambiguous code.

**Identify this exact ROM** stores title, version, publisher, platform and notes
against the complete SHA-256. Built-in catalogue records live in
`app/rom_catalogue.json`. User records live in an owner-scoped catalogue in the
work volume, so another browser owner does not inherit them.

### Disassembly

![ROM Workbench Disassembly showing controls, reachability and references](../app/static/help/rom-workbench-disassembly.png)

Select bank, architecture, mapped origin, byte offset and byte count. Numeric
fields accept normal `0x` notation. The result reports decoded instruction
count, reachable instructions and referenced targets.

| Architecture | Interpretation |
| --- | --- |
| NMOS 6502 | Native Acorn byte order. Unknown or undocumented opcodes remain `EQUB` data. |
| ARM | Little-endian 32-bit ARM instruction mode, suitable for classic Archimedes and RISC OS code. |
| 68000 | Native big-endian 68000 instruction decoding. |
| Auto | ARM for an Archimedes target, 68000 when a header declares it, otherwise 6502. |

Known language, service and decoded command-handler entries seed control-flow
reachability. Direct branch and call destinations receive cross-references.
Calls through the BBC MOS jump table are labelled, including `OSBYTE`,
`OSWORD`, `OSFILE` and `OSCLI` where applicable. This is a bounded static
analysis, not an emulator. Indirect calls, generated code and bank-switching
logic can remain unresolved.

Project symbols use `address = label`, for example `0x8036 = ServiceEntry`.
Known regions use `start-end = meaning`, for example
`0x9000-0x91ff = Command table`. Save them in Project and disassemble again.

### Compare and guarded patches

Open a second ROM in another pane, then choose it in Compare. The report groups
contiguous changed byte ranges and counts changed bytes. You can export all
changes or tick reviewed ranges for a selective patch.

An Acorn File Forge patch stores the patch format, complete source SHA-256,
complete target SHA-256, source and target sizes, and fixed byte ranges. Patch
creation has a 16 MiB safety limit. Applying a patch fails if the selected
source checksum is wrong, any range is invalid, or the completed image does not
match the target checksum. Patch application creates a normal image checkpoint.

### Build

The service-ROM scaffold creates an inert BBC-family header and command table.
Its handlers return immediately. It is a development starting point, not a
finished ROM and not proof that entered commands are implemented.

The AFFROMFS builder stores named host bytes in the documented `AFFROMFS1` data
archive layout. It needs companion service code written for that layout. An
unmodified MOS does not mount it and Acorn File Forge does not describe it as a
native filing system.

Both builders replace all working ROM bytes after a dangerous-operation
confirmation and automatic checkpoint.

### Programmer

![ROM Workbench Programmer tab configured for two byte-wide chips](../app/static/help/rom-workbench-programmer.png)

Programmer prepares bytes for a physical device without changing the logical
working ROM. Available transforms are applied in a defined sequence:

1. pad with the configured erased byte, or mirror the image to the requested
   device size;
2. optionally swap adjacent byte pairs;
3. optionally swap 16-bit words within each 32-bit group;
4. optionally swap address-bit pairs such as `0:1` for A0 and A1;
5. split the result into one, two or four physical byte lanes.

The requested device must be large enough for the image. Address-bit numbers
must be valid for its address range and a bit cannot participate in conflicting
swaps. The ZIP contains each chip file and a programming report with transform,
size and checksum details. Verify those checksums against programmer read-back.

### Project

Project fields are annotations. They do not modify ROM bytes. Store:

- hardware, board, socket and chip information;
- research or repair notes;
- address labels used by Disassembly;
- known address regions;
- retained emulator results.

The normal saved ZIP includes `ROM-project.json`, allowing the reasoning behind
a repair or build to travel with the ROM.

### Emulator

Set `ACORN_ROM_EMULATOR_COMMAND` in the local deployment and include a `{rom}`
placeholder. The command is parsed into arguments and executed directly without
a shell. It receives the current working ROM path, has a 30-second time limit,
and retains the last 20,000 characters of standard output and standard error.
Results are appended to project metadata, capped at 512 records.

Example Compose fragment:

```yaml
services:
  acorn-file-forge:
    environment:
      ACORN_ROM_EMULATOR_COMMAND: /tools/check-rom --image {rom}
```

The executable and any emulator ROMs must already exist inside the container.
An exit code is evidence from that configured tool, not a universal hardware
compatibility certificate.

## Editing operations

| Operation | Result | Important restriction |
| --- | --- | --- |
| Rename image | Changes the working filename. | Does not alter internal ROM title. |
| Rename bank | Changes a safely allocated recognised header title. | Raw banks cannot be renamed as if they were files. |
| Add ROM banks | Appends one or several files. | Exact bank multiples split; silent truncation is refused. |
| Append empty bank | Grows by one configured bank. | Uses the configured erased byte. |
| Erase bank | Fills the selected bank. | Keeps bank and image size. |
| Cut, Copy, Paste | Moves or duplicates whole logical banks. | An overlapping move is atomic. |
| Drag between ROM panes | Copies selected banks in order. | Target layout and capacity rules still apply. |
| Hex edit | Replaces fixed byte ranges. | Cannot insert, delete or resize bytes. |
| Repair | Applies a proven metadata correction. | Offered only for supported deterministic faults. |

ROM banks can move between ROM panes. A disk filesystem cannot represent a ROM
bank as a mounted directory, and an MMB slot accepts a DFS disk image rather
than loose ROM bytes. Where a destination can store ordinary files, use an
explicit file export or archive workflow rather than pretending a bank is a
filesystem.

## Hex editor behaviour

Opening Hex from the pane scopes the editor to that pane. Opening Table,
Handler, a known region or the whole bank from the decoder scopes the editor to
the decoder dialog. Closing the nested editor returns to the same decoder scroll
position. If bytes were written, the decoder is rebuilt from the new data.

Raw writes are fixed-size replacements and require the dangerous-operation
confirmation. The server rejects stale, overlapping and out-of-range changes,
creates an undo checkpoint, writes reviewed ranges, flushes storage and clears
decoded caches. Refresh the pane and run Image Health afterwards.

## Saving and accompanying files

Save produces a timestamped ZIP rather than replacing the browser-selected
source. A ROM save includes:

- the logical ROM image;
- a detailed technical README;
- `ROM-project.json`;
- reconstructed component files when a component set was opened;
- applicable loose-file metadata generated by other export operations.

The technical README records format, byte size, bank size, bank count, erased
byte, platform, logical layout, component order, recognised headers, bank
fingerprints and complete image SHA-256. Keep it with the programmed image.

After a successful save, the pane's changed indicator clears only when the
prepared archive corresponds to the current image revision.

## Health checks and troubleshooting

Choose **Analyse -> Image health dashboard** after structural changes and raw
edits. ROM checks include:

- zero length and invalid configured bank size;
- partial final bank;
- erased or unrecognised banks;
- byte-identical banks;
- BBC header roles that contradict their entry vectors;
- RISC OS extension size and checksum consistency;
- current target and layout context.

### A title is missing or wrong

The bank may have no standard header, a corrupt offset, a non-standard title
scheme or a different logical bank size. Confirm layout first, then inspect the
header bytes. Use fingerprinted identity for collection metadata rather than
inventing a header repair.

### Commands are missing

Static extraction intentionally favours precision. Dynamic command matching,
abbreviations and unusual tables can be invisible. Check `*HELP` on the target,
inspect the service routine and save useful addresses as project symbols.

### A reported command is wrong

Record the ROM SHA-256, bank, reported command and relevant table bytes. Do not
rename the bank to hide the result. The extractor needs better structural
evidence or an additional supported dispatch pattern.

### The processor or mapped address looks wrong

Check target family, bank size and mapped origin. Processor flags come from the
header and can themselves be corrupt. A custom image may have no single mapped
origin.

### Disassembly looks like nonsense

Confirm architecture, origin and offset. You may be looking at text, tables,
compressed data, an interleaved physical dump or code reached only after a bank
switch. Disassembly is not an automatic separation of code and data.

### A physical chip does not boot

Verify chip size, erase value, lane order, byte and word swaps, address-line
mapping and programmer read-back checksum. Confirm the board's links and ROM
socket voltage. Return to the untouched original before trying another
transform.

### The ROM is known but the catalogue says Unknown

Built-in and private identities are exact SHA-256 matches. A one-byte change,
different padding or a concatenated bank set is a different image. Use
**Identify this exact ROM** only after confirming that the dump is sound.

## What ROM support deliberately does not claim

Acorn File Forge does not fully emulate a machine, infer arbitrary ROM board
bank-switch registers, decompile machine code into source, defeat copy
protection, prove electrical compatibility, or convert arbitrary disk software
into a bootable ROM automatically. The service scaffold and AFFROMFS are tools
for developers who will supply the missing code. Labels such as `candidate`,
`reconstructed` and `unrecognised` are intentional boundaries between evidence
and guesswork.
