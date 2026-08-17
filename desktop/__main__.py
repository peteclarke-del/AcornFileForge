"""Launch Acorn File Forge as a native Linux desktop application."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

from .runtime import DesktopServer


def _arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Acorn File Forge Linux desktop host")
    parser.add_argument("images", nargs="*", type=Path, help="Images to open")
    parser.add_argument("--work-dir", type=Path, help="Override the XDG working directory")
    return parser.parse_args(argv)


def _desktop_libraries():
    try:
        import gi

        gi.require_version("Adw", "1")
        gi.require_version("Gtk", "4.0")
        gi.require_version("WebKit", "6.0")
        from gi.repository import Adw, Gio, GLib, Gtk, WebKit
    except (ImportError, ValueError) as exc:
        raise RuntimeError(
            "The Linux desktop host needs GTK 4, Libadwaita, WebKitGTK 6 and "
            "their Python GObject bindings. The Docker/browser edition remains "
            "available without these desktop packages."
        ) from exc
    return Adw, Gio, GLib, Gtk, WebKit


def _paired_selection(paths: list[Path]) -> list[Path]:
    resolved = [path.expanduser().resolve() for path in paths]
    dat_stems = {
        (path.parent, path.stem.casefold())
        for path in resolved if path.suffix.casefold() == ".dat"
    }
    return [
        path for path in resolved
        if path.suffix.casefold() != ".dsc"
        or (path.parent, path.stem.casefold()) not in dat_stems
    ]


def run(argv: list[str] | None = None) -> int:
    args = _arguments(list(argv if argv is not None else sys.argv[1:]))
    try:
        Adw, Gio, GLib, Gtk, WebKit = _desktop_libraries()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    server = DesktopServer(args.work_dir)

    class AcornFileForgeApplication(Adw.Application):
        def __init__(self) -> None:
            super().__init__(
                application_id="uk.co.acornfileforge.AcornFileForge",
                flags=Gio.ApplicationFlags.HANDLES_OPEN,
            )
            self.window = None
            self.webview = None
            self.content_manager = None
            self.style_manager = None
            self.loaded = False
            self.pending_paths = []
            self.chooser_targets = {}

        def do_startup(self) -> None:
            Adw.Application.do_startup(self)
            action = Gio.SimpleAction.new("open", None)
            action.connect("activate", self._choose_images)
            self.add_action(action)
            self.set_accels_for_action("app.open", ["<Primary>o"])
            quit_action = Gio.SimpleAction.new("quit", None)
            quit_action.connect("activate", lambda *_args: self.quit())
            self.add_action(quit_action)
            self.set_accels_for_action("app.quit", ["<Primary>q"])

        def do_activate(self) -> None:
            if self.window is None:
                server.start()
                self.window = Adw.ApplicationWindow(application=self)
                self.window.set_title("Acorn File Forge")
                self.window.set_default_size(1440, 900)
                self.style_manager = Adw.StyleManager.get_default()
                self.style_manager.connect(
                    "notify::dark",
                    self._native_appearance_changed,
                )
                settings = Gtk.Settings.get_default()
                if settings is not None:
                    settings.connect(
                        "notify::gtk-font-name",
                        self._native_appearance_changed,
                    )
                toolbar = Adw.ToolbarView()
                header = Adw.HeaderBar()
                header.set_title_widget(Adw.WindowTitle.new(
                    "Acorn File Forge",
                    "Acorn media image workbench",
                ))
                open_button = Gtk.Button.new_from_icon_name("document-open-symbolic")
                open_button.set_tooltip_text("Open media image")
                open_button.set_action_name("app.open")
                header.pack_start(open_button)
                menu = Gio.Menu()
                menu.append("Open Image…", "app.open")
                menu.append("Quit", "app.quit")
                menu_button = Gtk.MenuButton(
                    icon_name="open-menu-symbolic",
                    menu_model=menu,
                )
                menu_button.set_tooltip_text("Application menu")
                header.pack_end(menu_button)
                toolbar.add_top_bar(header)
                self.content_manager = WebKit.UserContentManager()
                self.content_manager.register_script_message_handler("acornDesktop")
                self.content_manager.connect(
                    "script-message-received::acornDesktop",
                    self._desktop_message,
                )
                self.webview = WebKit.WebView(
                    user_content_manager=self.content_manager,
                )
                self.webview.connect("load-changed", self._loaded)
                self.webview.connect("decide-policy", self._navigation_policy)
                toolbar.set_content(self.webview)
                self.window.set_content(toolbar)
                request = WebKit.URIRequest.new(server.url)
                request.get_http_headers().append(
                    "X-Acorn-Desktop-Token", server.token
                )
                self.webview.load_request(request)
                self.window.connect("close-request", self._closing)
            self.window.present()

        def _desktop_message(self, _manager, result) -> None:
            message = result.get_js_value().to_string()
            if not message.startswith("open-images"):
                return
            _command, separator, pane_value = message.partition(":")
            try:
                preferred_pane = int(pane_value) if separator else None
            except ValueError:
                preferred_pane = None
            self._choose_images(None, None, preferred_pane)

        def _navigation_policy(self, _view, decision, decision_type) -> bool:
            if decision_type not in (
                WebKit.PolicyDecisionType.NAVIGATION_ACTION,
                WebKit.PolicyDecisionType.NEW_WINDOW_ACTION,
            ):
                return False
            uri = decision.get_navigation_action().get_request().get_uri()
            if uri.startswith(server.url) or uri == "about:blank" or uri.startswith("blob:"):
                return False
            decision.ignore()
            if uri.startswith(("http://", "https://")):
                Gio.AppInfo.launch_default_for_uri(uri, None)
            return True

        def do_open(self, files, _count, _hint) -> None:
            self.pending_paths.extend(
                (path, None)
                for path in _paired_selection(
                    [Path(item.get_path()) for item in files if item.get_path()]
                )
            )
            self.activate()
            self._drain_paths()

        def _loaded(self, _view, event) -> None:
            if event != WebKit.LoadEvent.FINISHED:
                return
            self.loaded = True
            self._apply_native_appearance()
            self._drain_paths()

        def _apply_native_appearance(self) -> None:
            settings = Gtk.Settings.get_default()
            font = settings.get_property("gtk-font-name") if settings else "system-ui 11"
            dark = self.style_manager.get_dark() if self.style_manager else False
            script = (
                "window.AcornDesktopHost.applyNativeAppearance("
                f"{json.dumps({'font': font, 'dark': dark})});"
            )
            self.webview.evaluate_javascript(script, -1, None, None, None)

        def _native_appearance_changed(self, *_args) -> None:
            if self.loaded:
                self._apply_native_appearance()

        def _choose_images(
            self,
            _action,
            _parameter,
            preferred_pane: int | None = None,
        ) -> None:
            chooser = Gtk.FileChooserNative.new(
                "Open Acorn media images",
                self.window,
                Gtk.FileChooserAction.OPEN,
                "_Open",
                "_Cancel",
            )
            chooser.set_select_multiple(True)
            self.chooser_targets[id(chooser)] = preferred_pane
            chooser.connect("response", self._files_chosen)
            chooser.show()

        def _files_chosen(self, chooser, response) -> None:
            try:
                if response == Gtk.ResponseType.ACCEPT:
                    files = chooser.get_files()
                    paths = [
                        Path(files.get_item(index).get_path())
                        for index in range(files.get_n_items())
                        if files.get_item(index).get_path()
                    ]
                    preferred = self.chooser_targets.get(id(chooser))
                    self.pending_paths.extend(
                        (path, preferred if index == 0 else None)
                        for index, path in enumerate(_paired_selection(paths))
                    )
                    self._drain_paths()
            finally:
                self.chooser_targets.pop(id(chooser), None)
                chooser.destroy()

        def _drain_paths(self) -> None:
            if not self.loaded or not self.pending_paths:
                return
            paths, self.pending_paths = self.pending_paths, []
            threading.Thread(
                target=self._open_paths,
                args=(paths,),
                name="acorn-file-forge-desktop-open",
                daemon=True,
            ).start()

        def _open_paths(self, paths: list[tuple[Path, int | None]]) -> None:
            for path, preferred_pane in paths:
                try:
                    GLib.idle_add(self._deliver_opening, path.name, preferred_pane)
                    request = urllib.request.Request(
                        f"http://127.0.0.1:{server.port}/api/desktop/open-path",
                        data=json.dumps({"path": str(path)}).encode("utf-8"),
                        headers={
                            "Content-Type": "application/json",
                            "X-Acorn-Desktop-Token": server.token,
                        },
                        method="POST",
                    )
                    with urllib.request.urlopen(request, timeout=3600) as response:
                        image = json.load(response)["image"]
                    GLib.idle_add(self._deliver_image, image, preferred_pane)
                except urllib.error.HTTPError as exc:
                    try:
                        details = json.load(exc)
                        message = str(details.get("error") or exc.reason)
                    except (OSError, ValueError, AttributeError):
                        message = str(exc.reason or exc)
                    finally:
                        exc.close()
                    GLib.idle_add(self._deliver_error, path.name, message)
                except (OSError, ValueError, urllib.error.URLError) as exc:
                    GLib.idle_add(self._deliver_error, path.name, str(exc))

        def _deliver_opening(self, name: str, preferred_pane: int | None) -> bool:
            script = (
                "window.AcornDesktopHost.showOpening("
                f"{json.dumps(name)}, {json.dumps(preferred_pane)});"
            )
            self.webview.evaluate_javascript(script, -1, None, None, None)
            return GLib.SOURCE_REMOVE

        def _deliver_image(self, image: dict, preferred_pane: int | None) -> bool:
            script = (
                "window.AcornDesktopHost.acceptImage("
                f"{json.dumps(image)}, {json.dumps(preferred_pane)});"
            )
            self.webview.evaluate_javascript(script, -1, None, None, None)
            return GLib.SOURCE_REMOVE

        def _deliver_error(self, name: str, message: str) -> bool:
            script = (
                "window.AcornDesktopHost.showError("
                f"{json.dumps(f'Could not open {name}: {message}')});"
            )
            self.webview.evaluate_javascript(script, -1, None, None, None)
            return GLib.SOURCE_REMOVE

        def _closing(self, _window) -> bool:
            server.stop()
            return False

        def do_shutdown(self) -> None:
            server.stop()
            Adw.Application.do_shutdown(self)

    application = AcornFileForgeApplication()
    return int(application.run([sys.argv[0], *map(str, args.images)]))


if __name__ == "__main__":
    raise SystemExit(run())
