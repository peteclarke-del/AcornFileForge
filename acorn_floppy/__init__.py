"""Reusable, UI-neutral floppy-controller support for Acorn media."""

from .device import (
    ACORN_GEOMETRIES,
    KNOWN_DEVICES,
    FloppyDevice,
    FloppyError,
    FloppyGeometry,
    FloppyProbe,
    FloppyReadResult,
    FloppyWriteResult,
    available_devices,
    geometry,
    validated_device,
    geometry_for_size,
)

__all__ = [
    "ACORN_GEOMETRIES",
    "KNOWN_DEVICES",
    "FloppyDevice",
    "FloppyError",
    "FloppyGeometry",
    "FloppyProbe",
    "FloppyReadResult",
    "FloppyWriteResult",
    "available_devices",
    "geometry",
    "validated_device",
    "geometry_for_size",
]
