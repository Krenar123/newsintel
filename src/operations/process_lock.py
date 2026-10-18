"""Small cross-platform process lock backed by an OS-level file lock."""

from __future__ import annotations

import os
from pathlib import Path
from typing import IO, Optional


class ProcessFileLock:
    """Prevent two local processes from running the same operation at once."""

    def __init__(self, path: Path):
        self.path = path
        self.handle: Optional[IO[str]] = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.handle = self.path.open("a+", encoding="utf-8")
            self.handle.seek(0)
            if not self.handle.read(1):
                self.handle.seek(0)
                self.handle.write(" ")
                self.handle.flush()
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, IOError):
            if self.handle is not None:
                self.handle.close()
            self.handle = None
            return False

        self.handle.seek(0)
        self.handle.truncate()
        self.handle.write(str(os.getpid()))
        self.handle.flush()
        return True

    def release(self) -> None:
        if self.handle is None:
            return
        try:
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None

    def __enter__(self) -> "ProcessFileLock":
        if not self.acquire():
            raise RuntimeError(f"Operation already running: {self.path}")
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()
