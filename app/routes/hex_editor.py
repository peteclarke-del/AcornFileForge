from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..disk_service import DiskError, DiskService
from ..hex_service import raw_image_range, search_raw_image, write_raw_image
from .common import payload


def _integer(value: object, label: str, default: int = 0) -> int:
    try:
        return int(value if value not in (None, "") else default)
    except (TypeError, ValueError) as exc:
        raise DiskError(f"The {label} must be a whole number.") from exc


def create_hex_editor_blueprint(service: DiskService) -> Blueprint:
    blueprint = Blueprint("hex_editor", __name__)

    @blueprint.get("/api/images/<image_id>/hex")
    def read_hex(image_id):
        session = service.get(image_id)
        return jsonify(raw_image_range(
            session,
            _integer(request.args.get("offset"), "offset"),
            _integer(request.args.get("length"), "length", 256),
            str(request.args.get("target") or "image"),
        ))

    @blueprint.get("/api/images/<image_id>/hex/search")
    def search_hex(image_id):
        session = service.get(image_id)
        return jsonify(search_raw_image(
            session,
            str(request.args.get("query") or ""),
            str(request.args.get("mode") or "hex"),
            _integer(request.args.get("start"), "start"),
            str(request.args.get("direction") or "forward"),
            str(request.args.get("wrap") or "true").lower() not in {"0", "false", "no"},
            str(request.args.get("target") or "image"),
        ))

    @blueprint.post("/api/images/<image_id>/hex")
    def write_hex(image_id):
        data = payload()
        session = service.get(image_id)
        return jsonify(write_raw_image(
            service,
            session,
            str(data.get("version") or ""),
            data.get("changes"),
            data.get("confirmed") is True,
            str(data.get("target") or "image"),
        ))

    return blueprint
