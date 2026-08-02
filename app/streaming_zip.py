from __future__ import annotations

import io
import queue
import threading
import zipfile
from collections.abc import Iterator, Sequence
from pathlib import Path


_STREAM_CHUNK_SIZE = 1024 * 1024
_STREAM_QUEUE_DEPTH = 8


class _ZipStreamSink(io.RawIOBase):
    """Bounded bridge from ZipFile writes to a response iterator."""

    def __init__(
        self,
        chunks: queue.Queue[bytes | BaseException | None],
        stopped: threading.Event,
    ) -> None:
        super().__init__()
        self.chunks = chunks
        self.stopped = stopped
        self.buffer = bytearray()
        self.position = 0

    def writable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False

    def tell(self) -> int:
        return self.position

    def write(self, data) -> int:
        content = bytes(data)
        self.position += len(content)
        self.buffer.extend(content)
        while len(self.buffer) >= _STREAM_CHUNK_SIZE:
            self._emit(bytes(self.buffer[:_STREAM_CHUNK_SIZE]))
            del self.buffer[:_STREAM_CHUNK_SIZE]
        return len(content)

    def flush(self) -> None:
        if self.buffer:
            self._emit(bytes(self.buffer))
            self.buffer.clear()

    def _emit(self, item: bytes | BaseException | None) -> None:
        while not self.stopped.is_set():
            try:
                self.chunks.put(item, timeout=0.2)
                return
            except queue.Full:
                continue
        raise BrokenPipeError("ZIP download was closed")

    def finish(self, error: BaseException | None = None) -> None:
        try:
            self.flush()
            if error is not None:
                self._emit(error)
            self._emit(None)
        except BrokenPipeError:
            pass


def stream_stored_zip(files: Sequence[tuple[Path, str]]) -> Iterator[bytes]:
    """Yield a ZIP_STORED archive immediately with bounded memory use."""
    chunks: queue.Queue[bytes | BaseException | None] = queue.Queue(
        maxsize=_STREAM_QUEUE_DEPTH
    )
    stopped = threading.Event()

    def produce() -> None:
        sink = _ZipStreamSink(chunks, stopped)
        try:
            with zipfile.ZipFile(
                sink,
                "w",
                compression=zipfile.ZIP_STORED,
                allowZip64=True,
            ) as archive:
                for path, archive_name in files:
                    archive.write(path, archive_name)
        except BaseException as error:
            sink.finish(error)
        else:
            sink.finish()

    producer = threading.Thread(
        target=produce,
        name="acorn-file-forge-zip",
        daemon=True,
    )
    producer.start()
    try:
        while True:
            item = chunks.get()
            if item is None:
                break
            if isinstance(item, BaseException):
                raise item
            yield item
    finally:
        stopped.set()
