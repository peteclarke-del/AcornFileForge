# Web and Linux desktop platform contract

Acorn File Forge has one application implementation with two hosts. The web
host runs in Docker and a normal browser. The Linux desktop host places the
same frontend, Flask routes, filesystem services, editors, format handlers and
tests inside a GTK 4 and Libadwaita window. It is not a second implementation.

This contract is part of the definition of done for every change. A feature or
fix that applies to shared behaviour must work in both hosts before it is
complete. Reviews must reject a web-only or desktop-only copy of shared domain
logic.

## Required boundaries

1. `app/server.py:create_app` is the only application composition root. Both
   hosts create the application through that factory.
2. `app/static/` is the only product frontend. The desktop package embeds it
   with WebKitGTK and must not carry a copied HTML, CSS or JavaScript tree.
3. Image opening, editing, validation, conversion, menus, metadata, recipes,
   undo and saving remain in shared `app/` modules.
4. Host adapters contain only work that a browser cannot perform. Current
   examples are choosing an absolute local path, owning a native window and
   launching an emulator on the host display.
5. A host-only API must be declared in `HOST_EXCLUSIVE_ENDPOINTS` in
   `app/platform_contract.py`. Adding an exception is an architectural change,
   not a shortcut around parity.
6. A host-only user capability must be declared in `HOST_CAPABILITIES`, tested
   and documented. Shared capabilities belong in `SHARED_CAPABILITIES`.
7. Shared API response shapes and persisted image data cannot vary by host.
   A presentation hint such as `displayMode` is allowed when the operation is
   the same but its operating-system surface differs.

## Change checklist

Every pull request that changes application behaviour must answer these points:

- Does the change live in the shared service or frontend?
- Does it work through both `create_app()` and `create_app(platform="desktop")`?
- If it is genuinely host-specific, is the exception declared and tested?
- Do keyboard, pointer, dialog, progress, error and recovery paths still work
  in a browser and inside WebKitGTK?
- Are the main handbook, specialist guide and in-app Help updated where the
  workflow changed?
- Were the platform-contract tests and the relevant browser regressions run?

The route-map test constructs both hosts and fails when an undeclared endpoint
appears on only one. It also verifies that both hosts serve the same static
tree. These checks prevent accidental drift, but they do not replace a manual
desktop smoke test for native file selection, downloading and emulator windows.

## Storage and security

The web host uses the configured Docker work directory and browser-owner
identity. The desktop host stores working images under
`$XDG_DATA_HOME/acorn-file-forge/work`, or
`~/.local/share/acorn-file-forge/work` when `XDG_DATA_HOME` is unset.

The desktop Flask service listens only on a random `127.0.0.1` port. Each
launch creates a high-entropy token. The initial WebKit request supplies it in
a private header, then the view receives its strict, HttpOnly cookie. The token
does not appear in the address or server access log. The direct path-opening route
does not exist in the web host, so a remote browser cannot ask the server to
read arbitrary host paths.

Source images are still copied into a working session. The native file chooser
does not grant in-place mutation. Downloads use WebKitGTK's normal Downloads
directory handling, and saved packages retain the same timestamped image,
metadata and README content as browser downloads.

## Native host scope

The first native host deliberately reuses the mature web workbench. GTK owns
the application lifecycle, primary window, file associations and local image
chooser. WebKitGTK renders the shared workspace. Managed emulators use ordinary
native windows rather than the Docker noVNC surface.

Environment variables can point the desktop host at local emulator builds:

| Variable | Default |
| --- | --- |
| `ACORN_ELKULATOR_ROOT` | `/opt/elkulator` |
| `ACORN_BEM_ROOT` | `/opt/b-em` |
| `ACORN_MAME_EXECUTABLE` | `/usr/games/mame` |
| `ACORN_MAME_ROM_PATH` | `/opt/acorn-file-forge/firmware/mame` |

The web Docker image continues to use those defaults. A Linux installation may
override them in its desktop session without changing shared emulator logic.
