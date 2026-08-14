# Release checklist

This checklist defines the `1.0.0-rc.1` release-candidate gate. It is deliberately reproducible without anything from `samples/`.

## Automated gate

1. Build the Docker image on `linux/amd64` and `linux/arm64`.
2. Run every Python test inside the built image.
3. Run `node tests/run_js_tests.js`.
4. Start the application on port 8666 and run `npm run test:browser`.
5. Run `python -m tools.benchmark_media --profile quick --output output/benchmark-quick.json` inside the application image.
6. Confirm `git diff --check` and that `samples/`, `output/` and working-session data are absent from the commit.

The generated-media matrix creates SSD, DSD, ADFS S/M/L, BeebSCSI DAT/DSC, MMB, UEF, HFE, raw banked ROM and ROMFS media. It writes and rereads known files on writable filesystems and checks all 511 MMB slots. Fault tests cover an interrupted upload, exact checkpoint rollback after a partial write, a full DFS image, and a corrupt catalogue. Operation tests cover cancellation, browser ownership and a simulated container restart. Browser tests cover refresh recovery, pane lifecycle, guarded changes, undo and a complete timestamped download.

## Performance record

The benchmark JSON records minimum, median and maximum duration for:

- listing all 511 MMB slots;
- listing a populated DFS catalogue;
- browsing a generated ADFS tree;
- bulk import into an ADFS hard disk;
- rebuilding an ADFS menu database;
- browsing and checkpointing BeebSCSI DAT/DSC;
- validating, documenting and building the complete BeebSCSI download ZIP.

Use `--profile full` before a tagged release. Keep the JSON as a CI or release artefact and compare medians with the previous candidate. A regression must be explained or fixed before tagging.

## Manual gate

- Open the light and dark themes at desktop and narrow widths. Check keyboard focus, labels, status announcements and 200 percent zoom.
- Create, modify, undo, save and reopen one image from each writable family.
- On real 8-bit hardware, validate one edited DFS disk, one ADFS floppy, one BeebSCSI pair and one MMB menu image from the release build.
- Confirm that long operations show phase, item count, elapsed time, throughput, ETA and Abort where the operation has a safe cancellation boundary.
- Confirm the saved ZIP contains the image, applicable partner or metadata files and its generated technical `README.md`.

## Tagging

Merge the single reviewed release-candidate pull request first. Tag the merge commit so the tag contains exactly what reached `main`:

```bash
git switch main
git pull --ff-only
git tag -a v1.0.0-rc.1 -m "Acorn File Forge 1.0.0 release candidate 1"
git push origin v1.0.0-rc.1
```

Do not tag the feature-branch head. GitHub may create a different merge commit, and a release tag must identify the tested commit users actually clone.
