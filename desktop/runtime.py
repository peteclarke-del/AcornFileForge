"""Authenticated loopback runtime used by the Linux desktop shell."""

from __future__ import annotations

import os
import re
import secrets
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from werkzeug.serving import BaseWSGIServer, make_server

from app.server import create_app


@dataclass(frozen=True)
class DesktopPaths:
    data: Path
    config: Path
    cache: Path
    work: Path


def _xdg_path(variable: str, fallback: Path) -> Path:
    value = os.environ.get(variable, "").strip()
    if not value:
        return fallback
    path = Path(value).expanduser()
    snap_root = Path.home() / "snap"
    try:
        path.relative_to(snap_root)
    except ValueError:
        return path
    return fallback


def desktop_paths() -> DesktopPaths:
    home = Path.home()
    data = _xdg_path("XDG_DATA_HOME", home / ".local" / "share") / "acorn-file-forge"
    config = _xdg_path("XDG_CONFIG_HOME", home / ".config") / "acorn-file-forge"
    cache = _xdg_path("XDG_CACHE_HOME", home / ".cache") / "acorn-file-forge"
    return DesktopPaths(data=data, config=config, cache=cache, work=data / "work")


def _stable_owner(config_dir: Path) -> str:
    """Load or create the durable owner used to recover desktop sessions."""
    config_dir.mkdir(parents=True, exist_ok=True)
    config_dir.chmod(0o700)
    path = config_dir / "owner-id"
    try:
        value = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        value = ""
    if re.fullmatch(r"[A-Za-z0-9_-]{32,64}", value):
        path.chmod(0o600)
        return value
    value = secrets.token_urlsafe(32)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="ascii",
            dir=config_dir,
            prefix="owner-id-",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            os.fchmod(temporary.fileno(), 0o600)
            temporary.write(value)
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path.replace(path)
        directory = os.open(config_dir, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return value


class DesktopServer:
    """Own one private Flask server and its shared image service lifecycle."""

    def __init__(self, work_dir: Path | None = None) -> None:
        paths = desktop_paths()
        self.work_dir = Path(work_dir or paths.work)
        self.config_dir = paths.config if work_dir is None else self.work_dir.parent / "config"
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.token = secrets.token_urlsafe(32)
        self.owner = _stable_owner(self.config_dir)
        self.application = create_app(
            work_dir=self.work_dir,
            platform="desktop",
            desktop_token=self.token,
            desktop_owner=self.owner,
            desktop_state_path=self.config_dir / "client-state.json",
        )
        self._server: BaseWSGIServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        if self._server is None:
            raise RuntimeError("The desktop service has not started.")
        return int(self._server.server_port)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def start(self) -> None:
        if self._server is not None:
            return
        self._server = make_server(
            "127.0.0.1",
            0,
            self.application,
            threaded=True,
        )
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="acorn-file-forge-desktop-api",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        emulator = self.application.extensions.get("acorn_interactive_emulator")
        if emulator is not None:
            emulator.stop()
        server, thread = self._server, self._thread
        self._server = self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)

    def __enter__(self) -> "DesktopServer":
        self.start()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.stop()


__all__ = ["DesktopPaths", "DesktopServer", "desktop_paths"]
