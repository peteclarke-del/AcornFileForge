# Emulator firmware

This directory contains the small, fixed firmware set needed by Acorn File
Forge's managed emulator profiles. Firmware is kept separate from application
source because it has different provenance, licensing and update rules.

The application does not search the host for firmware at runtime. The
Dockerfile copies or reconstructs these files into explicit read-only runtime
locations, and compatible Run or Debug actions verify them before launch.

Return to the [documentation index](../docs/README.md) for installation,
media-format, editor, ROM and release references.

## Included files

| Repository file | Runtime purpose | Runtime location |
| --- | --- | --- |
| `mame/aa310.zip` | MAME Archimedes A310 machine ROM set | `/opt/acorn-file-forge/firmware/mame/aa310.zip` |
| `mame/archimedes_keyboard.zip` | Shared Archimedes keyboard controller device | `/opt/acorn-file-forge/firmware/mame/archimedes_keyboard.zip` |
| `elkulator/RHPLUS133.rom.gz.b64` | Compressed and Base64-wrapped RH Plus 1.33 support ROM | reconstructed as `/opt/elkulator/roms/RHPLUS133.rom` |

Do not unpack, rename or casually replace the MAME ZIP members. MAME ROM sets
are version-sensitive and the installed MAME release expects exact names,
sizes and checksums.

## MAME Archimedes A310

`aa310.zip` provides the A310 machine set. `archimedes_keyboard.zip` provides
its shared keyboard controller device. The container passes their directory to
MAME as an explicit ROM search path rather than installing files into a host
MAME collection.

The set was audited with the MAME version installed by the Docker image:

```text
romset aa310 is good
1 romsets found, 1 were OK.
```

Acorn File Forge repeats the relevant audit before enabling an Archimedes Run
or Debug action. A failed audit is reported as a configuration problem rather
than allowing MAME to start with missing or mismatched firmware.

Source SHA-256 values for the repository files are:

```text
518bc51045f47127a73348e747682e9b5cb0f6766764fff89da978617b502a74  aa310.zip
1d02b14cd4d2ff80a343c3afb1ba43de0bd77815952816fc19d0736f8644664e  archimedes_keyboard.zip
```

Verify them from the repository root:

```bash
sha256sum firmware/mame/aa310.zip firmware/mame/archimedes_keyboard.zip
```

A future MAME package may require a matching revision of one or both sets. An
update must change the files, recorded checksums, runtime audit and tested MAME
version together.

## Elkulator RH Plus 1.33

`elkulator/RHPLUS133.rom.gz.b64` is the exact 16 KiB support ROM used by the
tested Electron configuration in the adjacent 1MHzWifi project. It supports the
RH Plus 1 and RH Plus 2 selections exposed by the hardware Workbench.

During the image build, the Dockerfile:

1. decodes the Base64 text;
2. decompresses the gzip stream;
3. writes `/opt/elkulator/roms/RHPLUS133.rom`;
4. checks SHA-256
   `cda520a110b160af2c750b2d28c84353ad2c3ede15b4821cf96452ee4dc3b5f8`;
5. removes the temporary encoded file.

Elkulator loads the verified ROM in sideways bank C when RH Plus 1 or RH Plus 2
is selected. The Workbench also applies the associated hardware profile, so
placing the ROM in the container alone does not claim that every Electron
configuration has RH Plus hardware.

To inspect the packaged source without writing a decoded ROM into the
repository:

```bash
base64 -d firmware/elkulator/RHPLUS133.rom.gz.b64 | gzip -dc | sha256sum
```

The result must match the decoded checksum above.

## Licensing and redistribution

These firmware files are not Acorn File Forge source code. Possession of the
repository does not grant additional rights to firmware or software contained
in media images.

Before publishing a derived source archive or container:

- confirm the right to use and redistribute every firmware file;
- retain any notices required by its copyright holder;
- do not replace a known set with material copied from an unrelated collection;
- do not add personal firmware directories, emulator configurations or ROM
  collections to the repository;
- record the source, exact version and checksum for any approved replacement.

## Updating firmware safely

Treat a firmware update as a runtime dependency change:

1. Identify the emulator version and exact machine or expansion being updated.
2. Obtain the smallest complete set from an authorised source.
3. Record provenance and redistribution terms outside the binary where the
   project maintainers can review them.
4. Compute SHA-256 before modifying build files.
5. Update the Dockerfile verification and this document in the same commit.
6. Build on `linux/amd64`, `linux/arm64` and `linux/arm/v7`.
7. Run the emulator audit inside the final image.
8. Launch representative media through the application Workbench and noVNC.
9. Check that an intentionally damaged or missing file produces a clear,
   user-visible error.

Do not weaken a checksum check to make a replacement build. A checksum mismatch
means the file or the expected value needs an explicit review.

## Troubleshooting

### Archimedes Run or Debug remains disabled

Confirm that the pane has an Archimedes-compatible hardware profile, the image
format can be mounted by MAME and both MAME ZIP files passed the runtime audit.
The application log contains the audit result.

### MAME reports missing ROMs

Check the MAME version in the container and run its ROM audit against
`/opt/acorn-file-forge/firmware/mame`. Do not unzip the sets. If the installed
MAME version changed, compare its required set with the recorded one before
updating anything.

### RH Plus is selected but the support ROM is not loaded

Check the selected base machine and expansion chassis in the Workbench, then
inspect the emulator launch log for the bank-C load message. Verify the decoded
checksum inside the image. RH Plus options are machine-dependent and are not
offered for incompatible base systems.

### Emulator launches but no display appears

Firmware validation and display transport are separate. Check the service log,
the noVNC process and published port `8668` as described in the
[installation guide](../docs/INSTALLATION.md).
