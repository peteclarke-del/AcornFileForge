from __future__ import annotations

import io
import os
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
from app.menu_service import delete_adfs_items


class DiskPerformanceTests(unittest.TestCase):
    @staticmethod
    def _small_mmb(root: Path, name: str, titles: dict[int, str]) -> ImageSession:
        path = root / name
        header = bytearray(MMB_HEADER_SIZE)
        for slot in range(8):
            offset = 16 + slot * MMB_ENTRY_SIZE
            header[offset + 15] = 0xF0
        for slot, title in titles.items():
            offset = 16 + slot * MMB_ENTRY_SIZE
            header[offset : offset + 12] = title.encode("latin-1")[:12].ljust(12, b"\0")
            header[offset + 15] = 0x0F
        with path.open("wb") as image:
            image.write(header)
            image.truncate(MMB_HEADER_SIZE + 8 * MMB_SLOT_SIZE)
            for slot in titles:
                image.seek(MMB_HEADER_SIZE + slot * MMB_SLOT_SIZE)
                image.write(bytes([slot]) * MMB_SLOT_SIZE)
        return ImageSession(name[0] * 32, name, "mmb", path)

    def test_mmb_cut_paste_allows_an_overlapping_slot_range(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = DiskService(root / "work")
            session = self._small_mmb(
                root,
                "source.mmb",
                {2: "TWO", 3: "THREE", 4: "FOUR"},
            )

            result = service.paste_mmb_slots(
                session, session, [2, 3, 4], 3, cut=True
            )

            self.assertTrue(result["pasted"])
            slots = service.list_slots(session)
            self.assertTrue(slots[2]["empty"])
            self.assertEqual([slots[number]["name"] for number in (3, 4, 5)], [
                "TWO", "THREE", "FOUR",
            ])
            with session.path.open("rb") as image:
                image.seek(MMB_HEADER_SIZE + 5 * MMB_SLOT_SIZE)
                self.assertEqual(image.read(1), b"\x04")

    def test_mmb_copy_paste_reports_then_replaces_occupied_slots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = DiskService(root / "work")
            source = self._small_mmb(root, "source.mmb", {1: "SOURCE"})
            target = self._small_mmb(root, "target.mmb", {4: "OCCUPIED"})

            conflict = service.paste_mmb_slots(source, target, [1], 4)
            self.assertFalse(conflict["pasted"])
            self.assertEqual(conflict["conflicts"], [{"slot": 4, "name": "OCCUPIED"}])
            self.assertEqual(service.list_slots(target)[4]["name"], "OCCUPIED")

            copied = service.paste_mmb_slots(source, target, [1], 4, replace=True)
            self.assertTrue(copied["pasted"])
            self.assertEqual(service.list_slots(source)[1]["name"], "SOURCE")
            self.assertEqual(service.list_slots(target)[4]["name"], "SOURCE")

    def test_copy_stream_falls_back_for_an_in_memory_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "upload.img"
            content = b"Acorn" * 100_000

            DiskService._copy_stream(io.BytesIO(content), target)

            self.assertEqual(target.read_bytes(), content)

    def test_local_checkpoint_copy_preserves_sparse_zero_ranges(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.dat"
            target = Path(directory) / "checkpoint.dat"
            with source.open("wb") as output:
                output.write(b"ADFS")
                output.seek(32 * 1024 * 1024 - 1)
                output.write(b"\0")

            DiskService._copy_local_file(source, target)

            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertLess(target.stat().st_blocks * 512, target.stat().st_size // 4)

    def test_trusted_local_open_uses_filesystem_copy_not_upload_stream(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "firmware.rom"
            source.write_bytes(bytes([0xFF]) * (16 * 1024))
            service = DiskService(root / "work")

            with patch.object(
                service,
                "_copy_local_file",
                wraps=service._copy_local_file,
            ) as local_copy, patch.object(
                service,
                "_copy_stream",
                side_effect=AssertionError("local open used the upload copy path"),
            ):
                session = service.create_from_path(source, force_kind="rom")

            self.assertEqual(local_copy.call_count, 1)
            self.assertEqual(session.path.read_bytes(), source.read_bytes())

    def test_known_adfs_local_open_skips_the_all_filesystem_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = DiskService(root / "source-work").create_blank(
                "adfs-e", "SOURCE"
            ).path
            service = DiskService(root / "open-work")

            with patch.object(
                service,
                "_run_json",
                side_effect=AssertionError("known ADFS media used the generic probe"),
            ):
                opened = service.create_from_path(source)

            self.assertEqual(opened.kind, "adfs")
            self.assertEqual(opened.path.stat().st_size, source.stat().st_size)

    def test_sparse_optimisation_does_not_look_like_an_image_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "scsi0.dat"
            image.write_bytes(b"ADFS" + bytes(8 * 1024 * 1024))
            timestamp = 1_700_000_000_123_456_789
            os.utime(image, ns=(timestamp, timestamp))

            DiskService._optimise_sparse_file(image)

            self.assertEqual(image.stat().st_mtime_ns, timestamp)
            self.assertEqual(image.read_bytes()[:4], b"ADFS")

    def test_directory_tree_copy_avoids_the_cli_for_an_adfs_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = DiskService(root / "work")
            source = service.create_blank("ssd", "SOURCE")
            target = service.create_blank("adfs-s", "TARGET")
            for name in ("ONE", "TWO"):
                host = root / name.lower()
                host.write_bytes(name.encode("ascii"))
                service.put(source, None, f"$.{name}", host, "0x1900", "0x1900", None)
            rows = service.list_dfs_catalogue_files(source, None)

            with patch.object(service, "_run", wraps=service._run) as run:
                service._copy_rows_to_adfs(
                    source, None, None, rows, target, "$.SOFTWARE"
                )

            self.assertEqual(run.call_count, 0)
            self.assertEqual(
                {
                    row["name"]
                    for row in service.list_directory(target, "$.SOFTWARE", None)["entries"]
                },
                {"ONE", "TWO"},
            )

    def test_adfs_browse_returns_capacity_without_the_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = DiskService(root / "work")
            session = service.create_blank("adfs-s", "BROWSE")
            service.make_directory(session, "$.Games")

            with patch.object(service, "_run", wraps=service._run) as run:
                listing = service.browse_directory(session, "$", None)

            self.assertEqual(run.call_count, 0)
            self.assertEqual([row["name"] for row in listing["entries"]], ["Games"])
            self.assertTrue(listing["capacity"]["available"])
            self.assertGreater(listing["capacity"]["free"], 0)

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

    def test_multiple_dfs_files_change_access_in_one_mount(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = DiskService(root / "work")
            session = service.create_blank("ssd", "ACCESS")
            first = root / "one.bin"
            second = root / "two.bin"
            first.write_bytes(b"one")
            second.write_bytes(b"two")
            service.put(session, None, "$.ONE", first, "1900", "1900", None)
            service.put(session, None, "$.TWO", second, "1900", "1900", None)

            updated = service.set_access(
                session,
                None,
                ["$.ONE", "$.TWO"],
                False,
            )

            self.assertEqual(updated, ["$.ONE", "$.TWO"])
            entries = service.list_directory(session, "$", None)["entries"]
            self.assertTrue(all("L" in row["attr"] for row in entries))

            service.set_access(session, None, ["$.ONE", "$.TWO"], True)
            entries = service.list_directory(session, "$", None)["entries"]
            self.assertTrue(all("L" not in row["attr"] for row in entries))

    def test_multiple_dfs_files_delete_in_one_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = DiskService(root / "work")
            session = service.create_blank("ssd", "DELETE")
            for name in ("ONE", "TWO", "KEEP"):
                host = root / f"{name.lower()}.bin"
                host.write_bytes(name.encode("ascii"))
                service.put(session, None, f"$.{name}", host, "1900", "1900", None)

            service.mutate(
                session,
                None,
                ["rm", "--force", "{image}:$.ONE", "$.TWO"],
            )

            names = {row["name"] for row in service.list_directory(session, "$", None)["entries"]}
            self.assertEqual(names, {"KEEP"})

    def test_multiple_adfs_items_delete_in_one_mount(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = DiskService(root / "work")
            session = service.create_blank("adfs-s", "DELETE")
            for name in ("ONE", "TWO", "KEEP"):
                host = root / f"{name.lower()}.bin"
                host.write_bytes(name.encode("ascii"))
                service.put(session, None, f"$.{name}", host, "1900", "1900", None)

            result = delete_adfs_items(service, session, ["$.ONE", "$.TWO"])

            self.assertEqual(len(result["deletedItems"]), 2)
            names = {row["name"] for row in service.list_directory(session, "$", None)["entries"]}
            self.assertEqual(names, {"KEEP"})

    def test_host_folder_import_preserves_an_adfs_tree_in_one_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = DiskService(root / "work")
            session = service.create_blank("adfs-s", "FOLDERS")
            one = root / "one.bin"
            two = root / "two.bin"
            one.write_bytes(b"one")
            two.write_bytes(b"two")

            result = service.put_host_tree(
                session,
                None,
                "$",
                [
                    {
                        "targetPath": "Pack/One",
                        "hostPath": one,
                        "metadata": {"load": "0xFFFF1900", "execute": "0xFFFF8023"},
                    },
                    {"targetPath": "Pack/Sub/Two", "hostPath": two},
                ],
                preserve_directories=True,
            )

            self.assertEqual(result["conflicts"], [])
            self.assertEqual(
                {row["name"] for row in service.list_directory(session, "$.Pack", None)["entries"]},
                {"One", "Sub"},
            )
            self.assertEqual(
                [row["name"] for row in service.list_directory(session, "$.Pack.Sub", None)["entries"]],
                ["Two"],
            )
            imported = next(
                row for row in service.list_directory(session, "$.Pack", None)["entries"]
                if row["name"] == "One"
            )
            self.assertEqual(imported["load"], 0xFFFF1900)
            self.assertEqual(imported["exec"], 0xFFFF8023)

    def test_host_folder_import_reports_existing_files_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = DiskService(root / "work")
            session = service.create_blank("ssd", "FOLDERS")
            old = root / "old.bin"
            new = root / "new.bin"
            old.write_bytes(b"old")
            new.write_bytes(b"new")
            service.put(session, None, "$.SAME", old, None, None, None)

            result = service.put_host_tree(
                session,
                None,
                "$",
                [{"targetPath": "SAME", "hostPath": new}],
                preserve_directories=False,
            )

            self.assertEqual(result["conflicts"], ["$.SAME"])
            self.assertEqual(service.read_file(session, None, "$.SAME"), b"old")

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

            @contextmanager
            def adfs_mount(_session):
                yield FakeMount()

            service.adfs_mount = adfs_mount

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

            @contextmanager
            def adfs_mount(_session):
                yield FakeMount()

            service.adfs_mount = adfs_mount

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
