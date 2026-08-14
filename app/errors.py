"""Shared application exceptions.

Keeping these exceptions outside the service modules avoids circular imports while
giving routes and collaborating services one stable error hierarchy to catch.
"""

from __future__ import annotations


class DiskError(RuntimeError):
    """A user-facing image or filing-system operation failed."""


class EmptyDiskError(DiskError):
    """A bulk extraction needs a user skip or abort decision."""

    def __init__(self, disk: dict):
        self.disk = disk
        super().__init__(
            f"MMB slot {disk['sourceSlot']} · {disk['sourceName']} has an empty DFS catalogue."
        )


class DestinationExistsError(DiskError):
    """A bulk extraction needs a keep, replace or abort decision."""

    def __init__(self, conflict: dict):
        self.conflict = conflict
        super().__init__(
            f"MMB slot {conflict['sourceSlot']} · {conflict['sourceName']} cannot use "
            f"{conflict['destination']} because that directory already exists."
        )
