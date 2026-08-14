from __future__ import annotations

import shutil
import subprocess
import re
from dataclasses import dataclass
from pathlib import Path

from .hardware_profiles import profile_addons


@dataclass(frozen=True)
class ManagedEmulator:
    identifier: str
    label: str
    executable: str
    debugger: str
    platforms: tuple[str, ...]

    @property
    def available(self) -> bool:
        return Path(self.executable).is_file() or shutil.which(self.executable) is not None


EMULATORS = {
    "elkulator-pi1mhz": ManagedEmulator(
        "elkulator-pi1mhz", "Elkulator with Pi1MHz/AP5 patches",
        "/opt/elkulator/elkulator", "elkulator-debug", ("electron",),
    ),
    "b-em": ManagedEmulator(
        "b-em", "B-em BBC Micro systems", "/opt/b-em/b-em", "b-em-debug",
        ("bbc-b", "bbc-b-plus", "master"),
    ),
    "mame": ManagedEmulator(
        "mame", "MAME Archimedes", "/usr/games/mame", "mame-debug",
        ("archimedes",),
    ),
}

MAME_MACHINES = {
    "bbc-b": "bbcb",
    "bbc-b-plus": "bbcbp",
    "master": "bbcm",
    "archimedes": "aa310",
}
MAME_ROM_PATH = "/opt/acorn-file-forge/firmware/mame"

BEM_TUBES = {
    "tube-6502": 6, "tube-z80": 2, "tube-80186": 3, "tube-arm": 1,
    "tube-65816": 4, "tube-32016": 5, "tube-6809": 7, "tube-pdp11": 9,
}
MAME_PODULES = {
    "arch-scsi": "scsi_aka31", "arch-ide": "ide_rdev",
    "arch-ethernet": "ether1", "arch-midi": "midi_aka16", "arch-tube": "tube",
}


def profile_machine(session) -> str:
    profile = getattr(session, "hardware_profile", {}) or {}
    machine = str(profile.get("machine") or "").strip().lower()
    aliases = {
        "electron": "electron", "acorn electron": "electron",
        "bbc micro": "bbc-b", "bbc micro model b": "bbc-b",
        "bbc/master": "master", "master 128": "master",
        "archimedes": "archimedes", "archimedes / risc os": "archimedes",
    }
    if machine in {"electron", "bbc-b", "bbc-b-plus", "master", "archimedes"}:
        return machine
    return aliases.get(machine, "electron" if getattr(session, "target_hardware", "") == "electron-plus3" else "bbc-b")


def configured_emulator(session) -> ManagedEmulator:
    profile = getattr(session, "hardware_profile", {}) or {}
    machine = profile_machine(session)
    selected = str(profile.get("emulator") or "auto").strip().lower()
    if selected == "auto" or selected not in EMULATORS:
        selected = "elkulator-pi1mhz" if machine == "electron" else "mame" if machine == "archimedes" else "b-em"
    emulator = EMULATORS[selected]
    if machine not in emulator.platforms:
        return EMULATORS["elkulator-pi1mhz" if machine == "electron" else "mame" if machine == "archimedes" else "b-em"]
    return emulator


def emulator_status(session) -> dict:
    emulator = configured_emulator(session)
    machine = profile_machine(session)
    available = emulator.available
    firmware_message = ""
    if available and emulator.identifier == "mame":
        driver = MAME_MACHINES.get(machine, "")
        podule_arguments = _mame_podule_arguments(profile_addons(session))
        try:
            check = subprocess.run(
                [emulator.executable, "-rompath", MAME_ROM_PATH, "-verifyroms", driver, *podule_arguments],
                capture_output=True, text=True, timeout=20, check=False,
            )
            available = check.returncode == 0 and "is good" in f"{check.stdout}\n{check.stderr}".lower()
        except (OSError, subprocess.TimeoutExpired):
            available = False
        if not available:
            firmware_message = f" Matching MAME firmware for {driver} is not installed; add the corresponding ROM set before running this profile."
    return {
        "id": emulator.identifier,
        "label": emulator.label,
        "available": available,
        "machine": machine,
        "debugger": emulator.debugger,
        "configuredBy": "managed workbench profile",
        "message": (
            f"{emulator.label} is installed and configured for {machine}."
            if available else
            f"{emulator.label} is selected for {machine}, but it cannot start yet."
            if emulator.available and firmware_message else
            f"{emulator.label} is selected for {machine}, but its executable is missing from this build."
        ) + firmware_message,
    }


def emulator_command(session, media_path: str | Path, *, debug: bool = False, interactive: bool = False) -> tuple[list[str], str]:
    emulator = configured_emulator(session)
    if not emulator.available:
        raise ValueError(f"{emulator.label} is not installed in this build.")
    profile = getattr(session, "hardware_profile", {}) or {}
    addons = profile_addons(session)
    media = Path(media_path)
    suffix = media.suffix.lower()
    boot = str(profile.get("emulatorBoot") or "auto")
    machine = profile_machine(session)
    if emulator.identifier == "elkulator-pi1mhz":
        if suffix not in {".ssd", ".dsd", ".adf", ".ads", ".adm", ".adl", ".uef"}:
            raise ValueError("Elkulator can launch DFS or ADFS floppy images and UEF tapes. This parent image cannot be mounted by Elkulator; run a self-contained BASIC file from a temporary test disk, or export a compatible floppy image first.")
        executable, cwd = _elkulator_variant(addons)
        arguments = _desktop_command(executable, debug=debug, interactive=interactive)
        ram_banks = [6, 7] if "electron-swram-32" in addons else [4, 5, 6, 7] if "electron-swram-64" in addons else []
        for bank in ram_banks:
            arguments += ["-ram", str(bank)]
        if "tube-6502" in addons:
            arguments += ["-tube6502", "/opt/b-em/roms/tube/6502Tube.rom"]
        if {"electron-rh-plus1", "electron-rh-plus2"} & addons:
            arguments += ["-rom", "12", "/opt/elkulator/roms/RHPLUS133.rom"]
        arguments += ["-tape" if suffix == ".uef" else "-disc", str(media)]
        if boot in {"auto", "boot"} and suffix != ".uef":
            arguments.append("-autoboot")
        if debug:
            arguments.append("-debug")
        return arguments, cwd
    if emulator.identifier == "b-em":
        if suffix not in {".ssd", ".dsd", ".adf", ".ads", ".adm", ".adl", ".img", ".uef", ".csw"}:
            raise ValueError("B-em can launch BBC DFS or ADFS floppy images and UEF/CSW tapes. This parent image cannot be mounted by B-em; run a self-contained BASIC file from a temporary test disk, or export compatible media first.")
        model = _bem_model(machine, addons)
        arguments = [*_desktop_command(emulator.executable, debug=debug, interactive=interactive), f"-m{model}"]
        tube = next((BEM_TUBES[item] for item in addons if item in BEM_TUBES), None)
        if tube is not None and model not in {11, 12, 14}:
            arguments.append(f"-t{tube}")
        arguments += ["-cfg", str(_bem_profile_config(session, addons))]
        arguments += ["-tape" if suffix in {".uef", ".csw"} else "-disc", str(media)]
        if boot in {"auto", "boot"} and suffix not in {".uef", ".csw"}:
            arguments.append("-autoboot")
        if debug:
            arguments.append("-debug")
        return arguments, "/opt/b-em"
    driver = MAME_MACHINES.get(machine)
    if not driver:
        raise ValueError(f"MAME has no managed machine mapping for {machine}.")
    status = emulator_status(session)
    if not status["available"]:
        raise ValueError(status["message"])
    media_option = "-cass" if suffix == ".uef" else "-hard1" if suffix in {".dat", ".hdf", ".hd4"} else "-flop1"
    if suffix in {".mmb", ".rom", ".bin"}:
        raise ValueError("This container format cannot be attached directly to the selected MAME machine. Open or export a bootable disk or hard-disk image first.")
    arguments = [
        emulator.executable, "-rompath", MAME_ROM_PATH, driver,
        *_mame_podule_arguments(addons),
        media_option, str(media), "-skip_gameinfo", "-sound", "none",
    ]
    if debug and not interactive:
        arguments = ["timeout", "--signal=TERM", "--kill-after=2", "15", *arguments, "-debug", "-debugger", "qt"]
    elif debug:
        arguments += ["-debug", "-debugger", "qt"]
    elif interactive:
        arguments += ["-video", "soft"]
    else:
        arguments += ["-video", "none", "-seconds_to_run", "8"]
    return arguments, "/app"


def _desktop_command(executable: str, *, debug: bool, interactive: bool) -> list[str]:
    """Run in the shared browser display or a bounded private X server."""
    environment = ["env", "ALSA_CONFIG_PATH=/app/alsa-null.conf", "ALSOFT_DRIVERS=null"]
    if interactive:
        return [
            "timeout", "--signal=TERM", "--kill-after=2", "900",
            *environment, "DISPLAY=:99", executable,
        ]
    duration = "15" if debug else "8"
    return [
        "timeout", "--signal=TERM", "--kill-after=2", duration,
        *environment,
        "xvfb-run", "-a", executable,
    ]


def _elkulator_variant(addons: set[str]) -> tuple[str, str]:
    plus1 = bool({"electron-plus1", "electron-ap1", "electron-rh-plus1", "electron-rh-plus2"} & addons)
    disk = "ap4" if "electron-ap4" in addons else "plus3" if {"electron-plus3", "electron-ap3"} & addons else "base"
    variant = f"plus1-{disk}" if plus1 and disk != "base" else "plus1" if plus1 else disk
    if "electron-mrb" in addons:
        variant += "-mrb"
    folder = f"/opt/elkulator/profiles/{variant}"
    return f"{folder}/elkulator", folder


def _bem_model(machine: str, addons: set[str]) -> int:
    if machine == "bbc-b-plus":
        return 9 if "bplus-128" in addons else 8
    if machine == "master":
        if "master-512" in addons:
            return 11
        if "master-turbo" in addons:
            return 12
        if "master-arm" in addons:
            return 14
        return 10
    disk = next((item for item in addons if (item.startswith("bbc-") and "1770" in item) or item == "bbc-8271"), "bbc-8271")
    if "bbc-integra-b" in addons:
        return 25 if disk == "bbc-acorn1770" else 26
    return {
        "bbc-8271": 4 if "bbc-swram" in addons else 3,
        "bbc-acorn1770": 5, "bbc-solidisk1770": 17,
        "bbc-opus1770": 18, "bbc-watford1770": 19,
    }.get(disk, 3)


def _bem_profile_config(session, addons: set[str]) -> Path:
    source = Path("/opt/b-em/b-em.cfg")
    config = source.read_text(encoding="utf-8")
    settings = {
        "scsienable": "true" if "beebscsi" in addons else "false",
        "ideenable": "true" if "ide" in addons else "false",
    }
    for key, value in settings.items():
        replacement = f"{key}={value}"
        pattern = rf"(?m)^{re.escape(key)}=.*$"
        config, count = re.subn(pattern, replacement, config, count=1)
        if not count:
            config += f"\n{replacement}"
    target = Path(session.path).parent / ".b-em-hardware-profile.cfg"
    target.write_text(config.rstrip() + "\n", encoding="utf-8")
    return target


def _mame_podule_arguments(addons: set[str]) -> list[str]:
    selected = [MAME_PODULES[item] for item in sorted(addons) if item in MAME_PODULES]
    arguments = []
    for slot, option in zip(("-podule0", "-podule2"), selected):
        arguments += [slot, option]
    return arguments
