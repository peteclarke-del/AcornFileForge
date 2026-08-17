from __future__ import annotations

import csv
import io
import re
from collections import defaultdict, deque
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from .checksum import sha256_bytes, sha256_path
from .dfs_compat import dfs_catalogue_files, infer_dfs_launch_page
from .disk_service import MMB_HEADER_SIZE, MMB_SLOT_SIZE, DiskError
from .menu_interpreter import decode_basic
from .menu.adfs import installed_adfs_menus, test_installed_adfs_menu_entries
from .menu.mmb import parse_mmb_menu_data
from .menu.mmb_discovery import installed_mmb_menus
from .operations import OperationCancelled


MAX_INSPECT_BYTES = 1024 * 1024
COMMAND_RE = re.compile(
    r"(?:\*\s*)?(CHAIN|EXEC|RUN|LOAD|DIR|LIB)\s*[\"']?([^\"'\s:\r]+)",
    re.IGNORECASE,
)


def _join(parent: str, name: str) -> str:
    return f"$.{name}" if parent == "$" else f"{parent}.{name}"


def _row_size(row: dict) -> int:
    try:
        return int(row.get("length", row.get("size", 0)) or 0)
    except (TypeError, ValueError):
        return 0


def _walk(
    service,
    session,
    slot: int | None = None,
    side: int | None = None,
    progress=None,
):
    is_dfs = session.kind == "dfs" or (session.kind == "mmb" and slot is not None)
    pending = deque(["" if is_dfs else "$"])
    visited = set()
    count = 0
    while pending:
        parent = pending.popleft()
        if parent.casefold() in visited:
            continue
        visited.add(parent.casefold())
        if progress:
            progress(f"Reading directory {parent}", count, None)
        listing = service.list_directory(session, parent, slot, side)
        for row in listing["entries"]:
            if is_dfs and parent == "" and row.get("virtual"):
                pending.append(str(row.get("name") or "$"))
                continue
            path = _join(parent, str(row.get("name") or "Untitled"))
            yield path, row
            count += 1
            if count > 100_000:
                raise DiskError("The filesystem walk exceeded the 100,000-object safety limit.")
            if row.get("type") in {"dir", "directory"}:
                pending.append(path)


def inspect_file(
    service,
    session,
    path: str,
    slot: int | None,
    side: int | None,
    progress=None,
) -> dict:
    report = progress or (lambda _message, _current=None, _total=None: None)
    report(f"Reading launcher {path}", 0, None)
    exported = service.export_file(session, slot, path, side)
    try:
        size = exported.stat().st_size
        with exported.open("rb") as source:
            preview = source.read(MAX_INSPECT_BYTES)
        truncated = size > len(preview)
        digest = sha256_path(
            exported,
            (
                lambda current, total: report(
                    f"Checksumming launcher {path}", current, total
                )
            ) if progress else None,
        )
    finally:
        exported.unlink(missing_ok=True)
    basic = decode_basic(preview)
    printable = sum(value in (9, 10, 13) or 32 <= value < 127 for value in preview)
    looks_text = bool(preview) and printable / len(preview) >= 0.82
    if basic:
        text = "\n".join(f"{line.number} {line.text}" for line in basic)
        view = "basic"
    elif looks_text:
        text = preview.decode("latin-1", "replace").replace("\r", "\n")
        view = "text"
    else:
        text = ""
        view = "hex"
    commands = [
        {"action": action.upper(), "target": target}
        for action, target in COMMAND_RE.findall(text)
    ]
    hex_lines = []
    for offset in range(0, min(len(preview), 4096), 16):
        chunk = preview[offset : offset + 16]
        hex_lines.append(
            f"{offset:06X}  {' '.join(f'{value:02X}' for value in chunk):<47}  "
            + "".join(chr(value) if 32 <= value < 127 else "." for value in chunk)
        )
    return {
        "path": path,
        "size": size,
        "sha256": digest,
        "view": view,
        "text": text,
        "hex": "\n".join(hex_lines),
        "truncated": truncated,
        "editable": looks_text and not truncated and size <= 64 * 1024,
        "tokenisedBasic": basic is not None,
        "commands": commands,
    }


def dependency_report(
    service,
    session,
    path: str,
    slot: int | None,
    side: int | None,
    progress=None,
) -> dict:
    inspected = inspect_file(service, session, path, slot, side, progress)
    parent = path.rsplit(".", 1)[0] if "." in path else "$"
    catalogue = [
        (candidate_path, row)
        for candidate_path, row in _walk(service, session, slot, side, progress)
        if row.get("type") not in {"dir", "directory"}
    ]
    by_path = {candidate_path.casefold(): (candidate_path, row) for candidate_path, row in catalogue}
    by_leaf: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for candidate_path, row in catalogue:
        by_leaf[str(row.get("name") or candidate_path.rsplit(".", 1)[-1]).casefold()].append((candidate_path, row))
    dependencies = []
    for command in inspected["commands"]:
        original_target = command["target"].strip()
        target = original_target.split(".")[-1]
        rooted = original_target.startswith("$")
        relative_path = original_target if rooted else _join(parent, original_target)
        exact = by_path.get(relative_path.casefold())
        leaf_candidates = by_leaf.get(target.casefold(), [])
        found = exact or (leaf_candidates[0] if len(leaf_candidates) == 1 else None)
        dependencies.append({
            **command,
            "resolved": bool(found),
            "path": found[0] if found else None,
            "rootRelative": rooted,
            "ambiguous": not exact and len(leaf_candidates) > 1,
            "candidates": [candidate[0] for candidate in leaf_candidates[:20]],
        })
    unsafe = [item for item in dependencies if not item["resolved"] or item["rootRelative"] or item["ambiguous"]]
    return {
        "launcher": path,
        "dependencies": dependencies,
        "safeForSubdirectory": not unsafe,
        "warnings": [
            f"{item['action']} {item['target']} is "
            + ("root-relative" if item["rootRelative"] else "ambiguous" if item["ambiguous"] else "not present in the image")
            for item in unsafe
        ],
        "filesIndexed": len(catalogue),
    }


def _mmb_manifest(service, session, progress=None) -> dict:
    slots = service.list_slots(session)
    rows = []
    with session.path.open("rb") as image:
        for index, slot in enumerate(slots):
            if progress:
                progress(
                    f"Reading MMB slot {slot['slot']} · {slot['name'] or 'Empty'}",
                    index,
                    len(slots),
                )
            record = {
                "recordType": "slot",
                "slot": slot["slot"],
                "diskTitle": slot["name"],
                "formatted": slot["formatted"],
                "writable": slot["writable"] if slot["formatted"] else None,
                "sourceName": session.slot_source_names.get(slot["slot"], ""),
            }
            if not slot["formatted"]:
                rows.append(record)
                continue
            image.seek(MMB_HEADER_SIZE + slot["slot"] * MMB_SLOT_SIZE)
            data = image.read(MMB_SLOT_SIZE)
            files = dfs_catalogue_files(data)
            record["sha256"] = sha256_bytes(data)
            record["fileCount"] = len(files)
            rows.append(record)
            for item in files:
                payload = data[item.start : item.start + item.length]
                rows.append({
                    "recordType": "file",
                    "slot": slot["slot"],
                    "diskTitle": slot["name"],
                    "path": item.path,
                    "size": item.length,
                    "load": f"{item.load:06X}",
                    "execute": f"{item.execute:06X}",
                    "sha256": sha256_bytes(payload),
                })
    if progress:
        progress("Reading installed MMB menu records", len(slots), len(slots))
    menus = []
    for menu in installed_mmb_menus(service, session):
        item = dict(menu)
        if item["type"] in {"universal", "universal-4r", "spi-game-menu"}:
            data_file = "$.EGAMDAT" if item["type"] == "universal-4r" else "$.GAMDATA"
            try:
                item["entries"] = parse_mmb_menu_data(
                    service.read_file(session, item["slot"], data_file), item["type"]
                )
            except DiskError:
                item["entries"] = []
        menus.append(item)
    return {"image": service.summary(session), "records": rows, "menus": menus}


def build_manifest(service, session, progress=None) -> dict:
    if session.kind == "mmb":
        return _mmb_manifest(service, session, progress)
    if session.kind == "rom":
        records = []
        banks = service.list_rom_banks(session)
        for index, row in enumerate(banks):
            path = f"bank:{row['bank']}"
            if progress:
                progress(f"Checksumming ROM {path}", index, len(banks))
            exported = service.export_file(session, None, path)
            try:
                digest = sha256_path(
                    exported,
                    (lambda current, total: progress(
                        f"Checksumming ROM {path}", current, total
                    )) if progress else None,
                )
            finally:
                exported.unlink(missing_ok=True)
            records.append({
                "recordType": "rom-bank",
                "path": path,
                "bank": row["bank"],
                "title": row["name"],
                "size": row["length"],
                "romType": row["filetype"],
                "empty": row["empty"],
                "sha256": digest,
            })
        return {"image": service.summary(session), "records": records, "menus": []}
    records = []
    sides = [0, 2] if session.kind == "dfs" and session.path.name.lower().endswith(".dsd") else [None]
    for side in sides:
        for path, row in _walk(service, session, None, side, progress):
            record = {
                "recordType": "directory" if row.get("type") in {"dir", "directory"} else "file",
                "path": path,
                "side": side,
                "size": _row_size(row),
                "load": row.get("loadHex", row.get("load")),
                "execute": row.get("executeHex", row.get("exec")),
                "attributes": row.get("attr", ""),
            }
            if record["recordType"] == "file":
                try:
                    exported = service.export_file(session, None, path, side)
                    try:
                        record["sha256"] = sha256_path(
                            exported,
                            (lambda current, total: progress(
                                f"Checksumming {path}", current, total
                            )) if progress else None,
                        )
                    finally:
                        exported.unlink(missing_ok=True)
                except OperationCancelled:
                    raise
                except DiskError as exc:
                    record["error"] = str(exc)
            records.append(record)
    menus = installed_adfs_menus(service, session) if session.kind == "adfs" else []
    return {"image": service.summary(session), "records": records, "menus": menus}


def manifest_csv(manifest: dict) -> str:
    keys = sorted({key for row in manifest["records"] for key in row})
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=keys, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(manifest["records"])
    return output.getvalue()


def _menu_search_record(entry: dict, *, menu_type: str, slot=None, root=None) -> dict:
    filename = str(entry.get("filename") or "").strip()
    disk_title = str(entry.get("diskTitle") or "").strip()
    if root is not None:
        directory = (
            disk_title if disk_title.startswith("$")
            else _join(str(root), disk_title) if disk_title
            else str(root)
        )
        path = filename if filename.startswith("$") else _join(directory, filename) if filename else directory
    else:
        path = filename if filename.startswith("$") else _join("$", filename) if filename else "$"
    return {
        "virtual": True,
        "resultType": "menu",
        "kind": "menu",
        "name": str(entry.get("title") or filename or disk_title or "Menu entry"),
        "fileName": path.rsplit(".", 1)[-1] if filename else "",
        "path": path,
        "openable": bool(filename and (root is not None or slot is not None)),
        "searchFields": {
            "menu title": entry.get("title"),
            "publisher": entry.get("publisher"),
            "disk title": disk_title,
            "launcher": filename,
            "action": entry.get("action"),
            "PAGE": entry.get("page"),
            "menu type": menu_type,
        },
        **({"slot": int(slot)} if slot is not None else {}),
    }


def _project_offset(value) -> int | None:
    try:
        text = str(value).strip()
        return int(text[1:], 16) if text.startswith("&") else int(text, 0)
    except (TypeError, ValueError):
        return None


def workspace_metadata_records(service, session) -> list[dict]:
    """Return bounded menu and saved-project records for workspace search."""
    records: list[dict] = []
    if session.kind == "mmb":
        slots_by_title: dict[str, list[int]] = defaultdict(list)
        for slot in service.list_slots(session):
            if slot.get("formatted"):
                slots_by_title[str(slot.get("name") or "").casefold()].append(int(slot["slot"]))
        for menu in installed_mmb_menus(service, session):
            menu_type = str(menu.get("type") or "")
            if menu_type not in {"universal", "universal-4r", "spi-game-menu"}:
                continue
            data_file = "$.EGAMDAT" if menu_type == "universal-4r" else "$.GAMDATA"
            try:
                entries = parse_mmb_menu_data(
                    service.read_file(session, int(menu["slot"]), data_file), menu_type
                )
            except DiskError:
                continue
            for entry in entries:
                matching_slots = slots_by_title.get(str(entry.get("diskTitle") or "").casefold()) or [None]
                records.extend(
                    _menu_search_record(entry, menu_type=menu_type, slot=slot)
                    for slot in matching_slots
                )
    elif session.kind == "adfs":
        for menu in installed_adfs_menus(service, session):
            records.extend(
                _menu_search_record(
                    entry,
                    menu_type=str(menu.get("type") or "adfs-universal"),
                    root=str(menu.get("root") or "$"),
                )
                for entry in menu.get("entries", [])
            )
    if session.kind == "rom":
        project = session.rom_project or {}
        identity = project.get("identity") or {}
        records.append({
            "virtual": True, "resultType": "rom-project", "kind": "rom-project",
            "name": str(identity.get("title") or session.name), "path": "ROM project",
            "openable": False, "romProject": True,
            "searchFields": {
                "title": identity.get("title"), "version": identity.get("version"),
                "publisher": identity.get("publisher"), "platform": identity.get("platform"),
                "identity notes": identity.get("notes"), "project notes": project.get("notes"),
                "hardware": project.get("hardware"),
            },
        })
        for address, label in dict(project.get("symbols") or {}).items():
            records.append({
                "virtual": True, "resultType": "rom-symbol", "kind": "rom-project",
                "name": str(label), "path": "ROM project symbols", "openable": False,
                "romProject": True, "romTab": "code", "address": address,
                "searchFields": {"symbol": label, "address": address},
            })
        for region in project.get("regions") or []:
            records.append({
                "virtual": True, "resultType": "rom-region", "kind": "rom-project",
                "name": str(region.get("name") or "ROM region"), "path": "ROM project regions",
                "openable": False, "romProject": True, "romTab": "code",
                "address": region.get("start"),
                "searchFields": {
                    "region": region.get("name"), "start": region.get("start"),
                    "end": region.get("end"),
                },
            })
    for key, project in list((session.editor_projects or {}).items())[:4096]:
        parts = str(key).split("|", 2)
        if len(parts) != 3:
            continue
        slot_text, side_text, path = parts
        context = {
            "path": path,
            **({"slot": int(slot_text)} if slot_text != "-" else {}),
            **({"side": int(side_text)} if side_text != "-" else {}),
        }
        common = {
            "virtual": True, "kind": "project", "path": path,
            "fileName": path.rsplit(".", 1)[-1], "openable": True, **context,
        }
        if project.get("notes"):
            records.append({
                **common, "resultType": "project-notes", "name": path.rsplit(".", 1)[-1],
                "searchFields": {"project notes": project.get("notes")},
            })
        for offset, label in dict(project.get("symbols") or {}).items():
            parsed_offset = _project_offset(offset)
            if parsed_offset is None:
                continue
            records.append({
                **common, "resultType": "project-symbol", "name": str(label),
                "offset": parsed_offset, "searchFields": {"symbol": label, "offset": offset},
            })
        for offset, comment in dict(project.get("comments") or {}).items():
            parsed_offset = _project_offset(offset)
            if parsed_offset is None:
                continue
            records.append({
                **common, "resultType": "project-comment", "name": path.rsplit(".", 1)[-1],
                "offset": parsed_offset, "searchFields": {"comment": comment, "offset": offset},
            })
    return records[:20_000]


def duplicate_report(service, session, progress=None) -> dict:
    manifest = build_manifest(service, session, progress)
    exact: dict[str, list[dict]] = defaultdict(list)
    variants: dict[str, list[dict]] = defaultdict(list)
    for row in manifest["records"]:
        if row.get("sha256"):
            exact[str(row["sha256"])].append(row)
        if row.get("recordType") == "file" and row.get("diskTitle"):
            continue
        if row.get("recordType") == "slot" and not row.get("formatted"):
            continue
        title = str(row.get("diskTitle") or row.get("path") or "")
        key = re.sub(r"[^a-z0-9]", "", re.sub(r"(?:disc|disk|side|v|rev)[-_ ]?[0-9a-z]+$", "", title.casefold()))
        if key:
            variants[key].append(row)
    result = {
        "exact": [items for items in exact.values() if len(items) > 1],
        "variants": [items for items in variants.values() if len(items) > 1],
    }
    if session.kind != "mmb":
        return result

    slot_records = {
        int(row["slot"]): row
        for row in manifest["records"]
        if row.get("recordType") == "slot" and row.get("formatted")
    }
    slots_by_title: dict[str, list[int]] = defaultdict(list)
    for slot, row in slot_records.items():
        slots_by_title[str(row.get("diskTitle") or "").casefold()].append(slot)

    files_by_slot: dict[int, list[dict]] = defaultdict(list)
    for row in manifest["records"]:
        if row.get("recordType") == "file" and row.get("sha256") and row.get("slot") is not None:
            files_by_slot[int(row["slot"])].append(row)
    content_fingerprints: dict[tuple, list[int]] = defaultdict(list)
    for slot, files in files_by_slot.items():
        fingerprint = tuple(sorted(
            (
                str(row.get("path") or "").casefold(),
                int(row.get("size") or 0),
                str(row.get("load") or ""),
                str(row.get("execute") or ""),
                str(row.get("sha256") or ""),
            )
            for row in files
        ))
        if fingerprint:
            content_fingerprints[fingerprint].append(slot)
    exact_slot_signatures = {
        tuple(sorted(int(row["slot"]) for row in items if row.get("recordType") == "slot"))
        for items in result["exact"]
    }
    content_matches = []
    for slots in content_fingerprints.values():
        signature = tuple(sorted(slots))
        if len(signature) > 1 and signature not in exact_slot_signatures:
            content_matches.append([slot_records[slot] for slot in signature])

    game_groups: dict[str, list[dict]] = defaultdict(list)
    editable_menu = next((
        menu for menu in manifest.get("menus", [])
        if menu.get("type") in {"universal", "universal-4r", "spi-game-menu"}
    ), None)
    if editable_menu:
        for entry_index, entry in enumerate(editable_menu.get("entries", [])):
            title = str(entry.get("title") or "").strip()
            game_key = re.sub(r"[^a-z0-9]", "", title.casefold())
            if not game_key:
                continue
            disk_title = str(entry.get("diskTitle") or "")
            game_groups[game_key].append({
                "entryIndex": entry_index,
                "title": title,
                "publisher": str(entry.get("publisher") or ""),
                "diskTitle": disk_title,
                "filename": str(entry.get("filename") or ""),
                "action": str(entry.get("action") or ""),
                "page": str(entry.get("page") or ""),
                "slots": slots_by_title.get(disk_title.casefold(), []),
            })
    game_duplicates = [
        items for items in game_groups.values()
        if len(items) > 1 and (
            len({item["diskTitle"].casefold() for item in items}) > 1
            or len({slot for item in items for slot in item["slots"]}) > 1
        )
    ]
    result.update(
        slots=list(slot_records.values()),
        gameDuplicates=game_duplicates,
        contentMatches=content_matches,
    )
    return result


def menu_test_report(service, session, root: str | None = None, progress=None) -> dict:
    if session.kind == "adfs":
        roots, tests = test_installed_adfs_menu_entries(
            service, session, root, progress
        )
        return {
            "tests": tests,
            "passed": sum(item["passed"] for item in tests),
            "failed": sum(not item["passed"] for item in tests),
            "menuRoots": roots,
        }
    if session.kind != "mmb":
        raise DiskError("The menu-entry test runner requires an MMB or ADFS image.")
    slots = service.list_slots(session)
    by_title = defaultdict(list)
    for slot in slots:
        if slot["formatted"]:
            by_title[slot["name"].casefold()].append(slot["slot"])
    slot_catalogues: dict[int, tuple[bytes, set[str]]] = {}

    def catalogue(slot: int) -> tuple[bytes, set[str]]:
        if slot not in slot_catalogues:
            data = service._slot_path(session, slot).read_bytes()
            slot_catalogues[slot] = (
                data,
                {item.path.casefold() for item in dfs_catalogue_files(data)},
            )
        return slot_catalogues[slot]

    tests = []
    for menu in installed_mmb_menus(service, session):
        if menu["type"] not in {"universal", "universal-4r", "spi-game-menu"}:
            continue
        data_file = "$.EGAMDAT" if menu["type"] == "universal-4r" else "$.GAMDATA"
        try:
            entries = parse_mmb_menu_data(
                service.read_file(session, menu["slot"], data_file),
                menu["type"],
            )
        except (DiskError, ValueError, IndexError) as exc:
            tests.append({
                "index": 0,
                "menuSlot": menu.get("slot"),
                "menuType": menu.get("type", ""),
                "title": "Menu database",
                "diskTitle": "",
                "slots": [],
                "launcher": data_file,
                "action": "READ",
                "page": "",
                "passed": False,
                "problems": [f"Could not read or parse {data_file}: {exc}"],
                "evidence": "The remaining detected menus were still checked.",
            })
            continue
        for offset, entry in enumerate(entries):
            if progress and offset % 20 == 0:
                progress(
                    f"Testing menu entry {offset + 1} of {len(entries)}",
                    offset,
                    len(entries),
                )
            candidates = by_title.get(str(entry["diskTitle"]).casefold(), [])
            problems = []
            evidence = "disk missing"
            if not candidates:
                problems.append("No formatted slot has the required disk title")
            else:
                slot = candidates[0]
                data, names = catalogue(slot)
                page, evidence = infer_dfs_launch_page(data, entry["filename"], entry["action"])
                leaf = str(entry["filename"]).split(".")[-1].casefold()
                if not any(path.rsplit(".", 1)[-1] == leaf for path in names):
                    problems.append("Launch file is missing")
                if page and str(entry.get("page") or "").lstrip("0").casefold() != page.lstrip("0").casefold():
                    problems.append(f"PAGE should be &{page}")
            tests.append({
                "index": offset,
                "menuSlot": menu.get("slot"),
                "menuType": menu.get("type", ""),
                "title": entry["title"],
                "diskTitle": entry["diskTitle"],
                "slots": candidates,
                "launcher": entry["filename"],
                "action": entry["action"],
                "page": entry["page"],
                "passed": not problems,
                "problems": problems,
                "evidence": evidence,
            })
    return {
        "tests": tests,
        "passed": sum(item["passed"] for item in tests),
        "failed": sum(not item["passed"] for item in tests),
    }


def _failed_menu_findings(menu_tests: dict) -> list[dict]:
    """Keep the evidence needed to act on every failed menu-record check."""
    return [
        {
            "record": int(item.get("index", 0)) + 1,
            "title": str(item.get("title") or "Untitled entry"),
            "diskTitle": str(item.get("diskTitle") or ""),
            "slots": [int(slot) for slot in item.get("slots", [])],
            "menuSlot": int(item["menuSlot"]) if item.get("menuSlot") is not None else None,
            "menuType": str(item.get("menuType") or ""),
            "menuRoot": str(item.get("menuRoot") or ""),
            "launcher": str(item.get("launcher") or ""),
            "action": str(item.get("action") or ""),
            "page": str(item.get("page") or ""),
            "problems": [str(problem) for problem in item.get("problems", [])],
            "evidence": str(item.get("evidence") or ""),
        }
        for item in menu_tests.get("tests", [])
        if not item.get("passed")
    ]


def health_report(service, session, progress=None) -> dict:
    checks = []
    repairable = []
    def check(name, function):
        try:
            detail = function()
            checks.append({"name": name, "status": "pass", "detail": str(detail)})
        except OperationCancelled:
            raise
        except Exception as exc:
            checks.append({"name": name, "status": "fail", "detail": str(exc)})

    if session.kind == "mmb":
        if progress:
            progress("Reading the MMB slot table", 0, None)
        formatted = [slot for slot in service.list_slots(session) if slot["formatted"]]
        check("MMB header and slot table", lambda: f"{len(formatted)} formatted slots")
        invalid = [slot for slot in service.list_slots(session) if slot["invalid"]]
        checks.append({"name": "Invalid MMB slots", "status": "warn" if invalid else "pass", "detail": f"{len(invalid)} invalid entries"})
        menu_tests = menu_test_report(service, session, progress=progress)
        checks.append({
            "name": "Menu records",
            "status": "fail" if menu_tests["failed"] else "pass",
            "detail": f"{menu_tests['passed']} passed, {menu_tests['failed']} failed",
            "findings": _failed_menu_findings(menu_tests),
        })
        project = service.editor_project(session, "$MMB", None, None)
        project = project if isinstance(project, dict) else {}
        sandbox_runs = [
            row for row in project.get("tests", [])
            if row.get("kind") == "menu-sandbox"
        ]
        source_path = getattr(session, "path", None)
        current_hash = (
            sha256_path(source_path)
            if isinstance(source_path, Path) and source_path.is_file()
            else ""
        )
        current_runs = [
            row for row in sandbox_runs
            if row.get("sourceSha256") == current_hash
        ]
        latest_run = current_runs[-1] if current_runs else None
        checks.append({
            "name": "Whole-MMB emulator evidence",
            "status": (
                "pass" if latest_run and latest_run.get("inputChangedDisplay") and latest_run.get("repeatable")
                else "warn"
            ),
            "detail": (
                latest_run.get("summary", "Current image captured in the menu sandbox")
                if latest_run else
                "No isolated emulator capture matches the current MMB revision. Use Preview installed menu > Capture actual menu."
            ),
            "findings": (
                [{
                    "time": latest_run.get("time"),
                    "menuSlot": latest_run.get("menuSlot"),
                    "menuType": latest_run.get("menuType"),
                    "machine": latest_run.get("machine"),
                    "frameHashes": latest_run.get("frameHashes", []),
                    "changedPixels": latest_run.get("changedPixels"),
                    "repeatable": bool(latest_run.get("repeatable")),
                    "pageEvidence": (
                        "The menu display and navigation are emulator-proven. Individual launcher PAGE values remain governed by the itemised static menu checks above."
                    ),
                }] if latest_run else []
            ),
        })
        page_problems = sum(
            any(problem.startswith("PAGE should be") for problem in item["problems"])
            for item in menu_tests["tests"]
        )
        if page_problems:
            repairable.append({
                "action": "menu-page-audit",
                "label": "Repair menu PAGE values",
                "detail": f"{page_problems} menu record(s) have a provably different launcher PAGE",
            })
    elif session.kind == "rom":
        if progress:
            progress("Inspecting ROM banks and headers", 0, None)
        rows = service.list_rom_banks(session)
        check("ROM byte structure", lambda: service.validate(session, None))
        checks.append({
            "name": "Recognised sideways-ROM headers",
            "status": "pass" if any(row["header"] or row.get("extensionHeader") for row in rows) else "warn",
            "detail": (
                f"{sum(bool(row['header']) for row in rows)} of {len(rows)} bank(s) "
                "carry a recognised BBC-family header; "
                f"{sum(bool(row.get('extensionHeader')) for row in rows)} RISC OS extension trailer(s) found"
            ),
        })
        bad_extension_checksums = [
            row for row in rows
            if row.get("extensionHeader") and not row["extensionHeader"]["checksumValid"]
        ]
        if bad_extension_checksums:
            checks.append({
                "name": "RISC OS extension ROM checksum",
                "status": "fail",
                "detail": "The ExtnROM0 trailer checksum does not match the image bytes.",
            })
        duplicate_groups = [
            [row["bank"], *row.get("matchingBanks", [])]
            for row in rows
            if row.get("matchingBanks") and row["bank"] < min(row["matchingBanks"])
        ]
        checks.append({
            "name": "Bank fingerprints",
            "status": "warn" if duplicate_groups else "pass",
            "detail": (
                "; ".join("Identical banks " + ", ".join(map(str, group)) for group in duplicate_groups)
                if duplicate_groups else "Every bank has a distinct SHA-256 fingerprint"
            ),
        })
        header_warnings = [
            f"Bank {row['bank']}: {warning}"
            for row in rows for warning in row.get("warnings", [])
        ]
        checks.append({
            "name": "Header flag consistency",
            "status": "warn" if header_warnings else "pass",
            "detail": (
                f"{len(header_warnings)} header/vector disagreement(s)"
                if header_warnings else "Recognised header flags agree with their entry vectors"
            ),
            "findings": header_warnings,
        })
        partial = session.path.stat().st_size % session.rom_bank_size
        checks.append({
            "name": "Bank boundaries",
            "status": "warn" if partial else "pass",
            "detail": (
                f"Final bank contains {partial:,} bytes"
                if partial else f"All banks are {session.rom_bank_size:,} bytes"
            ),
        })
    else:
        if progress:
            progress("Validating the filesystem structure", 0, None)
        check("Filesystem structure", lambda: service.validate(session, None))
        def catalogue_count():
            sides = [0, 2] if session.kind == "dfs" and session.path.name.lower().endswith(".dsd") else [None]
            count = sum(
                1
                for side in sides
                for _path, _row in _walk(service, session, None, side, progress)
            )
            return f"{count} objects"
        check("Filesystem catalogue", catalogue_count)
        if session.kind == "adfs":
            menu_tests = menu_test_report(service, session, progress=progress)
            checks.append({
                "name": "ADFS menu records",
                "status": "fail" if menu_tests["failed"] else "pass",
                "detail": f"{menu_tests['passed']} passed, {menu_tests['failed']} need review across {len(menu_tests['menuRoots'])} menu(s)",
                "findings": _failed_menu_findings(menu_tests),
            })
            for root in menu_tests["menuRoots"]:
                if any(
                    item["menuRoot"] == root
                    and any(problem.startswith("PAGE should be") for problem in item["problems"])
                    for item in menu_tests["tests"]
                ):
                    repairable.append({
                        "action": "adfs-menu-page-audit",
                        "root": root,
                        "label": f"Repair PAGE values in {root}",
                        "detail": "Only PAGE values proved from the installed launchers will change",
                    })
    if session.descriptor_path:
        check("BeebSCSI DAT/DSC geometry", lambda: service.stat(session, None).get("description", "valid"))
    warnings = [*session.warnings, *(list(session.tape.warnings) if session.tape else [])]
    profile = session.hardware_profile or {}
    if profile:
        additions = ", ".join(profile.get("addons") or []) or "stock machine"
        checks.append({
            "name": "Hardware profile",
            "status": "pass",
            "detail": f"{profile.get('name', 'Custom')} · {profile.get('machine', 'Acorn')} · {profile.get('filingSystem', 'automatic')} · {additions}",
        })
        if profile.get("tube") and session.kind == "mmb":
            checks.append({
                "name": "Tube compatibility",
                "status": "warn",
                "detail": "Many Electron and low-PAGE MMFS titles require the Tube to be disabled before launch.",
            })
    checks.extend({"name": "Compatibility warning", "status": "warn", "detail": warning} for warning in warnings)
    score = "healthy" if all(item["status"] == "pass" for item in checks) else (
        "attention" if not any(item["status"] == "fail" for item in checks) else "failed"
    )
    if progress:
        progress("Health check complete", 1, 1)
    return {"status": score, "checks": checks, "repairable": repairable}


COMPATIBILITY_REPORT_FORMAT = "acorn-file-forge-compatibility-report"
COMPATIBILITY_REPORT_VERSION = 1


def accept_compatibility_report(service, session, document: dict) -> dict:
    """Regenerate and retain one reviewed report for the next saved package."""
    if not isinstance(document, dict):
        raise DiskError("The compatibility report is not a JSON object.")
    if (
        document.get("format") != COMPATIBILITY_REPORT_FORMAT
        or document.get("version") != COMPATIBILITY_REPORT_VERSION
    ):
        raise DiskError(
            f"Only {COMPATIBILITY_REPORT_FORMAT} version "
            f"{COMPATIBILITY_REPORT_VERSION} reports can be retained."
        )
    if not document.get("dryRun") or not isinstance(document.get("changes"), list):
        raise DiskError("Only a complete dry-run compatibility report can be retained.")
    if not isinstance(document.get("source"), dict) or not isinstance(document.get("target"), dict):
        raise DiskError("The compatibility report source or target is incomplete.")
    target = document.get("target") or {}
    if target.get("image") != session.name or target.get("kind") != session.kind:
        raise DiskError("The compatibility report belongs to a different image or filesystem.")
    report = preflight_report(
        service,
        session,
        {
            "operation": document.get("operation"),
            "changes": deepcopy(document["changes"]),
            "sourceKind": document["source"].get("kind"),
            "targetKind": target.get("kind"),
        },
    )
    if not report["canProceed"]:
        raise DiskError("Resolve the report's blocking findings before accepting it.")
    report["acceptedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report["acceptedImage"] = {
        "name": session.name,
        "kind": session.kind,
        "size": session.path.stat().st_size,
        "modifiedNs": session.path.stat().st_mtime_ns,
    }
    session.compatibility_reports = [*session.compatibility_reports[-9:], report]
    return report


def compatibility_report_markdown(report: dict) -> str:
    lines = [
        "# Acorn File Forge compatibility report",
        "",
        f"Operation: {report['operation']}",
        f"Source: {report['source']['kind']}",
        f"Target: {report['target']['kind']}",
        f"Can proceed: {'yes' if report['canProceed'] else 'no'}",
        "",
        "## Items",
        "",
    ]
    for item in report["items"]:
        lines.append(f"### {item['sourceName'] or 'Unnamed item'}")
        lines.append("")
        lines.append(f"- Target name: `{item['targetName']}`")
        lines.append(f"- Type: {item['type']}")
        lines.append(f"- Load: {item['metadata']['load'] or 'not supplied'}")
        lines.append(f"- Execute: {item['metadata']['execute'] or 'not supplied'}")
        for conversion in item["conversions"]:
            lines.append(f"- Conversion: {conversion}")
        for loss in item["losses"]:
            lines.append(f"- Metadata loss: {loss}")
        lines.append("")
    lines.extend(["## Findings", ""])
    lines.extend(
        f"- {finding['severity'].upper()}: {finding['message']}"
        for finding in report["issues"]
    )
    if not report["issues"]:
        lines.append("- No compatibility findings.")
    return "\n".join(lines) + "\n"


def preflight_report(service, session, payload: dict) -> dict:
    operation = str(payload.get("operation") or "review")
    changes = list(payload.get("changes") or [])
    issues = []
    items = []
    seen = set()
    target_kind = str(payload.get("targetKind") or session.kind)
    source_kind = str(payload.get("sourceKind") or session.kind)
    default_limit = 7 if target_kind in {"dfs", "mmb"} else 10 if target_kind == "adfs" else 255 if target_kind in {"host", "deployment"} else 12
    for offset, change in enumerate(changes):
        name = str(change.get("name") or change.get("destination") or "")
        leaf = name if change.get("nameIsLeaf") else name.rsplit(".", 1)[-1]
        item_type = str(change.get("type") or "file")
        # An MMB row names a complete DFS disk, whose catalogue title is
        # twelve characters. Files inside that disk still use DFS's seven.
        limit = 12 if target_kind == "mmb" and item_type in {"disk", "disk image"} else default_limit
        invalid = r"[/\x00-\x1f]" if target_kind in {"host", "deployment"} else r"[.:*#/\x00-\x1f]"
        normal = re.sub(invalid, "_", leaf)[:limit]
        conversions = []
        losses = []
        if normal != leaf:
            issues.append({"severity": "warning", "item": offset, "message": f"{leaf} becomes {normal or 'FILE'}"})
            conversions.append(f"Filename {leaf} becomes {normal or 'FILE'}")
        key = normal.casefold()
        if key in seen:
            issues.append({"severity": "error", "item": offset, "message": f"{normal} clashes after target-name conversion"})
        seen.add(key)
        if target_kind in {"dfs", "mmb"} and item_type in {"dir", "directory", "folder"}:
            losses.append("The target DFS catalogue cannot preserve a hierarchical directory.")
            issues.append({
                "severity": "error", "item": offset,
                "message": f"{leaf} is a directory, but the target DFS catalogue is flat",
            })
        if source_kind == "adfs" and target_kind in {"dfs", "mmb"} and change.get("filetype"):
            losses.append("RISC OS filetype metadata is not represented directly by DFS.")
        items.append({
            "index": offset,
            "sourceName": leaf,
            "targetName": normal or "FILE",
            "source": str(change.get("source") or ""),
            "type": item_type,
            "metadata": {
                "load": str(change.get("load") or ""),
                "execute": str(change.get("execute") or ""),
                "access": str(change.get("access") or change.get("attr") or ""),
                "filetype": str(change.get("filetype") or ""),
            },
            "conversions": conversions,
            "losses": losses,
        })
    report = {
        "format": COMPATIBILITY_REPORT_FORMAT,
        "version": COMPATIBILITY_REPORT_VERSION,
        "operation": operation,
        "dryRun": True,
        "source": {"kind": source_kind},
        "target": {
            "kind": target_kind,
            "image": session.name,
            "hardwareProfile": str((session.hardware_profile or {}).get("name") or ""),
        },
        "changes": changes,
        "items": items,
        "issues": issues,
        "canProceed": not any(item["severity"] == "error" for item in issues),
        "summary": f"{len(changes)} proposed changes, {len(issues)} findings",
    }
    report["markdown"] = compatibility_report_markdown(report)
    return report
