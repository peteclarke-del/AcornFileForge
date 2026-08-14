import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.beebscsi_geometry import descriptor_size, old_map_checksum, old_map_size
from app.menu_records import normalise_page, parse_menu_data, serialise_menu
from app.mmb_layout import ENTRY_SIZE, HEADER_SIZE, INDEX_START, SLOT_SIZE, entry_offset, image_size, slot_offset


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


if __name__ == "__main__":
    unittest.main()
