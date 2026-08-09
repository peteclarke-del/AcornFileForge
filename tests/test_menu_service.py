from __future__ import annotations

import unittest
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.disk_service import (
    DiskError,
    MMB_HEADER_SIZE,
    MMB_SLOT_SIZE,
    DiskService,
    ImageSession,
)
from app.menu_service import (
    _adfs_boot_content,
    _adfs_launch_page,
    _rewrite_adfs_menu_records,
    _upgrade_universal_launcher_program,
    analyse_adfs_directory,
    analyse_copied_dfs_items,
    backup_mmb_menu_slot,
    build_index,
    continuation_metadata_from_mmb_menu,
    delete_adfs_items,
    configure_mmb_universal_page,
    discover_adfs_menu_paths,
    edit_mmb_menu_entries,
    eject_mmb_slots,
    enrich_if_ambiguous,
    find_menu_slot,
    installed_mmb_menus,
    fit_menu_display_fields,
    menu_title_case,
    mmb_metadata_for_adfs,
    metadata_records_from_mmb_menu,
    parse_menu_data,
    parse_spi_menu_data,
    parse_distribution_filename,
    serialise_menu,
    serialise_spi_menu,
    update_menu,
)


class FakeService:
    def __init__(self, entries=None, files=None):
        self.entries = entries or []
        self.files = files or {}

    def list_slots(self, _session):
        return [
            {"slot": 0, "name": "MENU", "formatted": True},
            {"slot": 1, "name": "GAME DISC", "formatted": True},
        ]

    def list_directory(self, _session, path, _slot):
        return {"entries": self.entries if path == "$.GAME" else []}

    def read_file(self, _session, _slot, path):
        return self.files[path]


class MenuServiceTests(unittest.TestCase):
    def test_bulk_adfs_delete_rewrites_all_matching_menu_records_once(self):
        class FakeMount:
            def exists(self, _path):
                return True

            def stat(self, _path):
                return SimpleNamespace(is_dir=False)

            def remove(self, _path, force=False):
                self.removed.append((_path, force))

            removed = []

        mount = FakeMount()

        @contextmanager
        def resolved_mount(_path, writable=False):
            self.assertTrue(writable)
            yield SimpleNamespace(mount=mount)

        records = [
            {"title": "One", "diskTitle": "$.Games", "filename": "ONE"},
            {"title": "Two", "diskTitle": "$.Games", "filename": "TWO"},
            {"title": "Keep", "diskTitle": "$.Games", "filename": "KEEP"},
        ]
        session = SimpleNamespace(
            kind="adfs",
            lock=threading.RLock(),
            path=Path("test.adl"),
            adfs_menu_roots=["$.Games"],
            adfs_source_names={},
            dirty=False,
        )
        service = Mock()

        @contextmanager
        def adfs_mount(_session):
            yield mount

        service.adfs_mount = adfs_mount

        with (
            patch("app.menu_service._installed_adfs_menus", return_value=[{
                "root": "$.Games",
                "entries": records,
            }]),
            patch("app.menu_service._write_adfs_menu_records") as write_records,
        ):
            result = delete_adfs_items(service, session, ["$.Games.ONE", "$.Games.TWO"])

        write_records.assert_called_once_with(mount, "$.Games", [records[2]])
        self.assertEqual(result["menuEntriesRemoved"], 2)
        self.assertEqual(mount.removed, [("$.Games.ONE", True), ("$.Games.TWO", True)])
        service._persist_session.assert_called_once_with(session)

    @patch("app.menu_service.edit_mmb_menu_entries")
    @patch("app.menu_service.parse_mmb_menu_data")
    @patch("app.menu_service.installed_mmb_menu", return_value=(0, "universal"))
    def test_bulk_eject_removes_every_menu_record_for_the_selected_disks(
        self,
        _installed_menu,
        parse_menu,
        edit_entries,
    ):
        service = Mock()
        service.list_slots.return_value = [
            {"slot": 0, "name": "MENU", "formatted": True},
            {"slot": 42, "name": "DISC ONE", "formatted": True},
            {"slot": 43, "name": "DISC TWO", "formatted": True},
            {"slot": 99, "name": "KEEP", "formatted": True},
        ]
        service.clear_slots.return_value = [42, 43]
        entries = [
            {"title": "One A", "diskTitle": "DISC ONE"},
            {"title": "One B", "diskTitle": "DISC ONE"},
            {"title": "Two", "diskTitle": "DISC TWO"},
            {"title": "Keep", "diskTitle": "KEEP"},
        ]
        parse_menu.return_value = entries
        session = SimpleNamespace(
            kind="mmb",
            lock=threading.RLock(),
            menu_type="universal",
        )

        result = eject_mmb_slots(service, session, [42, 43])

        edit_entries.assert_called_once_with(service, session, [entries[3]], entries)
        service.clear_slots.assert_called_once_with(session, [42, 43])
        self.assertEqual(result["menuEntriesRemoved"], 3)
        self.assertEqual(result["slots"], [42, 43])

    @patch("app.menu_service.edit_mmb_menu_entries")
    @patch("app.menu_service.parse_mmb_menu_data")
    @patch("app.menu_service.installed_mmb_menu", return_value=(0, "universal"))
    def test_eject_keeps_menu_records_when_another_slot_has_the_same_title(
        self,
        _installed_menu,
        parse_menu,
        edit_entries,
    ):
        service = Mock()
        service.list_slots.return_value = [
            {"slot": 0, "name": "MENU", "formatted": True},
            {"slot": 42, "name": "SHARED", "formatted": True},
            {"slot": 43, "name": "SHARED", "formatted": True},
        ]
        service.clear_slots.return_value = [42]
        parse_menu.return_value = [{"title": "Still available", "diskTitle": "SHARED"}]
        session = SimpleNamespace(
            kind="mmb",
            lock=threading.RLock(),
            menu_type="universal",
        )

        result = eject_mmb_slots(service, session, [42])

        edit_entries.assert_not_called()
        service.clear_slots.assert_called_once_with(session, [42])
        self.assertEqual(result["menuEntriesRemoved"], 0)

    def test_uppercase_menu_metadata_is_given_readable_title_case(self):
        self.assertEqual(menu_title_case("3D-MAZE"), "3D-Maze")
        self.assertEqual(
            menu_title_case("THE WAY OF THE EXPLODING FIST II"),
            "The Way of the Exploding Fist II",
        )
        self.assertEqual(menu_title_case("AQOS"), "AQOS")
        self.assertEqual(menu_title_case("Frak!"), "Frak!")

    def test_menu_title_and_publisher_fit_the_hardware_line(self):
        title, publisher = fit_menu_display_fields(
            "THE TIMES CROSSWORD PROGRAM JUBILEE PUZZLES",
            "A Very Long Publisher Name",
        )

        self.assertLessEqual(len(f"{title},{publisher}"), 38)
        self.assertEqual(title, "The Times Crossword Program")
        self.assertEqual(publisher, "A Very")

    def test_configures_low_page_universal_menu_boot(self):
        service = FakeService()
        session = SimpleNamespace(kind="mmb", menu_type="universal")
        with (
            patch("app.menu_service.find_menu_slot", return_value=0),
            patch("app.menu_service._put_bytes") as put,
        ):
            result = configure_mmb_universal_page(service, session, "&e00")

        self.assertEqual(result["menuPage"], "E00")
        put.assert_called_once_with(
            service,
            session,
            0,
            "$.!BOOT",
            b'PAGE=&E00\rCH."UNIMENU"\r',
        )

    def test_rejects_unsafe_arbitrary_universal_menu_page(self):
        service = FakeService()
        session = SimpleNamespace(kind="mmb", menu_type="universal")
        with (
            patch("app.menu_service.find_menu_slot", return_value=0),
            patch("app.menu_service._put_bytes") as put,
            self.assertRaisesRegex(DiskError, "current PAGE, &800, or &E00"),
        ):
            configure_mmb_universal_page(service, session, "1900")
        put.assert_not_called()

    def test_edits_universal_menu_after_validating_disk_and_launcher(self):
        original = {
            "title": "Old title", "publisher": "Acornsoft", "filename": "!BOOT",
            "action": "E", "page": "1900", "diskTitle": "GAME DISC", "system": "M",
        }
        edited = {**original, "title": "New title", "filename": "LOADER", "action": "R"}
        database, _index = serialise_menu([original])
        service = FakeService(
            entries=[{"name": "LOADER", "type": "file"}],
            files={"$.GAMDATA": database},
        )
        service.list_directory = lambda _session, _path, slot: {
            "entries": [{"name": "LOADER", "type": "file"}] if slot == 1 else []
        }
        session = SimpleNamespace(kind="mmb", menu_type="universal")

        with (
            patch("app.menu_service.find_menu_slot", return_value=0),
            patch("app.menu_service._write_mmb_databases") as write,
        ):
            result = edit_mmb_menu_entries(service, session, [edited], [original])

        self.assertEqual(result, {"menuSlot": 0, "entries": 1})
        self.assertEqual(write.call_args.args[3][0]["title"], "New title")

    def test_rejects_universal_menu_launcher_missing_from_target_disk(self):
        original = {
            "title": "Game", "publisher": "", "filename": "!BOOT",
            "action": "E", "page": "1900", "diskTitle": "GAME DISC", "system": "M",
        }
        database, _index = serialise_menu([original])
        service = FakeService(files={"$.GAMDATA": database})
        session = SimpleNamespace(kind="mmb", menu_type="universal")
        edited = {**original, "filename": "MISSING"}

        with (
            patch("app.menu_service.find_menu_slot", return_value=0),
            patch("app.menu_service._write_mmb_databases") as write,
            self.assertRaisesRegex(DiskError, "launcher MISSING does not exist"),
        ):
            edit_mmb_menu_entries(service, session, [edited], [original])
        write.assert_not_called()

    def test_clones_universal_menu_entry_for_second_game_on_same_disk(self):
        original = {
            "title": "Game One", "publisher": "Acornsoft", "filename": "ONE",
            "action": "", "page": "1900", "diskTitle": "GAME DISC", "system": "M",
        }
        cloned = {**original, "title": "Game Two", "filename": "TWO", "action": "R"}
        database, _index = serialise_menu([original])
        service = FakeService(files={"$.GAMDATA": database})
        service.list_directory = lambda _session, _path, slot: {
            "entries": [
                {"name": "ONE", "type": "file"},
                {"name": "TWO", "type": "file"},
            ] if slot == 1 else []
        }
        session = SimpleNamespace(kind="mmb", menu_type="universal")

        with (
            patch("app.menu_service.find_menu_slot", return_value=0),
            patch("app.menu_service._write_mmb_databases") as write,
        ):
            result = edit_mmb_menu_entries(
                service, session, [original, cloned], [original]
            )

        self.assertEqual(result, {"menuSlot": 0, "entries": 2})
        records = write.call_args.args[3]
        self.assertEqual([record["title"] for record in records], ["Game One", "Game Two"])
        self.assertEqual({record["diskTitle"] for record in records}, {"GAME DISC"})

    def test_clones_spi_menu_entry_for_second_game_on_same_disk(self):
        original = {
            "title": "Game One", "publisher": "Acornsoft", "filename": "!BOOT",
            "action": "E", "page": "1900", "diskTitle": "GAME DISC", "system": "M",
        }
        cloned = {**original, "title": "Game Two"}
        database, _index = serialise_spi_menu([original])
        service = FakeService(files={"$.GAMDATA": database})
        service.list_directory = lambda _session, _path, slot: {
            "entries": [{"name": "!BOOT", "type": "file"}] if slot == 1 else []
        }
        session = SimpleNamespace(kind="mmb", menu_type="spi-game-menu")

        with (
            patch("app.menu_service.find_menu_slot", return_value=0),
            patch("app.menu_service._write_mmb_databases") as write,
        ):
            result = edit_mmb_menu_entries(
                service, session, [original, cloned], [original]
            )

        self.assertEqual(result, {"menuSlot": 0, "entries": 2})
        records = write.call_args.args[3]
        self.assertEqual([record["title"] for record in records], ["Game One", "Game Two"])
        self.assertTrue(all(record["filename"] == "!BOOT" for record in records))

    def test_update_menu_preserves_an_unreadable_existing_database(self):
        service = FakeService()
        session = SimpleNamespace(menu_type="universal")
        metadata = {
            "title": "Game",
            "publisher": "",
            "filename": "!BOOT",
            "action": "E",
            "page": "1900",
            "diskTitle": "GAME",
            "system": "M",
        }

        with patch("app.menu_service.find_menu_slot", return_value=1):
            with self.assertRaisesRegex(DiskError, "left unchanged"):
                update_menu(service, session, metadata, 0, Path("."))

    def test_tosec_filename_supplies_title_date_and_publisher(self):
        self.assertEqual(
            parse_distribution_filename(
                "Elite, The (1984)(Acornsoft)(GB)[cr Smith].ssd"
            ),
            {
                "title": "The Elite",
                "year": "1984",
                "publisher": "Acornsoft",
                "sourceFilename": (
                    "Elite, The (1984)(Acornsoft)(GB)[cr Smith].ssd"
                ),
            },
        )

    def test_mmb_menu_discovery_reads_catalogues_without_mounting_slots(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "menu.mmb"
            image = bytearray(MMB_HEADER_SIZE + 3 * MMB_SLOT_SIZE)
            for slot in range(3):
                image[16 + slot * 16 + 15] = 0x0F
            names = ["!BOOT", "GAMDATA", "GAMINDX", "PUBDATA", "PUBINDX", "UNIMENU"]
            base = MMB_HEADER_SIZE + MMB_SLOT_SIZE
            image[base + 256 + 5] = len(names) * 8
            for offset, name in enumerate(names):
                start = base + 8 + offset * 8
                image[start : start + 7] = name.encode("latin-1").ljust(7)
                image[start + 7] = ord("$")
            path.write_bytes(image)
            session = ImageSession("test", path.name, "mmb", path)
            service = DiskService(root)

            self.assertEqual(find_menu_slot(service, session), 1)

    def test_every_recognised_menu_in_a_mixed_mmb_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "mixed-menu.mmb"
            image = bytearray(MMB_HEADER_SIZE + 3 * MMB_SLOT_SIZE)
            for slot in range(3):
                image[16 + slot * 16 + 15] = 0x0F

            def catalogue(slot, names):
                base = MMB_HEADER_SIZE + slot * MMB_SLOT_SIZE
                image[base + 256 + 5] = len(names) * 8
                for offset, name in enumerate(names):
                    start = base + 8 + offset * 8
                    image[start : start + 7] = name.encode("latin-1").ljust(7)
                    image[start + 7] = ord("$")

            catalogue(0, ["!BOOT", "DISCCAT", "GO-DTOP", "GO-MMC"])
            catalogue(
                1,
                ["!BOOT", "EGAMDAT", "EGAMIDX", "EPUBDAT", "EPUBIDX", "UNMNU4R"],
            )
            path.write_bytes(image)
            session = ImageSession("test", path.name, "mmb", path)
            service = DiskService(root)

            self.assertEqual(
                installed_mmb_menus(service, session),
                [
                    {"slot": 1, "type": "universal-4r"},
                    {"slot": 0, "type": "mmc-desktop"},
                ],
            )

    def test_copied_dfs_items_are_analysed_without_reopening_the_disk(self):
        service = FakeService()
        session = SimpleNamespace()
        items = [
            {
                "sourceName": "!BOOT",
                "dst": "$.GAME.!BOOT",
                "load": 0,
                "exec": 0,
                "data": b'*BASIC\rCHAIN "GAME"\r',
            },
            {
                "sourceName": "GAME",
                "dst": "$.GAME.GAME",
                "load": 0x1900,
                "exec": 0,
                "data": b"\r\x00\x0a",
            },
        ]

        metadata = analyse_copied_dfs_items(service, session, 1, items)

        self.assertEqual(metadata["filename"], "!BOOT")
        self.assertEqual(metadata["action"], "E")
        self.assertTrue(metadata["launchObvious"])

    def test_adfs_boot_selects_the_menu_directory_before_chaining(self):
        self.assertEqual(
            _adfs_boot_content("$.Games"),
            b'DIR $.Games\rCH."UNIMENU"\r',
        )

    def test_adfs_menu_page_comes_from_selected_chain_file(self):
        service = FakeService(entries=[
            {"name": "SSDMENU", "type": "file", "load": 0x1900},
        ])
        page, evidence, applicable = _adfs_launch_page(
            service, SimpleNamespace(), "$.GAME", "SSDMENU", ""
        )

        self.assertEqual(page, "1900")
        self.assertTrue(applicable)
        self.assertIn("saved at &1900", evidence)

    def test_adfs_exec_menu_page_follows_relative_chain(self):
        service = FakeService(
            entries=[
                {"name": "!BOOT", "type": "file", "load": 0},
                {"name": "LOADER", "type": "file", "load": 0xE00},
            ],
            files={"$.GAME.!BOOT": b'*BASIC\rCHAIN "LOADER"\r'},
        )
        page, evidence, applicable = _adfs_launch_page(
            service, SimpleNamespace(), "$.GAME", "!BOOT", "E"
        )

        self.assertEqual(page, "E00")
        self.assertTrue(applicable)
        self.assertIn("chains $.GAME.LOADER", evidence)

    def test_menu_data_round_trip(self):
        entries = [{
            "title": "Arcade Soccer",
            "publisher": "4th Dimension",
            "filename": "ARCADES",
            "action": "",
            "page": "E",
            "diskTitle": "GAME DISC",
        }]
        data, index = serialise_menu(entries, system="M")

        self.assertIn(b",ARCADES,M,E,GAME DISC", data)
        self.assertEqual(parse_menu_data(data)[0]["title"], "Arcade Soccer")
        self.assertEqual(parse_menu_data(data)[0]["page"], "E00")
        self.assertEqual(len(index), len(build_index([data.rstrip(b"\r\n")])))

    def test_first_menu_record_preserves_exec_after_system_marker(self):
        entries = [{
            "title": "Boot game",
            "publisher": "Publisher",
            "filename": "!BOOT",
            "action": "E",
            "page": "1900",
            "diskTitle": "GAME DISC",
        }]

        data, _index = serialise_menu(
            entries,
            system="M",
            preserve_first_action=True,
        )

        self.assertIn(b",!BOOT,ME,19,", data)
        self.assertEqual(parse_menu_data(data)[0]["action"], "E")

    def test_full_page_address_is_encoded_for_the_installed_basic_reader(self):
        entries = [{
            "title": "Arcadians", "publisher": "Acornsoft",
            "filename": "SSDMENU", "action": "", "page": "1900",
            "diskTitle": "ACN-ARCBOXCT",
        }]

        data, _index = serialise_menu(entries, system="M")

        self.assertIn(b",SSDMENU,M,19,ACN-ARCBOXCT", data)
        self.assertEqual(parse_menu_data(data)[0]["page"], "1900")

    def test_legacy_first_boot_record_is_recovered_as_exec(self):
        data = b"Boot game,Publisher,!BOOT,M,1900,GAME DISC\r\n"

        self.assertEqual(parse_menu_data(data)[0]["action"], "E")

    def test_universal_launcher_splits_system_marker_from_first_action(self):
        first = b"fld$(5)=fld$(1)"
        second = b'G$=\xa4luv:\xf2field:E%=\xa42pge:\xe7\xa7"DBMH",fld$(1))>0\x8cfld$(1)=""'
        list_line = b"\xdd\xf2scn:\xe7S%=\xa3 \x8c\xdb"
        program = b"".join((
            b"\x0D\x00\x69" + bytes((len(first) + 4,)) + first,
            b"\x0D\x04\x4C" + bytes((len(list_line) + 4,)) + list_line,
            b"\x0D\x07\xD5" + bytes((len(second) + 4,)) + second,
            b"\x0D\xFF",
        ))

        patched, compatible = _upgrade_universal_launcher_program(program)

        self.assertTrue(compatible)
        self.assertIn(b"fld$(5)=\xc0fld$(1),1)", patched)
        self.assertIn(b"fld$(1)=\xc1fld$(1),2)", patched)
        self.assertIn(list_line + b":\xf1", patched)

    def test_menu_slot_backup_is_read_only_and_ignored_as_installed_menu(self):
        with tempfile.TemporaryDirectory() as directory:
            service = DiskService(Path(directory))
            session = service.create_blank("mmb", "")
            template = Path(__file__).resolve().parents[1] / "app/assets/menu_templates/universal.ssd"
            service._write_slot(session, 0, template.read_bytes(), "AFF_UNIMENU")
            session.menu_slot = 0
            session.menu_type = "universal"
            session.menu_scanned = True

            result = backup_mmb_menu_slot(service, session, 5)
            slots = service.list_slots(session)

            self.assertEqual(result["backupSlot"], 5)
            self.assertEqual(slots[5]["name"], "MBACKUP-000")
            self.assertFalse(slots[5]["writable"])
            self.assertEqual(service._slot_path(session, 0).read_bytes(), service._slot_path(session, 5).read_bytes())
            self.assertEqual(installed_mmb_menus(service, session), [{"slot": 0, "type": "universal"}])

    def test_spi_menu_data_round_trip_uses_three_fields_and_valid_index(self):
        entries = [
            {
                "title": "Game Two",
                "publisher": "Publisher B",
                "diskTitle": "DISK-TWO",
            },
            {
                "title": "Game One",
                "publisher": "Publisher A",
                "diskTitle": "DISK-ONE",
            },
        ]

        data, index = serialise_spi_menu(entries)
        parsed = parse_spi_menu_data(data)

        self.assertEqual(
            data,
            b"Game One,Publisher A,DISK-ONE\r\nGame Two,Publisher B,DISK-TWO\r\n",
        )
        self.assertTrue(all(len(line.split(b",")) == 3 for line in data.splitlines()))
        self.assertEqual([item["title"] for item in parsed], ["Game One", "Game Two"])
        self.assertTrue(all(item["filename"] == "!BOOT" for item in parsed))
        self.assertTrue(all(item["action"] == "E" for item in parsed))
        self.assertEqual(index, build_index(data.splitlines()))

    def test_spi_menu_signature_is_discovered(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "spi-menu.mmb"
            image = bytearray(MMB_HEADER_SIZE + MMB_SLOT_SIZE)
            image[16 + 15] = 0x0F
            names = [
                "!BOOT", "DOEXEC", "GAMECOL", "GAMDATA",
                "GAMINDX", "PUBDATA", "PUBINDX",
            ]
            base = MMB_HEADER_SIZE
            image[base + 256 + 5] = len(names) * 8
            for offset, name in enumerate(names):
                start = base + 8 + offset * 8
                image[start : start + 7] = name.encode("latin-1").ljust(7)
                image[start + 7] = ord("$")
            path.write_bytes(image)
            session = ImageSession("test", path.name, "mmb", path)
            service = DiskService(root)

            self.assertEqual(
                installed_mmb_menus(service, session),
                [{"slot": 0, "type": "spi-game-menu"}],
            )

    def test_multiple_titles_can_share_one_disk_or_directory(self):
        entries = [
            {
                "title": title,
                "publisher": "Publisher",
                "filename": filename,
                "action": action,
                "page": page,
                "diskTitle": "$.Games.COMPIL",
            }
            for title, filename, action, page in (
                ("Game One", "GAME1", "", "E"),
                ("Game Two", "GAME2", "R", "19"),
            )
        ]

        data, _index = serialise_menu(entries, system="H", preserve_order=True)
        parsed = parse_menu_data(data)

        self.assertEqual([item["title"] for item in parsed], ["Game One", "Game Two"])
        self.assertEqual([item["diskTitle"] for item in parsed], ["$.Games.COMPIL"] * 2)
        self.assertEqual([item["page"] for item in parsed], ["E00", "1900"])

    def test_menu_data_can_preserve_a_manual_title_order(self):
        entries = [
            {
                "title": title,
                "publisher": "Publisher",
                "filename": "LAUNCH",
                "action": "",
                "page": "19",
                "diskTitle": f"$.{title}",
            }
            for title in ("Zulu", "Alpha", "Mike")
        ]

        data, _index = serialise_menu(entries, system="H", preserve_order=True)
        publisher_data, _publisher_index = serialise_menu(
            entries,
            publisher_view=True,
            system="H",
        )

        self.assertEqual(
            [entry["title"] for entry in parse_menu_data(data)],
            ["Zulu", "Alpha", "Mike"],
        )
        self.assertEqual(
            [entry["title"] for entry in parse_menu_data(publisher_data, publisher_view=True)],
            ["Alpha", "Mike", "Zulu"],
        )

    def test_cached_mmb_metadata_is_used_without_reading_disk(self):
        session = SimpleNamespace(
            menu_scanned=True,
            menu_slot=0,
            menu_entries=[{
                "title": "Arcade Soccer",
                "publisher": "4th Dimension",
                "filename": "ARCADES",
                "action": "",
                "page": "E",
                "diskTitle": "GAME DISC",
                "system": "M",
            }],
        )

        metadata = metadata_records_from_mmb_menu(FakeService(), session, 1)[0]

        self.assertEqual(metadata["filename"], "ARCADES")
        self.assertEqual(metadata["publisher"], "4th Dimension")
        self.assertEqual(metadata["action"], "")
        self.assertEqual(metadata["page"], "E00")
        self.assertTrue(metadata["fromMmbMenu"])
        self.assertEqual(metadata["confidence"], 100)
        self.assertFalse(metadata["ambiguous"])
        self.assertTrue(metadata["launchObvious"])

    def test_mmb_menu_fields_are_preserved_for_the_copied_adfs_directory(self):
        metadata = mmb_metadata_for_adfs(
            {
                "title": "Menu title",
                "publisher": "Menu publisher",
                "filename": "LOADER",
                "action": "R",
                "page": "1D",
                "diskTitle": "MMB TITLE",
                "launchObvious": True,
                "ambiguous": False,
                "fromMmbMenu": True,
                "warnings": [],
            },
            [
                {
                    "name": "LOADER",
                    "sourceName": "LOADER",
                    "path": "$.Games.DISC-0001",
                }
            ],
            "$.Games.DISC-0001",
            {
                "title": "Catalogue guess",
                "publisher": "",
                "action": "",
            },
        )

        self.assertEqual(metadata["title"], "Menu title")
        self.assertEqual(metadata["publisher"], "Menu publisher")
        self.assertEqual(metadata["filename"], "LOADER")
        self.assertEqual(metadata["action"], "R")
        self.assertEqual(metadata["page"], "1D00")
        self.assertEqual(metadata["path"], "$.Games.DISC-0001")
        self.assertEqual(metadata["diskTitle"], "$.Games.DISC-0001")
        self.assertTrue(metadata["launchObvious"])

    def test_missing_mmb_launcher_uses_obvious_boot_fallback(self):
        metadata = mmb_metadata_for_adfs(
            {
                "title": "Psycastria",
                "publisher": "Audiogenic",
                "filename": "4.SS",
                "action": "",
                "page": "1D",
                "diskTitle": "AUI-PPACK2",
                "launchObvious": True,
                "ambiguous": False,
                "fromMmbMenu": True,
                "warnings": [],
                "evidence": ["Loaded the existing MMB record"],
            },
            [
                {
                    "name": "!BOOT",
                    "sourceName": "!BOOT",
                    "path": "$.Games.DISC-0055",
                }
            ],
            "$.Games.DISC-0055",
            {
                "filename": "!BOOT",
                "action": "E",
                "launchObvious": True,
                "ambiguous": False,
                "evidence": ["Found a readable !BOOT command file"],
                "warnings": [],
            },
        )

        self.assertEqual(metadata["title"], "Psycastria")
        self.assertEqual(metadata["filename"], "!BOOT")
        self.assertEqual(metadata["action"], "E")
        self.assertEqual(metadata["page"], "1D00")
        self.assertTrue(metadata["launchObvious"])
        self.assertFalse(metadata["ambiguous"])
        self.assertIn("compilation-menu fallback", metadata["warnings"][0])

    def test_every_existing_menu_title_for_one_disk_is_returned(self):
        session = SimpleNamespace(
            menu_scanned=True,
            menu_slot=0,
            menu_entries=[
                {
                    "title": title,
                    "publisher": publisher,
                    "filename": filename,
                    "action": action,
                    "page": page,
                    "diskTitle": "GAME DISC",
                    "system": "M",
                }
                for title, publisher, filename, action, page in (
                    ("Game One", "Publisher A", "GAME1", "", "E"),
                    ("Game Two", "Publisher B", "GAME2", "R", "19"),
                )
            ],
        )

        metadata = metadata_records_from_mmb_menu(
            FakeService(),
            session,
            1,
        )

        self.assertEqual([item["title"] for item in metadata], ["Game One", "Game Two"])
        self.assertEqual([item["publisher"] for item in metadata], ["Publisher A", "Publisher B"])
        self.assertEqual([item["filename"] for item in metadata], ["GAME1", "GAME2"])
        self.assertEqual([item["action"] for item in metadata], ["", "R"])
        self.assertEqual([item["page"] for item in metadata], ["E00", "1900"])
        self.assertTrue(all(item["menuRecordCount"] == 2 for item in metadata))

    def test_numbered_data_disk_is_linked_to_its_primary_menu_disk(self):
        session = SimpleNamespace(
            menu_scanned=True,
            menu_slot=0,
            menu_entries=[{
                "title": "Superman: The Man of Steel",
                "publisher": "Tynesoft",
                "filename": "LOADER",
                "action": "",
                "page": "E00",
                "diskTitle": "TY-SUPERMAN0",
                "system": "M",
            }],
        )

        class ContinuationService(FakeService):
            def list_slots(self, _session):
                return [
                    {"slot": 0, "name": "MENU", "formatted": True},
                    {"slot": 1, "name": "TY-SUPERMAN2", "formatted": True},
                ]

        metadata = continuation_metadata_from_mmb_menu(
            ContinuationService(),
            session,
            1,
        )

        self.assertTrue(metadata["skipMenu"])
        self.assertEqual(metadata["continuationOf"], "TY-SUPERMAN0")
        self.assertEqual(metadata["continuationTitle"], "Superman: The Man of Steel")

    def test_readable_boot_is_preferred_as_an_exec_launcher(self):
        service = FakeService(
            entries=[
                {"name": "!BOOT", "type": "file", "load": "FFFF0000"},
                {"name": "GAME", "type": "file", "load": "1900"},
            ],
            files={"$.GAME.!BOOT": b"*BASIC\rCHAIN \"GAME\"\r"},
        )

        metadata = analyse_adfs_directory(service, SimpleNamespace(), "$.GAME")

        self.assertEqual(metadata["filename"], "!BOOT")
        self.assertEqual(metadata["action"], "E")
        self.assertTrue(metadata["launchObvious"])
        self.assertFalse(metadata["ambiguous"])

    def test_binary_boot_falls_back_to_a_conventional_launcher(self):
        service = FakeService(
            entries=[
                {"name": "!BOOT", "type": "file", "load": "0"},
                {"name": "LOADER", "type": "file", "load": "&1900"},
                {"name": "OTHER", "type": "file", "load": "&1900"},
            ],
            files={"$.GAME.!BOOT": b"\x00\x01\x02"},
        )

        metadata = analyse_adfs_directory(service, SimpleNamespace(), "$.GAME")

        self.assertEqual(metadata["filename"], "LOADER")
        self.assertEqual(metadata["action"], "")
        self.assertTrue(metadata["launchObvious"])
        self.assertFalse(metadata["ambiguous"])

    def test_loader_priority_is_obvious_when_start_is_also_present(self):
        service = FakeService(
            entries=[
                {"name": "START", "type": "file", "load": "&1900"},
                {"name": "LOADER", "type": "file", "load": "&1900"},
            ],
        )

        metadata = analyse_adfs_directory(service, SimpleNamespace(), "$.GAME")

        self.assertEqual(metadata["filename"], "LOADER")
        self.assertEqual(metadata["action"], "")
        self.assertTrue(metadata["launchObvious"])
        self.assertFalse(metadata["ambiguous"])
        self.assertIn("selected by launcher priority", metadata["warnings"][0])

    def test_ssdmenu_basic_program_is_selected_with_chain(self):
        service = FakeService(
            entries=[
                {"name": "SSDMENU", "type": "file", "load": "&1900"},
                {"name": "README", "type": "file", "load": "0"},
            ],
            files={"$.GAME.SSDMENU": b"\x0d\x00\x0a\xf4"},
        )

        metadata = analyse_adfs_directory(service, SimpleNamespace(), "$.GAME")

        self.assertEqual(metadata["filename"], "SSDMENU")
        self.assertEqual(metadata["action"], "")
        self.assertTrue(metadata["launchObvious"])

    def test_ssdmenu_chain_takes_priority_over_readable_boot(self):
        service = FakeService(
            entries=[
                {"name": "!BOOT", "type": "file", "load": "0"},
                {"name": "SSDMENU", "type": "file", "load": "&1900"},
            ],
            files={"$.GAME.!BOOT": b'*BASIC\rCHAIN "OTHER"\r'},
        )

        metadata = analyse_adfs_directory(service, SimpleNamespace(), "$.GAME")

        self.assertEqual(metadata["filename"], "SSDMENU")
        self.assertEqual(metadata["action"], "")
        self.assertEqual(metadata["page"], "1900")
        self.assertIn("priority over !BOOT", metadata["evidence"][0])

    def test_plain_menu_command_file_is_selected_with_exec(self):
        service = FakeService(
            entries=[
                {"name": "MENU", "type": "file", "load": "0"},
                {"name": "PROGRAM", "type": "file", "load": "&1900"},
            ],
            files={"$.GAME.MENU": b'*BASIC\rCHAIN \"PROGRAM\"\r'},
        )

        metadata = analyse_adfs_directory(service, SimpleNamespace(), "$.GAME")

        self.assertEqual(metadata["filename"], "MENU")
        self.assertEqual(metadata["action"], "E")
        self.assertTrue(metadata["launchObvious"])

    def test_group_holders_are_expanded_but_dfs_subpaths_are_not(self):
        listings = {
            "$.Games": [
                {"name": "GAMES1", "type": "dir"},
                {"name": "HOMEBREW", "type": "dir"},
            ],
            "$.Games.GAMES1": [
                {"name": f"DISC-{number:04d}", "type": "dir"}
                for number in range(3)
            ],
            "$.Games.HOMEBREW": [
                {"name": "eE", "type": "dir"},
                {"name": "eT", "type": "dir"},
            ],
        }

        class GroupedService:
            def list_directory(self, _session, path, _slot):
                return {"entries": listings[path]}

        paths, holders = discover_adfs_menu_paths(
            GroupedService(),
            SimpleNamespace(),
            "$.Games",
        )

        self.assertEqual(holders, ["$.Games.GAMES1"])
        self.assertEqual(
            paths,
            [
                "$.Games.GAMES1.DISC-0000",
                "$.Games.GAMES1.DISC-0001",
                "$.Games.GAMES1.DISC-0002",
                "$.Games.HOMEBREW",
            ],
        )

    def test_generic_adfs_directory_does_not_trigger_a_useless_online_lookup(self):
        metadata = {
            "title": "0184",
            "diskTitle": "$.Games.GAMES4.DISC-0184",
            "ambiguous": True,
            "warnings": [],
            "matches": [],
        }

        enriched = enrich_if_ambiguous(metadata)

        self.assertEqual(enriched["matches"], [])
        self.assertIn("generic directory name", enriched["warnings"][0])

    def test_adfs_menu_paths_follow_directory_and_launcher_moves(self):
        entries = [
            {
                "title": "Nested game",
                "publisher": "",
                "filename": "LOADER",
                "action": "",
                "page": "19",
                "diskTitle": "$.Games.GAMES1.DISC-0001",
            },
            {
                "title": "Renamed launcher",
                "publisher": "",
                "filename": "!BOOT",
                "action": "E",
                "page": "19",
                "diskTitle": "$.Games.DISC-0002",
            },
        ]
        moves = [
            {
                "source": "$.Games.GAMES1",
                "destination": "$.Library.GROUP1",
                "isDirectory": True,
            },
            {
                "source": "$.Games.DISC-0002.!BOOT",
                "destination": "$.Games.DISC-0002.START",
                "isDirectory": False,
            },
        ]

        changed = _rewrite_adfs_menu_records(entries, moves)

        self.assertEqual(changed, 2)
        self.assertEqual(
            entries[0]["diskTitle"],
            "$.Library.GROUP1.DISC-0001",
        )
        self.assertEqual(entries[1]["diskTitle"], "$.Games.DISC-0002")
        self.assertEqual(entries[1]["filename"], "START")


if __name__ == "__main__":
    unittest.main()
