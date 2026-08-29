from __future__ import annotations

from flask import request

from ..acorn_metadata import engine_address
from ..errors import DiskError


def payload() -> dict:
    return request.get_json(force=True, silent=False)


def optional_int(value) -> int | None:
    if value in (None, "", "null"):
        return None
    return int(value)


def catalogue_address(value) -> str | None:
    """Normalise an address a person typed into an unambiguous engine value.

    Acorn writes addresses in hexadecimal, so every address field in the
    application reads ``1900``, ``&1900`` and ``0x1900`` as the same number.
    The disk engine instead reads an unprefixed number as decimal, so the text
    is parsed here and re-emitted with an explicit ``0x`` prefix before it
    reaches any code that forwards it onward.

    This applies only where a value arrives from a person. Internal callers
    pass addresses the engine already reads unambiguously and must not be
    routed through here.
    """
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return engine_address(text)
    except ValueError as exc:
        raise DiskError(
            f"“{text}” is not a valid Acorn address. Use one to eight "
            "hexadecimal digits, optionally written as &1900 or 0x1900."
        ) from exc
