import io
import copy
import tempfile
import unittest
import zipfile

from app.catalog_service import CatalogueService, DEFAULT_SOURCES, archive_members
from app.disk_service import DiskError
from app.routes.catalog import _spark_metadata


def source(source_id):
    return next(item for item in DEFAULT_SOURCES if item["id"] == source_id)


class CatalogueServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.service = CatalogueService(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

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
