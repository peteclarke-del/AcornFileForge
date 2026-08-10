from __future__ import annotations

import os
import re
import secrets
from pathlib import Path

from flask import Flask, g, jsonify, request

from .disk_service import SESSION_OWNER, DiskError, DiskService
from .operations import OperationRegistry
from .routes.files import create_files_blueprint
from .routes.hex_editor import create_hex_editor_blueprint
from .routes.catalog import create_catalog_blueprint
from .routes.images import create_images_blueprint
from .routes.menus import create_menus_blueprint
from .routes.mmb import create_mmb_blueprint
from .routes.tools import create_tools_blueprint
from .routes.rom_tools import create_rom_tools_blueprint


ROOT = Path(__file__).resolve().parent
WORK_DIR = Path(os.environ.get("ACORN_FILE_FORGE_WORK_DIR", ROOT.parent / "work"))
MENU_TEMPLATE_DIR = ROOT / "assets" / "menu_templates"


IMAGE_MUTATIONS = {
    "images.rename_image": "renaming the image",
    "images.set_hardware_profile": "changing the hardware profile",
    "images.configure_rom_layout": "changing the ROM layout",
    "images.prepare_image_download": "finalising the image for download",
    "images.compact": "compacting the filesystem",
    "files.rename": "renaming an item",
    "files.move_items": "moving items",
    "files.move_dfs_items": "moving DFS files between catalogue groups",
    "files.delete": "deleting an item",
    "files.mkdir": "creating a folder",
    "files.lock": "changing file protection",
    "files.put_file": "adding a file",
    "files.append_blank_rom_bank": "appending a blank ROM bank",
    "files.move_rom_banks": "moving ROM banks",
    "files.put_folder": "importing a host folder",
    "files.extract_to_directory": "extracting an image",
    "mmb.insert_slot_upload": "inserting a disk",
    "mmb.insert_many_slot_uploads": "inserting disks",
    "mmb.insert_slot_from_image": "copying a disk into a slot",
    "mmb.create_blank_slot": "creating a blank disk",
    "mmb.clear_slot": "ejecting a disk",
    "mmb.move_slot": "moving an MMB slot",
    "mmb.paste_slots": "pasting MMB slots",
    "mmb.build_slots_from_files": "building MMB disks from files",
    "mmb.protect_slot": "changing slot protection",
    "mmb.protect_many_slots": "changing slot protection",
    "menus.add_menu_entry": "adding a menu entry",
    "menus.install_menu": "installing a menu",
    "menus.configure_menu_page": "changing the menu PAGE",
    "menus.audit_menu_pages": "auditing the menu",
    "menus.backup_menu_slot": "backing up the menu slot",
    "menus.restore_menu_slot": "restoring the menu slot",
    "menus.refresh_menu": "refreshing the menu catalogue",
    "menus.build_adfs_menu": "creating an ADFS menu",
    "menus.add_adfs_menu_entry": "adding an ADFS menu entry",
    "menus.add_adfs_menu_entries": "adding ADFS menu entries",
    "menus.reorder_adfs_menu_entries": "reordering the ADFS menu",
    "menus.audit_adfs_pages": "auditing the ADFS menu",
    "menus.rebuild_mmb_menu": "rebuilding the MMB menu",
    "menus.edit_mmb_menu": "editing the MMB menu",
    "menus.cleanup_mmb_duplicates": "cleaning duplicate MMB menu records",
    "tools.apply_manifest": "applying reviewed menu metadata",
    "tools.save_inspected_text": "editing a text file",
    "tools.repair_health": "applying a safe image-health repair",
    "hex_editor.write_hex": "editing raw image bytes",
    "rom_tools.rom_project": "editing ROM project notes",
    "rom_tools.rom_patch": "applying a ROM patch",
    "rom_tools.rom_repair": "repairing ROM metadata",
    "rom_tools.rom_build": "building a ROM image",
    "catalog.install": "installing software from the Online Library",
}

TRANSFER_MUTATIONS = {
    "files.transfer": "copying files",
    "files.transfer_slot_to_directory": "copying an MMB disk to ADFS",
    "files.transfer_mmb_batch_to_adfs": "copying MMB disks to ADFS",
    "files.transfer_image_to_directory": "extracting an image to ADFS",
}


def create_app() -> Flask:
    application = Flask(__name__, static_folder="static", static_url_path="")
    max_upload_gib = max(1, int(os.environ.get("ACORN_MAX_UPLOAD_GIB", "8")))
    application.config["MAX_CONTENT_LENGTH"] = max_upload_gib * 1024 * 1024 * 1024
    service = DiskService(WORK_DIR)
    operations = OperationRegistry(WORK_DIR / "operations.json")

    @application.before_request
    def establish_browser_owner():
        cookie_owner = request.cookies.get("acorn_file_forge_owner", "")
        browser_owner = request.headers.get("X-Acorn-Session-Owner", "")
        owner_id = (
            browser_owner
            if re.fullmatch(r"[A-Za-z0-9_-]{32,64}", browser_owner)
            else cookie_owner
        )
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,64}", owner_id):
            owner_id = secrets.token_urlsafe(32)
        g.set_owner_cookie = cookie_owner != owner_id
        g.session_owner_token = SESSION_OWNER.set(owner_id)
        g.session_owner_id = owner_id

    @application.before_request
    def checkpoint_image_mutation():
        """Create one undo point for every image-changing API request."""
        reason = IMAGE_MUTATIONS.get(request.endpoint)
        image_id = request.view_args.get("image_id") if request.view_args else None
        if request.endpoint in TRANSFER_MUTATIONS:
            data = request.get_json(silent=True) or {}
            image_id = data.get("targetImage")
            reason = TRANSFER_MUTATIONS[request.endpoint]
        if not reason or not image_id:
            return None
        session = service.get(str(image_id))
        g.undo_checkpoint_session = session
        g.undo_checkpoint_token = service.begin_automatic_checkpoint(session, reason)
        return None

    @application.teardown_request
    def release_browser_owner(_error=None):
        token = getattr(g, "session_owner_token", None)
        if token is not None:
            SESSION_OWNER.reset(token)

    application.register_blueprint(
        create_images_blueprint(service, ROOT / "static", operations)
    )
    application.register_blueprint(create_files_blueprint(service, WORK_DIR, operations))
    application.register_blueprint(create_catalog_blueprint(service, WORK_DIR))
    application.register_blueprint(create_mmb_blueprint(service))
    application.register_blueprint(create_hex_editor_blueprint(service))
    application.register_blueprint(create_tools_blueprint(service, WORK_DIR, operations))
    application.register_blueprint(create_rom_tools_blueprint(service, ROOT))
    application.register_blueprint(
        create_menus_blueprint(service, MENU_TEMPLATE_DIR)
    )

    @application.errorhandler(DiskError)
    def disk_error(error):
        return jsonify(error=str(error)), 400

    @application.errorhandler(413)
    def too_large(_error):
        return jsonify(error=f"The image exceeds the {max_upload_gib} GiB upload limit."), 413

    @application.after_request
    def prevent_stale_frontend_assets(response):
        checkpoint_session = getattr(g, "undo_checkpoint_session", None)
        checkpoint_token = getattr(g, "undo_checkpoint_token", None)
        if checkpoint_session is not None and checkpoint_token is not None:
            try:
                if response.status_code >= 400:
                    service.rollback_automatic_checkpoint(checkpoint_session, checkpoint_token)
                else:
                    service.finish_automatic_checkpoint(checkpoint_session, checkpoint_token)
            except Exception:
                application.logger.exception("Could not finalise the automatic image checkpoint")
        response.headers["X-Acorn-Session-Owner"] = g.session_owner_id
        if getattr(g, "set_owner_cookie", False):
            response.set_cookie(
                "acorn_file_forge_owner",
                g.session_owner_id,
                max_age=365 * 24 * 60 * 60,
                httponly=True,
                samesite="Strict",
            )
        if request.path == "/" or request.path.endswith((".js", ".css")):
            response.headers["Cache-Control"] = "no-store, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    return application


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8666, threaded=True)
