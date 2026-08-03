# Acorn File Forge delivery status

This file records the original improvement roadmap and what has now shipped.
All listed work is present in the current application. New bugs and ideas are
best tracked in the
[GitHub repository](https://github.com/peteclarke-del/AcornFileForge) so they
do not get lost in a long local checklist.

## Completed

- [x] Undo and named checkpoints
  - Create an automatic restore point before every image-changing operation.
  - Provide a one-click undo for the most recent change.
  - Let users create, name, restore and delete permanent checkpoints.
  - Keep checkpoints private to the owning browser session.
  - Use copy-on-write filesystem clones where available so large HDD images can
    be checkpointed without copying every byte.

## Completed roadmap

- [x] Preflight and dry-run mode
  - Show exactly which files, directories, slots and menu records will change.
  - Report name truncation, clashes, capacity limits and compatibility rewrites
    before writing the destination image.

- [x] Unified image health dashboard
  - Combine filesystem validation, geometry checks, free-space map checks, menu
    audits, PAGE audits and loader compatibility into one clear report.
  - Offer safe automatic repairs with an itemised preview.
  - Expand failed menu checks into individual records with the menu location,
    target slot or directory, launch command, PAGE, exact problem and evidence.
  - Report an unreadable menu database against its menu slot and data filename,
    then continue checking any other detected menus.

- [x] Hardware profiles
  - Save reusable Electron, BBC, Master, BeebSCSI and Archimedes/RISC OS setups.
  - Include filing system, MMFS build, Tube state, PAGE expectations and menu
    preferences.
  - Set the default Online Library machine filter for each applied profile,
    while allowing it to be changed for an individual search.
  - Warn when an imported title conflicts with the selected hardware profile.

- [x] Configurable Online Library
  - Search confirmed downloadable software for BBC, Master, Electron,
    Archimedes and RISC OS targets from a writable media pane.
  - Insert several images into MMB slots or extract supported downloads into
    DFS, ADFS and RISC OS filesystems through the normal checked workflows.
  - Keep provider URLs, categories, machine IDs, loading strategies, page
    layouts and media resolution in editable source configuration.
  - Suppress catalogue-only, gallery-only and unavailable records rather than
    presenting them as installable software.
  - Sort results by title, publisher, year or source in ascending or descending
    order without losing the current multi-selection.

- [x] Menu-entry test runner
  - Verify that every menu record selects the intended disk or directory.
  - Check launcher existence, action, PAGE, relative paths and obvious loader
    dependencies without needing real hardware for the first pass.

- [x] Dependency-aware copying
  - Inspect launchers for root-relative files, library directories and companion
    programs before copying.
  - Copy required dependencies or explain why a subdirectory installation is
    unsafe.

- [x] Better file inspection
  - Add hex, text and tokenised BASIC views.
  - Decode common Acorn metadata and show detected loader commands.
  - Provide safe edits for small text and BASIC loader files.

- [x] Collection manifest
  - Export a searchable CSV or JSON catalogue of images, MMB slots, files, menu
    records, publishers, PAGE values and checksums.
  - Import a reviewed manifest to apply bulk metadata corrections.

- [x] Duplicate and variant finder
  - Detect byte-identical images and likely title variants.
  - Compare catalogue contents while keeping genuinely different releases.
  - At an MMB's All disks level, compare installed game titles independently of
    disk labels and show equivalent catalogue content as a separate signal.
  - Select duplicate menu records inline, then separately decide whether to
    keep or eject each associated disk, with extra warnings for multi-game disks.
  - Keep ordinary single and multi-slot ejection in sync with installed
    Universal and SPI menu records.
  - Hide installed Online Library results using disk titles, remembered source
    names and installed menu titles without relying on punctuation.

- [x] Persistent jobs panel
  - Keep long-running jobs visible when dialogs close.
  - Show current phase, completed and skipped items, warnings and errors.
  - Allow safe abort, retry and resume from the last completed item.

- [x] Import recipes
  - Save repeatable choices for naming, directory grouping, metadata lookup,
    compatibility conversion and menu creation.
  - Apply a recipe to later collections and review only exceptions.

- [x] Portable project file
  - Save the current multi-pane workspace, image references, paths, menu roots,
    hardware profiles and import settings as one portable project description.
  - Reopen the project without losing pane layout or working context.

## Quality checks used for every item

- Preserve the original uploaded files and provide a clear recovery path.
- Work with one to three panes and both light and dark themes.
- Avoid loading complete large images into application memory.
- Disable creative and destructive controls while an operation is active.
- Report progress and actionable errors in front of the active dialog.
- Keep the README, generated archive notes and in-app handbook up to date.
- Add automated backend tests and an end-to-end browser check.

Local images in `samples/` are test fixtures only. Git and `git archive` ignore
that directory so large disk collections and software with redistribution
restrictions are not included in the repository or its source archives.
