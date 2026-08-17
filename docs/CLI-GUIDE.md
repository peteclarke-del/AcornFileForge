# Headless CLI and deterministic recipes

Acorn File Forge includes a supported command-line interface for repeatable
image work, build servers and collection maintenance. It calls the same disk,
menu, validation, manifest, comparison and guarded-patch services as the web
application. The CLI does not reproduce filesystem rules in a separate tool.

The entry point is:

```bash
python -m app.cli --help
```

The complete Docker image contains the Acorn filesystem and conversion tools
required by the commands. A source checkout without its Python and native
dependencies can display help, but it cannot open or safely dry-run real
images.

## Run it in Docker

Create a host directory for input and output files, then mount it at `/media`:

```bash
mkdir -p media
docker compose run --rm \
  -v "$PWD/media:/media" \
  acorn-file-forge \
  python -m app.cli validate /media/game.ssd
```

This one-off container uses the built application image and leaves the web
service alone. Files written below `/media` appear in the host `media`
directory. Use absolute container paths in recipes and commands.

## Output contract

Progress and human-readable phase messages go to standard error. Standard
output contains one JSON document with this stable envelope:

```json
{
  "format": "acorn-file-forge-cli-result",
  "version": 1,
  "command": "validate",
  "status": "ok",
  "exitCode": 0,
  "dryRun": false,
  "result": {}
}
```

The process exit codes are part of the version 1 interface:

| Code | Status | Meaning |
| ---: | --- | --- |
| 0 | `ok` or `planned` | The operation completed, or a dry-run completed without writing |
| 2 | `usage-error` | Command syntax or a required argument is wrong |
| 3 | `validation-failed` | The image, requested operation or target rule is invalid |
| 4 | `input-error` | A named source, descriptor or patch cannot be found |
| 5 | `identity-mismatch` | A recipe source no longer matches its recorded size or SHA-256 |
| 6 | `operation-failed` | A filesystem, conversion or host I/O operation failed |

Argument errors use the same JSON envelope on standard output and put the
short usage line on standard error. Scripts should test the numeric exit code
and may then inspect `status`, `result.error` and `result.errorType`.

## Commands

### Create an image

```bash
python -m app.cli create --format ssd --title WORK --output /media/work.ssd
```

`--format` accepts the same identifiers as the web creation service, including
`ssd`, `dsd`, ADFS floppy geometries, `mmb`, `beebscsi`, writable FileCore hard
disk choices, `rom`, `romfs` and supported HFE wrappers. Capacity is required
only for formats whose size is genuinely selectable. ROM commands can also
set bank size, total size, platform, layout and template.

### Finalise and save an existing image

```bash
python -m app.cli save /media/scsi0.dat \
  --descriptor /media/scsi0.dsc \
  --target-hardware beebscsi \
  --output /media/scsi0-ready.dat
```

Save runs the hardware finalisation path before copying bytes. A BeebSCSI DAT
output automatically receives a matching DSC with the same stem. HFE output is
re-encoded and verified when the source was opened as an editable HFE. Existing
outputs are rejected unless `--force` is explicit.

### Inspect and validate

```bash
python -m app.cli manifest /media/collection.mmb \
  --output /media/collection-manifest.json

python -m app.cli validate /media/collection.mmb --slot 42
```

The manifest contains filesystem records, Acorn metadata, hashes and recognised
menu data, plus the deterministic logical fingerprint used by recipes and
patches. MMB validation can address one slot. Omit `--slot` to validate the
container or normal image.

Build the same versioned compatibility report used by the browser from a JSON
array of proposed changes:

```bash
python -m app.cli preflight /media/work.ssd \
  --changes /media/proposed-changes.json \
  --source-kind adfs --target-kind dfs \
  --operation copy \
  --output /media/compatibility-report.json
```

Each proposed row can supply name, source, type, load, execute, access and
filetype. The report records per-item conversions and losses, blocking
findings, the target profile and `canProceed`. `import-file --dry-run` embeds
this same report under `result.compatibility`.

### Import one host file

```bash
python -m app.cli import-file /media/work.ssd /media/PROGRAM \
  --destination '$.PROGRAM' \
  --load 1900 --execute 1900 \
  --output /media/work-with-program.ssd
```

Use `--slot` for a disk inside an MMB and `--side` for a DSD side. Load and
execution addresses use the same hexadecimal notation accepted by the web
application. `--filetype` is for appropriate RISC OS targets and cannot be
combined with load or execution addresses where the filesystem model forbids
that combination. Filename, directory and metadata restrictions are enforced
by the destination filesystem service.

### Convert a UEF tape

```bash
python -m app.cli convert /media/program.uef \
  --format ssd --output /media/program.ssd
```

This command deliberately means UEF to SSD or DSD. It does not claim a generic
sector-image conversion. Tape reconstruction, filename conversion, load and
execution metadata, safe `!BOOT` generation and cassette-channel warnings are
the same as in the browser.

### Compact an image

```bash
python -m app.cli compact /media/work.ssd \
  --order name --output /media/work-compact.ssd
```

MMB disk compaction uses `--slot`. ROMFS is already rebuilt into storage order
after each edit and UEF is read-only, so those requests are rejected honestly.

### Create a menu

Install an MMB menu into an empty slot:

```bash
python -m app.cli menu-create /media/collection.mmb \
  --menu-type universal --slot 0 --page E00 \
  --output /media/collection-menu.mmb
```

Supported template identifiers are `universal`, `spi-game-menu`,
`electron-magazine` and `acorn-user`. An occupied slot is never overwritten.

For ADFS, provide reviewed menu records as a JSON array and the directory that
will own the menu files:

```bash
python -m app.cli menu-create /media/games.dat \
  --descriptor /media/games.dsc \
  --root '$.Games' --entries /media/menu-records.json \
  --output /media/games-menu.dat
```

The records use the same title, publisher, filename, action, PAGE and path
fields as the bulk menu editor. Menu creation does not perform unbounded online
metadata lookup in a headless build.

### Compare images and create patches

```bash
python -m app.cli compare /media/before.ssd /media/after.ssd \
  --output /media/comparison.json

python -m app.cli patch-create /media/before.ssd /media/after.ssd \
  --output /media/change.affpatch.zip

python -m app.cli patch-apply /media/before.ssd /media/change.affpatch.zip \
  --output /media/patched.ssd
```

Comparison uses logical records and exact fingerprints. Patch creation includes
only required payloads. Patch application verifies the base fingerprint,
layout, canonical operation plan and every payload before writing, then checks
the complete candidate fingerprint. Paired candidates use `--descriptor` for
the base and `--candidate-descriptor` for the candidate.

## Dry-run

Add `--dry-run` to every mutating command. No output image or patch is created.
The returned `status` is `planned`, `dryRun` is true and `result` contains the
resolved source identity, decisions and intended output where applicable.
Dry-run opens a private disposable copy and performs the real requested
mutation there, then discards it instead of writing the chosen output. This
catches capacity, catalogue and format errors that a descriptive plan alone
would miss. Patch application performs the complete guarded preflight,
including payload hashes, without applying it.

## Versioned recipes

`create`, `save`, `import-file`, `convert`, `compact` and `menu-create` accept
`--recipe-out`. After a successful operation, the file records:

- recipe format and version;
- exact physical size and SHA-256 for every input;
- the image's logical fingerprint where an image was opened;
- every non-secret action decision;
- the target-hardware and raw-ROM interpretation choices used to open inputs;
- the chosen output and hashes of generated files.

Run the recipe by mapping each source alias to a current path:

```bash
python -m app.cli recipe-run /media/import.affrecipe.json \
  --source image=/media/original.ssd \
  --source payload=/media/PROGRAM \
  --output /media/rebuilt.ssd
```

The rebuild stops with exit code 5 if an input's bytes have changed. The open
image's logical fingerprint is checked as a second guard. Paths are supplied at
run time so a recipe can move between computers without weakening its identity
checks. Secrets, browser session identifiers and private working paths are not
stored as execution authority.

After the rebuild, every generated primary and companion file is checked
against the size and SHA-256 recorded by the completed workflow. A mismatched
result also returns exit code 5 instead of being reported as a successful
deterministic rebuild.

Version 1 recipes execute create, import-file, compact, menu-create,
UEF-convert, guarded patch application and final save decisions. A recipe produced by a newer application
version is rejected until its schema is supported rather than guessed.

### Export a completed GUI workflow

Open **Workbench → Portable project**, choose an open image and select
**Export workflow bundle**. The downloaded `.affrecipe.zip` contains:

- `workflow.affrecipe.json`, the versioned recipe and every expected output
  hash;
- `changes.affpatch.zip`, the guarded logical changes from the earliest
  retained pre-change checkpoint to the current image;
- `README.md`, the exact base and optional DSC identities plus a ready-to-edit
  replay command.

The original image is deliberately not copied into the bundle. Extract it and
map `image` to the recorded base and `changes` to the bundled patch:

```bash
python -m app.cli recipe-run workflow.affrecipe.json \
  --source image=/media/original.ssd \
  --source changes=changes.affpatch.zip \
  --output rebuilt.ssd
```

For BeebSCSI, also map the companion with
`--descriptor image=/media/original.dsc`. Replay verifies both physical input
hashes, the base logical fingerprint, the patch payloads and the final output
hashes. The recipe retains the chosen hardware profile, target validation and
accepted compatibility reports as descriptive decisions, but never browser
ownership tokens or private server paths.

An edited legacy session with no retained pre-change checkpoint is rejected
rather than exported as a false reconstruction. Save it, create a named
checkpoint and use that as the base for subsequent recorded changes. UEF and
HFE workflow export remains unavailable until the container-level rebuild can
be proved lossless.

## Safety notes

- Inputs are copied into an isolated temporary work directory. The source file
  is never edited in place.
- Mutating commands require a separate output and reject existing files unless
  `--force` is given.
- DAT and DSC are treated as one hardware image. Keep both files together.
- The CLI does not bypass read-only UEF, protected HFE, composite ROMFS or
  incomplete geometry rules.
- Keep the JSON result with automated build logs. It records the exact failure
  category even when the filesystem utility writes additional diagnostics to
  standard error.
