# File editor and code analysis handbook

This handbook covers the file-level editors in Acorn File Forge. It describes
what the application proves from the bytes, what it infers from the active
hardware profile, and where it deliberately stops. The editor is intended for
maintenance, inspection and controlled changes inside a working image. It is
not a source-level debugger or a substitute for testing on the target machine.

## Safety model

Opening a file does not modify it. Editable source remains local to the editor
until **File > Save** or **File > Save As** is selected. A successful write:

1. verifies that the file still matches the SHA-256 recorded when the editor
   opened;
2. validates or tokenises the source as required by its content type;
3. creates an automatic image checkpoint;
4. writes through the mounted filesystem while retaining Acorn metadata;
5. refreshes the pane and marks the image as changed.

The stale-file check prevents one editor from silently replacing a newer
change made elsewhere in the workspace. Save As creates a sibling file and
leaves the source file intact. The image is still a private working copy until
the pane's Save Image control prepares its timestamped download ZIP.

Archive members are different. They are expanded in memory and opened
read-only. Acorn File Forge does not rewrite a ZIP, TAR or compressed stream
without a transactional archive writer. Export the member, edit it in a normal
image, then rebuild the distribution with a suitable archive tool.

## Opening and exporting a file

Double-click a file in a DFS, ADFS, FileCore, ROMFS, UEF or archive view. The
same dispatch is available through **Analyse > Open selected file**. The arrow
beside a filename downloads the original file and applicable Acorn metadata
without opening an editor.

Content detection uses evidence in this order:

1. an authoritative Acorn filetype or recognised filename;
2. bounded inspection of files up to 128 KiB while the directory mount is
   already open;
3. complete inspection when the user opens a file;
4. a raw hexadecimal fallback when no safer interpretation is available.

This keeps large DAT and HDF directory listings responsive without leaving
ordinary BASIC programs, command files and archives with misleading icons.
The cache is tied to the working image revision and is discarded after a
mutation.

## Editor window

Source and disassembly editors open as movable, resizable windows within the
browser. Drag the title bar to move one. Drag an edge or corner to resize it.
Use the square title-bar control, or double-click the title bar, to maximise
and restore it. The window is constrained to the browser viewport.

The menus follow desktop editor conventions:

- **File** contains Save, Save As, text or source export, original-byte
  download and Close where those operations apply.
- **Edit** contains Undo, Redo, clipboard operations, Select All, Find, Find
  and Replace, symbol references, symbol rename and line navigation.
- **View** contains folding, synchronized bytes and visual indentation.
- **Tools** contains language checks, outlines, transformation history,
  normalisation, BASIC verification, Condense and Refactor.
- **Project** contains notes, bookmarks, symbols, code and data regions, test
  history and the optional emulator hand-off.
- **Help** contains the language overview, searchable command reference,
  document symbols and current diagnostics.

The native textarea remains the editable document. Syntax colour, indentation,
folding, annotations and hover targets are presentation layers. This preserves
normal browser selection, input methods, clipboard behaviour and undo.

## Command-script editor

![Command script editor showing a real DFS !BOOT file](../app/static/help/file-editor-script.png)

Readable `!BOOT`, `BOOT`, `START`, `STARTUP`, `LOADER`, `MENU` and similar
files are opened as unnumbered scripts when their bytes contain a coherent run
of MOS or BASIC commands. Detection is based on content as well as name. A
tokenised BASIC file named `!BOOT` remains a BASIC program.

Scripts retain their physical order and use carriage-return line endings when
written back. The editor recognises star commands and common BASIC commands,
highlights strings and arguments, and flags:

- unclosed strings;
- rooted or filing-system-dependent `R.` and `L.` abbreviations;
- `CHAIN "!BOOT"` where an executable command file should normally be passed
  to `*EXEC`.

These checks are deliberately narrow. A command file can depend on a ROM,
filing system, memory layout or machine configuration that static text cannot
prove.

## BBC BASIC editor

![Tokenised BBC BASIC II opened from an ADFS floppy image](../app/static/help/file-editor-basic.png)

Tokenised BBC BASIC II opens as numbered source with one visible space after
each line number. The application retains the tokenised bytes as the authority
for saving. BASIC V and BASIC programs with trailing binary data open
read-only because writing them through the BASIC II tokeniser would change
their format.

### Editing and paste handling

Type a numbered line to insert or replace it. Remove the complete physical line
to delete it. When numbered text is pasted, the editor asks whether to validate
and normalise it as BBC BASIC or insert the bytes as plain text. The complete
listing must still tokenise successfully before it can be saved.

**Tools > Renumber BASIC** changes physical line numbers and encoded direct
targets used by `GOTO`, `GOSUB` and `RESTORE`. It does not rewrite numbers in
strings or dynamic line expressions.

### Diagnostics and help

The live analyser reports missing, duplicated or out-of-order line numbers,
unresolved direct destinations, missing local procedures, unmatched procedure
boundaries, unclosed strings and conservatively identified unreachable lines.
It also builds a procedure and function outline with direct call sites.

Commands with reference data have dotted hover targets. Hovering displays the
command's purpose, syntax, context and relevant cautions. Put the caret in a
command and press F1 for the keyboard equivalent. Inline assembler between `[`
and `]` uses the same 6502 or ARM instruction, MOS entry-point and directive
help as the disassembly editor.

The leading star is part of the command context. `LOAD "PROGRAM"` receives
BBC BASIC LOAD help, while `*LOAD CODE 3000` receives MOS `*LOAD` help and is
shown as `*LOAD` in the tooltip and command summary. The same distinction
applies to overlapping commands such as RUN and SAVE. Normalising command case
never removes the star.

### Visual indentation and folding

Visual indentation understands procedures, multi-line functions, `FOR`,
`REPEAT`, structured `IF`, `CASE`, `WHILE` and inline assembler boundaries.
Choose tabs or 2, 4 or 8 spaces. This changes only the rendered view. It does
not alter source text, dirty state, tokenised bytes or the saved image.

The left gutter folds recognised blocks. The state-aware View command reads
**Collapse all blocks** when everything is expanded and **Expand all blocks**
when anything is folded. Double-click a rendered source line to return to its
exact editable location.

Classic BBC BASIC `IF` semantics matter here. A line such as
`IF condition THEN 100` does not open a block, and an omitted-`THEN` form
controls only the following statement. Physical lines that follow it are not
indented as if the language had an implicit `ENDIF`.

### Refactor

Refactor operates on the physical selection, a selected line, or the complete
program when nothing is selected. It proposes a readable expansion of compact
BBC BASIC and can:

- split proven colon-separated statement boundaries;
- expand inline and nested `IF`, `ELSE IF` and `ELSE` logic;
- extract a compact `ON ERROR` handler behind an explicit branch;
- separate commands on `DEFPROC` and `ENDPROC` lines;
- normalise compact token spellings such as `UNTILINKEY` and `FORI%`;
- update direct line destinations after its proposed renumbering.

The proposal appears beside the original. It is tokenised, detokenised and
tokenised again before acceptance is enabled. No source is changed or
renumbered until the user accepts the review and confirms it. Cancel returns
to the untouched document. Acceptance is one undoable editor operation and
retains the logical cursor and viewport.

Refactor does not rename variables, alter strings, invent procedures, rewrite
dynamic destinations or split inline assembler. When a statement boundary
cannot be proved safe it remains unchanged for manual review. A physical line
whose body is only `:` is retained because BBC BASIC does not support a blank
numbered source line.

### Condense

Condense performs the controlled inverse. It packs adjacent statements with
`:` while preserving target lines and runtime order. It uses the installed BBC
BASIC tokeniser to enforce the 251-byte physical-line limit. Packing stops at
inline `IF`, `ON ERROR`, `REM`, star commands, unconditional transfers and
structured branch boundaries. Code with computed line destinations, or code
that uses `ERL` in a way affected by removing physical lines, is left alone.

Condense uses the same original and proposal review, round-trip proof, explicit
acceptance and single undo operation as Refactor.

### Synchronized bytes

**View > Show synchronized bytes** maps the caret's BASIC line to the bytes in
the last saved tokenised program. Unsaved source is never presented as if it
were already on disk. A newly inserted or renumbered line has no saved byte
range until Save succeeds; the strip says so rather than pointing at offset
zero. The Hex shortcut opens the exact saved offset.

## Text editor

Readable Latin-1 content that is neither tokenised BASIC nor a command script
opens as text. Save encodes Latin-1 and rejects characters that cannot be
represented rather than silently replacing them. File > Export downloads
browser-local text. Save preserves the existing load address, execution
address, filetype and access state where the destination filesystem supports
them.

## Disassembly editor

![Annotated 6502 disassembly opened from a DFS executable](../app/static/help/file-editor-disassembly.png)

Binary files open as editor-style disassembly rather than a report table. The
active workbench profile selects the initial architecture: 6502 for BBC,
Master and Electron targets, ARM for Archimedes and RISC OS. The toolbar can
override that choice with 6502, ARM or 68000 and accepts a mapped origin, file
offset and bounded byte count.

### Decoding and annotation

The 6502 decoder distinguishes official NMOS instructions from data. Unknown
opcodes remain `EQUB`. It tracks immediate register values only while the code
path proves them, drops assumptions at uncertain joins, and adds specific
comments for:

- MOS jump-table calls such as `OSBYTE`, `OSWORD`, `OSFILE` and `OSCLI`;
- known OSBYTE, OSWORD, OSFILE and OSFIND reason codes and proven parameters;
- OSWRCH characters and VDU control values;
- BBC hardware I/O regions;
- branch conditions and direct references;
- conventional BBC BRK error blocks;
- the file execution address.

Local targets receive stable semantic labels where behaviour is proven, with
their hexadecimal address retained to keep similar routines distinct. ARM and
68000 use Capstone 5.0.9. ARM words are decoded little-endian and 68000 words
big-endian. Saved project symbols apply to all three architectures.

Static disassembly cannot prove indirect targets, generated code, compression,
bank switching or whether bytes are data. Treat the original bytes and target
execution as the final evidence.

### Layout, strings and navigation

The grid measures the widest byte and instruction fields in the current
result, adds a small gutter, and places annotations immediately after them.
Long cells are capped and expose their complete content on hover. The heading
remains visible while scrolling.

Readable strings require alphabetic content and exclude incidental punctuation
and number runs. Strings found inside the decoded range are rendered as `EQUS`
data rows. Select one in the Readable strings list to jump to its disassembled
location. If the location is outside the current block, the editor requests a
new bounded disassembly around it. Double-click an instruction only when the
corresponding raw bytes are required in Hex.

### Project metadata

Project metadata is stored outside the file bytes in the private recoverable
session. It includes:

- notes;
- bookmarks tied to saved file offsets;
- address symbols;
- user-classified code, text, byte, 16-bit word, address-table and bitmap
  regions;
- transformation history;
- configured emulator results.

Shift-click disassembly rows to select a range, classify it, and rebuild the
listing using that decision. Word and address regions follow the selected
processor's byte order. Symbols can be imported and exported as
`&address = label`. Find references and the outline navigate direct users and
labelled entry points. Project metadata participates in session recovery and
checkpoints but does not alter the image bytes.

## Optional emulator hand-off

Set `ACORN_FILE_EMULATOR_COMMAND` in the container environment. It must contain
`{file}` and may contain `{image}`, `{path}`, `{load}` and `{execute}`. The
command is parsed into arguments and run without a shell. Acorn File Forge:

1. exports the current saved file to a temporary path;
2. substitutes the configured placeholders;
3. runs the command with a 60-second timeout;
4. retains the return code and the final 20,000 characters of each output
   stream in project metadata;
5. removes the temporary file.

Example:

```yaml
services:
  acorn-file-forge:
    environment:
      ACORN_FILE_EMULATOR_COMMAND: /tools/test-file --file {file} --load {load}
```

The executable and its dependencies must already exist inside the container.
An exit code records what that configured tool observed. It does not prove
compatibility with every Acorn machine or filing-system configuration.

## Archive and UEF members

UEF, gzip-compressed UEF, ZIP, TAR, TAR.GZ, TGZ, TAR.BZ2, TAR.XZ, standalone
GZIP, BZIP2 and XZ containers open as read-only hierarchies. UEF members expose
their reconstructed load and execution addresses and whether the cassette
block sequence was complete.

Archive handling rejects parent traversal, non-regular TAR objects, archives
over 512 MiB, individual expanded members over 128 MiB and catalogues with
20,000 or more entries. Small members are classified while the archive is open;
larger members are classified only when explicitly opened. These limits bound
memory use and decompression work.

## Hex fallback

The fixed-range hex editor remains available from the pane and from every file
editor. It shows byte offsets, hexadecimal data, ASCII, typed values and staged
changes. Search accepts text or byte patterns. Writes cannot insert, remove or
resize bytes. They require explicit confirmation, reject overlapping or stale
changes, create a checkpoint and refresh decoded caches.

## Keyboard reference

| Key | Action |
| --- | --- |
| `Ctrl+S` | Save editable source |
| `Ctrl+Shift+S` | Save As inside the image |
| `Ctrl+F` | Find |
| `Ctrl+H` | Find and Replace |
| `Ctrl+Z` / `Ctrl+Y` | Undo / Redo |
| `Ctrl+A` | Select All |
| `Ctrl+W` | Close editor, with an unsaved-change warning |
| `F1` | Help for the command at the caret |
| `Escape` | Dismiss hover help, menus or the current nested view |

## Troubleshooting

### A file opens as binary

Check its Acorn filetype, load address and actual bytes. A generic filename is
not sufficient evidence. Files larger than the directory sniff limit are
classified when opened, not during every listing.

### BASIC opens read-only

The program is BASIC V, has a trailing binary payload, exceeds the safe editor
limit or failed exact BASIC II round-trip requirements. Export it and use a
tool that understands that exact dialect or compound format.

### Disassembly looks wrong

Confirm architecture, mapped origin, file offset and hardware profile. The
selected bytes may be data, text, compressed content or code that depends on
relocation or bank switching. Classify proven regions and retain useful labels,
but do not treat a plausible instruction stream as proof.

### A bookmark points at older bytes

Bookmarks use saved file offsets. Save a newly inserted or renumbered BASIC
line before bookmarking it. After a successful save the line map is rebuilt
from the new tokenised bytes.

### Save reports a stale file

Another operation changed the file after this editor opened. Export or copy
the editor text if needed, close it, reopen the current file and reapply the
change. The stale check is intentional data-loss protection.

### Emulator testing is unavailable

Confirm that `ACORN_FILE_EMULATOR_COMMAND` exists in the running container and
contains `{file}`. Archive members must be extracted into an image before they
can be handed to an emulator.
