from __future__ import annotations

from flask import request


def payload() -> dict:
    return request.get_json(force=True, silent=False)


def optional_int(value) -> int | None:
    if value in (None, "", "null"):
        return None
    return int(value)
