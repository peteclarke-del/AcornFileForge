from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.disk_service import (
    BEEBSCSI_MAX_SIZE,
    SESSION_OWNER,
    DiskError,
    DiskService,
    ImageSession,
)
try:
    from app.server import create_app
except ModuleNotFoundError:  # Flask is intentionally absent from the light host test env.
    create_app = None


class DiskErrorTests(unittest.TestCase):
    @unittest.skipIf(create_app is None, "Flask is available in the application container")
    def test_browser_storage_owner_restores_missing_cookie(self) -> None:
        with tempfile.TemporaryDirectory() as folder, patch(
            "app.server.WORK_DIR", Path(folder)
        ):
            application = create_app()
            first_browser = application.test_client()
            first_response = first_browser.get("/api/health")
            owner = first_response.headers["X-Acorn-Session-Owner"]
            self.assertRegex(owner, r"^[A-Za-z0-9_-]{32,64}$")

            replacement_cookie_jar = application.test_client()
            restored_response = replacement_cookie_jar.get(
                "/api/health",
                headers={"X-Acorn-Session-Owner": owner},
            )

            self.assertEqual(restored_response.headers["X-Acorn-Session-Owner"], owner)
            self.assertIn(
                f"acorn_file_forge_owner={owner}",
                restored_response.headers["Set-Cookie"],
            )

    def test_beebscsi_is_a_distinct_target_profile(self) -> None:
        self.assertEqual(DiskService._target_hardware("beebscsi"), "beebscsi")

    def test_image_rename_preserves_format_and_renames_descriptor_download(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            session_folder = Path(folder) / ("a" * 32)
            session_folder.mkdir()
            image_path = session_folder / "scsi0.dat"
            descriptor_path = session_folder / "scsi0.dsc"
            image_path.write_bytes(b"image")
            descriptor_path.write_bytes(b"descriptor")
            service = DiskService(folder)
            session = ImageSession(
                "a" * 32,
                "scsi0.dat",
                "adfs",
                image_path,
                descriptor_name="scsi0.dsc",
                descriptor_path=descriptor_path,
            )

            service.rename_session(session, "Games")

            self.assertEqual(session.name, "Games.dat")
            self.assertEqual(session.descriptor_name, "Games.dsc")
            self.assertEqual(session.path, image_path)
            self.assertTrue((session_folder / "session.json").is_file())

    def test_image_rename_cannot_change_its_format(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            image_path = Path(folder) / "disk.ssd"
            image_path.write_bytes(b"image")
            session = ImageSession("b" * 32, "disk.ssd", "dfs", image_path)

            with self.assertRaisesRegex(DiskError, "Keep the .ssd extension"):
                DiskService(folder).rename_session(session, "disk.adf")

    def test_blank_image_targets_follow_the_selected_format(self) -> None:
        self.assertEqual(
            DiskService._blank_target_hardware("beebscsi", "electron-plus3"),
            "beebscsi",
        )
        self.assertEqual(
            DiskService._blank_target_hardware("adfs-hard", "bbc-master"),
            "risc-os",
        )
        self.assertEqual(
            DiskService._blank_target_hardware("adfs-physical", "beebscsi"),
            "risc-os",
        )
        self.assertEqual(
            DiskService._blank_target_hardware("adfs-m", "electron-plus3"),
            "electron-plus3",
        )
        self.assertEqual(
            DiskService._blank_target_hardware("hfe-adfs-l", "bbc-master"),
            "bbc-master",
        )
        self.assertEqual(
            DiskService._blank_target_hardware("mmb", "beebscsi"),
            "auto",
        )
        self.assertEqual(
            DiskService._blank_target_hardware("ssd", "risc-os"),
            "auto",
        )

    def test_failed_blank_creation_removes_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root)

            with patch.object(service, "_run", side_effect=DiskError("failed")):
                with self.assertRaisesRegex(DiskError, "failed"):
                    service.create_blank("ssd", "Blank")

            self.assertEqual(list(root.iterdir()), [])

    def test_image_can_extract_directly_into_current_adfs_directory(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root)
            source_path = root / "source.ssd"
            target_path = root / "target.dat"
            source_path.write_bytes(b"source")
            target_path.write_bytes(b"target")
            source = ImageSession("1" * 32, source_path.name, "dfs", source_path)
            target = ImageSession("2" * 32, target_path.name, "adfs", target_path)

            def listing(session, *_args, **_kwargs):
                return {"entries": [{"name": "GAME", "type": "file"}]} if session is source else {"entries": []}

            with (
                patch.object(service, "require_writable_geometry"),
                patch.object(service, "list_directory", side_effect=listing),
                patch.object(service, "_copy_image_listing_to_adfs") as copy_listing,
                patch.object(service, "_repair_copied_adfs_loaders", return_value=([], [])),
                patch.object(service, "_run") as run,
            ):
                destination = service.extract_image_to_adfs_directory(
                    source,
                    target,
                    "$.Games",
                    None,
                    create_directory=False,
                )

            self.assertEqual(destination, "$.Games")
            copy_listing.assert_called_once()
            run.assert_not_called()
            self.assertTrue(target.dirty)
            self.assertEqual(list(root.glob(".import-rollback-*")), [])

    def test_failed_current_directory_extraction_restores_target_image(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root)
            source_path = root / "source.ssd"
            target_path = root / "target.dat"
            source_path.write_bytes(b"source")
            target_path.write_bytes(b"original target")
            source = ImageSession("3" * 32, source_path.name, "dfs", source_path)
            target = ImageSession("4" * 32, target_path.name, "adfs", target_path)

            def listing(session, *_args, **_kwargs):
                return {"entries": [{"name": "GAME", "type": "file"}]} if session is source else {"entries": []}

            def fail_copy(*_args, **_kwargs):
                target_path.write_bytes(b"partly modified")
                target.warnings.append("partial warning")
                raise DiskError("copy failed")

            with (
                patch.object(service, "require_writable_geometry"),
                patch.object(service, "list_directory", side_effect=listing),
                patch.object(service, "_copy_image_listing_to_adfs", side_effect=fail_copy),
            ):
                with self.assertRaisesRegex(DiskError, "copy failed"):
                    service.extract_image_to_adfs_directory(
                        source,
                        target,
                        "$",
                        None,
                        create_directory=False,
                    )

            self.assertEqual(target_path.read_bytes(), b"original target")
            self.assertFalse(target.dirty)
            self.assertEqual(target.warnings, [])
            self.assertEqual(list(root.glob(".import-rollback-*")), [])

    def test_adfs_import_preview_traverses_source_directories(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root)
            image = root / "source.adf"
            image.write_bytes(b"image")
            session = ImageSession("5" * 32, image.name, "adfs", image)

            def listing(_session, path, *_args, **_kwargs):
                if path == "$":
                    return {"entries": [
                        {"name": "!BOOT", "type": "file", "size": 24},
                        {"name": "Games", "type": "dir", "size": 0},
                    ]}
                return {"entries": [
                    {"name": "Chuck", "type": "file", "size": 1088},
                ]}

            with patch.object(service, "list_directory", side_effect=listing):
                preview = service.preview_image_contents(session)

            self.assertEqual(preview["total"], 3)
            self.assertFalse(preview["truncated"])
            self.assertEqual(
                [(entry["path"], entry["name"]) for entry in preview["entries"]],
                [("$", "!BOOT"), ("$", "Games"), ("$.Games", "Chuck")],
            )

    def test_recoverable_sessions_lists_persisted_working_image(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root)
            image_id = "a" * 32
            session_folder = root / image_id
            session_folder.mkdir()
            image = session_folder / "scsi0.dat"
            descriptor = session_folder / "scsi0.dsc"
            image.write_bytes(bytes(512))
            descriptor.write_bytes(bytes(22))
            session = ImageSession(
                image_id,
                image.name,
                "adfs",
                image,
                descriptor_name=descriptor.name,
                descriptor_path=descriptor,
                target_hardware="beebscsi",
            )
            service._persist_session(session)

            recovered = service.recoverable_sessions()

            self.assertEqual(len(recovered), 1)
            self.assertEqual(recovered[0]["id"], image_id)
            self.assertEqual(recovered[0]["name"], "scsi0.dat")
            self.assertEqual(recovered[0]["size"], 512)
            self.assertTrue(recovered[0]["hasDescriptor"])

    def test_recovery_is_scoped_to_current_browser_owner(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root)
            owner_token = SESSION_OWNER.set("owner-one")
            try:
                image_id = "b" * 32
                session_folder = root / image_id
                session_folder.mkdir()
                image = session_folder / "private.ssd"
                image.write_bytes(bytes(204800))
                session = ImageSession(image_id, image.name, "dfs", image)
                service.sessions[image_id] = session
                service._persist_session(session)
                self.assertEqual(len(service.recoverable_sessions()), 1)
            finally:
                SESSION_OWNER.reset(owner_token)

            other_token = SESSION_OWNER.set("owner-two")
            try:
                self.assertEqual(service.recoverable_sessions(), [])
                with self.assertRaisesRegex(DiskError, "no longer exists"):
                    service.get(image_id)
                self.assertEqual(service.clear_recoverable_sessions(), 0)
                self.assertTrue(image.is_file())
            finally:
                SESSION_OWNER.reset(other_token)

    def test_restore_drops_legacy_ambiguous_command_false_positives(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root)
            image_id = "6" * 32
            session_folder = root / image_id
            session_folder.mkdir()
            image = session_folder / "working.ssd"
            image.write_bytes(bytes(204800))
            session = ImageSession(image_id, image.name, "dfs", image)
            session.warnings = [
                "$.Games.Review: contains ambiguous ADFS command r. This text, but no safe immediate OSCLI pointer was found",
                "A useful current warning",
            ]
            service._persist_session(session)

            restored = service._restore_session(image_id)

            self.assertEqual(restored.warnings, ["A useful current warning"])

    def test_one_time_key_claims_only_unowned_legacy_session(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root)
            image_id = "c" * 32
            session_folder = root / image_id
            session_folder.mkdir()
            image = session_folder / "legacy.ssd"
            image.write_bytes(bytes(204800))
            session = ImageSession(
                image_id,
                image.name,
                "dfs",
                image,
                owner_id=None,
                recovery_key="AFF-TEST-ONLY",
            )
            service.sessions[image_id] = session
            service._persist_session(session)

            owner_token = SESSION_OWNER.set("new-browser-owner")
            try:
                claimed = service.claim_recovery_key("aff-test-only")
                self.assertEqual(claimed.owner_id, "new-browser-owner")
                self.assertIsNone(claimed.recovery_key)
                with self.assertRaisesRegex(DiskError, "invalid or has already"):
                    service.claim_recovery_key("AFF-TEST-ONLY")
            finally:
                SESSION_OWNER.reset(owner_token)

    def test_one_time_key_can_reclaim_owned_session_after_cookie_loss(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root)
            image_id = "d" * 32
            session_folder = root / image_id
            session_folder.mkdir()
            image = session_folder / "working.mmb"
            image.write_bytes(bytes(8192 + 204800))
            session = ImageSession(
                image_id,
                image.name,
                "mmb",
                image,
                owner_id="lost-browser-owner",
            )
            service.sessions[image_id] = session
            service._persist_session(session)
            recovery_key = service.issue_recovery_key(image_id)

            owner_token = SESSION_OWNER.set("replacement-browser-owner")
            try:
                claimed = service.claim_recovery_key(recovery_key.lower())
                self.assertEqual(claimed.owner_id, "replacement-browser-owner")
                self.assertIsNone(claimed.recovery_key)
                with self.assertRaisesRegex(DiskError, "invalid or has already"):
                    service.claim_recovery_key(recovery_key)
            finally:
                SESSION_OWNER.reset(owner_token)

    def test_descriptor_is_rejected_for_non_dat_image(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(Path(folder))

            with self.assertRaisesRegex(DiskError, "only accompany"):
                service.create_from_stream(
                    "disk.ssd",
                    io.BytesIO(bytes(204800)),
                    ("disk.dsc", io.BytesIO(b"geometry")),
                )

    def test_zero_geometry_tail_is_removed_to_match_adfs_map(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            dat = root / "scsi0.dat"
            dsc = root / "scsi0.dsc"
            descriptor = bytearray(22)
            descriptor[13:16] = bytes((0, 2, 4))
            dsc.write_bytes(descriptor)
            geometry_size = 2 * 4 * 33 * 256
            map_size = geometry_size - 1024
            data = bytearray(map_size)
            data[0xFC:0xFF] = (map_size // 256).to_bytes(3, "little")
            dat.write_bytes(data + bytes(1024))
            session = ImageSession(
                "a" * 32,
                dat.name,
                "adfs",
                dat,
                descriptor_name=dsc.name,
                descriptor_path=dsc,
            )

            DiskService(root)._normalise_beebscsi_dat_size(session)

            self.assertEqual(dat.stat().st_size, map_size)
            self.assertTrue(session.dirty)
            self.assertIn("all-zero 1,024-byte geometry tail", session.warnings[0])

    def test_nonzero_data_beyond_adfs_map_is_not_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            dat = root / "scsi0.dat"
            dsc = root / "scsi0.dsc"
            descriptor = bytearray(22)
            descriptor[13:16] = bytes((0, 2, 4))
            dsc.write_bytes(descriptor)
            geometry_size = 2 * 4 * 33 * 256
            map_size = geometry_size - 1024
            data = bytearray(geometry_size)
            data[0xFC:0xFF] = (map_size // 256).to_bytes(3, "little")
            data[-1] = 1
            dat.write_bytes(data)
            session = ImageSession(
                "a" * 32,
                dat.name,
                "adfs",
                dat,
                descriptor_name=dsc.name,
                descriptor_path=dsc,
            )

            DiskService(root)._normalise_beebscsi_dat_size(session)

            self.assertEqual(dat.stat().st_size, geometry_size)
            self.assertFalse(session.dirty)
            self.assertIn("non-zero data beyond", session.warnings[0])

    def test_oaknut_traceback_is_reduced_to_final_error(self) -> None:
        message = """Traceback (most recent call last):
  File "/usr/local/bin/disc", line 8, in <module>
ValueError: A concise engine failure"""

        self.assertEqual(
            DiskService._friendly_engine_error(message),
            "A concise engine failure",
        )

    def test_created_beebscsi_pair_uses_map_extent_within_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            dat = root / "scsi0.dat"
            dsc = root / "scsi0.dsc"
            descriptor = bytearray(22)
            descriptor[3] = 8
            descriptor[9:12] = (256).to_bytes(3, "big")
            descriptor[12] = 1
            descriptor[13:16] = bytes((0, 2, 4))
            dsc.write_bytes(descriptor)
            geometry_size = 2 * 4 * 33 * 256
            map_size = geometry_size - 1024
            data = bytearray(map_size)
            data[0xFC:0xFF] = (map_size // 256).to_bytes(3, "little")
            dat.write_bytes(data)
            session = ImageSession(
                "a" * 32,
                dat.name,
                "adfs",
                dat,
                descriptor_name=dsc.name,
                descriptor_path=dsc,
            )

            DiskService._validate_created_beebscsi_pair(session)

            descriptor[15] = 17
            dsc.write_bytes(descriptor)
            with self.assertRaisesRegex(DiskError, "unsupported hardware geometry"):
                DiskService._validate_created_beebscsi_pair(session)

    def test_created_beebscsi_pair_cannot_exceed_adfs_sector_limit(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            dat = root / "scsi0.dat"
            dsc = root / "scsi0.dsc"
            descriptor = bytearray(22)
            descriptor[9:12] = (256).to_bytes(3, "big")
            descriptor[13:16] = bytes((0xFF, 0xFF, 16))
            dsc.write_bytes(descriptor)
            dat.touch()
            session = ImageSession(
                "a" * 32,
                dat.name,
                "adfs",
                dat,
                descriptor_name=dsc.name,
                descriptor_path=dsc,
            )

            with self.assertRaisesRegex(DiskError, "21-bit sector limit"):
                DiskService._validate_created_beebscsi_pair(session)
            self.assertEqual(BEEBSCSI_MAX_SIZE, 536_870_656)

    def test_created_beebscsi_root_uses_bbc_adfs_string_terminators(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            dat = root / "scsi0.dat"
            dsc = root / "scsi0.dsc"
            data = bytearray(2 * 256 + 1280)
            root_offset = 2 * 256
            tail = root_offset + 0x4CB
            data[root_offset + 1 : root_offset + 5] = b"Hugo"
            data[tail + 1] = ord("$")
            data[tail + 47 : tail + 52] = b"\0Hugo"
            dat.write_bytes(data)
            dsc.touch()
            session = ImageSession(
                "a" * 32,
                dat.name,
                "adfs",
                dat,
                descriptor_name=dsc.name,
                descriptor_path=dsc,
            )

            DiskService._canonicalise_created_beebscsi_root(session, "HARDTEST")

            result = dat.read_bytes()
            self.assertEqual(result[tail + 1 : tail + 11], b"$\r" + bytes(8))
            self.assertEqual(
                result[tail + 14 : tail + 33],
                b"HARDTEST\r" + bytes(10),
            )

    def test_beebscsi_download_repairs_child_directory_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            dat = root / "scsi0.dat"
            dsc = root / "scsi0.dsc"
            data = bytearray(12 * 256)

            def directory(sector: int, name: bytes, parent: int, sequence: int) -> None:
                offset = sector * 256
                tail = offset + 0x4CB
                data[offset] = sequence
                data[offset + 1 : offset + 5] = b"Hugo"
                data[tail + 1 : tail + 11] = name.ljust(10, b"\r")
                data[tail + 11 : tail + 14] = parent.to_bytes(3, "little")
                data[tail + 47] = sequence
                data[tail + 48 : tail + 52] = b"Hugo"

            directory(2, b"$", 2, 4)
            directory(7, b"Games", 2, 35)
            entry = 2 * 256 + 5
            data[entry : entry + 10] = b"Games".ljust(10, b"\r")
            data[entry + 3] |= 0x80
            data[entry + 22 : entry + 25] = (7).to_bytes(3, "little")
            data[entry + 25] = 0
            dat.write_bytes(data)
            dsc.touch()
            session = ImageSession(
                "a" * 32,
                dat.name,
                "adfs",
                dat,
                descriptor_name=dsc.name,
                descriptor_path=dsc,
            )

            repaired = DiskService._finalise_beebscsi_directories(session)

            self.assertEqual(repaired, 1)
            self.assertEqual(dat.read_bytes()[entry + 25], 35)
            self.assertTrue(session.dirty)

    def test_beebscsi_sequence_repair_rejects_bad_parent_link(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            dat = root / "scsi0.dat"
            dsc = root / "scsi0.dsc"
            data = bytearray(7 * 256)
            offset = 2 * 256
            tail = offset + 0x4CB
            data[offset + 1 : offset + 5] = b"Hugo"
            data[tail + 11 : tail + 14] = (99).to_bytes(3, "little")
            data[tail + 48 : tail + 52] = b"Hugo"
            dat.write_bytes(data)
            dsc.touch()
            session = ImageSession(
                "a" * 32,
                dat.name,
                "adfs",
                dat,
                descriptor_name=dsc.name,
                descriptor_path=dsc,
            )

            with self.assertRaisesRegex(DiskError, "parent link"):
                DiskService._finalise_beebscsi_directories(session)

    def test_beebscsi_sequence_repair_preserves_directory_identity(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            dat = root / "scsi0.dat"
            dsc = root / "scsi0.dsc"
            data = bytearray(12 * 256)

            def directory(sector: int, parent: int, sequence: int) -> None:
                offset = sector * 256
                tail = offset + 0x4CB
                data[offset] = sequence
                data[offset + 1 : offset + 5] = b"Hugo"
                data[tail + 11 : tail + 14] = parent.to_bytes(3, "little")
                data[tail + 47] = sequence
                data[tail + 48 : tail + 52] = b"Hugo"

            directory(2, 2, 4)
            directory(7, 2, 0x1A)
            entry = 2 * 256 + 5
            data[entry : entry + 10] = b"Games".ljust(10, b"\r")
            data[entry + 3] |= 0x80
            data[entry + 22 : entry + 25] = (7).to_bytes(3, "little")
            data[entry + 25] = 0
            dat.write_bytes(data)
            dsc.touch()
            session = ImageSession(
                "a" * 32,
                dat.name,
                "adfs",
                dat,
                descriptor_name=dsc.name,
                descriptor_path=dsc,
            )

            DiskService._finalise_beebscsi_directories(session)

            repaired = dat.read_bytes()
            self.assertEqual(repaired[7 * 256], 0x1A)
            self.assertEqual(repaired[7 * 256 + 0x4FA], 0x1A)
            self.assertEqual(repaired[entry + 25], 0x1A)

    def test_beebscsi_download_advances_disc_id_and_map_checksum_once(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            dat = Path(folder) / "scsi0.dat"
            data = bytearray(512)
            data[0xFC:0xFF] = (2048).to_bytes(3, "little")
            data[507:509] = (0x20BD).to_bytes(2, "little")
            data[255] = DiskService._old_map_checksum(data[:256])
            data[511] = DiskService._old_map_checksum(data[256:])
            dat.write_bytes(data)
            session = ImageSession("a" * 32, dat.name, "adfs", dat)

            self.assertTrue(DiskService._advance_beebscsi_disc_id(session))
            repaired = dat.read_bytes()
            self.assertEqual(int.from_bytes(repaired[507:509], "little"), 0x20BE)
            self.assertEqual(
                repaired[511],
                DiskService._old_map_checksum(repaired[256:]),
            )
            self.assertFalse(DiskService._advance_beebscsi_disc_id(session))

    def test_beebscsi_old_map_checksum_uses_acorn_reverse_byte_order(self) -> None:
        # Carry is propagated towards lower addresses.  This byte pattern
        # deliberately differs by one when incorrectly processed forwards.
        block = bytearray(256)
        block[0] = 1
        block[1] = 0xFF

        self.assertEqual(DiskService._old_map_checksum(block), 0)

    def test_sector_bounds_error_explains_missing_beebscsi_descriptor(self) -> None:
        message = "ValueError: Sector range [161, 166) exceeds disc bounds (0-156)"

        self.assertIn("matching DSC", DiskService._friendly_engine_error(message))

    def test_descriptorless_dat_is_not_writable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "scsi0.dat"
            path.touch()
            session = ImageSession("test", path.name, "adfs", path)

            with self.assertRaisesRegex(DiskError, "matching DSC"):
                DiskService.require_writable_geometry(session)


if __name__ == "__main__":
    unittest.main()
