# Acorn File Forge

Acorn File Forge is a browser-based workshop for Acorn disk, hard-drive and
tape images. It covers BBC Micro, BBC Master, Electron, Archimedes and
compatible RISC OS media.

Open up to three images together, browse their real filing systems and drag
files between them. You can add, export, rename, move, delete, lock, compact and
validate files without touching the original image on your computer. MMB and
ADFS menu tools, private session recovery, undo points, health checks and
format-aware imports are built in rather than left to separate utilities.

![Acorn File Forge in light mode](docs/images/acorn-file-forge-light.png)

Dark mode is included too.

![Acorn File Forge in dark mode](docs/images/acorn-file-forge-dark.png)

## Quick start

The source lives at
[github.com/peteclarke-del/AcornFileForge](https://github.com/peteclarke-del/AcornFileForge).
Clone it over SSH and start the Docker service:

```bash
git clone git@github.com:peteclarke-del/AcornFileForge.git
cd AcornFileForge
docker compose up --build -d
```

Open <http://localhost:8666>.

If your system still uses the standalone Compose command, replace
`docker compose` with `docker-compose` in the examples below.

The service listens on port `8666`. Its working images are stored in the
`bbcfm-work` Docker volume. Files selected in the browser are uploaded into
private working sessions; the application does not mount or alter the source
directory on the host.

To stop it:

```bash
docker compose down
```

To remove the saved working sessions as well:

```bash
docker compose down -v
```

Only use the second command when you really want to discard every working
copy.

The `samples/` directory is intentionally excluded from Git and from archives
made with `git archive`. Local test images can be large and may contain software
that is not ours to redistribute. Add your own fixtures there when developing;
they will not be committed or packaged.

## Current status

The current build supports the editing and transfer workflows described in
this guide, including one to three rearrangeable panes, undo and named
checkpoints, browser-private recovery, background job tracking, MMB and ADFS
menu maintenance, HFE handling, UEF extraction, an Online Library and
hardware-aware ADFS checks.
The application is useful today, but disk images can contain unusual loaders,
copy protection and filesystem variants. Keep a known-good source image and
test important downloads before putting them onto real hardware.

The completed development roadmap is recorded in [TODO.md](TODO.md). Bug
reports and proposed improvements can be raised in the
[GitHub repository](https://github.com/peteclarke-del/AcornFileForge).

## The basic workflow

1. The app starts with one full-width work pane. Open or create an image there.
2. Select **Add Pane** in the header when you need a source, destination or
   scratch area. Add a third in the same way; three is the maximum.
3. Double-click directories or MMB slots to browse them.
4. Drag files, directories, disk images, or MMB slots to their destination.
5. Use **History** to undo the latest operation or create a named checkpoint
   before a larger experiment.
6. Use **Tools → Check filesystem** after substantial edits.
7. Use **Save** to download the finished image.

Uploads are copied into an isolated workspace. Editing an image never writes
back to the original file selected in the browser.

## Online Library

![Online Library search and multi-selection](app/static/help/online-library.png)

Every writable media pane has an Online Library action. At the root of an MMB
it is labelled **Find Discs**; inside DFS, ADFS and RISC OS filesystems it is
labelled **Online Library**. It searches enabled catalogues on the server so a
browser does not need to negotiate cross-site download rules.

The initial machine filter comes from the Workbench hardware profile applied
to that pane. For panes without an applied profile, the remembered active
Workbench profile is used as the workspace default. A fresh browser starts with
Electron Plus 3. It is still only a starting value: choose another machine in
the Online Library whenever an individual search needs a wider or different
catalogue.

The built-in catalogue set is:

- Complete BBC Micro Games Archive for directly downloadable SSD and DSD
  releases, including recent homebrew represented by that archive;
- all public media categories in Acorn Electron World, including professional,
  public-domain, companion, EUG, featured, unfinished and unreleased software;
- Every Game Going for BBC Model B, B+, Master 128, Master Compact, Electron
  and Archimedes A3000 releases;
- 8-Bit Software's public-domain catalogue;
- 0xC0DE and community Electron projects with direct SSD releases;
- itch.io homebrew searches chosen from the active BBC, Master, Electron,
  Archimedes or RISC OS workbench filter;
- the official and third-party RISC OS Open package feeds.

Only records with a confirmed public UEF, SSD, DSD, ADF, HFE, ZIP or RISC OS
package download appear. The app suppresses gallery pages, documentation-only
records, DVD-only Electron World entries and catalogue records whose item page
does not contain supported downloadable media. itch.io results are checked at
their project page and shown only when a supported Acorn disk or tape upload is
actually present. Its short-lived download address is generated only when you
install the item.

Choose **Sources…** in the Online Library to enable or disable a catalogue,
change its URL, or add another compatible provider. Configuration is stored in
the persistent work volume as `catalog-sources.json`. Each provider record
contains its loading and parsing settings, including query templates, Electron
category roots, crawl paths, machine IDs, cache durations and validation
limits. Item and download path rules are configurable too.
Site-specific URLs and IDs therefore live in source configuration rather than
application logic.

The bundled defaults live in `app/catalog_sources.json`. The catalogue engine
only understands reusable loading stages such as a single page, category crawl
or machine index, reusable page layouts, embedded media query parameters, and
optional link or upload-button resolution. Machine-specific itch.io search
phrases also live in the source record.
It does not branch on a catalogue name or identifier. The copy in the work
volume contains local changes made through **Sources…**.

### Add online disks to an MMB

1. Open the MMB at **All disks** and optionally select several empty slots.
2. Choose **Find Discs**, select a machine and search by title, publisher or
   keyword. A blank search browses the catalogue's current page.
3. Select the Title, Publisher, Year or Source heading to sort the results.
   The active heading shows ↑ for ascending or ↓ for descending order; select
   it again to reverse the order.
4. Choose **Not already present** to hide likely duplicates detected from MMB
   disk titles and remembered distribution filenames, or **All results** to
   include them.
5. Select several downloadable results. Selected empty slots are preferred.
   Otherwise the app scans from the requested starting slot, wraps safely and
   finds the next suitable run. DSD images still need two adjacent slots.
6. Leave the menu option selected to pass each inserted disk through the usual
   launcher, action and PAGE review. Clear it to keep the disks off-menu.

Dragging or importing an SSD that is already open in another pane carries its
visible image title into the MMB slot. MMB-to-MMB copies retain the source slot
title. The title is shortened only to the MMB format's 12-character limit.

Multi-item installs run one download at a time and show the current title.
**Abort operation** lets the active item reach a safe image boundary, then
prevents the next download from starting. Completed items remain installed and
undo checkpoints are retained.

If one download contains the same program in several media formats, the app
uses the best native disk format once. For example, an SSD is preferred over a
duplicate UEF tape, so an MMB import does not insert the SSD and then complain
about the tape. Installing into a blank SSD adopts the source catalogue and
disk title, padding shortened SSD distributions to the target's normal size.

The catalogue title and publisher seed the review form, while the actual disk
is still inspected for `SSDMENU`, `!BOOT`, `LOADER`, action and PAGE. An
installed menu therefore receives proper source metadata without trusting a
catalogue to describe the executable layout of the image.

### Add online software to DFS, ADFS and RISC OS

For a blank SSD, the downloaded SSD catalogue and title are adopted directly.
For a non-empty SSD, DSD or open MMB disk, files are copied into the current
DFS catalogue. Normal seven-character leaf names, catalogue entry limits, side
selection, free-space checks and existing-file errors still apply.

For ADFS, downloaded disk images extract into the current directory by
default. Select **Create a folder for each downloaded disk** when the software
is self-contained or when several images would otherwise clash. The existing
DFS-to-ADFS loader checks and compatibility reporting apply to these imports
too.

RISC OS Open packages install only into ADFS or RISC OS images. The installer
preserves application directory structure and SparkFS load, execute and
filetype metadata, while omitting the package manager's `RiscPkg` control
directory. Older ADFS formats can still reject long RISC OS names, which is a
filesystem restriction rather than a download failure.

Small remote catalogue pages are cached for 15 minutes. The larger Electron
World and Every Game Going indexes default to 24 hours, which can be changed in
their provider settings. Selected result tokens expire after an hour. Downloads
have fixed size limits, ZIP expansion is bounded, and path traversal members
are ignored. One unavailable source is reported under the remaining results
rather than cancelling a multi-source search. Availability in a catalogue does
not change a program's licence, so use the source page for permissions, payment
and release notes.

Drag the numbered grip at the left of a pane heading onto another pane to swap
their positions. The image, current directory or MMB slot, selection, and scroll
position all move together. This grip only arranges the workspace; dragging a
file row, MMB slot, or supported image heading still transfers content. Pane
order is restored after a normal refresh.

**Add Pane** disables while three panes are displayed and becomes available
again as soon as one is closed. Each open pane heading contains, in order, the
orange changed indicator and buttons for **New Blank Image**, **Load New
Image**, **Save Image**, **Refresh View**, and **Close Pane**. Save is no longer
duplicated in the file toolbar. The × closes the whole pane, not merely the
image inside it. A changed image prompts for **Save and close**, **Close without
saving**, or **Cancel**. Closing never deletes its private working copy: use
**Recover previous session** in another pane to reopen it.
Empty panes also have a top-right ×. If every pane is closed, **Add Pane**
remains available in the header; a fresh browser workspace always begins with
one pane.

Click the image filename in any pane heading to rename the working image.
Press Enter or click elsewhere to keep the new name, or press Escape to cancel.
The media extension is preserved automatically, and a BeebSCSI DAT rename also
renames its matching DSC in the downloaded ZIP. This changes the container
filename used by recovery and download, not the title stored inside its
filesystem or an individual MMB slot title.

Each pane has its own refresh button. Long operations display a progress
overlay with the current phase and item count. Dialog action buttons disable
after the first valid click, which prevents accidental duplicate imports or
copies. The controls in a pane also disable as soon as a creative,
destructive, validation, or maintenance action starts. Changes to one image
are serialized so that two writes cannot modify it at the same time.

The meter at the lower-right of every populated pane shows real filesystem
usage. It fills green, then orange at 70%, and red at 90%. Hover over it for
used, free, total, and percentage figures in appropriate units. At an MMB root
it counts formatted and empty slots; inside an MMB disk it reports that DFS
slot's byte capacity. UEF tapes show a neutral unavailable meter because tapes
do not have fixed filesystem free space.

## Undo and named checkpoints

Every request that can change an existing image begins by taking an automatic
checkpoint. If the request makes no change, that speculative checkpoint is
removed. If it succeeds, partially completes, or stops after some items in a
bulk operation, the previous state remains available through **History → Undo
last change**. Undo consumes the latest automatic point, so it can be repeated
to step backwards through the most recent operations. The newest 20 automatic
points are retained per working image.

Use **History → Checkpoints** to create a permanent named point before a large
import, compaction, menu rebuild, or directory reorganisation. The same dialog
lists named checkpoints and recent automatic points. Any listed point can be
restored, and named points can be deleted when no longer required. Restoring a
checkpoint first saves the state it is replacing as a fresh automatic undo
point.

Checkpoints include the complete working image, its matching descriptor when
present, its displayed filename, source metadata, hardware target, warnings,
and dirty state. MMB slot caches and installed-menu caches are rebuilt after a
restore. Every pane showing the restored image refreshes from the restored
bytes.

On filesystems that support reflinks, snapshots use copy-on-write cloning. A
large HDD checkpoint is therefore normally quick and initially consumes space
only for blocks that later differ. The app falls back to a complete safe copy
when reflinks are unavailable, so the first checkpoint of a large image can
take longer on some Docker storage drivers.

Checkpoints live inside the private, browser-owned working session. They
survive normal refreshes and container restarts with the Docker work volume,
but clearing that recovery session or removing the volume removes its
checkpoints too. They are not a replacement for downloading an important
finished image.

## Workbench and analysis tools

Every open pane has an **Analyse** menu. These tools are read-only unless a
repair or reviewed edit is explicitly selected, and normal automatic
checkpoints still protect every write.

![Workbench hardware profiles](docs/images/workbench-analysis.png)

### Preflight and dry runs

Select files, directories, or MMB slots and choose **Dry-run selected items**.
The report shows the proposed objects and detects target filename conversion,
truncation, case-insensitive clashes, and operations that cannot proceed. The
existing MMB-to-ADFS planner provides the deeper format-specific preflight for
large transfers, including old ADFS directory capacity, group holders,
shortened-name collisions, existing populated destinations, blank disks, and
the exact per-slot destination.

### Unified image health

**Image health dashboard** brings the applicable checks together:

- filesystem structure and recursive catalogue access;
- MMB header state, invalid slots, installed menus and menu records;
- launch-file existence, disk-title mapping, action and PAGE evidence;
- BeebSCSI DAT/DSC geometry where present;
- compatibility warnings and the applied hardware profile.

Before the scan begins, the app warns that a large MMB or HDD may take several
minutes. The progress display names the current filesystem or menu phase, and
**Abort operation** stops at the next safe traversal boundary. Health checks do
not hash every file; full checksums remain available through manifests and the
duplicate finder, keeping routine structural checks substantially faster.

Repairs are offered only when the evidence is deterministic. For example, a
menu PAGE value can be replaced when the selected tokenised BASIC launcher has
a different saved address. Missing launchers and ambiguous dependencies remain
for review. The repair dialog itemises what is eligible and creates an undo
checkpoint before writing.

### File and dependency inspection

Select a file and choose **Inspect selected file** to see:

- a text view for readable command and data files;
- a decoded BBC BASIC listing for tokenised programs;
- a conventional offset, hexadecimal and ASCII view;
- the SHA-256 digest and detected `CHAIN`, `EXEC`, `RUN`, `LOAD`, `DIR`, and
  `LIB` commands.

Small plain-text files can be edited safely from the inspector. Their existing
load and execution metadata is retained. Tokenised BASIC is deliberately
read-only in the free-form editor because converting an arbitrary listing back
to BBC BASIC requires dialect-aware line-reference tokenisation. Existing
compatibility repairs still make proven, length-safe changes to tokenised BASIC
loaders.

**Check loader dependencies** resolves conventional targets beside the
launcher and reports missing or root-relative paths. Complete disk extraction
already copies every catalogue file, so local companion programs travel with
the launcher. The report explains when installing below ADFS root is unsafe or
needs the existing guarded root-reference rewrite.

### Menu test runner

For an MMB with an editable Universal or SPI menu, or an ADFS volume with an
installed directory menu, **Test menu entries** checks every record without
pretending to emulate the game itself. It verifies disk or directory
selection, launcher existence, action, and whether the stored PAGE agrees with
the actual BASIC launch path. Results are shown per title so a broken record
can be corrected in the appropriate menu editor.

The command remains disabled until a suitable menu is detected. For MMB this
means a recognised menu in any slot, even while browsing another slot. For
ADFS it means the current directory itself contains the installed menu files;
navigating away disables the command and returning to that menu root enables
it again.

### Manifests, duplicates, and variants

**Export collection manifest** produces JSON or CSV. MMB JSON contains all
slots including empty ones, disk access, source names, per-disk and per-file
SHA-256 values, Acorn load/execute metadata, and recognised menu records. DFS,
ADFS, tape, and hard-drive manifests recursively catalogue their visible
objects and metadata.

An edited MMB JSON manifest can be reapplied with **Apply reviewed JSON**. Only
menu records are writable through this path. The current database must still
match the exported baseline, preventing an old manifest from replacing newer
menu work.

**Find duplicates / variants** uses full SHA-256 hashes for byte-identical
content and a conservative normalised-title comparison for likely release or
side variants. It reports candidates rather than deleting anything.

### Hardware profiles and import recipes

The header **Workbench** includes reusable hardware profiles for Electron Plus
3, BBC Micro with paged MMFS, BBC/Master BeebSCSI, Master ADFS, and
Archimedes/RISC OS. A profile records the machine, Online Library filter,
filing system, MMFS build, Tube state, expected PAGE, menu preference, and ADFS
validation target. Custom profiles are stored in the browser and the applied
profile is also persisted with the private image session. The health dashboard
highlights conflicts such as using the Tube with Electron or low-PAGE MMFS
software. The active Workbench profile is remembered and supplies the workspace
default used by Find Discs and Online Library on panes without their own
profile. On first use this is Electron Plus 3, and selecting, saving, or applying
a different profile changes that default.

Online Library search results carry short-lived server-side download tokens.
They are retained for one hour in the private application work area, so a safe
container restart does not invalidate a search dialog that is already open.
applied profile.

Import recipes record the directory naming strategy, group prefix, online
metadata preference, guarded compatibility rewrites, and whether copied titles
should be offered to a menu. They appear in the bulk MMB-to-ADFS planner and
can be adjusted for exceptional disks without changing the saved recipe.

### Portable projects

Workbench can export an `.aff-project.json` description containing one to
three pane positions, image names and private session references, current MMB
slots or ADFS paths, hardware profiles, import recipes, and theme. Importing it
on the same retained installation restores the workspace. The project is kept
small by referring to private working sessions; image bytes remain in the
Docker volume and in the normal timestamped image ZIP backups.

### Persistent jobs

Long transfer records are written to `operations.json` in the work volume.
The header **Jobs** panel shows the phase, item count, completion state, time,
completed and skipped disks, and errors even after the foreground dialog
closes. A restart changes unfinished records to **interrupted** instead of
losing them. Resumable MMB-to-ADFS jobs retain their safe request plan and omit
already completed or skipped source slots when **Resume** is selected. Abort
still stops only at a safe filesystem boundary.

## Supported media

| Media | Common names | What Acorn File Forge can do |
|---|---|---|
| Acorn DFS | SSD, DSD | Browse, add, export, rename, delete, lock, compact, validate, and copy files |
| MMB | MMB | Browse all slots, create or insert disks, set read-only/read-write access, edit embedded DFS disks, drag to move or swap, and maintain Universal or SPI game menus |
| ADFS floppy | ADS, ADM, ADL, ADF, DSK | Traverse directories and perform normal file and directory operations when the FileCore layout is supported |
| Acorn hard drive | DAT with matching DSC, HDF, HDD | Browse and edit hierarchical ADFS volumes, including virtual hard-drive images |
| Raw drive dump | IMG, RAW, BIN, extensionless images | Identify the filesystem from its contents, then open it as DFS or ADFS |
| Acorn cassette | UEF and compressed UEF | Reconstruct ordinary tape files, export them, drag them to disks, or convert them to SSD or DSD |
| HxC floppy container | HFE v1, v2 and v3 | Decode DFS or ADFS sectors for browsing and extraction; safely edit ordinary HFE v1 disks and save them back with their original track layout |

The file extension is only a hint. Generic names such as `HardDisc4`,
`drive.img`, or `backup.bin` are inspected by content. A DFS image renamed to
`.bin`, for example, is still opened as DFS.

### Images you can create

The **Create new disk image** dialog offers:

- DFS SSD, 200 KiB
- DFS DSD, 400 KiB
- ADFS S floppy, 160 KiB
- ADFS M floppy, 320 KiB
- ADFS L floppy, 640 KiB
- HFE-wrapped DFS SSD/DSD and ADFS S/M/L floppies
- BeebSCSI ADFS hard drive as a matched DAT and DSC pair
- Archimedes or RISC OS virtual hard drive in HDF form
- Raw physical-drive image
- MMB bank with 511 empty slots

Hard-drive capacity is entered as a size such as `4MB`, `20MB`, or `512MB`.
The size field follows the selected format. Fixed-size DFS, ADFS floppy, HFE,
and MMB choices show their actual capacity in a read-only field. BeebSCSI,
HDF, and RAW hard-drive choices keep the field editable and preserve the last
typed HDD capacity while switching between formats.

The target-hardware control follows the format too. It is disabled as not
applicable for DFS and MMB, fixed to BeebSCSI for a DAT/DSC pair, and fixed to
Archimedes / RISC OS for HDF and RAW hard drives. It remains selectable for a
normal ADFS S, M or L floppy because the same floppy geometry can be used by
more than one Acorn system. An MMB has no bank-wide filesystem title, so its
title field is disabled. Each disk inserted into the bank keeps its own title.

When adding a recognised SSD, DSD, HFE, ADFS, MMB or UEF image to an open ADFS
hard drive, Acorn File Forge uploads it once and shows a bounded catalogue
preview before anything is written. Extraction defaults to the directory
currently shown in the pane. Optionally open the directory picker to choose a
different existing destination, and optionally create a named child directory
inside that destination. The original image can instead be retained as an
ordinary file. Direct extraction never overwrites an existing name. It creates
an efficient rollback copy of the working image first, so a failed or aborted
copy restores the destination instead of leaving a partial import behind.

The filesystem engine checks whether the requested geometry is valid. A newly
created BeebSCSI image remains linked to its DSC while it is edited and
downloads as a hardware-ready ZIP containing `BeebSCSI0/scsi0.dat` and
`BeebSCSI0/scsi0.dsc`. Extract the ZIP into the root of the BeebSCSI SD card
and keep the `BeebSCSI0` directory. The firmware does not scan the card root
for DAT/DSC files. Newly created pairs are also checked against the firmware's
256-byte sector, 33-sector track, 16-head and ADFS 21-bit size limits. Their
old-format ADFS root directory is written with the CR-terminated name and title
fields expected by the original BBC ADFS ROM, rather than relying on the more
permissive parsing used by modern desktop tools.

## Drag and drop

Drag and drop is format-aware. The application will only offer an operation
that makes sense for the target filing system.

### Files and directories

- Drag a file between any two writable filesystems.
- Drag an ADFS directory to another ADFS image to copy its complete tree.
- Within one ADFS image, drag files or complete directories onto another
  directory to move them. Open the same image in multiple panes when it is useful
  to keep the source and destination visible at once.
- Select several ADFS rows before dragging to move the whole selection in one
  operation. A populated destination is never overwritten silently.
- Drag a UEF file to DFS or ADFS to copy the reconstructed tape payload.
- If the destination cannot accept the source name, a dialog asks for a legal
  replacement.
- Load and execute addresses, RISC OS filetypes, dates, and access flags are
  preserved where the destination format supports them.

### Complete images

- Drag an open SSD, DSD, HFE, ADFS floppy, HDF, raw drive image, or MMB header
  onto an ADFS pane. Acorn File Forge previews the source and defaults to
  copying into the current directory. A picker can select another existing
  directory, with an optional new child directory inside it.
- Drop a supported image file from the host onto an open ADFS pane. You can
  preview and extract its contents using the same destination controls, or
  store it as an ordinary file.
- ZIP distributions are accepted when opening an image, extracting an image
  into ADFS, or inserting disks into MMB. A ZIP dropped into MMB can contain
  several SSD/DSD/HFE members and they are allocated in archive order. Opening or
  extracting a ZIP requires one supported image; a matching DAT/DSC pair
  counts as one image. Unrelated text and artwork files are ignored.
- Drop an SSD, DSD, HFE, or ZIP containing them onto an empty MMB slot to
  insert it. The HFE must contain a DFS disk.
- Select an empty MMB slot and use **Slot → Add disk** to insert host or open
  media, or create a formatted blank SSD/DSD directly. This is useful for save
  disks and user-writable data.
- Drag an open DFS disk onto an empty MMB slot in another pane.
- Drag one MMB slot onto another slot to move or swap it.
- Drag an MMB slot onto ADFS to create a named directory containing the slot's
  DFS catalogue.
- DFS directory letters become ADFS subdirectories. Extraction starts at the
  DFS virtual root rather than only catalogue directory `$`, so compilation
  disks with launchers in `A`, `B`, `C`, `D`, and other directory letters keep
  every file. Existing MMB menu records can then resolve those complete paths
  without unnecessary launch prompts.
- Multiple selected MMB slots can be copied together. Old-format ADFS
  directories hold at most 47 entries, so larger batches are automatically
  divided among editable group directories such as `DISCS1` and `DISCS2`.
  Interrupted batches remember completed slots while their dialog remains
  open, allowing **Copy** to continue with only the remaining disks.
- The bulk preflight is a wide, fixed-height planner. Naming strategy,
  editable parent groups, and the ADFS menu choice remain visible beside a
  dense scrollable table of slot-to-directory mappings. On a normal desktop
  only the table scrolls, so the summary and Copy button stay visible.
- When a formatted MMB slot has an empty DFS catalogue during a bulk ADFS
  copy, the foreground dialog shows its slot number and title. Choose
  **Skip this disk and continue** or **Abort bulk copy**. Completed directories
  are retained, skipped disks are listed in the completion warning, and no
  empty ADFS directory is created. Blank SSD and DSD images can still be
  inserted into MMB.
- If a destination directory already exists during a resumed batch, choose to
  keep it and continue, replace and recopy it, or abort. An empty existing
  directory is reused automatically without prompting. Replacing a populated
  directory is always an explicit choice because it recursively removes the
  existing directory first.
- Before a bulk copy starts, all shortened ADFS directory names are checked
  together and case-insensitively. If shortening would create a collision, use
  the default generic `DISC-0000`, `DISC-0001` naming scheme or review the
  highlighted names manually. Parent group directory names are always editable;
  `DISCS1`, `DISCS2`, and similar names are suggestions rather than fixed names.

### Bulk MMB-to-ADFS naming and recovery

The complete destination plan is checked before the first disk is copied.
Names are compared case-insensitively within the parent directory where they
will be created. This matters because two distinct long MMB titles can become
the same ten-character ADFS name after shortening.

When that would happen, the dialog offers two choices:

1. **Use generic unique names**, which is selected by default and proposes
   `DISC-0000`, `DISC-0001`, and so on.
2. **Review shortened names**, which restores the proposed short names,
   highlights collisions, and requires every name to be legal and unique
   before copying can begin.

The generic leaf name affects only the ADFS directory. The original MMB slot
number and title remain available to metadata detection and menu generation.
If grouping is required by the 47-entry old-ADFS limit, every suggested parent
group name is editable before the operation starts.

Generic names prevent collisions between the outer disk directories. DFS also
allows a literal dot inside a seven-character filename, while ADFS uses the dot
as its directory separator. During extraction, a DFS name such as `eS.Rob`
therefore becomes the equivalent ADFS path `eS.Rob` inside the disk directory.
This preserves the complete catalogue name and keeps `eS.Rob`, `eT.Rob`, and
other same-leaf files distinct instead of silently overwriting one another.

![Bulk copy shortened-name preflight](docs/images/copy-name-preflight.png)

Destination checks are deliberately conservative:

- A directory that exists but contains no children is reused automatically.
- A populated directory pauses the batch and offers **Keep existing and
  continue**, **Replace and continue**, or **Abort bulk copy**.
- Keep leaves all existing content untouched and skips that source disk.
- Replace recursively removes the populated directory, recopies the current
  disk, and then continues.
- Abort keeps completed directories and starts no further disks.
- A same-named ordinary file is never considered an empty directory and is
  never overwritten silently.
- Distinct dotted DFS filenames are expanded into their corresponding ADFS
  subpaths before any file is written, so an internal name collision cannot
  stop a generic-directory batch part way through.

![Populated destination recovery choices](docs/images/destination-conflict.png)

DSD insertion needs two adjacent empty MMB slots. The two sides become two
200 KiB SSD slots, which is how MMB stores that content.

When another pane has an SSD, DSD, DFS-formatted HFE, or an individual MMB
disk open, select one empty destination slot and use **Slot → Import from open
&lt;filename&gt;**. One command is shown for each other open image. Incompatible
ADFS images and MMB panes that are still at **All disks** remain visible but
disabled, with the reason shown beside them. This keeps the operation within
MMB's DFS-only format restrictions. A DSD imported this way still needs two
adjacent empty slots.

Use **Slot → Mark read-only** or **Mark read / write** to set protection on
one disk or every formatted disk in a multiple selection. Empty slots have no
access state until a disk is inserted.

Dropping a whole image onto DFS as an extracted tree is not offered because
DFS has no hierarchical directory model and has much tighter catalogue and
space limits. Individual files can still be dragged across.

## Working with SSD and DSD

DFS rules are enforced before a write is attempted:

- Leaf names contain at most seven characters.
- DFS directory prefixes contain one character.
- A standard catalogue holds at most 31 files per side.
- A file must fit in the available contiguous sector layout.

DSD images expose side 0 and side 2 separately, matching BBC drive numbering.
Compaction can optionally prioritize boot files or another requested order.

## HFE floppy images

HFE is a track and bit-cell container rather than a filing system. Acorn File
Forge uses the official HxC conversion engine to expose the DFS or ADFS sectors
inside an HFE, then presents them through the normal file browser.

![Creating an HFE floppy image](docs/images/hfe-create.png)

- Ordinary HFE v1 images with clean sector data are editable. Saving encodes
  the changed sectors against the original HFE as a reference, decodes the new
  file again, and byte-compares every sector before offering the download.
- HFE v2/v3 images, images with reported bad sectors, weak bits, variable
  timing, protection data, or other advanced track features open in a
  read-only safe view. Files may still be inspected, exported, or dragged to
  another image.
- DFS-formatted HFE images can be inserted into MMB slots. An HFE can also be
  extracted to an ADFS directory just like its underlying SSD, DSD, or ADFS
  disk.
- New HFE images can wrap DFS SSD/DSD and ADFS S/M/L floppy formats.
- Inserting an advanced read-only HFE into MMB intentionally copies only its
  readable DFS sectors. MMB has no place to store HFE timing, weak-bit, or
  protection information, so the destination receives a visible warning.

The pane badge reads `HFE`, while navigation and file rules follow the decoded
DFS or ADFS filesystem. A read-only HFE is labelled `Read-only safe view` and
does not offer editing, compaction, or menu-writing controls.

The original HFE remains untouched in the session until a verified replacement
has been produced. This matters because an apparently normal catalogue can
coexist with non-sector protection data that a filesystem editor cannot
represent.

## Working with MMB

An MMB opens at its slot index, not directly inside slot zero.

- Every slot is shown, including unformatted slots.
- Double-click a formatted slot to browse its embedded DFS disk.
- Use **All disks** to return to the MMB index. The slot you came from remains
  selected.
- Rename, clear, protect, unprotect, move, or swap formatted slots.
- Import several SSD, DSD, and DFS-formatted HFE images in one operation. The
  importer walks forward looking for the next suitable empty slot or empty
  pair.
- Create blank SSD or DSD images and insert them as needed.

Slot edits are first made in an isolated SSD working file, then synchronized
back to the correct 200 KiB region in the MMB.

## MMB menu choices

Any new or existing MMB can install a menu through
**Menu → Create / manage menu**.
Choose the menu type and its reserved empty slot:

- **Games Universal Menu** provides editable title, publisher, launch file,
  action and PAGE records. Its databases can be updated, regenerated and
  previewed by Acorn File Forge.
- **SPI Game Menu** installs the Ray Harper Electron MMFS menu. It stores
  title, publisher and MMB disk title, then selects that disk and executes its
  `!BOOT`. It supports several titles on one compilation disk. The original
  BASIC program describes itself on screen as the `ELECTRON SDI GAME MENU`;
  Acorn File Forge keeps the familiar SPI name in its menu selector.
- **Electron User / Magazine Menu** and **Acorn User Menu** provide their
  original catalogue browsers and databases.
- When another pane contains an MMB with recognised menus, choose the exact
  menu and source slot to copy. Images containing both Universal Menu 4R and
  MMC Desktop 3 expose both choices. A copied MMC Desktop `DISCCAT` catalogue
  is rebuilt for the new MMB rather than retaining stale entries.

Menu titles supplied wholly in capitals are converted to readable title case,
while recognised acronyms, Roman numerals, numeric forms such as `3D`, and
deliberately mixed-case titles are retained. Generated title and publisher text
is fitted to the installed menu's 40-column display, including its `A-`
selection label, so an entry cannot wrap onto the next hardware line. Long
values are shortened at a word boundary where possible.

When inserting a DFS image into MMB, tokenised BASIC loaders are checked for
single-character `#` wildcard references. If exactly one file in the relevant
DFS directory matches, the reference is replaced with its exact catalogue
name. This avoids MMFS variants failing to resolve a loader such as
`CHAIN "BUG#1"` when the disk actually contains `BUG?1`. Ambiguous references
are left untouched rather than guessed.

A new MMB remains menu-free until a menu is explicitly installed. Local sample
images are development and compatibility fixtures, are excluded from Git and
are not presented as built-in user disks. Installing or copying a menu maps MMFS drive 0 to its
reserved slot in the MMB power-on header, so a menu placed somewhere other
than slot 0 still becomes the initial drive-0 disk.

## Universal and SPI Game Menu support

The menu workflow can:

- Install a menu in a chosen empty slot.
- Set the Universal Menu boot PAGE to the current BASIC value, `&E00` for a
  verified paged or sideways-RAM MMFS setup, or `&800` for a verified
  DataCentre/low-PAGE environment. The generated `!BOOT` applies that PAGE
  before chaining `UNIMENU`; arbitrary values are rejected.
- Scan a disk title, catalogue, `!BOOT`, launch command, and PAGE value.
- Derive the default PAGE from the selected launcher in the actual disk image.
  For CHAIN this is the tokenised BASIC program's saved load address; for an
  EXEC loader the boot commands are followed to the BASIC program where
  possible. Old programs with complete BASIC line records but no conventional
  terminator are recognised too. Machine-code launches are marked as not using
  BASIC PAGE. If you replace an image-derived value, Acorn File Forge requires
  an explicit Yes/Cancel confirmation and explains the risk before writing the
  menu.
- Let you review or correct title, publisher, launch file, action, and disk
  title.
- Bulk edit the installed database in a compact CSV-style table. Name,
  publisher, MMB disk, launch file, action and PAGE can all be corrected across
  many rows before one atomic save. Search the table, sort it by name, drag rows
  into manual order, add or remove rows, and clone compilation titles. Launch
  fields expose files from the selected slot catalogue on demand, avoiding a
  slow scan of every disk just to open the editor. SPI rows correctly omit the
  inapplicable launch, action and PAGE fields. Changed records must name one
  unique formatted disk and a file that exists in its DFS catalogue before the
  four database files are replaced together.
- Keep individual disks off-menu.
- Add entries that were skipped earlier.
- Recover inserted disks that have no saved record with **Add missing disks**
  directly from the preview. Creating a game menu in an already populated MMB
  starts the same scan automatically.
- Regenerate every menu entry.
- Rebuild title and publisher indexes.
- Run **Menu → Audit launch PAGE values** against any installed Universal
  Menu. The audit follows every CHAIN or EXEC launcher in its actual MMB slot,
  repairs only provable PAGE differences, converts legacy full-address fields
  to the database's required high-byte encoding, and validates the menu disk.
  RUN, LOAD and machine-code launches are counted separately because BASIC
  PAGE is not part of their hand-off. Anything ambiguous is reported by slot,
  title and reason for manual review instead of being guessed.
- Copy the complete active MMB menu disk with **Menu → Backup menu slot**.
  Choose any empty slot; the copy is labelled `MBACKUP-xxx`, marked read-only,
  excluded from installed-menu detection and omitted from automatic menu
  scans. **Restore menu backup** copies it back over the active menu slot,
  retains the backup, keeps the drive-0 mapping and rolls back if validation
  fails.
- Interpret the installed tokenised BBC BASIC menu program, including its
  screen mode, logical palette, text window, embedded heading/help strings,
  database selection and page size. The preview then renders the real
  `GAMDATA` order using those values and lets you inspect each launch command.
  Programs outside the supported Universal Menu family are labelled as a
  database-only preview instead of being dressed up as an invented hardware
  screen.

SPI Game Menu records deliberately do not contain a launch filename, action or
PAGE. Acorn File Forge therefore asks only for title, publisher and the unique
12-character MMB disk title. It writes three-field `GAMDATA` and `PUBDATA`
records, rebuilds their BBC BASIC binary indexes in 26-entry pages, and shows
the effective disk selection and `!BOOT` hand-off in Preview. The installed
program loads its small `DOEXEC` helper, performs `*DIN 0 <disk-title>`, then
runs the helper to execute the newly selected disk's `!BOOT`.
Adding a second title for the same disk creates another record without
duplicating the disk image.

On an Electron, `PAGE=&E00` is valid only with an MMFS build whose workspace
really lives in sideways RAM, such as the appropriate ESWMMFS or relocating
ZEMMFS build. Do not force ordinary ROM-based EMMFS down from its natural
`PAGE=&1900`; BASIC will overwrite filing-system workspace and typically fail
with corrupted tokens or repeated `GOSUB` text. Tube-hosted execution can also
break software that expects the native Electron memory map. Disable the Tube
for those titles.

Treat the image-derived PAGE as the safe default. Changing it can place BASIC
over MMFS, ADFS, loader or Tube workspace and lead to corrupted tokens, hangs,
random crashes or errors that appear unrelated to the menu. Override it only
for a hardware or filing-system configuration you have verified.

The Universal Menu database stores only PAGE's high byte because its original
BBC BASIC reader reconstructs the address with `EVAL("&"+field+"00")`.
Acorn File Forge therefore displays and edits the clearer complete address
(`&E00`, `&1900`, `&1D00`) but writes `E`, `19` or `1D` to `GAMDATA` and
`PUBDATA`. Older app builds could write the full address into that compact
field, causing the reader to construct values such as `&190000`; rewriting or
regenerating the menu now repairs those records.

The maintained Universal Menu program prints one blank line before entry A.
This centres a normal 26-entry page vertically without adding a blank line to
search-result rendering. Installing, updating or auditing a Universal Menu
applies this program upgrade to both MMB and ADFS copies.

This rule is shared by every Universal Menu writer. It applies equally to an
MMB menu disk and to a menu installed in an ADFS floppy, HDD, HDF, RAW or
BeebSCSI DAT/DSC directory. ADFS menus expose the same **Audit launch PAGE
values** action at the directory containing the menu. It follows that menu's
ADFS paths and launch files, repairs provable values and legacy encodings, then
validates the complete image. Run it separately at each menu root when one HDD
contains several installed menus.

Metadata discovery uses the strongest local evidence first. Existing MMB menu
records are reused before reading a disk again. The importer then considers
TOSEC, Ghostware and similar archive/member filenames, examines the catalogue,
load addresses, `!BOOT` command files and conventional loaders, and maps the
chosen launcher to its copied ADFS name. Only unresolved or ambiguous records
go online. Those searches check the Complete BBC Micro Games Archive first,
then the Internet Archive and itch.io for newer homebrew releases. Multiple
matches are shown for confirmation and do not silently replace reliable local
details.

Metadata lookup is field-aware and stays local for as long as possible:

1. An existing Universal or SPI Game Menu record for an MMB slot is authoritative.
2. The original distribution or ZIP-member filename is parsed for a TOSEC-like
   title, release date, and publisher. This provenance is retained per MMB
   slot and per extracted ADFS directory, including after a container restart.
3. The filesystem is inspected locally. DFS uses its disk title, catalogue,
   load/execute addresses, readable `!BOOT`, and conventional launchers. ADFS
   uses its directory title, files, child directories, `!BOOT`, and launchers.
4. If title or launch metadata remains ambiguous, the Complete BBC Micro Games
   Archive is checked first, followed by the Internet Archive and itch.io for
   archive releases and newer homebrew software.

For a standalone SSD/DSD the host filename and DFS catalogue are therefore the
first useful sources. For MMB, an existing menu record comes first, followed by
the retained source filename and embedded DFS disk. For ADFS, an existing menu
already contains the saved values; newly imported directories use the retained
distribution filename and local directory analysis before an online lookup.

An existing MMB menu record is carried across as a complete record, including
display title, publisher, launch filename, CHAIN/RUN/EXEC/LOAD action, PAGE,
and disk title. Those fields are not replaced by an online match. The copied
directory is still inspected to locate that launch file at its new ADFS path;
if it cannot be found, the original menu values remain visible for manual
review rather than being silently discarded.

Universal Menu stores its global filing-system marker in the first database
record. Acorn File Forge upgrades the installed menu reader and stores the
first record as a combined value such as `ME` for MMB plus EXEC. This preserves
the selected action even when an EXEC `!BOOT` title sorts first. Legacy first
records that name `!BOOT` are recovered as EXEC when the menu is next updated;
they are never presented or rewritten as `CHAIN "!BOOT"`.

Some compilation disks have several Universal Menu records with the same MMB
disk title. Acorn File Forge collects every matching record, resolves each
launcher inside the one copied ADFS directory, and offers every game as a
separate ADFS menu entry. PAGE is represented as the complete hexadecimal
address, so abbreviated values such as `E` and `19` are normalised to `E00`
and `1900`.

Numbered continuation disks are treated differently. For example, the sample
`TY-SUPERMAN0` disk owns the Universal Menu record and launches `LOADER`, while
`TY-SUPERMAN2` contains later `GAME5`, `GAME6`, and `GAME7` data. The
continuation disk is identified from the existing MMB menu and kept off the
ADFS menu instead of presenting its data chunks as possible launch programs.
The copy is still retained on ADFS. Software that changes physical disks may
need a title-specific conversion before it can run from extracted directories.

Menu metadata is retained after every completed section of a bulk transfer.
If an empty disk, destination conflict, cancellation, or later copy error
pauses the batch, the records collected for disks already copied are carried
into the resumed operation. The final menu therefore represents the whole
successful batch, not only the last uninterrupted section.

Parsed MMB menu records are cached for later copies and refreshed whenever the
application rewrites the menu. SPI records are normalised internally as an
`!BOOT` EXEC launch when software is copied onward to ADFS.

The interpreted preview is deliberately narrower than a complete Electron or
BBC emulator. It executes the installed menu's declarative display path. That
includes the Universal Menu `TXT2SCN` renderer and the SPI menu's tokenised
`GAMECOL` Mode 1 program, palette, heading, function-key legend and three-field
database renderer. It does not run selected software or pretend to reproduce
unsupported machine-code menus. The preview shows the menu program name and
SHA-256 prefix so the screen can be tied to the exact program installed in the
image.

ADFS volumes can have a similar menu. Pick a root directory and each software
directory beneath it is treated like the contents of one disk. Structural
group directories created to satisfy the old ADFS 47-entry limit, such as
`GAMES1` through `GAMES5`, are detected and kept off-menu. Their contained
`DISC-####` directories become the entries instead. Internal DFS-derived paths
such as `eE` and `eT` are not mistaken for group holders.

The launch file is selected from a dropdown populated from the extracted
files. The complete directory containing that file is stored in `GAMDATA`.
Automatic detection gives `SSDMENU` first priority and always launches it with
`CHAIN`, even when the disk also contains `!BOOT`. Without `SSDMENU`, it checks
a readable `!BOOT`, then familiar loader names including `DISKMENU`, `MENU`,
`LOADER`, `START`, and similar menu-like names. The candidate itself is inspected: readable command files use
`*EXEC`, BBC BASIC programs loaded at `&1900` use `CHAIN`, and other
conventional executable loaders use `RUN`. When several plausible launchers
remain, the choice is left for review in the populated dropdown.
The supplied Universal Menu handles an ADFS record by issuing `*DIR` with that
full path before it runs, chains, loads, or executes the selected file, so
grouped and nested software directories launch in their proper context.
Choosing **Keep off-menu** does not require a launch file.

The generated ADFS `!BOOT` first selects the menu root itself, for example
`DIR $.Games`, and then chains `UNIMENU`. The menu program deliberately opens
`GAMDATA`, `GAMINDX`, `PUBDATA`, and `PUBINDX` relative to that current
directory. This works whether `!BOOT` is executed after manually entering the
directory or by its full ADFS path, and avoids accidentally looking for the
databases in the volume root.

Future bulk MMB extractions also store the original slot title as the ADFS
directory title. This retains useful menu metadata even when generic
`DISC-####` path names are selected.

An installed ADFS directory menu can be reordered from its preview. Choose
name ascending or descending, or drag entries into a manual order, then use
**Save order** to rebuild `GAMDATA` and its index. The publisher database stays
alphabetised, and later additions are appended without discarding a saved
manual order.

ADFS file rows keep the everyday actions close to the object. Use the pencil
icon to rename a file or directory in place and the × icon to delete it after
confirmation. Moving is handled by drag and drop, so it does not need a
separate toolbar command. If a renamed, moved or deleted directory or launcher
is referenced by an installed menu, Acorn File Forge rewrites the affected
menu path or removes the obsolete entry and rebuilds its indexes.

Online matches are always shown for review before anything is written.
Temporary internet failure does not prevent manual metadata entry.
Generic path labels such as `DISC-0184` do not provide a meaningful search
term, so the scanner skips that otherwise slow lookup and asks for local
review. Named ambiguous titles are still checked online.
After adding or regenerating entries, the installed menu preview opens at the
newest entry so the result can be checked immediately.

## Archimedes and RISC OS images

Acorn File Forge uses the FileCore and ADFS structure, so directories are
fully traversable. Normal operations work at any level of the hierarchy.
RISC OS filetype, load address, execute address, datestamp, and access metadata
are displayed when present.

The target-hardware choice controls compatibility checks rather than changing
the file extension:

- **Auto / inspect only** identifies and browses the filesystem without adding
  machine-specific repairs.
- **Electron Plus 3** and **BBC / Master** apply the normal 8-bit old-ADFS
  directory checks.
- **BeebSCSI** is a separate Electron/BBC/Master target and requires a matched
  DAT and DSC pair.
- **Archimedes / RISC OS** selects the 32-bit target without applying old-ADFS
  hardware repairs.

To reorganise one ADFS image, drag a row onto a directory row. Multiple
selected rows move together. You can also show the same image in multiple
panes, navigate them to different directories, and drag between them. Every
pane showing that image refreshes after the move, including any pane whose
current path moved with its parent directory.

The application accepts virtual hard-drive images and byte-for-byte dumps of
physical drives. "Physical drive" means an image captured from the device. A
web browser does not receive direct access to host paths such as `/dev/sdb`,
and the Docker container is not granted raw-device access.

This separation is intentional. It prevents a typo in a web request from
writing directly to a real disk. If a finished raw image must be restored to
hardware, do that outside Acorn File Forge with a trusted imaging tool and
verify the target device carefully.

### FileCore compatibility note

The installed Oaknut engine safely edits:

- ADFS S, M, and L floppy layouts
- Old-map D and old-map hard-drive layouts that it can identify
- BeebSCSI DAT images, with a matching DSC carried alongside the DAT

The DSC is mandatory when editing a BeebSCSI DAT. It contains the physical
drive geometry that is not safely recoverable from the DAT alone. If only one
half of the pair is selected, Acorn File Forge retains and prefills it in a
paired upload dialog, leaving only the missing companion to choose.
Descriptor-less DAT sessions remain browseable but all writes are blocked.
Reopen the original DAT and DSC together to edit it.

The DAT length follows the old-format ADFS map, while the DSC describes the
slightly larger device geometry presented by BeebSCSI. This distinction matters
on physical hardware. The official Quickstart pair has an ADFS extent of
536,719,360 bytes and a DSC geometry of 536,752,128 bytes. Acorn File Forge keeps
that layout. If an older version of the app added an all-zero geometry tail, the
tail is removed automatically without moving or rewriting filesystem content.
Data beyond the map is never removed when any byte in that area is non-zero.
Likewise, a DAT shorter than its ADFS extent is not padded because real
filesystem data may be missing.

New-map E, F, F+, and later large FileCore variants are not currently edited.
They are rejected instead of being guessed at. Standard Archimedes floppy
images are often E or F format, so an `.adf` filename alone does not guarantee
that the image can be opened by this build.

This is the main compatibility gap to be aware of. The user interface and
transfer model are ready for those layouts, but the underlying writer must
support them before edits can be made safely.

### HDF and RAW creation detail

Oaknut currently chooses hard-drive geometry correctly for its native DAT
creation path, but it does not infer that same geometry from a new `.hdf` or
`.raw` filename. Acorn File Forge works around that quirk by creating the
filesystem through a temporary DAT path, then giving the completed working
image its requested HDF or RAW name. The bytes are the same raw FileCore disk
image; no container header is added.

## UEF tapes

UEF support reconstructs standard Acorn cassette filing-system blocks.

- Compressed and uncompressed UEF files are accepted.
- File names, load addresses, execute addresses, and block completeness are
  shown.
- Reconstructed files can be exported or dragged to another image.
- A complete tape can be converted to SSD or DSD. Conversion analyses each
  tokenised BASIC program, replaces cassette-order calls such as an empty
  `*/` or `CHAIN ""` with the final DFS filename, and updates references when
  a long name is shortened.
- Control-only or empty cassette catalogue names receive stable inferred names
  instead of appearing as `_` or `_1`.
- Converted disks receive DFS boot option 3 and receive `!BOOT` only when the
  proposed loader is safe to start independently. Tokenised BASIC is also
  checked for file-channel operations inherited from the cassette loader. If
  it uses a channel without opening one itself, automatic `!BOOT` generation
  is suppressed and the image explains that a direct launch would raise BASIC
  error 222 (`Channel`). Binary, incomplete, protected or otherwise uncertain
  loaders likewise carry a visible warning rather than being presented as a
  guaranteed working conversion.
- When a UEF, SSD, DSD, HFE, or MMB disk is extracted into ADFS, binary loaders are
  checked for DFS-only OSCLI abbreviations such as `R.` and `L.`. These can be
  ambiguous under ADFS because it adds commands including RENAME, REMOVE,
  LCAT, LEX, and LIB. If the loader uses a provable immediate OSCLI pointer and
  its address range has safe room, Acorn File Forge appends full `RUN` or
  `LOAD` commands and redirects only those pointers. It leaves uncertain code
  unchanged rather than risking a blind binary patch. Analysis begins with
  conventional boot scripts and follows their directly named launch target.
  Unrelated documentation, magazine text and game data are not scanned as
  loaders merely because their bytes happen to contain `R.` or `L.`. Every
  successful change is reported as a persistent image warning. Multiple
  unresolved commands in one reachable loader are condensed into one warning.
- ADFS floppy-to-HDD imports receive the same guarded loader pass. Some ADF
  releases still contain DFS-style `R.`, `L.`, or `LO.` commands even though
  their files are stored on ADFS. Textual `!BOOT`, `MENU`, `LOADER`, `START`,
  and `GO` scripts are expanded to unambiguous `RUN` and `LOAD` commands.
  Reachable tokenised BASIC loaders are also checked for rooted references such
  as `$.LOADER`. When that exact file is present in the newly extracted
  directory, the reference is made relative and the BASIC line length is
  rebuilt. This lets software moved below the HDD root find its own files while
  preserving genuine dependencies on files elsewhere in the volume.
  Proven machine-code OSCLI pointers are repaired by the same safe binary
  process. Reimport a directory created by an older release to apply these
  compatibility changes.

Cycle-level encodings, deliberate read errors, protection schemes, and other
non-standard chunks cannot always be represented as ordinary files. The
application reports those chunks and marks incomplete recovered files rather
than silently pretending the conversion was perfect.

## Saving and recovery

**Save** first validates and finalises the current working image, then starts
the download in an isolated browser target. A validation or network error is
reported inside Acorn File Forge and cannot replace the application with a raw
JSON error page.

- Every format is returned as a timestamped ZIP named
  `<image-name>-YYYYMMDD-HHMMSS.zip`, so repeated saves do not silently reuse
  the old `-edited` filename.
- Every ZIP includes a comprehensive `README.md` with the format, target
  hardware, byte size, SHA-256 checksum, warnings, usage notes and a filesystem
  catalogue. MMB reports list all 511 slots, including empty ones, access state
  and the files inside each formatted DFS disk.
- A DAT image with a DSC descriptor keeps both files together below the
  `BeebSCSI0/` directory in the ZIP. The README remains at the archive root.
- ZIPs are streamed as they are built, so even a multi-gigabyte image does not
  need to be held in server memory before downloading starts.
- Opening or creating ADFS media offers a target-hardware profile. The 8-bit
  profiles validate matching old `Hugo` directory headers, footers, parent
  links and sequence copies. A saved BeebSCSI volume also receives a new
  old-map disc ID and checksum so ADFS does not confuse the edited filesystem
  with the original cached volume.
- Saving an MMB returns the complete MMB, including all slots.
- Saving an edited HFE v1 first writes against the original track layout, then
  decodes and byte-compares the resulting sectors. A mismatch blocks the
  download. Read-only HFE v2/v3 and damaged images download unchanged.

Session metadata is stored beside each working image. If the Gunicorn worker
restarts, the application can reopen a valid session from disk. On either empty
pane, choose **Recover previous session** to list retained working copies newest
first. Recovery preserves completed edits after a refresh, accidental browser
navigation, interrupted download, or container restart. Removing the Docker
volume removes those sessions.

Recovery is private to the browser that opened or created the image. The server
issues a random, year-long `HttpOnly`, `SameSite=Strict` ownership cookie and
mirrors the same opaque ID in origin-scoped browser storage. Either copy can
restore the other after a browser update or container restart. Recovery
listings, direct image API access and deletion all enforce the owner match.
There is no shared global session browser. Clearing both site cookies and site
storage deliberately breaks the link; sessions from releases before private
ownership can be attached once with a
one-time recovery key. An operator can also issue a key for a specific saved
session if its browser cookie has been lost. Claiming the key transfers only
that session to the current browser, then immediately expires the key.

Closing a work pane now detaches the image without deleting its server-side
working copy. Reopen it through **Recover previous session**. Permanent removal
is deliberately confined to the recovery dialog's confirmed **Clear** actions.

The browser remembers the currently displayed one, two or three work panes and
their order. A normal refresh reopens each
image and returns to the same MMB slot, DFS side or ADFS directory. Closing a
pane removes it from automatic reopening while keeping its recovery copy.
On the first refresh after upgrading from a version without workspace memory,
the newest working session owned by that browser is reopened automatically.
This one-time bridge stops the upgrade itself returning active work to the
empty start screen.

The recovery dialog can permanently clear the selected previous session or all
previous sessions shown there. Images currently open in any pane are omitted
from those clearing controls. Clearing removes only Docker-side working copies,
never the source files selected from the host.

Each recovered session includes its named checkpoints and automatic undo
history. Recovery ownership therefore protects both the active working image
and every snapshot beneath it.

## Built-in help

Use **Help** in the top-right corner for the illustrated handbook. It covers
the expandable one-to-three-pane workflow and pane rearranging, undo and named
checkpoints, all supported formats, MMB blank disks and protection,
drag and drop, directory traversal, Universal Menus, UEF conversion,
HFE safety and conversion, BeebSCSI pairing, long-operation recovery, keyboard
selection, saving, and safety. The guide uses screenshots from the current
interface and works in light or dark mode.

Browser state is not a substitute for saving. Download important work before
upgrading the container, deleting its volume, or cleaning Docker storage.

The in-app handbook and this README describe the same current workflows. If
they disagree with the controls in a newer build, please report the mismatch
in the [project repository](https://github.com/peteclarke-del/AcornFileForge).

## Limits and practical considerations

- The default upload limit is 8 GiB. Set `ACORN_MAX_UPLOAD_GIB` in
  `docker-compose.yml` to change it.
- A working image needs roughly its own size again in the Docker volume.
  Extraction and conversion may need additional temporary space. HFE sessions
  retain the original container, decoded sectors, and a verified encoded copy
  while saving.
- Large hard-drive uploads and recursive copies can take time. Keep the page
  open while the progress overlay is visible.
- A failed long operation replaces the progress view with a foreground error
  screen. It shows the completed count and last reported path. **Back / retry**
  returns to the original operation and completed MMB slots are skipped.
- Read-only requests retry brief connection failures automatically. ADFS menu
  writes also retry safely because matching directory entries replace one
  another and concurrent menu rebuilds are serialised per image.
- MMB slot extraction mounts the ADFS destination once for a complete batch.
  Common DFS metadata is written with two catalogue updates instead of four.
- Grouped ADFS menu scans also use one open destination mount. Holder
  directories are expanded in memory instead of launching one filesystem
  process for every contained disk.
- Complete DFS/ADFS directory extraction uses one recursive engine invocation,
  rather than starting a process for every top-level object.
- Menu database rebuilds write all four title/publisher files through one
  mounted image, while menu support files are installed with one source and
  destination mount. On the bundled test setup, a three-entry ADFS menu
  creation fell from about 17.8 seconds to 0.5 seconds, and a reorder fell
  from about 8.3 seconds to about 2.7 seconds.
- Local source-image benchmarks use clone or kernel-copy paths where available.
  In the 512 MiB DAT test this reduced open time from about 4.9 to 4.5
  seconds; storage speed remains the dominant cost.
- Individual files are exported to disk-backed responses, and DAT/DSC bundles
  stream with bounded memory. The 512 MiB test bundle produced its first byte
  in about 0.01 seconds and validated as a complete ZIP.
- Mutations to the same image are locked and run in sequence.
- The `disc` subprocess timeout is 240 seconds. Gunicorn allows requests for
  up to 300 seconds.
- Acorn filenames are matched case-insensitively. The application preserves
  the spelling stored in the image.
- For safe cross-format operation, the interface rejects control characters
  and path syntax characters even if a byte-edited source image happens to
  contain them.
- Compact is important for old-map ADFS and DFS. New-map media would not need
  the same contiguous-free-space maintenance, but those formats are outside
  the current write support.

## Configuration

The Compose defaults are:

```yaml
ports:
  - "8666:8666"
environment:
  BBCFM_WORK_DIR: /app/work
  ACORN_MAX_UPLOAD_GIB: "8"
volumes:
  - bbcfm-work:/app/work
```

`BBCFM_WORK_DIR` is retained for compatibility with existing installations.
It controls internal working storage and does not affect the Acorn File Forge
branding.

## Architecture

```text
Browser
  dynamic panes, dialogs, HTML drag and drop
                    |
                    | JSON and multipart HTTP
                    v
Flask API
  images | files | MMB slots | menus
                    |
                    v
Disk service
  session copies | locking | MMB adapter | UEF parser | HFE safety
             |                              |
             v                              v
      Oaknut Disc                      HxC engine
  DFS | ADFS | FileCore          HFE tracks | sector conversion
```

The application runs one Gunicorn worker with eight threads. A single worker
keeps the in-memory session cache coherent, while per-image locks allow safe
parallel reads and prevent overlapping writes to the same image.

Backend routes are split by responsibility:

- `app/routes/images.py` handles opening, creating, saving, conversion, and
  compaction.
- `app/routes/files.py` handles tree browsing, file operations, extraction,
  and cross-image transfers.
- `app/routes/mmb.py` handles slots and multi-image insertion.
- `app/routes/menus.py` handles MMB and ADFS menu maintenance.
- `app/disk_service.py` owns image sessions and calls the disk engine.
- `app/menu_service.py` owns metadata analysis and Universal, SPI and ADFS menu databases.
- `app/uef.py` parses cassette blocks.
- `app/hfe.py` validates HFE headers and classifies HFE versions safely.

Frontend format declarations live in `app/static/formats.js`, and backend
extension declarations live in `app/formats.py`. This keeps accepted
Archimedes and raw-image names in one place on each side of the API.

## Development checks

Local development media belongs in `samples/`, which is ignored by Git, source
archives and the Docker build context. Tests that need optional real-world
fixtures should skip cleanly when those files are not present.

Generated test images belong in `output/`. That directory is also excluded
from Git and source archives so local build artefacts are never published with
the application source.

Run the Python regression tests:

```bash
python3 -m unittest discover -s tests -v
```

Check Python and JavaScript syntax:

```bash
python3 -m py_compile app/*.py app/routes/*.py
node --check app/static/formats.js
node --check app/static/core.js
node --check app/static/app.js
```

Check the running service:

```bash
curl http://localhost:8666/api/health
```

A healthy response looks like:

```json
{"engine":"oaknut","status":"ok"}
```

## Main dependencies

- Python 3.12
- Flask 3.1
- Gunicorn 23
- Oaknut Disc 12.13
- HxC Floppy Emulator command-line engine 2.16.15.2, compiled from a pinned
  upstream revision during the Docker build
- Docker or Docker Compose

Oaknut provides the filesystem implementation. Acorn File Forge adds the web
workspace, safe working copies, MMB handling, UEF reconstruction, verified HFE
conversion, metadata review, menu generation, and format-aware drag and drop.

The first Docker build compiles the HxC command-line engine and therefore takes
longer than an ordinary application-only build. Docker caches that builder
layer, so later source and documentation rebuilds are much quicker.
