from __future__ import annotations

import csv
import hashlib
import io
import re
from collections import defaultdict, deque

from .checksum import sha256_path
from .dfs_compat import dfs_catalogue_files, infer_dfs_launch_page
from .disk_service import MMB_HEADER_SIZE, MMB_SLOT_SIZE, DiskError
from .menu_interpreter import decode_basic
from .menu_service import (
    installed_adfs_menus,
    installed_mmb_menus,
    parse_mmb_menu_data,
    test_installed_adfs_menu_entries,
)
from .operations import OperationCancelled


MAX_INSPECT_BYTES = 1024 * 1024
COMMAND_RE = re.compile(
    r"(?:\*\s*)?(CHAIN|EXEC|RUN|LOAD|DIR|LIB)\s*[\"']?([^\"'\s:\r]+)",
    re.IGNORECASE,
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def inspect_file(service, session, path: str, slot: int | None, side: int | None) -> dict:
    exported = service.export_file(session, slot, path, side)
    try:
        size = exported.stat().st_size
        with exported.open("rb") as source:
            preview = source.read(MAX_INSPECT_BYTES)
        truncated = size > len(preview)
        digest = sha256_path(exported)
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


def dependency_report(service, session, path: str, slot: int | None, side: int | None) -> dict:
    inspected = inspect_file(service, session, path, slot, side)
    parent = path.rsplit(".", 1)[0] if "." in path else "$"
    catalogue = [
        (candidate_path, row)
        for candidate_path, row in _walk(service, session, slot, side)
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


def _mmb_manifest(service, session) -> dict:
    slots = service.list_slots(session)
    rows = []
    with session.path.open("rb") as image:
        for slot in slots:
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
            record["sha256"] = _sha256(data)
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
                    "sha256": _sha256(payload),
                })
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


def build_manifest(service, session) -> dict:
    if session.kind == "mmb":
        return _mmb_manifest(service, session)
    if session.kind == "rom":
        records = []
        for row in service.list_rom_banks(session):
            path = f"bank:{row['bank']}"
            exported = service.export_file(session, None, path)
            try:
                digest = sha256_path(exported)
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
        for path, row in _walk(service, session, None, side):
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
                        record["sha256"] = sha256_path(exported)
                    finally:
                        exported.unlink(missing_ok=True)
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


def duplicate_report(service, session) -> dict:
    manifest = build_manifest(service, session)
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


def preflight_report(service, session, payload: dict) -> dict:
    operation = str(payload.get("operation") or "review")
    changes = list(payload.get("changes") or [])
    issues = []
    seen = set()
    limit = 7 if session.kind == "dfs" else 10 if session.kind == "adfs" else 12
    for offset, change in enumerate(changes):
        name = str(change.get("name") or change.get("destination") or "")
        leaf = name.rsplit(".", 1)[-1]
        normal = re.sub(r"[.:*#/\x00-\x1f]", "_", leaf)[:limit]
        if normal != leaf:
            issues.append({"severity": "warning", "item": offset, "message": f"{leaf} becomes {normal or 'FILE'}"})
        key = normal.casefold()
        if key in seen:
            issues.append({"severity": "error", "item": offset, "message": f"{normal} clashes after target-name conversion"})
        seen.add(key)
    return {
        "operation": operation,
        "dryRun": True,
        "changes": changes,
        "issues": issues,
        "canProceed": not any(item["severity"] == "error" for item in issues),
        "summary": f"{len(changes)} proposed changes, {len(issues)} findings",
    }
