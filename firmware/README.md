# Emulator firmware

This directory contains the minimum local firmware set required by the managed
Archimedes emulator profile.

## MAME Archimedes A310

`mame/aa310.zip` is the main A310 machine set. `mame/archimedes_keyboard.zip`
is its shared keyboard controller device. Both archives are passed to MAME via
an explicit, read-only ROM search path inside the application image.

The set was audited with the MAME version installed by the Docker image:

```text
romset aa310 is good
1 romsets found, 1 were OK.
```

Acorn File Forge repeats that audit at runtime before enabling an Archimedes
Run or Debug action. Do not unpack, rename or modify files within these ZIP
archives. A different MAME release may require a matching revision of the set.

Source SHA-256 values used for this build:

```text
518bc51045f47127a73348e747682e9b5cb0f6766764fff89da978617b502a74  aa310.zip
1d02b14cd4d2ff80a343c3afb1ba43de0bd77815952816fc19d0736f8644664e  archimedes_keyboard.zip
```

These firmware files are not application source code. Check your right to use
and redistribute the firmware before publishing a derived container or source
archive.

## Elkulator RH Plus

`elkulator/RHPLUS133.rom.gz.b64` is the exact 16 KiB RH Plus 1.33 support ROM
from the tested Electron configuration in the adjacent 1MHzWifi project. The
Docker build reconstructs it, verifies SHA-256
`cda520a110b160af2c750b2d28c84353ad2c3ede15b4821cf96452ee4dc3b5f8`, and
loads it in Elkulator bank C when RH Plus 1 or RH Plus 2 is selected.
