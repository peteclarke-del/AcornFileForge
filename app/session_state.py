from __future__ import annotations

import re

from .image_session import ImageSession


def normalise_warnings(warnings: list[str]) -> list[str]:
    """Keep durable image history concise and discard superseded diagnostics."""
    result: list[str] = []
    directory_fields_repaired = False
    tube_warning = False
    loader_review = False
    for value in warnings:
        warning = str(value).strip()
        if not warning:
            continue
        if re.match(r"^Repaired \d+ old-ADFS directory sequence field", warning):
            directory_fields_repaired = True
            continue
        if "selected hardware profile has a Tube second processor enabled" in warning:
            tube_warning = True
            continue
        if (
            "contains ambiguous ADFS command" in warning
            or "loader contains" in warning and "ambiguous abbreviated command" in warning
        ):
            loader_review = True
            continue
        if warning not in result:
            result.append(warning)
    if directory_fields_repaired:
        result.append("Maintained old-ADFS directory sequence fields for 8-bit hardware.")
    if tube_warning:
        result.append(
            "The selected hardware profile has a Tube second processor enabled. "
            "Some 8-bit software requires the Tube to be disabled unless it explicitly supports it."
        )
    if loader_review:
        result.append(
            "Installed ADFS loader diagnostics have changed since this image was edited. "
            "Run Tools > Check installed disk software for the current path-aware results."
        )
    return result


def session_metadata(session: ImageSession) -> dict:
    """Build the stable JSON representation of a recoverable image session."""
    return {
        "id": session.id,
        "name": session.name,
        "kind": session.kind,
        "descriptorName": session.descriptor_name,
        "descriptorFile": session.descriptor_path.name if session.descriptor_path else None,
        "slotSourceNames": {str(slot): name for slot, name in session.slot_source_names.items()},
        "adfsSourceNames": session.adfs_source_names,
        "distributionName": session.distribution_name,
        "targetHardware": session.target_hardware,
        "hardwareProfile": session.hardware_profile,
        "adfsCapabilities": session.adfs_capabilities,
        "workingFile": session.path.name,
        "hfeOriginalFile": session.hfe_original_path.name if session.hfe_original_path else None,
        "hfeVersion": session.hfe_version,
        "hfeReadOnly": session.hfe_read_only,
        "hfeLayout": session.hfe_layout,
        "hfeExportFile": session.hfe_export_path.name if session.hfe_export_path else None,
        "romBankSize": session.rom_bank_size,
        "romEraseByte": session.rom_erase_byte,
        "romPlatform": session.rom_platform,
        "romLayout": session.rom_layout,
        "romComponentNames": session.rom_component_names,
        "romProject": session.rom_project,
        "editorProjects": session.editor_projects,
        "dirty": session.dirty,
        "finalisedMtimeNs": session.finalised_mtime_ns,
        "ownerId": session.owner_id,
        "warnings": session.warnings,
    }
