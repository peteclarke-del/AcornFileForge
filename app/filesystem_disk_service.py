from __future__ import annotations

from contextlib import contextmanager

from .adfs_capabilities import capabilities_from_mount
from .errors import DiskError
from .image_session import ImageSession


class FilesystemDiskMixin:
    """Trusted ADFS and ROMFS mounts plus ROMFS filesystem metadata edits."""

    @contextmanager
    def adfs_mount(self, session: ImageSession):
        """Open an identified ADFS image without probing or copying it again."""
        if session.kind != "adfs":
            raise DiskError("This operation requires an ADFS image.")
        try:
            from oaknut.filesystem import create_filesystem, geometry_from_dsc, reader_for
        except ImportError as exc:
            raise DiskError("The Oaknut ADFS filesystem API is unavailable.") from exc

        with session.lock:
            reader = reader_for(session.path, writable=True)
            mount = None
            try:
                geometry = None
                if session.descriptor_path and session.descriptor_path.is_file():
                    geometry = geometry_from_dsc(session.descriptor_path.read_bytes())
                mount = create_filesystem("adfs").open(reader, geometry)
                yield mount
            except DiskError:
                raise
            except Exception as exc:
                raise DiskError(self._friendly_engine_error(str(exc))) from exc
            finally:
                if mount is not None:
                    adfs = getattr(mount, "_adfs", None)
                    unified = getattr(adfs, "_d", None)
                    disc_image = getattr(unified, "_disc_image", None)
                    try:
                        close_adfs = getattr(adfs, "close", None)
                        if callable(close_adfs):
                            close_adfs()
                    finally:
                        close_disc = getattr(disc_image, "close", None)
                        if callable(close_disc):
                            close_disc()
                reader.close()

    def refresh_adfs_capabilities(self, session: ImageSession) -> dict:
        """Cache the mounted FileCore format and its real directory limits."""
        if session.kind != "adfs":
            session.adfs_capabilities = {}
            return {}
        with self.adfs_mount(session) as mount:
            capabilities = capabilities_from_mount(mount).to_dict()
        session.adfs_capabilities = {
            "format": capabilities["format"],
            "map": capabilities["map"],
            "directories": capabilities["directories"],
            "nameLimit": capabilities["name_limit"],
            "directoryEntryLimit": capabilities["directory_entry_limit"],
        }
        return session.adfs_capabilities

    @contextmanager
    def romfs_mount(self, session: ImageSession, *, writable: bool = False):
        """Open an identified ROMFS image without probing it again."""
        if session.kind != "romfs":
            raise DiskError("This operation requires an Acorn ROMFS image.")
        if writable:
            self.require_writable_geometry(session)
        try:
            from oaknut.filesystem import create_filesystem, reader_for
        except ImportError as exc:
            raise DiskError("The Oaknut ROMFS filesystem API is unavailable.") from exc
        with session.lock:
            reader = reader_for(session.path, writable=writable)
            try:
                mount = create_filesystem("acorn-romfs").open(reader, None)
                yield mount
            except DiskError:
                raise
            except Exception as exc:
                raise DiskError(self._friendly_engine_error(str(exc))) from exc
            finally:
                reader.close()

    def romfs_details(self, session: ImageSession) -> dict:
        """Return decoded ROMFS identity, safety and capacity information."""
        try:
            from oaknut.romfs.romfs import ROMFS
            romfs = ROMFS.from_bytes(session.path.read_bytes())
        except Exception as exc:
            raise DiskError(f"The ROMFS catalogue is invalid: {exc}") from exc
        warnings = []
        if not romfs.is_complete:
            warnings.append(
                "The ROMFS block chain has no end marker. It may be truncated or one part of a multi-ROM set."
            )
        if romfs.is_complete and not romfs.is_plain:
            warnings.append(
                "Executable or opaque content follows the ROMFS catalogue, so this composite image is read-only."
            )
        fs_end = int(getattr(romfs, "_fs_end", session.path.stat().st_size))
        total = session.path.stat().st_size
        return {
            "title": romfs.title,
            "headerTitle": romfs.header_title,
            "version": romfs.version,
            "copyright": romfs.copyright,
            "romType": romfs.rom_type,
            "dataOffset": romfs.data_offset,
            "fileCount": len(romfs.data_files),
            "complete": romfs.is_complete,
            "plain": romfs.is_plain,
            "readOnly": not romfs.is_complete or not romfs.is_plain,
            "capacity": {
                "available": romfs.is_complete and romfs.is_plain,
                "unit": "bytes",
                "total": total,
                "used": min(total, fs_end),
                "free": max(0, total - fs_end),
                "reason": "Composite and multi-ROM images cannot report safely writable tail space."
                if not (romfs.is_complete and romfs.is_plain) else None,
            },
            "warnings": warnings,
        }

    def set_romfs_properties(
        self,
        session: ImageSession,
        *,
        title: str,
        version: int,
        copyright_text: str,
    ) -> None:
        """Update ROMFS catalogue and paged-ROM identity as one guarded edit."""
        if session.kind != "romfs":
            raise DiskError("This image does not contain an Acorn ROMFS filesystem.")
        title = str(title or "").strip()
        if not title or len(title) > 8:
            raise DiskError("A ROMFS title can contain 1 to 8 characters.")
        copyright_text = str(copyright_text or "").strip()
        if not copyright_text.startswith("(C)"):
            raise DiskError("A paged-ROM copyright must begin with (C).")
        if len(copyright_text) > 120:
            raise DiskError("A paged-ROM copyright can contain at most 120 characters.")
        try:
            version = int(version)
        except (TypeError, ValueError) as exc:
            raise DiskError("ROMFS version must be from 0 to 255.") from exc
        if not 0 <= version <= 255:
            raise DiskError("ROMFS version must be from 0 to 255.")
        original = session.path.read_bytes()
        try:
            with self.romfs_mount(session, writable=True) as mount:
                mount.set_title(title)
            from oaknut.romfs.romfs import set_copyright, set_version
            data = set_version(session.path.read_bytes(), version)
            session.path.write_bytes(set_copyright(data, copyright_text))
        except Exception as exc:
            session.path.write_bytes(original)
            raise DiskError(f"The ROMFS paged-ROM header could not be updated: {exc}") from exc
        self._mark_mutated(session, None)
