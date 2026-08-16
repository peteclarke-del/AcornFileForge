from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.routes.effects import (
    ImageMutation,
    effect_for,
    image_mutation,
    mutation_for,
)
try:
    from app.server import create_app
except ModuleNotFoundError:  # Flask is intentionally absent from the light host test env.
    create_app = None


class RouteEffectTests(unittest.TestCase):
    def test_image_mutation_metadata_stays_on_the_registered_view(self) -> None:
        @image_mutation("changing a test image", target="targetImage")
        def view():
            return None

        self.assertEqual(
            mutation_for(view),
            ImageMutation("changing a test image", target="targetImage"),
        )

    @unittest.skipIf(create_app is None, "Flask is available in the application container")
    def test_every_checkpointed_route_owns_its_metadata(self) -> None:
        required = {
            "catalog.install",
            "files.append_blank_rom_bank", "files.create_empty_file",
            "files.delete", "files.extract_to_directory", "files.lock",
            "files.mkdir", "files.move_dfs_items", "files.move_items",
            "files.move_rom_banks", "files.put_file", "files.put_folder",
            "files.rename", "files.save_archive_inspect", "files.transfer",
            "files.transfer_image_to_directory", "files.transfer_mmb_batch_to_adfs",
            "files.transfer_slot_to_directory", "hex_editor.write_file_hex",
            "hex_editor.write_hex", "images.compact", "images.configure_rom_layout",
            "images.configure_romfs", "images.prepare_image_download",
            "images.rename_image", "images.set_hardware_profile",
            "menus.add_adfs_menu_entries", "menus.add_adfs_menu_entry",
            "menus.add_menu_entry", "menus.audit_adfs_pages",
            "menus.audit_menu_pages", "menus.backup_menu_slot",
            "menus.build_adfs_menu", "menus.cleanup_mmb_duplicates",
            "menus.configure_menu_page", "menus.edit_mmb_menu",
            "menus.install_menu", "menus.rebuild_mmb_menu",
            "menus.refresh_menu", "menus.reorder_adfs_menu_entries",
            "menus.restore_menu_slot", "mmb.build_slots_from_files",
            "mmb.clear_slot", "mmb.create_blank_slot", "mmb.insert_many_slot_uploads",
            "mmb.insert_slot_from_image", "mmb.insert_slot_upload", "mmb.move_slot",
            "mmb.paste_slots", "mmb.protect_many_slots", "mmb.protect_slot",
            "rom_tools.rom_build", "rom_tools.rom_patch", "rom_tools.rom_project",
            "rom_tools.rom_repair", "tools.apply_manifest",
            "tools.apply_image_patch",
            "tools.repair_adfs_installations", "tools.repair_health",
            "tools.save_editor_project", "tools.save_inspected_properties",
            "tools.save_inspected_text",
        }
        with tempfile.TemporaryDirectory() as folder, patch(
            "app.server.WORK_DIR", Path(folder)
        ):
            application = create_app()

        missing = sorted(
            endpoint for endpoint in required
            if mutation_for(application.view_functions.get(endpoint)) is None
        )
        self.assertEqual(missing, [])

        transfers = {
            "files.transfer", "files.transfer_image_to_directory",
            "files.transfer_mmb_batch_to_adfs", "files.transfer_slot_to_directory",
        }
        for endpoint in transfers:
            self.assertEqual(
                mutation_for(application.view_functions[endpoint]).target,
                "targetImage",
            )

    @unittest.skipIf(create_app is None, "Flask is available in the application container")
    def test_every_unsafe_route_explicitly_classifies_its_effect(self) -> None:
        with tempfile.TemporaryDirectory() as folder, patch(
            "app.server.WORK_DIR", Path(folder)
        ):
            application = create_app()

        unsafe = {"POST", "PUT", "PATCH", "DELETE"}
        missing = sorted({
            rule.endpoint
            for rule in application.url_map.iter_rules()
            if rule.methods & unsafe
            and effect_for(application.view_functions.get(rule.endpoint)) is None
        })
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
