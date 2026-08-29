# Release checklist

This checklist defines the release gate for Acorn File Forge. It is
version-neutral so it remains valid for every candidate and final release. The
gate must be reproducible from a clean checkout without anything in `samples/`.

Return to the [documentation index](README.md) for the operator and technical
handbooks validated by this gate.

Retained local evidence is stored under `docs/release-evidence/`. The
[17 August 2026 AMD64 RC2 record](release-evidence/2026-08-17-amd64-rc2.md)
covers the current complete automated and browser suites. It does not satisfy
the independent ARM64, ARMv7 or physical-hardware rows below.

Record the intended version before starting:

```bash
export RELEASE_VERSION=1.1.0
test "$(cat VERSION)" = "$RELEASE_VERSION"
```

Use the real release value. Do not copy the example unchanged.

## 1. Source and scope

- [ ] The release branch contains only reviewed, intentional changes.
- [ ] `git status --short` is empty before the final build.
- [ ] `VERSION`, the API health response, generated archive README and planned
      Git tag all report the same version.
- [ ] No secrets, personal paths, commercial media or local firmware sources
      have entered the change.
- [ ] `samples/`, `output/`, browser downloads, working sessions and benchmark
      scratch data are absent from the commit and `git archive` output.
- [ ] Dependency and firmware changes include provenance, version, licence and
      checksum review.
- [ ] `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES.md`, `SECURITY.md` and the
      dependency inventory agree with the release contents.
- [ ] Firmware redistribution rights have been established for every binary
      retained in the source archive or published image. Unresolved material is
      omitted rather than assumed to be covered by the project licence.
- [ ] Any format restriction or repair behaviour changed by the release is
      called out in the release notes.
- [ ] `tools/build-release.sh` creates a source archive, native `.deb` and
      `SHA256SUMS` from the clean tagged tree.
- [ ] `.github/workflows/release.yml` builds Debian 13 and Ubuntu 24.04
      packages for AMD64, ARM64 and ARMv7, inspects their metadata and imports
      their vendored native dependencies before publication.

## 2. Documentation

- [ ] [README.md](../README.md) describes the current formats, UI and limits.
- [ ] [Installation](INSTALLATION.md) matches the Dockerfile, Compose service,
      ports, volume and all supported host architectures.
- [ ] [File editor guide](FILE-EDITOR-GUIDE.md) matches editor menus, save
      semantics, analysis, emulators and read-only cases.
- [ ] [ROM guide](ROM-GUIDE.md) matches ROM, ROMFS, Workbench and programmer
      behaviour.
- [ ] In-app Help uses the same menu names and workflow decisions.
- [ ] Firmware notes contain current checksums and runtime paths.
- [ ] Every local Markdown link and image reference resolves.
- [ ] Screenshots of changed interfaces come from the release build, use no
      private media and remain readable at their rendered size.
- [ ] Documentation contains no obsolete project name, stale hardcoded release
      command or unsupported claim.

## 3. Automated build matrix

Build and test these native targets:

| Platform | Typical system | Required result |
| --- | --- | --- |
| `linux/amd64` | x86-64 Linux or Docker Desktop | Image builds, native runtime gate and complete tests pass |
| `linux/arm64` | 64-bit Raspberry Pi OS or Apple Silicon builder | Image builds, native runtime gate and service health pass |
| `linux/arm/v7` | 32-bit Raspberry Pi OS | Image builds, native runtime gate and service health pass |

For each target:

- [ ] Docker builds from a clean enough cache to exercise changed dependency
      stages.
- [ ] Native Capstone exposes ARM, M68K and MOS 65xx support.
- [ ] HxC, Elkulator and B-em builder stages complete.
- [ ] Runtime package names resolve on the selected Debian base.
- [ ] Every Python test passes inside the primary AMD64 test image.
- [ ] `node tests/run_js_tests.js` passes in the primary test job.
- [ ] Each architecture imports Oaknut and Flask, creates the application,
      exercises all required Capstone engines and contains the native HxC,
      Elkulator and B-em executables.
- [ ] The service starts on port `8666` and the health endpoint reports the
      expected version.
- [ ] `npm run test:browser` passes against the primary built service.
- [ ] A generated BASIC file and a generated machine-code file produce bounded,
      read-only cheat-candidate reports; plain text is rejected explicitly.
- [ ] Guarded cheat preparation refuses BASIC and archive members, changing
      source hashes, mismatched original bytes and fewer than two distinct
      tester-supplied emulator observations. A valid apply creates a checkpoint,
      while the private library matches the exact file hash and original bytes.
- [ ] `git diff --check` passes.
- [ ] The native `.deb` builds on each claimed Debian or Ubuntu target, passes
      `dpkg-deb --info` and `dpkg-deb --contents`, and contains no firmware,
      samples, working images or Git metadata.
- [ ] A clean test machine installs the `.deb` with APT, shows the desktop
      entry and MIME associations, launches the GTK host, saves an image, then
      upgrades and removes the package without deleting XDG user state.

When a build fails, retain the first Docker `ERROR` block. Later `CANCELED`
stages are usually consequences of that failure.

## 4. Generated-media and fault gate

The generated-media test matrix must create and reopen:

- [ ] DFS SSD and DSD images;
- [ ] ADFS S, M and L images;
- [ ] BeebSCSI DAT with matching DSC;
- [ ] MMB with all 511 slots represented;
- [ ] UEF with one proof-editable standard member and one deliberately
      ambiguous read-only recording;
- [ ] clean writable HFE v1 and guarded read-only HFE variants;
- [ ] raw and banked ROM images;
- [ ] editable ROMFS data images;
- [ ] supported HDF and RAW FileCore layouts.

Writable filesystems must write, rename, lock, move, delete, compact, save and
reread known data. Cross-format tests must cover valid metadata conversion,
filename replacement, directory capacity, empty disks, multiple MMB slots and
cancelled batch work.

Fault tests must cover:

- [ ] interrupted upload;
- [ ] exact checkpoint rollback after a partial write;
- [ ] full DFS data area and full DFS catalogue;
- [ ] corrupt DFS and ADFS structures;
- [ ] mismatched or invalid DAT/DSC geometry;
- [ ] cancellation at every safe cancellation boundary;
- [ ] browser ownership isolation;
- [ ] simulated container restart with retained sessions;
- [ ] failed save packaging without loss of the working image;
- [ ] stale online catalogue result and partial network failure.

## 5. Browser and interface gate

- [ ] Start with one pane, add more than three, move, resize, overlap, snap,
      minimise, restore and close panes.
- [ ] Refresh restores open images, paths, selections and every pane's window
      geometry, snap, stack and minimised state.
- [ ] Long open, copy, analysis, menu and save operations show phase, item
      count, elapsed time, throughput, ETA and Abort when safe.
- [ ] Creative and destructive controls disable while their operation runs.
- [ ] Errors appear above the active editor or workflow dialog and remain
      actionable.
- [ ] Menus close after an item is selected, on outside click, and when moving
      to another open top-level menu.
- [ ] Light and dark themes work at desktop and narrow widths, 200 percent zoom
      and reduced motion.
- [ ] Keyboard focus, labels, live regions, dialog trapping and non-colour state
      cues satisfy the documented WCAG 2.2 AA target.
- [ ] Save downloads do not announce completion until the ZIP is genuinely
      available to the browser.
- [ ] The platform-contract tests report no undeclared web or desktop route
      differences and both hosts serve the same static frontend.
- [ ] On Linux, the GTK host starts without Docker, opens multiple associated
      image files from both the native chooser and file manager, pairs DAT/DSC,
      recovers its XDG sessions and saves a complete package to Downloads.
- [ ] A managed emulator opens in a native window from the Linux host, closes
      with the application, and still uses noVNC when launched from Docker.

## 6. Format and workflow gate

Manually verify at least one representative image for each changed family.
For a broad release, cover all of these:

- [ ] DFS catalogue groups, metadata, file operations and image creation.
- [ ] File-level Load and Execute columns show full eight-digit words on DFS,
      MMB disk, ADFS and ROMFS views. Packed DFS addresses are conventionally
      sign-extended rather than displayed as misleading short positive values.
- [ ] Address editing changes both catalogue words without changing file bytes,
      creates an undo point and presents the general and FileCore-specific
      safety warnings where applicable.
- [ ] MMB empty slots, multi-selection, slot drag, Cut/Copy/Paste, access,
      duplicate detection, menu edit and individual slot download.
- [ ] ADFS directory traversal, same-image move, installed-disk audit, global
      menu generation and large DAT/DSC save.
- [ ] HFE capability detection and guarded save.
- [ ] UEF hierarchy, same-length structural rebuild, read-only ambiguity gate
      and extraction into writable media.
- [ ] ROM banking, command and help discovery, Workbench, compare, build,
      programmer export and project persistence.
- [ ] ROMFS create, edit, capacity handling and save.
- [ ] ZIP and archive hierarchy, member preview and editor hand-off.
- [ ] Online Library machine default, sorting, already-present filtering,
      multi-selection and installation.
- [ ] Private collection persistence in web IndexedDB and desktop XDG state,
      stale revision handling, cross-image reports and bounded backup merge,
      replacement and clearing.
- [ ] Menu metadata priority, launch action, PAGE derivation, multi-title disk,
      keep-off-menu and complete regeneration.
- [ ] Headless CLI create, save, validate, preflight, import, menu, compare and patch
      commands return the versioned JSON envelope and documented exit codes.
- [ ] CLI dry-run writes no output, deterministic recipes reject changed
      inputs, and accepted compatibility reports appear in saved ZIPs.
- [ ] Cross-format drag, clipboard, File-menu and Online Library batches show
      the shared compatibility report before their first destination write.
- [ ] Gotek, MMFS, BeebSCSI, Pi1MHz and RISC OS deployment plans list exact
      paths and hashes, reject stale revisions and produce a ZIP whose manifest
      matches every payload. Confirm planning leaves the live image unchanged.

## 7. Editor and emulator gate

- [ ] Tokenised BASIC opens with correct line spacing and saves valid tokens.
- [ ] Scripts, plain text, archives, binary files and unknown data select the
      documented editor or hex fallback.
- [ ] Search and replace, undo/redo, save, save as and local export work.
- [ ] Tooltips distinguish BASIC commands from star commands and decode VDU,
      `*FX`, OSBYTE, OSWORD, OSCLI and SYS in the active hardware context.
- [ ] Formatting is presentation-only. Refactor and condense are guarded,
      reversible edits and do not renumber before acceptance.
- [ ] Disassembly headers align with rows, code/data regions persist, strings
      navigate correctly and annotations identify known calls.
- [ ] Elkulator, B-em and MAME options match the selected profile and mounted
      media capabilities.
- [ ] noVNC on port `8668` displays the launched emulator and errors are visible
      above the invoking editor or pane.
- [ ] An Electron MMFS profile mounts a complete MMB through the isolated FAT16
      Pi1MHz card, while BBC and Master profiles retain their explicit adapter
      limitation.
- [ ] Two installed-menu sandbox runs reproduce the same frame hashes, respond
      visibly to navigation and appear against the exact current revision in
      Image Health.

## 8. Performance record

Run the quick profile during development and the full profile before tagging:

```bash
python -m tools.benchmark_media --profile quick --output output/benchmark-quick.json
python -m tools.benchmark_media --profile full --output output/benchmark-full.json
```

The full record must include minimum, median and maximum duration for:

- listing all 511 MMB slots;
- listing a populated DFS catalogue;
- browsing a generated ADFS tree;
- bulk import into an ADFS hard disk;
- rebuilding an ADFS menu database;
- browsing and checkpointing BeebSCSI DAT/DSC;
- validating, documenting and building the complete BeebSCSI save ZIP.

Keep the full JSON as a CI or release artefact. Compare medians with the previous
candidate and explain or fix a material regression.

## 9. Real-hardware gate

For a tagged release, use downloads produced by that exact build:

- [ ] edited DFS disk on a supported BBC or Electron setup;
- [ ] edited ADFS floppy;
- [ ] BeebSCSI DAT/DSC on the selected normal ADFS or BeebSCSI target;
- [ ] MMB and installed menu on the intended MMFS build;
- [ ] Tube-enabled and Tube-disabled launch where the profile says each applies;
- [ ] at least one Archimedes or RISC OS image when that code changed.

Confirm directory changes, access flags, launchers, PAGE values and menus after
a cold restart, not only in an emulator.

## 10. Saved-package gate

Every tested **Save image** download must contain:

- [ ] a timestamped, collision-resistant ZIP name;
- [ ] the image under its intended user-facing name;
- [ ] DSC, INF or other partner metadata files where applicable;
- [ ] individual file exports include a matching `.inf` with the real Acorn
      path, load word, execute word, length and lock state;
- [ ] generated technical `README.md` with version, profile, catalogue,
      warnings, checksums and usage notes;
- [ ] `ROM-project.json` for ROM projects;
- [ ] no temporary, session, source-path or private browser data.

Reopen the contents of at least one ZIP from each writable media family.

## 11. Tagging and publication

Merge the reviewed release pull request first. Tag the exact merge commit on
`main`:

```bash
git switch main
git pull --ff-only
test "$(cat VERSION)" = "$RELEASE_VERSION"
git tag -a "v$RELEASE_VERSION" -m "Acorn File Forge $RELEASE_VERSION"
git push origin "v$RELEASE_VERSION"
```

Do not tag a feature-branch head. GitHub may create a different merge commit,
and the release tag must identify the code users actually clone.

Pushing the tag starts the release workflow. It validates the tag against
`VERSION`, builds the source archive and six distribution-specific packages,
creates `SHA256SUMS`, and publishes the GitHub Release only after every package
gate succeeds.

Finally:

- [ ] create the GitHub Release from that tag;
- [ ] attach benchmark and other intended release artefacts;
- [ ] publish human release notes with known restrictions and upgrade advice;
- [ ] verify the public HTTPS clone and clean Compose build instructions;
- [ ] keep the previous known-good release available for rollback.
