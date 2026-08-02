#!/usr/bin/env python3
"""Audit an installed MMB menu using the same engine as the web application."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from app.disk_service import DiskService
from app.menu_service import audit_mmb_menu_pages


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    service = DiskService(args.work_dir)
    session = service._restore_session(args.session)
    backup = session.path.with_name(f"{session.path.stem}.before-page-audit.mmb")
    if not backup.exists():
        shutil.copy2(session.path, backup)

    result = audit_mmb_menu_pages(service, session)
    report = {
        "session": session.id,
        "backup": str(backup),
        **result,
    }
    if result["rewritten"]:
        session.warnings.append(
            f"PAGE audit corrected {result['corrected']} value(s) and repaired "
            f"{result['encodingRepairs']} database field encoding(s)."
        )
        service._persist_session(session)
    if args.report:
        args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
