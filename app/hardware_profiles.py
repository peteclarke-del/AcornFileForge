from __future__ import annotations

from copy import deepcopy


def _addon(identifier, label, group, machines, description, *, emulator="profile", requires=(), conflicts=()):
    return {
        "id": identifier, "label": label, "group": group,
        "machines": list(machines), "description": description,
        "emulator": emulator, "requires": list(requires), "conflicts": list(conflicts),
    }


ADDONS = [
    _addon("electron-plus1", "Acorn Plus 1", "expansion", ["electron"], "Two cartridge sockets, analogue input and printer port.", emulator="elkulator", conflicts=["electron-ap1"]),
    _addon("electron-ap1", "PRES Advanced Plus 1", "expansion", ["electron"], "Plus 1 compatible cartridge, printer and analogue expansion.", emulator="elkulator", conflicts=["electron-plus1"]),
    _addon("electron-rh-plus1", "RH Plus 1", "expansion", ["electron"], "Retro Hardware Plus 1 expansion using the RH Plus 1.33 support ROM.", emulator="elkulator"),
    _addon("electron-rh-plus2", "RH Plus 2", "expansion", ["electron"], "Retro Hardware Plus 2 expansion; uses the same RH Plus 1.33 support ROM and may be fitted with RH Plus 1.", emulator="elkulator"),
    _addon("electron-ap2-rom", "PRES AP2 ROM", "firmware", ["electron"], "ADFS utility ROM for expanded Electron systems."),
    _addon("electron-plus3", "Acorn Plus 3 ADFS", "disk", ["electron"], "WD1770 floppy interface and ADFS drive.", emulator="elkulator"),
    _addon("electron-ap3", "PRES Advanced Plus 3 ADFS", "disk", ["electron"], "PRES ADFS-compatible floppy interface.", emulator="elkulator"),
    _addon("electron-ap4", "PRES Advanced Plus 4 DFS/ADFS", "disk", ["electron"], "BBC-compatible DFS plus ADFS floppy interface.", emulator="elkulator"),
    _addon("electron-ap5", "PRES Advanced Plus 5", "bus", ["electron"], "Tube, 1 MHz bus and user-port interface; requires a Plus 1 style carrier.", requires=["electron-plus1|electron-ap1|electron-rh-plus1|electron-rh-plus2"]),
    _addon("electron-swram-32", "32 KiB sideways RAM", "sideways-ram", ["electron"], "Two writable sideways banks.", emulator="elkulator"),
    _addon("electron-swram-64", "64 KiB sideways RAM", "sideways-ram", ["electron"], "Four writable sideways banks.", emulator="elkulator"),
    _addon("electron-swram-256", "256 KiB sideways RAM", "sideways-ram", ["electron"], "Banked quarter-megabyte sideways RAM; recorded for compatibility checks."),
    _addon("electron-mrb", "Slogger Master RAM Board", "main-memory", ["electron"], "64 KiB shadow/main-memory expansion.", emulator="elkulator"),
    _addon("bbc-8271", "Intel 8271 DFS", "disk", ["bbc-b"], "Original BBC Micro DFS controller.", emulator="b-em"),
    _addon("bbc-acorn1770", "Acorn 1770 DFS", "disk", ["bbc-b"], "Acorn double-density 1770 controller.", emulator="b-em"),
    _addon("bbc-solidisk1770", "Solidisk 1770 DFS", "disk", ["bbc-b"], "Solidisk 1770 controller and DFS.", emulator="b-em"),
    _addon("bbc-opus1770", "Opus 1770 DFS", "disk", ["bbc-b"], "Opus 1770 controller and DDOS.", emulator="b-em"),
    _addon("bbc-watford1770", "Watford 1770 DFS", "disk", ["bbc-b"], "Watford Electronics 1770 controller.", emulator="b-em"),
    _addon("bbc-swram", "Sideways RAM", "sideways-ram", ["bbc-b"], "Writable sideways ROM banks.", emulator="b-em"),
    _addon("bbc-integra-b", "Integra-B", "memory-system", ["bbc-b"], "Shadow RAM, sideways RAM and real-time clock.", emulator="b-em"),
    _addon("bplus-1770", "Built-in 1770 DFS", "disk", ["bbc-b-plus"], "The standard WD1770 disk interface used by disk-equipped BBC B+ systems.", emulator="b-em"),
    _addon("bplus-128", "128 KiB upgrade", "main-memory", ["bbc-b-plus"], "BBC B+ 128 KiB configuration.", emulator="b-em"),
    _addon("mmfs", "MMFS / SD interface", "storage", ["electron", "bbc-b", "bbc-b-plus", "master"], "MMFS-capable mass-storage interface."),
    _addon("beebscsi", "BeebSCSI", "storage", ["electron", "bbc-b", "bbc-b-plus", "master"], "SCSI hard-drive emulation; Electron use requires the AP5 1 MHz bus.", requires=["electron:electron-ap5"]),
    _addon("ide", "IDE interface", "storage", ["bbc-b", "bbc-b-plus", "master"], "IDE hard-drive interface.", emulator="b-em"),
    _addon("tube-6502", "6502 second processor", "tube", ["electron", "bbc-b", "bbc-b-plus", "master"], "External 6502 Tube processor.", emulator="managed", requires=["electron:electron-ap5"]),
    _addon("tube-z80", "Z80 second processor", "tube", ["bbc-b", "bbc-b-plus", "master"], "Acorn Z80 Tube processor.", emulator="b-em"),
    _addon("tube-80186", "80186 second processor", "tube", ["bbc-b", "bbc-b-plus", "master"], "Master 512 compatible 80186 processor.", emulator="b-em"),
    _addon("tube-arm", "ARM evaluation system", "tube", ["bbc-b", "bbc-b-plus", "master"], "ARM evaluation Tube processor.", emulator="b-em"),
    _addon("tube-65816", "65816 second processor", "tube", ["bbc-b", "bbc-b-plus", "master"], "ReCo 65816 Tube processor.", emulator="b-em"),
    _addon("tube-32016", "32016 second processor", "tube", ["bbc-b", "bbc-b-plus", "master"], "National Semiconductor 32016 Tube processor.", emulator="b-em"),
    _addon("tube-6809", "6809 second processor", "tube", ["bbc-b", "bbc-b-plus", "master"], "6809 Tube processor.", emulator="b-em"),
    _addon("tube-pdp11", "PDP-11 second processor", "tube", ["bbc-b", "bbc-b-plus", "master"], "PDP-11 Tube processor.", emulator="b-em"),
    _addon(
        "tube-pitube-direct", "PiTubeDirect", "tube",
        ["electron", "bbc-b", "bbc-b-plus", "master"],
        "Raspberry Pi Tube co-processor host. The Electron requires an AP5 Tube interface.",
        requires=["electron:electron-ap5"],
    ),
    _addon("master-turbo", "Master Turbo internal 65C102", "tube", ["master"], "Internal 4 MHz 65C102 configuration.", emulator="b-em"),
    _addon("master-512", "Master 512", "tube", ["master"], "Internal 80186 co-processor configuration.", emulator="b-em"),
    _addon("master-arm", "Master ARM evaluation system", "tube", ["master"], "Internal ARM evaluation processor configuration.", emulator="b-em"),
    _addon("arch-scsi", "Acorn AKA31 SCSI podule", "podule", ["archimedes"], "SCSI expansion podule.", emulator="mame"),
    _addon("arch-ide", "RISC Developments IDE podule", "podule", ["archimedes"], "IDE hard-disc podule.", emulator="mame"),
    _addon("arch-ethernet", "Acorn Ethernet podule", "podule", ["archimedes"], "Ethernet expansion podule.", emulator="mame"),
    _addon("arch-midi", "Acorn MIDI podule", "podule", ["archimedes"], "MIDI expansion podule.", emulator="mame"),
    _addon("arch-tube", "Acorn Tube podule", "podule", ["archimedes"], "BBC Tube interface podule.", emulator="mame"),
]

GROUPS = {
    "expansion": {"label": "Expansion chassis", "max": 4},
    "firmware": {"label": "Firmware and utilities", "max": 8},
    "disk": {"label": "Floppy interface", "max": 1},
    "bus": {"label": "Bus and user-port expansion", "max": 1},
    "sideways-ram": {"label": "Sideways RAM", "max": 1},
    "main-memory": {"label": "Main memory", "max": 1},
    "memory-system": {"label": "Memory system", "max": 1},
    "storage": {"label": "Mass storage", "max": 4},
    "tube": {"label": "Tube or co-processor", "max": 1},
    "podule": {"label": "Archimedes podules", "max": 2},
}

MACHINES = [
    {"id": "electron", "label": "Acorn Electron", "baseRam": "32K", "processor": "6502A"},
    {"id": "bbc-b", "label": "BBC Micro Model B", "baseRam": "32K", "processor": "6502A"},
    {"id": "bbc-b-plus", "label": "BBC Micro Model B+ 64K", "baseRam": "64K", "processor": "6502A"},
    {"id": "master", "label": "BBC Master 128", "baseRam": "128K", "processor": "65C12"},
    {"id": "archimedes", "label": "Acorn Archimedes A310", "baseRam": "1M", "processor": "ARM2"},
]


def hardware_catalogue() -> dict:
    return {"machines": deepcopy(MACHINES), "groups": deepcopy(GROUPS), "addons": deepcopy(ADDONS)}


def normalise_hardware_profile(data: dict) -> dict:
    machine = str(data.get("machine") or "bbc-b").strip().lower()
    machine_ids = {row["id"] for row in MACHINES}
    if machine not in machine_ids:
        raise ValueError("Choose a supported base machine.")
    known = {row["id"]: row for row in ADDONS}
    addons = []
    for value in data.get("addons", []):
        identifier = str(value).strip().lower()
        if identifier and identifier not in addons:
            addons.append(identifier)
    invalid = [identifier for identifier in addons if identifier not in known or machine not in known[identifier]["machines"]]
    if invalid:
        raise ValueError(f"{', '.join(invalid)} cannot be fitted to {machine}.")
    for group, definition in GROUPS.items():
        selected = [identifier for identifier in addons if known[identifier]["group"] == group]
        if len(selected) > definition["max"]:
            raise ValueError(f"Choose no more than {definition['max']} option(s) from {definition['label']}.")
    selected = set(addons)
    for identifier in addons:
        conflicts = selected.intersection(known[identifier].get("conflicts", []))
        if conflicts:
            labels = ", ".join(known[conflict]["label"] for conflict in sorted(conflicts))
            raise ValueError(f"{known[identifier]['label']} cannot be fitted with {labels}.")
        for requirement in known[identifier]["requires"]:
            scoped_machine, _, expression = requirement.partition(":")
            if expression and scoped_machine != machine:
                continue
            choices = (expression or scoped_machine).split("|")
            if not any(choice in selected for choice in choices):
                labels = " or ".join(known[choice]["label"] for choice in choices)
                raise ValueError(f"{known[identifier]['label']} requires {labels}.")
    profile = dict(data)
    profile["machine"] = machine
    profile["addons"] = addons
    profile["tube"] = any(known[item]["group"] == "tube" for item in addons)
    return profile


def profile_addons(session) -> set[str]:
    profile = getattr(session, "hardware_profile", {}) or {}
    addons = {str(value) for value in profile.get("addons", []) if isinstance(value, str)}
    if profile.get("tube") and not any(value.startswith("tube-") or value.startswith("master-") for value in addons):
        addons.add("tube-6502")
    return addons
