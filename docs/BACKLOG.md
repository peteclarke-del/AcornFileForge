# Acorn File Forge backlog

This is the product backlog agreed after the 1.0.0-rc.1 feature review. It is
separate from the [release checklist](RELEASE-CHECKLIST.md): the checklist is a
repeatable validation gate, while this page records product work that is not
finished yet.

Items are split so completed work can be checked without hiding the remaining
part of a larger idea. A checked item is implemented and covered by the normal
project documentation. An unchecked item remains in scope.

## 1. Release engineering

- [x] Remove the obsolete statement that the workspace is limited to three
      panes. The workspace now documents its unlimited movable, resizable,
      stackable and minimisable pane model.
- [x] Provide a reproducible, version-neutral release checklist.
- [x] Make the Dockerfile build native dependencies on AMD64, ARM64 and ARMv7,
      including the Raspberry Pi package-name and Capstone fixes.
- [ ] Run and retain the complete AMD64, ARM64 and ARMv7 clean-build matrix for
      the release candidate.
- [x] Run the generated-media and fault-injection gates for the candidate and
      retain the AMD64 evidence in `docs/release-evidence/`.
- [ ] Complete the real-hardware gate for the affected BBC, Electron,
      BeebSCSI, MMFS and RISC OS workflows.
- [ ] Choose the release version, update `VERSION`, create the signed or
      annotated tag, publish release notes and retain the previous known-good
      release for rollback.

## 2. Image comparison and patch sets

- [x] Compare logical filesystem objects across open DFS, MMB, ADFS, ROM and
      ROMFS images.
- [x] Report added, removed, content-modified and metadata-only records using
      deterministic manifests and SHA-256 fingerprints.
- [x] Export the complete comparison as JSON.
- [x] Build a compact `.affpatch.zip` containing only changed payloads and a
      human-readable operation plan.
- [x] Verify the exact base revision, physical layout, operation plan and every
      payload before enabling Apply.
- [x] Create an automatic checkpoint, verify the final candidate fingerprint
      and roll back a failed or aborted application.
- [x] Show persistent phase, item and byte progress with safe Abort for compare,
      patch creation, preflight and application.
- [x] Classify proven renames directly instead of presenting every rename as a
      remove plus add pair.
- [x] Add filesystem-contextual raw-byte differences to the same comparison
      report, separated by primary image and companion descriptor. Equal
      chunks are skipped without byte-by-byte expansion and changed ranges are
      reported alongside the logical filesystem evidence.
- [x] Allow a reviewed subset of independent operations to be exported and
      applied. Each subset receives its own derived candidate fingerprint and
      automatically includes required parent directories, removed descendants
      and complete MMB-slot dependencies.

## 3. Workspace-wide search

- [x] Search filenames and bounded readable BASIC, script and text content
      across every distinct open filesystem image.
- [x] Search every formatted MMB slot without opening each disk individually.
- [x] Restore, raise and navigate the containing pane, slot and directory, then
      open the selected file.
- [x] Search catalogue metadata, load and execution addresses, filetype and
      access state.
- [x] Add known publisher and installed-menu metadata to workspace search,
      including launch action and PAGE evidence from recognised MMB and ADFS
      menus.
- [x] Search exact and prefix SHA-256 values from a manifest or collection
      index.
- [x] Search useful printable strings in binary files and jump to the matching
      disassembly or Hex address.
- [x] Add raw ROM bank strings, ROM symbols and regions, disassembly labels,
      project notes and comments to workspace search, with direct navigation
      to the matching bank, Workbench tab and address.

## 4. Headless CLI and repeatable recipes

- [x] Save reusable GUI import recipes for naming, grouping, online metadata,
      compatibility rewrites and menu policy.
- [x] Export and restore a portable GUI project containing panes, paths,
      profiles and recipes.
- [x] Provide a supported headless CLI for image creation, imports, conversion,
      validation, menu generation, comparison, patching and saving.
- [x] Export a completed GUI workflow as a versioned recipe with source
      identities, expected hashes and all non-secret decisions required for a
      deterministic rebuild.
- [x] Add a dry-run CLI report and stable machine-readable exit statuses.

## 5. Compatibility and conversion reports

- [x] Preflight cross-format transfers for target names, truncation, collisions,
      directory capacity, empty disks and destination conflicts.
- [x] Report load and execution metadata, safe DFS-to-ADFS loader rewrites,
      PAGE evidence, profile conflicts and image warnings in the applicable
      workflows and saved README.
- [x] Define a versioned consolidated compatibility-report schema and use it
      for the current selection dry-run.
- [ ] Present that shared report before every cross-format batch from drag and
      drop, File commands and Online Library. The headless CLI already uses it
      for imports and exposes it directly through `preflight`.
- [x] Export a generated compatibility report directly as JSON or Markdown.
- [x] Include the final accepted report in the saved image package.
- [x] Record explicit filename, directory and filetype losses or conversions
      per item rather than only as batch-level prose.

## 6. Whole-MMB emulator integration

- [x] Run or debug one selected MMB slot by extracting an isolated temporary
      SSD without changing the MMB.
- [x] Disable whole-MMB launch honestly when the selected emulator has no MMFS
      storage adapter.
- [ ] Add an MMFS-compatible virtual SD-card adapter to Elkulator or B-em.
- [ ] Mount, boot and debug the complete MMB, including its actual menu and
      selected MMFS build.
- [ ] Feed authoritative whole-MMB emulator results back into menu health and
      PAGE diagnostics.

## 7. Writable archives and UEF projects

- [x] Browse ZIP, TAR, compressed TAR, GZIP, BZIP2 and XZ hierarchies with
      bounded extraction and path safety.
- [x] Edit supported readable archive members, rebuild the outer container,
      verify hashes and checkpoint the containing image.
- [x] Decode raw, compressed and extensionless UEF into a read-only cassette
      hierarchy and copy reconstructed files to writable media.
- [ ] Rebuild UEF while preserving chunk order, baud-rate changes, gaps,
      carrier tones, security cycles and unknown control chunks byte for byte
      where they are not intentionally changed.
- [ ] Provide a tape-project view and a structural before-save comparison that
      makes every timing or control-chunk change explicit.
- [ ] Enable UEF member editing only when the reconstruction proof succeeds;
      retain read-only behaviour for ambiguous or unsupported recordings.

## 8. Expanded menu interpretation

- [x] Detect, edit and preview supported Universal, Universal 4R, SPI and other
      explicitly modelled menu records.
- [x] Show a database-oriented fallback when a machine-code menu cannot be
      interpreted safely.
- [ ] Run unfamiliar menu programs in an isolated emulator sandbox with bounded
      time, deterministic media and no access to working images.
- [ ] Capture display, palette, text and input behaviour from the sandbox and
      link it to the menu database records that produced each screen entry.
- [ ] Promote a captured interpreter profile only after repeatable evidence and
      regression fixtures exist for that menu family.

## 9. Collection database

- [x] Export manifests containing logical paths, MMB slots, metadata, hashes
      and recognised menu records.
- [x] Detect byte-identical files and disks, equivalent MMB catalogue content,
      likely title variants and duplicate games across differently named disks.
- [x] Filter Online Library results against remembered distributions, disk
      titles and installed menu entries.
- [x] Maintain a browser-private catalogue of owned images, titles, publishers,
      target machines, hashes, menu entries and user-supplied locations.
- [x] Refresh the catalogue incrementally after edits and invalidate stale
      records using the exact image revision fingerprint.
- [x] Produce collection, duplicate, variant and missing-title reports across
      images that are not currently open.
- [x] Add explicit export, import, backup and clear controls for the private
      catalogue without exposing one browser owner's records to another.

## 10. Hardware deployment assistant

- [x] Model target machines, filing systems, expansions, Tube state and managed
      emulator capabilities in hardware profiles.
- [x] Validate images and saved packages against the selected profile and
      generate a technical README with applicable warnings.
- [ ] Model deployment layouts for Gotek, MMFS, BeebSCSI, Pi1MHz and supported
      RISC OS targets, including filenames, directories, companion files and
      capacity rules.
- [ ] Generate the chosen SD-card or host-directory tree in a downloadable ZIP
      without changing the open working images.
- [ ] Include a hardware-specific installation, backup, verification and
      rollback guide generated from the exact profile and package contents.
- [ ] Validate the generated layout itself before download and report anything
      that still requires a manual hardware step.

## 11. Cheat analysis and verified patches

- [x] Find conservative BBC BASIC gameplay variables, direct memory writes and
      terminal-value tests from one selected file.
- [x] Find counter, comparison, branch and semantically labelled state evidence
      in supported 6502, 65C02, 65816, ARM and 68000 disassembly.
- [x] Present confidence, purpose filters, risk, online title identification
      and configured specialist reference searches as a read-only Analyse tool.
- [ ] Correlate static candidates with emulator watchpoints and repeatable
      gameplay events before offering a patch.
- [ ] Save a proved cheat as a guarded project patch with original-byte hash,
      machine profile, rationale, author and rollback instructions.
- [ ] Add a user-owned cheat library that matches exact image and file hashes,
      never title alone.

## Delivery order

Work should normally proceed in this order:

1. Present the shared compatibility report consistently before every remaining
   cross-format GUI workflow.
2. Build the deployment assistant on hardware profiles, compatibility reports
   and deterministic recipes.
3. Develop writable UEF projects and sandboxed menu interpretation as isolated
   expert projects with their own fixtures and safety gates.
4. Add a real MMFS storage adapter and use whole-MMB emulator results for menu
   and PAGE diagnostics.
5. Correlate static cheat candidates with repeatable emulator evidence before
   permitting guarded patches or a private cheat library.
6. Run the complete multi-architecture and real-hardware release gates, then
   publish the tagged release candidate.

Safety takes precedence over marking a checkbox. Unsupported token streams,
tape control data, menu programs and emulator adapters must remain read-only or
disabled until the relevant proof and rollback path exist.
