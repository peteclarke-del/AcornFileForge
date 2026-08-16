from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from app.disk_service import DiskService, ImageSession
from tests.uef_fixture import minimal_uef


@dataclass(frozen=True)
class GeneratedMedium:
    format: str
    session: ImageSession


def generated_media_matrix(service: DiskService) -> list[GeneratedMedium]:
    """Create representative media using only public application APIs."""
    rows = [
        GeneratedMedium("ssd", service.create_blank("ssd", "TESTSSD")),
        GeneratedMedium("dsd", service.create_blank("dsd", "TESTDSD")),
        GeneratedMedium("adfs-s", service.create_blank("adfs-s", "TESTS")),
        GeneratedMedium("adfs-m", service.create_blank("adfs-m", "TESTM")),
        GeneratedMedium("adfs-l", service.create_blank("adfs-l", "TESTL")),
        GeneratedMedium("adfs-d", service.create_blank("adfs-d", "TESTD")),
        GeneratedMedium("adfs-e", service.create_blank("adfs-e", "TESTE")),
        GeneratedMedium("adfs-e-plus", service.create_blank("adfs-e-plus", "TESTEP")),
        GeneratedMedium("adfs-f", service.create_blank("adfs-f", "TESTF")),
        GeneratedMedium("adfs-f-plus", service.create_blank("adfs-f-plus", "TESTFP")),
        GeneratedMedium("adfs-g", service.create_blank("adfs-g", "TESTG")),
        GeneratedMedium("adfs-g-plus", service.create_blank("adfs-g-plus", "TESTGP")),
        GeneratedMedium("mmb", service.create_blank("mmb", "TESTMMB")),
        GeneratedMedium(
            "beebscsi",
            service.create_blank("beebscsi", "TESTSCSI", "20MB", "beebscsi-bbc"),
        ),
        GeneratedMedium(
            "rom",
            service.create_blank(
                "rom", "TESTROM", options={"bankSize": 16 * 1024, "totalSize": 32 * 1024},
            ),
        ),
        GeneratedMedium("romfs", service.create_blank("romfs", "TESTRFS")),
        GeneratedMedium("hfe", service.create_blank("hfe-ssd", "TESTHFE")),
    ]
    tape = service.create_from_stream("test.uef", io.BytesIO(minimal_uef()))
    rows.append(GeneratedMedium("uef", tape))
    return rows


def add_test_file(
    service: DiskService,
    session: ImageSession,
    host_root: Path,
    *,
    path: str = "$.TEST",
    payload: bytes = b"Acorn File Forge generated fixture\r",
) -> None:
    source = host_root / f"fixture-{session.id}.bin"
    source.write_bytes(payload)
    service.put(session, None, path, source, "0x1900", "0x1900", None)
