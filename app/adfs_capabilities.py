"""Describe the FileCore layout exposed by the supported Oaknut release."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ADFSCapabilities:
    """Pane-facing limits derived from the mounted on-disc structures."""

    format: str
    map: str
    directories: str
    name_limit: int
    directory_entry_limit: int | None

    def to_dict(self) -> dict:
        return asdict(self)


def capabilities_from_mount(mount) -> ADFSCapabilities:
    """Return format and directory limits for an Oaknut ADFS mount.

    Oaknut deliberately keeps the concrete ADFS implementation behind its
    generic mount API. The adapter is isolated here so the rest of the app
    consumes a stable, serialisable capability record rather than depending
    on concrete directory classes.
    """

    adfs = getattr(mount, "_adfs", None)
    if adfs is None:
        raise TypeError("The mounted filesystem is not ADFS.")

    size = int(mount.size_bytes())
    is_new_map = bool(adfs.is_new_map)
    directory_format = getattr(adfs, "_dir_format", None)
    name_grammar = getattr(adfs, "_name_grammar", None)
    name_limit = int(getattr(name_grammar, "max_length", 10))
    maximum_entries = int(getattr(directory_format, "max_entries", 47))
    big_directories = name_limit > 10
    new_directories = big_directories or maximum_entries == 77

    format_name = _format_name(size, is_new_map, big_directories, new_directories)
    return ADFSCapabilities(
        format=format_name,
        map="new" if is_new_map else "old",
        directories="big" if big_directories else "new" if new_directories else "old",
        name_limit=name_limit,
        directory_entry_limit=None if big_directories else maximum_entries,
    )


def _format_name(
    size: int,
    is_new_map: bool,
    big_directories: bool,
    new_directories: bool,
) -> str:
    if size == 160 * 1024 and not is_new_map:
        return "S"
    if size == 320 * 1024 and not is_new_map:
        return "M"
    if size == 640 * 1024 and not is_new_map:
        return "L"
    if size == 800 * 1024:
        if not is_new_map and new_directories:
            return "D"
        return "E+" if big_directories else "E"
    if size == 1600 * 1024 and is_new_map:
        return "F+" if big_directories else "F"
    if size == 3200 * 1024 and is_new_map:
        return "G+" if big_directories else "G"
    return "FileCore hard disk" if size > 3200 * 1024 else "ADFS"


__all__ = ["ADFSCapabilities", "capabilities_from_mount"]
