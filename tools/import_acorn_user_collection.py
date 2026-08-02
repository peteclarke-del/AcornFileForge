#!/usr/bin/env python3
"""Install the complete Acorn User source collection into an existing MMB session.

The requested collection begins at slot 400. An MMB ends at slot 510, so the
remaining issues wrap into the explicitly supplied overflow range. The source
header entries are copied with each SSD payload to preserve titles and access.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from app.disk_service import (
    MMB_ENTRY_SIZE,
    MMB_HEADER_SIZE,
    MMB_SLOT_SIZE,
    DiskError,
    DiskService,
    ImageSession,
    SESSION_OWNER,
)


def slot_bytes(path: Path, slot: int) -> tuple[bytes, bytes]:
    with path.open("rb") as image:
        image.seek(16 + slot * MMB_ENTRY_SIZE)
        header = image.read(MMB_ENTRY_SIZE)
        image.seek(MMB_HEADER_SIZE + slot * MMB_SLOT_SIZE)
        payload = image.read(MMB_SLOT_SIZE)
    if len(header) != MMB_ENTRY_SIZE or len(payload) != MMB_SLOT_SIZE:
        raise DiskError(f"Source MMB slot {slot} is truncated.")
    return header, payload


def write_slot(path: Path, slot: int, header: bytes, payload: bytes) -> None:
    with path.open("r+b") as image:
        image.seek(16 + slot * MMB_ENTRY_SIZE)
        image.write(header)
        image.seek(MMB_HEADER_SIZE + slot * MMB_SLOT_SIZE)
        image.write(payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", default="/app/work")
    parser.add_argument("--owner", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--source", required=True, type=Path)
    args = parser.parse_args()

    owner_token = SESSION_OWNER.set(args.owner)
    service = DiskService(args.work_dir)
    target = service.get(args.target)
    source = ImageSession("f" * 32, args.source.name, "mmb", args.source)
    try:
        source_slots = service.list_slots(source)
        target_slots = service.list_slots(target)
        source_data = list(range(300, 442))
        destinations = list(range(400, 511)) + list(range(338, 369))
        if len(source_data) != len(destinations):
            raise DiskError("The Acorn User source and destination layouts differ.")
        if any(not source_slots[slot]["formatted"] for slot in [2, *source_data]):
            raise DiskError("The source Acorn User menu or collection is incomplete.")
        requested = [399, *destinations]
        occupied = [slot for slot in requested if target_slots[slot]["formatted"]]
        if occupied:
            raise DiskError(f"Destination slots are already occupied: {occupied}")

        checkpoint = service.create_checkpoint(
            target,
            "Before Acorn User magazine collection",
        )
        written: list[dict] = []
        try:
            for source_slot, destination in [(2, 399), *zip(source_data, destinations)]:
                header, payload = slot_bytes(source.path, source_slot)
                write_slot(target.path, destination, header, payload)
                target.slot_cache.pop(destination, None)
                source_name = (
                    "Acorn User menu from source MMB"
                    if source_slot == 2
                    else f"Acorn User source slot {source_slot}"
                )
                target.slot_source_names[destination] = source_name
                written.append({
                    "source": source_slot,
                    "destination": destination,
                    "title": source_slots[source_slot]["name"],
                    "sha256": hashlib.sha256(payload).hexdigest(),
                })
            target.dirty = True
            target.menu_scanned = False
            target.menu_slot = None
            target.menu_type = None
            service._persist_session(target)

            refreshed = service.list_slots(target)
            for item in written:
                source_header, source_payload = slot_bytes(source.path, item["source"])
                target_header, target_payload = slot_bytes(target.path, item["destination"])
                if source_header != target_header or source_payload != target_payload:
                    raise DiskError(
                        f"Verification failed for destination slot {item['destination']}."
                    )
                if not refreshed[item["destination"]]["formatted"]:
                    raise DiskError(
                        f"Destination slot {item['destination']} is not formatted after import."
                    )
        except Exception:
            service.restore_checkpoint(target, checkpoint["id"])
            raise

        print(json.dumps({
            "checkpoint": checkpoint,
            "menuSlot": 399,
            "primaryRange": [400, 510],
            "overflowRange": [338, 368],
            "disks": len(source_data),
            "written": written,
        }, indent=2))
    finally:
        SESSION_OWNER.reset(owner_token)


if __name__ == "__main__":
    main()
