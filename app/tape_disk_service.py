from __future__ import annotations

import uuid
from pathlib import Path

from .errors import DiskError
from .image_session import ImageSession
from .uef import (
    TapeFile,
    UEFContents,
    UEFError,
    basic_unopened_channel_io,
    is_tokenized_basic,
    parse_uef,
    rewrite_basic_loader,
)


class TapeDiskMixin:
    """Tape parsing and UEF-to-DFS conversion for ``DiskService``."""

    @staticmethod
    def _tape(session: ImageSession) -> UEFContents:
        if session.tape is None:
            try:
                session.tape = parse_uef(session.path.read_bytes())
            except UEFError as exc:
                raise DiskError(str(exc)) from exc
        return session.tape

    def _tape_file(self, session: ImageSession, inner: str) -> TapeFile:
        name = inner.rsplit(".", 1)[-1]
        for item in self._tape(session).files:
            if item.name.casefold() == name.casefold():
                return item
        raise DiskError(f"Tape file “{name}” was not found.")

    def _dfs_conversion_name(self, name: str, used: set[str]) -> str:
        return self._unique_import_name(name, used, 7)

    def convert_uef(self, session: ImageSession, disk_format: str) -> tuple[ImageSession, list[dict]]:
        if session.kind != "tape":
            raise DiskError("Only UEF tapes can be converted.")
        if disk_format not in {"ssd", "dsd"}:
            raise DiskError("A UEF can be converted to SSD or DSD.")
        tape = self._tape(session)
        if not tape.files:
            raise DiskError("No standard Acorn tape files were found to place on a DFS disk.")
        title = Path(session.name).stem[:12] or "UEF"
        target = self.create_blank(disk_format, title)
        new_name = self.safe_filename(f"{Path(session.name).stem}.{disk_format}")
        new_path = target.path.with_name(new_name)
        target.path.rename(new_path)
        target.path = new_path
        target.name = new_name
        self._persist_session(target)
        used: set[str] = set()
        plans: list[tuple[TapeFile, str]] = [
            (tape_file, self._dfs_conversion_name(tape_file.name, used))
            for tape_file in tape.files
        ]
        name_map = {
            source_name: dfs_name
            for tape_file, dfs_name in plans
            for source_name in (tape_file.name, tape_file.original_name)
            if source_name and source_name.strip()
        }
        converted: list[dict] = []
        generated_boot: dict | None = None
        boot_name = next((name for tape_file, name in plans if tape_file.name.casefold() == "!boot"), None)
        if boot_name is None:
            launch_file, launch_name = next(
                ((item, name) for item, name in plans if item.complete),
                plans[0],
            )
            if basic_unopened_channel_io(launch_file.data):
                self._append_warning(
                    target,
                    f"No !BOOT was generated because {launch_name} uses a cassette-inherited "
                    "file channel without opening it. Direct disk launch would raise BASIC "
                    "error 222 (Channel).",
                )
            else:
                command = f'CHAIN "{launch_name}"\r' if is_tokenized_basic(launch_file.data) else f"*RUN {launch_name}\r"
                temp_path = self.work_dir / f"uef-boot-{uuid.uuid4().hex}"
                temp_path.write_bytes(command.encode("latin-1"))
                try:
                    self.put(target, None, "$.!BOOT", temp_path, "0", "0", None, 0 if disk_format == "dsd" else None)
                finally:
                    temp_path.unlink(missing_ok=True)
                generated_boot = {
                    "source": "Generated disk boot",
                    "destination": "!BOOT",
                    "side": 0,
                    "complete": True,
                    "generated": True,
                    "loaderChanges": [f"Created {command.strip()} as the disk boot command."],
                }
        current_side = 0
        for position, (tape_file, dfs_name) in enumerate(plans):
            next_name = plans[position + 1][1] if position + 1 < len(plans) else None
            payload, loader_changes = rewrite_basic_loader(tape_file.data, next_name, name_map)
            temp_path = self.work_dir / f"uef-convert-{uuid.uuid4().hex}"
            temp_path.write_bytes(payload)
            try:
                try:
                    self.put(
                        target, None, f"$.{dfs_name}", temp_path,
                        hex(tape_file.load), hex(tape_file.execute), None,
                        current_side if disk_format == "dsd" else None,
                    )
                except DiskError:
                    if disk_format != "dsd" or current_side == 2:
                        raise
                    current_side = 2
                    self.put(
                        target, None, f"$.{dfs_name}", temp_path,
                        hex(tape_file.load), hex(tape_file.execute), None, current_side,
                    )
            finally:
                temp_path.unlink(missing_ok=True)
            converted.append({
                "source": tape_file.name,
                "destination": dfs_name,
                "side": current_side if disk_format == "dsd" else 0,
                "complete": tape_file.complete,
                "inferredName": tape_file.inferred_name,
                "loaderChanges": list(loader_changes),
            })

        if generated_boot:
            converted.append(generated_boot)
        try:
            self._run(["opt", str(target.path), "3"])
            self._mark_mutated(target, None)
        except DiskError as exc:
            self._append_warning(target, f"The files were converted, but DFS boot option 3 could not be set: {exc}")

        if len(plans) > 1 and not is_tokenized_basic(plans[0][0].data):
            self._append_warning(
                target,
                "The initial tape loader is not tokenised BASIC. Its internal cassette calls could not be "
                "rewritten automatically; test the converted disk before relying on it.",
            )
        for tape_file, dfs_name in plans:
            if not tape_file.complete:
                self._append_warning(
                    target,
                    f"{dfs_name} was recovered from an incomplete tape file and may not run correctly.",
                )
        return target, converted
