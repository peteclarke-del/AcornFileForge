from __future__ import annotations

import io
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from app.disk_service import (
    MMB_ENTRY_SIZE,
    MMB_HEADER_SIZE,
    MMB_SLOT_SIZE,
    DiskError,
    DiskService,
    DestinationExistsError,
    EmptyDiskError,
    ImageSession,
)


class DiskPerformanceTests(unittest.TestCase):
    def test_copy_stream_falls_back_for_an_in_memory_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "upload.img"
            content = b"Acorn" * 100_000

            DiskService._copy_stream(io.BytesIO(content), target)

            self.assertEqual(target.read_bytes(), content)

    def test_directory_tree_copy_uses_one_engine_invocation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = DiskService(root / "work")
            source_path = root / "source.ssd"
            target_path = root / "target.hdf"
            source_path.touch()
            target_path.touch()
            source = ImageSession("1", "source.ssd", "dfs", source_path)
            target = ImageSession("2", "target.hdf", "adfs", target_path)
            calls: list[list[str]] = []
            service._run = lambda args, binary=False: calls.append(args) or ""

            service._copy_rows_to_adfs(
                source,
                None,
                None,
                [{"name": "ONE", "type": "file"}, {"name": "TWO", "type": "file"}],
                target,
                "$.SOFTWARE",
            )

            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][:2], ["cp", "--recursive"])
            self.assertIn("source.ssd:*", calls[0][2])

    def test_multiple_mmb_access_flags_are_updated_in_one_open_image(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "access.mmb"
            header = bytearray(MMB_HEADER_SIZE)
            header[16 + 15] = 0x0F
            header[16 + MMB_ENTRY_SIZE + 15] = 0x0F
            with path.open("wb") as image:
                image.write(header)
                image.truncate(MMB_HEADER_SIZE + 2 * MMB_SLOT_SIZE)
            service = DiskService(root / "work")
            session = ImageSession("1", path.name, "mmb", path)

            updated = service.protect_slots(session, [0, 1], False)

            self.assertEqual(updated, [0, 1])
            self.assertEqual(
                [slot["writable"] for slot in service.list_slots(session)],
                [False, False],
            )
            with self.assertRaises(DiskError):
                service.protect_slots(session, [], True)

    def test_bulk_copy_pauses_for_a_blank_disk_when_decision_is_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = DiskService(root / "work")
            source = ImageSession("1", "library.mmb", "mmb", root / "library.mmb")
            target = ImageSession("2", "drive.hdf", "adfs", root / "drive.hdf")
            service.require_writable_geometry = lambda _session: None
            service.list_slots = lambda _session: [
                {"slot": 12, "name": "SAVE DISK", "formatted": True}
            ]
            service.resolve = lambda _session, _slot=None: root / "slot.ssd"

            class FakeMount:
                _dfs = types.SimpleNamespace(files=[])

                def exists(self, _path):
                    return False

                def path_root(self):
                    return "$"

            @contextmanager
            def resolve_mount(_spec, writable=False):
                yield types.SimpleNamespace(mount=FakeMount(), path="$")

            cli = types.ModuleType("oaknut.disc.cli")
            cli._collect_copy_items = lambda *_args, **_kwargs: []
            cli._ensure_dir_chain = lambda *_args, **_kwargs: None
            cli._file_item = lambda *_args, **_kwargs: {}
            cli._in_global_storage_order = lambda _mount, items: items
            cli._walk_post_order_mount = lambda *_args, **_kwargs: []
            cli._write_copy_item = lambda *_args, **_kwargs: None
            mount = types.ModuleType("oaknut.disc.mount")
            mount.resolve_mount = resolve_mount
            modules = {
                "oaknut": types.ModuleType("oaknut"),
                "oaknut.disc": types.ModuleType("oaknut.disc"),
                "oaknut.disc.cli": cli,
                "oaknut.disc.mount": mount,
            }
            completed = []
            skipped = []

            with patch.dict(sys.modules, modules):
                with self.assertRaises(EmptyDiskError) as raised:
                    service.copy_mmb_slots_to_adfs_directories(
                        source,
                        target,
                        [{
                            "sourceSlot": 12,
                            "sourceName": "SAVE DISK",
                            "targetPath": "$",
                            "directoryName": "SAVEDISK",
                        }],
                        completed=completed.append,
                        skipped=skipped.append,
                        stop_on_empty=True,
                    )

            self.assertEqual(raised.exception.disk["sourceSlot"], 12)
            self.assertEqual(raised.exception.disk["sourceName"], "SAVE DISK")
            self.assertEqual(completed, [])
            self.assertEqual(skipped, [])

    def test_bulk_copy_pauses_before_overwriting_an_existing_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = DiskService(root / "work")
            source = ImageSession("1", "library.mmb", "mmb", root / "library.mmb")
            target = ImageSession("2", "drive.hdf", "adfs", root / "drive.hdf")
            service.require_writable_geometry = lambda _session: None
            service.list_slots = lambda _session: [
                {"slot": 76, "name": "AUI-PPACK2D2", "formatted": True}
            ]
            service.resolve = lambda _session, _slot=None: root / "slot.ssd"

            class FakeMount:
                def exists(self, path):
                    return path == "$.Games.DISCS2.AUI-PPACK2"

                def stat(self, _path):
                    return types.SimpleNamespace(is_dir=True)

                def iter_entries(self, _path):
                    return iter([types.SimpleNamespace(name="!BOOT")])

                def path_root(self):
                    return "$"

            @contextmanager
            def resolve_mount(_spec, writable=False):
                yield types.SimpleNamespace(mount=FakeMount(), path="$")

            cli = types.ModuleType("oaknut.disc.cli")
            cli._collect_copy_items = lambda *_args, **_kwargs: []
            cli._ensure_dir_chain = lambda *_args, **_kwargs: None
            cli._file_item = lambda *_args, **_kwargs: {}
            cli._in_global_storage_order = lambda _mount, items: items
            cli._walk_post_order_mount = lambda *_args, **_kwargs: []
            cli._write_copy_item = lambda *_args, **_kwargs: None
            mount = types.ModuleType("oaknut.disc.mount")
            mount.resolve_mount = resolve_mount
            modules = {
                "oaknut": types.ModuleType("oaknut"),
                "oaknut.disc": types.ModuleType("oaknut.disc"),
                "oaknut.disc.cli": cli,
                "oaknut.disc.mount": mount,
            }

            with patch.dict(sys.modules, modules):
                with self.assertRaises(DestinationExistsError) as raised:
                    service.copy_mmb_slots_to_adfs_directories(
                        source,
                        target,
                        [{
                            "sourceSlot": 76,
                            "sourceName": "AUI-PPACK2D2",
                            "targetPath": "$.Games.DISCS2",
                            "directoryName": "AUI-PPACK2",
                        }],
                        stop_on_conflict=True,
                    )

            self.assertEqual(raised.exception.conflict["sourceSlot"], 76)
            self.assertEqual(
                raised.exception.conflict["destination"],
                "$.Games.DISCS2.AUI-PPACK2",
            )

    def test_empty_adfs_directory_is_safe_to_reuse(self):
        empty_mount = types.SimpleNamespace(
            stat=lambda _path: types.SimpleNamespace(is_dir=True),
            iter_entries=lambda _path: iter(()),
        )
        populated_mount = types.SimpleNamespace(
            stat=lambda _path: types.SimpleNamespace(is_dir=True),
            iter_entries=lambda _path: iter([types.SimpleNamespace(name="!BOOT")]),
        )
        file_mount = types.SimpleNamespace(
            stat=lambda _path: types.SimpleNamespace(is_dir=False),
            iter_entries=lambda _path: iter(()),
        )

        self.assertTrue(DiskService._is_empty_directory(empty_mount, "$.EMPTY"))
        self.assertFalse(DiskService._is_empty_directory(populated_mount, "$.SOFTWARE"))
        self.assertFalse(DiskService._is_empty_directory(file_mount, "$.NOTADIR"))

    def test_raw_dfs_catalogue_collection_handles_numeric_directories(self):
        entries = [
            types.SimpleNamespace(directory="$", filename="!BOOT"),
            types.SimpleNamespace(directory="2", filename="ADV10"),
            types.SimpleNamespace(directory="u", filename="src"),
        ]
        mount = types.SimpleNamespace(_dfs=types.SimpleNamespace(files=entries))

        def file_item(_mount, source, destination):
            return {
                "kind": "file",
                "dst": destination,
                "data": source.encode("ascii"),
            }

        items = DiskService._collect_dfs_catalogue_items(
            mount,
            "$.DISC-0026",
            file_item,
        )

        files = [item for item in items if item["kind"] == "file"]
        self.assertEqual(
            [(item["sourceName"], item["dst"]) for item in files],
            [
                ("!BOOT", "$.DISC-0026.!BOOT"),
                ("2.ADV10", "$.DISC-0026.2.ADV10"),
                ("u.src", "$.DISC-0026.u.src"),
            ],
        )

    def test_dfs_to_adfs_names_resolve_file_directory_and_character_collisions(self):
        entries = [
            types.SimpleNamespace(directory="$", filename="o"),
            types.SimpleNamespace(directory="O", filename="E/ART2"),
        ]
        mount = types.SimpleNamespace(_dfs=types.SimpleNamespace(files=entries))

        def file_item(_mount, source, destination):
            return {"kind": "file", "dst": destination, "data": b"", "source": source}

        items = DiskService._collect_dfs_catalogue_items(
            mount,
            "$.DISC-0034",
            file_item,
        )

        self.assertIn(
            {"kind": "mkdir", "dst": "$.DISC-0034.O1"},
            items,
        )
        files = [item for item in items if item["kind"] == "file"]
        self.assertEqual(files[0]["dst"], "$.DISC-0034.o")
        self.assertEqual(files[1]["dst"], "$.DISC-0034.O1.E_ART2")
        self.assertEqual(files[1]["sourceName"], "O.E/ART2")

    def test_extracted_boot_relocates_dfs_root_to_adfs_directory(self):
        boot = b'*B.\r*DIR $\rPA.=&1D00\rCH."$.HAVEN"\r'

        relocated = DiskService._relocate_dfs_boot_script(
            boot,
            "$.Games.DISCS2.DISC-0055",
        )

        self.assertEqual(
            relocated,
            (
                b"*B.\r*DIR $.Games.DISCS2.DISC-0055\rPA.=&1D00\r"
                b'CH."$.Games.DISCS2.DISC-0055.HAVEN"\r'
            ),
        )

if __name__ == "__main__":
    unittest.main()
