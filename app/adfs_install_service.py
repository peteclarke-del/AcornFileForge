from __future__ import annotations

from typing import Callable

from .errors import DiskError
from .image_session import ImageSession


class ADFSInstallMixin:
    """Audit and repair software trees installed into ADFS hard disks."""

    @staticmethod
    def _adfs_directory_items(mount, directory: str, file_item) -> list[dict]:
        pending = [directory]
        items: list[dict] = []
        while pending:
            parent = pending.pop()
            for entry in mount.iter_entries(parent):
                path = str(entry.path)
                if entry.is_dir:
                    pending.append(path)
                    continue
                item = file_item(mount, path, path)
                item["sourceName"] = (
                    path[len(directory) + 1 :]
                    if path.startswith(f"{directory}.")
                    else path.rsplit(".", 1)[-1]
                )
                items.append(item)
        return items

    def _repair_copied_adfs_loaders(
        self, target: ImageSession, directory: str
    ) -> tuple[list[str], list[str]]:
        try:
            from oaknut.disc.cli import _file_item, _write_copy_item
        except ImportError as exc:
            raise DiskError("The Oaknut loader-repair API is unavailable.") from exc
        with self.adfs_mount(target) as mount:
            items = self._adfs_directory_items(mount, directory, _file_item)
            repairs, warnings = self._repair_adfs_loader_items(items)
            for item in items:
                if item.get("loaderRepairs"):
                    _write_copy_item(mount, str(item["dst"]), item, True)
        if repairs:
            target.dirty = True
        return repairs, warnings

    @staticmethod
    def _adfs_installation_roots(
        directory_files: dict[str, list[str]], source_names: dict[str, str]
    ) -> list[str]:
        loader_names = {"!BOOT", "BOOT", "GO", "MENU", "LOADER", "START"}
        menu_markers = {"GAMDATA", "GAMINDX", "PUBDATA", "PUBINDX", "UNIMENU"}
        candidates = {path for path in source_names if path in directory_files}
        for path, names in directory_files.items():
            upper = {name.upper() for name in names}
            if upper & loader_names and not menu_markers.issubset(upper):
                candidates.add(path)
        roots: list[str] = []
        for candidate in sorted(candidates, key=lambda item: (item.count("."), item.casefold())):
            if any(candidate.casefold().startswith(f"{root.casefold()}.") for root in roots):
                continue
            roots.append(candidate)
        return roots

    def audit_adfs_installations(
        self,
        session: ImageSession,
        root: str = "$",
        progress: Callable[[str, int | None, int | None], None] | None = None,
    ) -> dict:
        if session.kind != "adfs" or not self.summary(session)["hardDisk"]:
            raise DiskError("Installed disk auditing is available only for ADFS HDD images.")
        report = progress or (lambda _message, _current=None, _total=None: None)
        try:
            from oaknut.disc.cli import _file_item
        except ImportError as exc:
            raise DiskError("The Oaknut ADFS audit API is unavailable.") from exc
        with self.adfs_mount(session) as mount:
            if not mount.exists(root):
                raise DiskError(f"Path not found: {root}")
            directory_files: dict[str, list[str]] = {}
            pending = [root]
            while pending:
                directory = pending.pop()
                entries = list(mount.iter_entries(directory))
                directory_files[directory] = [str(entry.name) for entry in entries if not entry.is_dir]
                pending.extend(str(entry.path) for entry in entries if entry.is_dir)
            source_names = {
                path: name for path, name in session.adfs_source_names.items()
                if path == root or path.startswith(f"{root}.")
            }
            roots = self._adfs_installation_roots(directory_files, source_names)
            findings = []
            for offset, directory in enumerate(roots):
                report(f"Checking installed software in {directory}", offset, len(roots))
                files = self._adfs_directory_items(mount, directory, _file_item)
                proposed = [dict(item) for item in files]
                repairs, warnings = self._repair_adfs_loader_items(proposed)
                findings.append({
                    "path": directory,
                    "source": source_names.get(directory, ""),
                    "fileCount": len(files),
                    "repairs": repairs,
                    "warnings": warnings,
                    "status": "repairable" if repairs else "warning" if warnings else "clean",
                })
            report("Installed software audit complete", len(roots), len(roots))
        return {
            "root": root,
            "directories": findings,
            "checked": len(findings),
            "repairable": sum(bool(item["repairs"]) for item in findings),
            "warnings": sum(bool(item["warnings"]) for item in findings),
        }

    def repair_adfs_installations(
        self,
        session: ImageSession,
        directories: list[str],
        progress: Callable[[str, int | None, int | None], None] | None = None,
    ) -> dict:
        if session.kind != "adfs" or not self.summary(session)["hardDisk"]:
            raise DiskError("Installed disk repair is available only for ADFS HDD images.")
        unique = list(dict.fromkeys(str(path) for path in directories if str(path)))
        if not unique:
            raise DiskError("Choose at least one repairable installed disk directory.")
        current = self.audit_adfs_installations(session)
        available = {item["path"]: item for item in current["directories"] if item["repairs"]}
        unknown = [path for path in unique if path not in available]
        if unknown:
            raise DiskError(
                "The audit result is stale or no deterministic repair remains for: " + ", ".join(unknown)
            )
        report = progress or (lambda _message, _current=None, _total=None: None)
        repaired = []
        try:
            from oaknut.disc.cli import _file_item, _write_copy_item
        except ImportError as exc:
            raise DiskError("The Oaknut loader-repair API is unavailable.") from exc
        with self.adfs_mount(session) as mount:
            for offset, directory in enumerate(unique):
                report(f"Repairing installed software in {directory}", offset, len(unique))
                items = self._adfs_directory_items(mount, directory, _file_item)
                repairs, warnings = self._repair_adfs_loader_items(items)
                for item in items:
                    if item.get("loaderRepairs"):
                        _write_copy_item(mount, str(item["dst"]), item, True)
                for repair in repairs:
                    self._append_warning(session, f"{directory}: ADFS compatibility change made: {repair}.")
                for warning in warnings:
                    self._append_warning(session, f"{directory}: {warning}")
                repaired.append({"path": directory, "repairs": repairs, "warnings": warnings})
        session.dirty = True
        self._persist_session(session)
        report("Installed software repair complete", len(unique), len(unique))
        return {"repaired": repaired, "count": len(repaired)}
