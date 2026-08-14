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
from .routes.effects import mutation_for


ROOT = Path(__file__).resolve().parent
WORK_DIR = Path(os.environ.get("ACORN_FILE_FORGE_WORK_DIR", ROOT.parent / "work"))
MENU_TEMPLATE_DIR = ROOT / "assets" / "menu_templates"


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
        mutation = mutation_for(application.view_functions.get(request.endpoint))
        if mutation is None:
            return None
        image_id = request.view_args.get("image_id") if request.view_args else None
        if mutation.target == "targetImage":
            data = request.get_json(silent=True) or {}
            image_id = data.get("targetImage")
        if not image_id:
            return None
        session = service.get(str(image_id))
        g.undo_checkpoint_session = session
        g.undo_checkpoint_token = service.begin_automatic_checkpoint(
            session, mutation.reason
        )
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
    application.register_blueprint(create_tools_blueprint(service, operations))
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
