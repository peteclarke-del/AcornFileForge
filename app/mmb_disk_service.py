from __future__ import annotations

from typing import TYPE_CHECKING

from .errors import DiskError
from .mmb_layout import (
    ENTRY_SIZE,
    HEADER_SIZE,
    available_slots,
    entry_offset,
    image_size,
    slot_offset,
)

if TYPE_CHECKING:
    from .image_session import ImageSession


class MmbCatalogueMixin:
    """Read-only MMB slot catalogue operations shared by the disk service."""

    def list_slots(self, session: ImageSession) -> list[dict]:
        size = session.path.stat().st_size
        if size < image_size(1):
            raise DiskError("The MMB image is too small to contain a disk.")
        count = available_slots(size)
        with session.path.open("rb") as image:
            header = image.read(HEADER_SIZE)
        slots = []
        for number in range(count):
            offset = entry_offset(number)
            entry = header[offset : offset + ENTRY_SIZE]
            if len(entry) < ENTRY_SIZE:
                break
            status = entry[15]
            title = entry[:12].decode("latin-1", "replace").rstrip("\0 ")
            formatted = status < 0x80
            slots.append({
                "slot": number,
                "name": title if formatted and title else ("Untitled disk" if formatted else "Empty slot"),
                "legacyTitle": title if not formatted else "",
                "type": "disk",
                "formatted": formatted,
                "empty": not formatted,
                "writable": 0 < status < 0x80,
                "invalid": status == 0xFF,
                "status": status,
            })
        return slots

    def find_mmb_slot_with_catalogue_files(
        self, session: ImageSession, required_names: set[str]
    ) -> int | None:
        """Find a DFS menu slot directly, without mounting every MMB disk."""
        return self.find_mmb_slots_with_catalogue_files(
            session, {"match": required_names}
        ).get("match")

    def find_mmb_slots_with_catalogue_files(
        self, session: ImageSession, required_groups: dict[str, set[str]]
    ) -> dict[str, int]:
        """Find several DFS menu signatures in one sequential catalogue scan."""
        if session.kind != "mmb":
            return {}
        pending = {
            key: {str(name).upper() for name in names}
            for key, names in required_groups.items()
        }
        matches = {}
        slots = self.list_slots(session)
        with session.lock, session.path.open("rb") as image:
            for entry in slots:
                if not pending:
                    break
                if not entry["formatted"]:
                    continue
                if str(entry.get("name") or "").upper().startswith("MBACKUP-"):
                    continue
                slot = int(entry["slot"])
                image.seek(slot_offset(slot))
                catalogue = image.read(512)
                if len(catalogue) != 512:
                    continue
                file_count = (catalogue[256 + 5] & 0xF8) // 8
                if file_count > 31:
                    continue
                names = {
                    catalogue[8 + offset * 8 : 15 + offset * 8]
                    .decode("latin-1", "replace")
                    .rstrip("\0 ")
                    .upper()
                    for offset in range(file_count)
                }
                for key, required in tuple(pending.items()):
                    if required.issubset(names):
                        matches[key] = slot
                        del pending[key]
        return matches
