import io
import copy
import tempfile
import unittest
import zipfile
from unittest.mock import Mock, patch

from flask import Flask

from app.catalog_service import CatalogueService, DEFAULT_SOURCES, archive_members
from app.disk_service import DiskError
from app.routes.catalog import (
    _catalogue_identities,
    _preferred_disk_members,
    _spark_metadata,
    create_catalog_blueprint,
)


def source(source_id):
    return next(item for item in DEFAULT_SOURCES if item["id"] == source_id)


class CatalogueServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.service = CatalogueService(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    @patch("app.catalog_service.urllib.request.urlopen")
    def test_fetch_rejects_non_http_url_before_opening_it(self, urlopen):
        with self.assertRaisesRegex(DiskError, "invalid URL"):
            self.service._fetch("file:///etc/passwd")
        urlopen.assert_not_called()

    def test_online_install_source_name_matches_catalogue_title(self):
        self.assertIn("jetpac", _catalogue_identities("Jetpac (Ultimate Play The Game).ssd"))
        self.assertTrue(
            _catalogue_identities("Repton 2")
            & _catalogue_identities("REPTON-2 (Superior Software).ssd")
        )

    @patch("app.routes.catalog.CatalogueService.search")
    @patch("app.routes.catalog.parse_mmb_menu_data")
    @patch("app.routes.catalog.installed_mmb_menus")
    def test_missing_filter_reads_installed_mmb_menu_titles(self, menus, parse_menu, search):
        service = Mock()
        service.get.return_value = Mock(kind="mmb", slot_source_names={})
        service.list_slots.return_value = []
        service.read_file.return_value = b"menu data"
        menus.return_value = [{"slot": 0, "type": "universal"}]
        parse_menu.return_value = [{"title": "Jetpac", "diskTitle": "JETPAC"}]
        search.return_value = ([{"title": "Jetpac", "pageUrl": "https://example.test/jetpac", "downloadable": True}], [])
        app = Flask(__name__)
        app.register_blueprint(create_catalog_blueprint(service, self.temporary.name))

        response = app.test_client().get("/api/images/test/catalog/search?scope=missing")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["items"], [])
        service.read_file.assert_called_once_with(service.get.return_value, 0, "$.GAMDATA")

    def test_parses_bbc_micro_download_cards(self):
        body = '''<div class="thumbnail text-center">
          <div class="row-title"><span class="row-title"><a href="game.php?id=7">Frak!</a></span></div>
          <div class="row-pub"><a>Acornsoft</a></div><div class="row-dt"><a>1984</a></div>
          <a href="gameimg/discs/7/frak.ssd">Download</a></div></div>'''
        rows = self.service._parse_thumbnail_cards(source("bbcmicro"), body, {})
        self.assertEqual(rows[0]["title"], "Frak!")
        self.assertEqual(rows[0]["publisher"], "Acornsoft")
        self.assertEqual(rows[0]["year"], "1984")
        self.assertTrue(rows[0]["downloadUrl"].endswith("/gameimg/discs/7/frak.ssd"))

    def test_parses_electron_featured_disc(self):
        body = '''tabulatE("alligata", "green", "img", "Blagger-1", "BLAGGER V1",
          "alligata", "-", "Arcade", "R. Goodley", 150, 224, "1983", "", "Available",
          "Electron, BBC B", "Haven DFS", "FC", "Review");'''
        rows = self.service._parse_function_calls(source("electron-world"), body, {})
        self.assertEqual(rows[0]["title"], "BLAGGER V1")
        self.assertEqual(rows[0]["machines"], ["electron"])
        self.assertTrue(rows[0]["downloadUrl"].endswith("/alligata/DFS/Blagger-1.zip"))

    def test_electron_world_page_returns_only_real_downloads_as_installable(self):
        body = '''<h6 id="cat_table_title_bar">ACORNSOFT</h6>
          <section id="Locked_1001"><b>LOCKED TITLE</b><p>Downloads:<a href="c-dvd.html">DVD</a></p></section>
          <section id="Public_1001"><b>PUBLIC TITLE</b><p>Release Date:<br/>1st May 1987</p>
          <a href="../../../download/electron/acornsoft/tapes/Public.uef">Tape</a></section>'''
        rows = self.service._parse_section_catalogue(
            source("electron-world"),
            body,
            {"url": "https://www.acornelectron.co.uk/profs/electron/cats/acornsoft.html", "category": "Professional Releases"},
        )
        self.assertFalse(rows[0]["downloadable"])
        self.assertTrue(rows[1]["downloadable"])
        self.assertEqual(rows[1]["year"], "1987")

    def test_everygamegoing_machine_page_uses_configured_profile(self):
        body = '''<td><a href="/litem/Frak/123/">Frak!</a> (1st May 1984) (Aardvark)
          (Acorn Electron, Cassette, English)</td>'''
        rows = self.service._parse_item_rows(
            source("everygamegoing"), body,
            {"profile": {"label": "Acorn Electron", "machines": ["electron"]}},
        )
        self.assertEqual(rows[0]["title"], "Frak!")
        self.assertEqual(rows[0]["publisher"], "Aardvark")
        self.assertEqual(rows[0]["machines"], ["electron"])

    def test_everygamegoing_urls_and_machine_ids_come_from_source_settings(self):
        configured = copy.deepcopy(source("everygamegoing"))
        configured["url"] = "https://catalogue.example/"
        configured["options"]["landingTemplate"] = "machines/{machineId}/software.html"
        configured["options"]["machineProfiles"] = {
            "electron": {"ids": [99], "label": "Configured machine"},
        }
        requested = []
        self.service._fetch = lambda url, **_options: requested.append(url) or (
            b'<td><a href="/litem/Game/1/">Game</a> (1985) (Publisher)</td>'
        )
        rows = self.service._load_machine_index(configured, "", "electron")
        self.assertEqual(requested, ["https://catalogue.example/machines/99/software.html"])
        self.assertEqual(rows[0]["description"].split(".")[0], "Configured machine")

    def test_everygamegoing_item_without_supported_media_is_suppressed(self):
        row = {
            "pageUrl": "https://www.everygamegoing.com/litem/No-Media/1/",
            "description": "Acorn Electron. Download availability is checked when installed.",
            "resolverOptions": {"downloadPathContains": "/download/"},
        }
        self.service._fetch = lambda *_args, **_kwargs: b'<a href="/images/cover.jpg">Cover</a>'
        self.assertIsNone(self.service._resolve_row(row))

    def test_everygamegoing_item_accepts_only_download_media_paths(self):
        row = {
            "pageUrl": "https://www.everygamegoing.com/litem/Frak/1/",
            "description": "Acorn Electron. Download availability is checked when installed.",
            "resolverOptions": {"downloadPathContains": "/download/"},
        }
        self.service._fetch = lambda *_args, **_kwargs: (
            b'<a href="/gallery/not-a-download.zip">Gallery</a>'
            b'<a href="/download/electron/aardvark/Frak.zip">Download</a>'
        )
        resolved = self.service._resolve_row(row)
        self.assertEqual(
            resolved["downloadUrl"],
            "https://www.everygamegoing.com/download/electron/aardvark/Frak.zip",
        )

    def test_parses_riscos_package_feed(self):
        body = (
            "Package: Blocks\nVersion: 0.15-2\nMaintainer: RISC OS Open\n"
            "Description: falling blocks\nURL: https://example.test/Blocks.zip\n\n"
        )
        rows = self.service._parse_package_paragraphs(source("riscos-rool"), body, {})
        self.assertEqual(rows[0]["artifactType"], "riscos-package")
        self.assertEqual(rows[0]["version"], "0.15-2")

    def test_query_media_tiles_extract_configured_download_parameter(self):
        body = '''<td><a href="https://player.example/run?dfs&amp;disk0=https://cdn.example/Pyjamarama.ssd"><img></a>
          <br>Pyjamarama<br><span><a href="https://project.example/pyjamarama">Project page</a></span></td>'''
        rows = self.service._parse_query_media_tiles(source("0xc0de6502"), body, {})
        self.assertEqual(rows[0]["title"], "Pyjamarama")
        self.assertEqual(rows[0]["downloadUrl"], "https://cdn.example/Pyjamarama.ssd")
        self.assertEqual(rows[0]["pageUrl"], "https://project.example/pyjamarama")

    def test_html_cards_use_configured_upload_resolver(self):
        body = '''<div class="game_cell"><div class="game_title"><a href="https://maker.example/game">Electron Game</a></div>
          <div class="game_text">For the Acorn Electron</div><div class="game_author"><a>Homebrew Author</a></div></div>'''
        rows = self.service._parse_html_cards(source("itch-acorn"), body, {})
        self.assertEqual(rows[0]["publisher"], "Homebrew Author")
        self.assertEqual(rows[0]["resolver"], "upload-buttons")

    def test_upload_resolver_suppresses_unrelated_archives_and_keeps_acorn_media(self):
        configured = source("itch-acorn")
        row = self.service._parse_html_cards(configured, '''<div class="game_cell"><div class="game_title">
          <a href="https://maker.example/electron-game">Electron Game</a></div>
          <div class="game_text">For the Acorn Electron</div><div class="game_author">Maker</div></div>''', {})[0]
        detail = '''<div class="upload"><a data-upload_id="123">Download</a><div><strong title="Electron Game.ssd">Electron Game.ssd</strong></div></div>
          <div class="upload"><a data-upload_id="456">Download</a><div><strong title="Windows build.exe">Windows build.exe</strong></div></div>'''
        resolved = self.service._resolve_upload_buttons(row, detail)
        self.assertEqual(resolved["downloadRequests"], [{
            "url": "https://maker.example/electron-game/file/123?source=view_game&as_props=1",
            "filename": "Electron Game.ssd",
        }])

    def test_page_loader_uses_configured_machine_query(self):
        configured = copy.deepcopy(source("itch-acorn"))
        requested = []
        self.service._fetch = lambda url, **_options: requested.append(url) or b""
        self.service._load_page(configured, "arcade", "bbc-b")
        self.assertEqual(requested, ["https://itch.io/search?q=bbc+micro+arcade"])

    def test_source_configuration_is_validated_and_persisted(self):
        rows = self.service.save_sources([{
            "id": "mine", "name": "Mine", "type": "links",
            "url": "https://example.test/catalogue", "machines": ["bbc-b"], "enabled": True,
        }])
        self.assertEqual(rows[0]["id"], "mine")
        self.assertEqual(
            CatalogueService(self.temporary.name).sources()[0]["url"],
            "https://example.test/catalogue",
        )
        self.assertIn("everygamegoing", {row["id"] for row in CatalogueService(self.temporary.name).sources()})
        self.assertNotIn("dcford", {row["id"] for row in CatalogueService(self.temporary.name).sources()})
        with self.assertRaises(DiskError):
            self.service.save_sources([{"name": "Unsafe", "url": "file:///etc/passwd"}])

    def test_catalogue_result_survives_service_restart(self):
        token = "a" * 32
        expected = {"title": "Chuckie Egg", "downloadUrl": "https://example.test/chuckie.ssd"}
        self.service._remember_item(token, expected)

        restarted = CatalogueService(self.temporary.name)

        self.assertEqual(restarted.item(token), expected)

    def test_new_default_settings_are_merged_without_overwriting_configuration(self):
        configured = copy.deepcopy(source("everygamegoing"))
        configured["options"].pop("itemPathPrefix")
        configured["options"]["landingTemplate"] = "custom/{machineId}/"
        self.service.save_sources([configured])
        loaded = next(row for row in self.service.sources() if row["id"] == "everygamegoing")
        self.assertEqual(loaded["options"]["itemPathPrefix"], "/litem/")
        self.assertEqual(loaded["options"]["landingTemplate"], "custom/{machineId}/")

    def test_bbc_search_is_sent_to_the_complete_remote_catalogue(self):
        body = b'''<div class="thumbnail"><div class="row-title"><a href="game.php?id=1">Frak!</a></div>
          <div class="row-pub"><a>Acornsoft</a></div><div class="row-dt"><a>1984</a></div>
          <a href="gameimg/discs/1/frak.ssd">Download</a></div></div>'''
        requested = []
        self.service.save_sources([source("bbcmicro")])
        self.service._fetch = lambda url, **_options: requested.append(url) or body
        rows, failures = self.service.search("Frak", "bbc-b")
        self.assertFalse(failures)
        self.assertEqual(rows[0]["title"], "Frak!")
        self.assertIn("search=frak", requested[0])

    def test_pipeline_uses_configuration_not_catalogue_identity(self):
        configured = copy.deepcopy(source("bbcmicro"))
        configured.update(id="arbitrary-provider", name="Arbitrary Provider", url="https://example.test/")
        self.service.save_sources([configured])
        self.service._fetch = lambda *_args, **_options: b'''<div class="thumbnail">
          <div class="row-title"><a href="game.php?id=1">Configured Game</a></div>
          <a href="files/configured.ssd">Download</a></div></div>'''
        rows, failures = self.service.search("Configured", "bbc-b", {"arbitrary-provider"})
        self.assertFalse(failures)
        self.assertEqual(rows[0]["title"], "Configured Game")
        self.assertEqual(rows[0]["sourceName"], "Arbitrary Provider")

    def test_archive_members_rejects_traversal_and_keeps_images(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("games/frak.ssd", b"disk")
            archive.writestr("../escape.ssd", b"bad")
        self.assertEqual(
            archive_members("games.zip", buffer.getvalue()),
            [("games/frak.ssd", b"disk")],
        )

    def test_native_disk_is_preferred_over_tape_variant_in_same_download(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("Repton-2-Upgraded.ssd", b"ssd")
            archive.writestr("Repton-2-Upgraded.uef", b"uef")
        self.assertEqual(
            _preferred_disk_members("repton-2.zip", buffer.getvalue()),
            [("Repton-2-Upgraded.ssd", b"ssd")],
        )

    def test_sparkfs_metadata_is_preserved(self):
        import struct
        payload = b"ARC0" + struct.pack("<III", 0xFFFABC00, 0x12345678, 3)
        extra = struct.pack("<HH", 0x4341, len(payload)) + payload
        load, execute, filetype = _spark_metadata(extra)
        self.assertEqual(load, hex(0xFFFABC00))
        self.assertEqual(execute, hex(0x12345678))
        self.assertEqual(filetype, "ABC")


if __name__ == "__main__":
    unittest.main()
