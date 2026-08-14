import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.beebscsi_geometry import descriptor_size, old_map_checksum, old_map_size
from app.adfs_install_service import ADFSInstallMixin
from app.menu_records import normalise_page, parse_menu_data, serialise_menu
from app.mmb_layout import ENTRY_SIZE, HEADER_SIZE, INDEX_START, SLOT_SIZE, entry_offset, image_size, slot_offset
from app.menu import adfs, analysis, mmb
from app.disk_service import DiskService
from app.filesystem_disk_service import FilesystemDiskMixin
from app.rom_disk_service import RomDiskMixin
from app.session_disk_service import SessionDiskMixin
from app.tape_disk_service import TapeDiskMixin


class ComponentBoundaryTests(unittest.TestCase):
    def test_mmb_offsets_have_one_canonical_definition(self):
        self.assertEqual(entry_offset(3), INDEX_START + 3 * ENTRY_SIZE)
        self.assertEqual(slot_offset(3), HEADER_SIZE + 3 * SLOT_SIZE)
        self.assertEqual(image_size(511), HEADER_SIZE + 511 * SLOT_SIZE)

    def test_beebscsi_geometry_helpers_are_pure(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            descriptor = bytearray(16)
            descriptor[13:15] = (80).to_bytes(2, "big")
            descriptor[15] = 2
            descriptor_path = root / "drive.dsc"
            descriptor_path.write_bytes(descriptor)
            self.assertEqual(descriptor_size(descriptor_path), 80 * 2 * 33 * 256)
            map_path = root / "drive.dat"
            map_sector = bytearray(256)
            map_sector[0xFC:0xFF] = (640).to_bytes(3, "little")
            map_path.write_bytes(map_sector)
            self.assertEqual(old_map_size(map_path), 640 * 256)
        block = bytearray(256)
        block[-1] = old_map_checksum(block)
        self.assertEqual(old_map_checksum(block), block[-1])

    def test_menu_codec_round_trips_complete_page_addresses(self):
        source = [{
            "title": "GAME",
            "publisher": "PUBLISHER",
            "filename": "!BOOT",
            "action": "E",
            "page": "E00",
            "diskTitle": "GAME",
        }]
        database, index = serialise_menu(source, preserve_first_action=True)
        result = parse_menu_data(database)
        self.assertEqual(result[0]["page"], "E00")
        self.assertEqual(result[0]["action"], "E")
        self.assertTrue(index)
        self.assertEqual(normalise_page("E"), "E00")

    def test_routes_use_domain_menu_apis_instead_of_the_compatibility_module(self):
        routes = Path(__file__).parents[1] / "app" / "routes"
        offenders = [
            path.name for path in routes.glob("*.py")
            if "menu_service import" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])
        self.assertTrue(callable(analysis.analyse_disk))
        self.assertTrue(callable(adfs.create_adfs_menu))
        self.assertTrue(callable(mmb.install_mmb_menu))

    def test_tape_operations_are_owned_by_the_tape_component(self):
        self.assertTrue(issubclass(DiskService, TapeDiskMixin))
        self.assertNotIn("convert_uef", DiskService.__dict__)
        self.assertIs(DiskService.convert_uef, TapeDiskMixin.convert_uef)

    def test_rom_operations_are_owned_by_the_rom_component(self):
        self.assertTrue(issubclass(DiskService, RomDiskMixin))
        self.assertNotIn("put_rom_bank", DiskService.__dict__)
        self.assertIs(DiskService.put_rom_bank, RomDiskMixin.put_rom_bank)

    def test_session_operations_are_owned_by_the_session_component(self):
        self.assertTrue(issubclass(DiskService, SessionDiskMixin))
        self.assertNotIn("recoverable_sessions", DiskService.__dict__)
        self.assertIs(DiskService.recoverable_sessions, SessionDiskMixin.recoverable_sessions)

    def test_filesystem_mounts_are_owned_by_the_filesystem_component(self):
        self.assertTrue(issubclass(DiskService, FilesystemDiskMixin))
        self.assertNotIn("adfs_mount", DiskService.__dict__)
        self.assertIs(DiskService.adfs_mount, FilesystemDiskMixin.adfs_mount)
        self.assertIs(DiskService.romfs_details, FilesystemDiskMixin.romfs_details)

    def test_adfs_installation_audit_is_owned_by_its_component(self):
        self.assertTrue(issubclass(DiskService, ADFSInstallMixin))
        self.assertNotIn("audit_adfs_installations", DiskService.__dict__)
        self.assertIs(DiskService.audit_adfs_installations, ADFSInstallMixin.audit_adfs_installations)


if __name__ == "__main__":
    unittest.main()
