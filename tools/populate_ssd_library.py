#!/usr/bin/env python3
"""Atomically populate an existing Universal Menu MMB from a catalogued SSD tree.

This is deliberately a maintenance command rather than an HTTP shortcut. It
writes a complete temporary MMB, validates it, keeps a pre-import backup, and
only then replaces the browser session's working image.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.disk_service import DiskError, DiskService
from app.dfs_compat import infer_dfs_launch_page
from app.menu_service import find_menu_slot, installed_mmb_menu, replace_mmb_menu


def games(*titles: str, filename: str = "!BOOT", action: str = "E", page: str = "E00") -> list[dict]:
    return [
        {"title": title, "filename": filename, "action": action, "page": page}
        for title in titles
    ]


# Hand-checked compilation and unusually packaged disks. An empty list means a
# continuation/second-side disk which must occupy a slot but not gain its own
# menu record.
OVERRIDES: dict[int, list[dict]] = {
    5: games("Holed Out"),
    7: games("Dungeon Adventure"),
    31: games("Nightworld", "Guardian", "Blagger", "Shuffle"),
    32: games("Bug Blaster", "Lunar Rescue", "Hell Hole", "Crown Jewels"),
    34: games("Diamond Pete", "Q-Bix", "Tarzan Boy"),
    36: games("Cops"),
    37: games(
        "Day At The Races", "Fishing", "Golf", "Grand Prix", "Howzat",
        "Indoor Soccer", "Karate Warrior", "Microball", "Parachute", "Soccer Boss",
    ),
    51: games("The Golden Figurine", filename="HAVENGF", action="", page="1900"),
    56: games("Thunderstruck 2", "Omega Orb", "Psycastria 2", "Sphere Of Destiny 2"),
    57: games(
        "Bug Eyes II", "Caveman Capers", "Bug Eyes", "Ultron", "Wongo",
        "Space Ranger", "Wizzy's Mansion", page="1D00",
    ),
    58: [],
    59: games(
        "Psycastria", "The Last Of The Free", "Thunderstruck", "Drain Mania",
        "Stix", "Froot Raid", "Saracoid", page="1D00",
    ),
    60: [],
    87: games(
        "Castle Frankenstein", "Quest For The Holy Grail",
        "The Kingdom Of Klein", "Wheel Of Fortune", page="1D00",
    ),
    102: games(
        "Moon Buggy", "Fighter Pilot", "Loony Loco", "Battlezone Six", "Snake",
        "Caveman", "Munchman", "Maniac Mower", "Reversi", "Pinball Arcade",
    ),
    103: games("Ring Of Time", "The Ferryman Awaits", "Dracula Island", "Revenge Of Zor"),
    105: games(
        "Hex", "The Nine Dancers", "The Puppet Man", "The Prophecy",
        "Return Of The Warrior", "Wychwood", page="1D00",
    ),
    113: games("Icarus"),
    114: [],
    120: games("The Way Of The Exploding Fist", page="1D00"),
    122: games("Felix And The Fruit Monsters", page="1D00"),
    123: games(
        "Bandits At 3 O'Clock", "Bumble Bee", "Croaker", "Felix In The Factory",
        "Jet Power Jack", "Killer Gorilla", "Stock Car", "Electron Invaders",
        filename="MENU", action="R", page="2100",
    ),
    124: games(
        "Cybertron Mission", "Escape From Moonbase Alpha", "Felix And The Fruit Monsters",
        "Frenzy", "Moon Raider", "Rubble Trouble", "Swag", "The Mine",
        filename="MENU", action="R", page="1D00",
    ),
    125: games(
        "Adventure", "Chess", "Danger UXB", "Felix Meets The Evil Weevils",
        "Galactic Commander", "Ghouls", "Positron", "Swoop",
        filename="MENU", action="R", page="1D00",
    ),
    158: [],
    167: games("Imogen"),
    168: games("Elixir", filename="HAVENEL", action="", page="1D00"),
    170: games("The Life Of Repton", page="1900"),
    171: games("Master Break"),
    172: [],
    175: games("Citadel", "Ravenskull", "Stryker's Run", "Thrust", page="1D00"),
    176: games("Cyborg Warriors", "Last Ninja 2", "Network", "Ricochet"),
    177: [],
    178: games("Codename: Droid", "Crazee Rider", "Repton 3", "Galaforce"),
    179: games("Commando", "Killer Gorilla", "Killer Gorilla 2", "Palace Of Magic"),
    180: games("Cosmic Camouflage", "Frak!", "Guardian", "Spellbinder"),
    181: games("Galaforce 2", "Hopper", "Hunchback", "Video's Revenge"),
    182: games("Around The World", "Mr. Wiz", "Quest", "Winter Olympiad"),
    183: [],
    184: games("Camelot", "Spycat", "Steve Davis Snooker", "The Life Of Repton"),
    185: games(
        "Zalaga", "Alien Dropout", "Centipede", "Fruit Machine", "Invaders",
        "Percy Penguin", "World Geography", "Stryker's Run",
        filename="MENU", action="R", page="2100",
    ),
    186: games("Repton Infinity"),
    187: [],
    195: games("Uggie's Garden", filename="!Boot", action="", page="1900"),
    196: games("The Times Crossword Program: Jubilee Puzzles", page="1900"),
    197: [],
    199: games("Avon", page="1900"),
    200: games("Hezarin", page="1900"),
    201: [],
    207: games("Spy Snatcher", page="1900"),
    210: games("Buffalo Bill's Wild West Rodeo Show"),
    212: games("Commonwealth Games", filename="LOADER", action="", page="1900"),
    213: games("Alphatron", "Rig Attack", "Vindaloo", "Wet Zone", page="1D00"),
    214: games("Kastle", "US Drag Racing", "Goal", "Space Caverns"),
    221: games("Summer Olympiad", filename="LOADER", action="", page="1900"),
}


def boot_page(row: dict) -> str:
    match = re.search(r"\bPA(?:GE|\.)?\s*=\s*&([0-9A-F]+)", row.get("boot", ""), re.I)
    return match.group(1).upper() if match else "E00"


def clean_title(title: str) -> str:
    return re.sub(
        r"\s*\([^()]*(?:soft|dimension|tynesoft|topologika)[^()]*\)\s*$",
        "",
        title,
        flags=re.I,
    ).strip()


def records_for(row: dict) -> list[dict]:
    slot = int(row["slot"])
    records = OVERRIDES.get(slot)
    if records is None:
        source = row.get("gamesSource")
        if source == "SSDMENU":
            inferred_page, _evidence = infer_dfs_launch_page(
                Path(row["source"]).read_bytes(),
                "SSDMENU",
                "",
            )
            records = games(
                *(clean_title(game["title"]) for game in row["games"]),
                filename="SSDMENU", action="", page=inferred_page or "1900",
            )
        elif source == "HAVEN":
            records = games(
                *(clean_title(game["title"]) for game in row["games"]),
                filename="!BOOT", action="E", page=boot_page(row),
            )
        else:
            raise DiskError(f'No verified menu metadata for slot {slot} · {row["sourceName"]}')
    return [
        {
            **record,
            "publisher": row["publisher"],
            "diskTitle": row["diskTitle"][:12],
            "system": "M",
        }
        for record in records
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--catalogue", type=Path, required=True)
    parser.add_argument("--start-slot", type=int, default=20)
    args = parser.parse_args()

    catalogue = json.loads(args.catalogue.read_text(encoding="utf-8"))
    by_slot = {int(row["slot"]): row for row in catalogue}
    service = DiskService(args.work_dir)
    session = service._restore_session(args.session)
    detected_slot, detected_type = installed_mmb_menu(service, session)
    session.menu_slot = detected_slot
    session.menu_type = detected_type
    if find_menu_slot(service, session) is None or detected_type not in {"universal", "universal-4r"}:
        raise DiskError("The target session does not contain an editable Universal Menu.")

    with tempfile.NamedTemporaryFile(dir=session.path.parent, suffix=".mmb", delete=False) as handle:
        temporary_path = Path(handle.name)
    temporary_path.unlink()
    shutil.copy2(session.path, temporary_path)
    working = replace(
        session,
        path=temporary_path,
        slot_cache={},
        slot_source_names=dict(session.slot_source_names),
        menu_entries=None,
    )
    try:
        added = 0
        for slot in range(args.start_slot, max(by_slot) + 1):
            row = by_slot[slot]
            source = Path(row["source"])
            if not source.is_file():
                raise DiskError(f"Missing catalogued image {source}")
            service._write_slot(
                working,
                slot,
                source.read_bytes(),
                title=row["diskTitle"],
            )
            working.slot_source_names[slot] = f'{row["publisher"]}/{row["sourceName"]}'
            added += 1

        records = [
            {
                "title": "Chuckulus",
                "publisher": "Robico",
                "diskTitle": "Chuckulus",
                "filename": "!BOOT",
                "action": "E",
                "page": "E00",
                "system": "M",
            }
        ]
        for slot in sorted(by_slot):
            records.extend(records_for(by_slot[slot]))
        result = replace_mmb_menu(service, working, records, append=False)
        # An MMB is a slot container, so oaknut validates its contained DFS
        # images rather than the outer file as a standalone filesystem. The
        # rebuilt menu slot is the only generated DFS image; the other slots
        # are byte-identical to the already catalogued SSD sources.
        service.validate(working, int(working.menu_slot))
        formatted = sum(1 for item in service.list_slots(working) if item.get("formatted"))
        if formatted < len(by_slot) + 2:  # menu + Chuckulus + publisher disks
            raise DiskError(
                f"The temporary MMB exposes only {formatted} formatted slots after import."
            )

        backup = session.path.with_name(f"{session.path.stem}.before-ssd-library.mmb")
        if not backup.exists():
            shutil.copy2(session.path, backup)
        temporary_path.replace(session.path)
        session.slot_source_names = working.slot_source_names
        session.menu_entries = working.menu_entries
        session.dirty = True
        service._persist_session(session)
        print(json.dumps({
            "session": session.id,
            "insertedDisks": added,
            "firstInsertedSlot": args.start_slot,
            "lastInsertedSlot": max(by_slot),
            "menuEntries": result["entries"],
            "backup": str(backup),
            "validation": "passed",
        }, indent=2))
    finally:
        temporary_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
