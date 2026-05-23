"""Append-safe JSONL event log writer."""

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, Optional

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class JsonlEventLog:
    def __init__(
        self,
        path: Path,
        max_bytes: Optional[int] = None,
        backups: int = 3,
    ):
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.backups = max(1, backups)
        self.malformed_record_count = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self.path.with_suffix(f"{self.path.suffix}.lock")

    def append(self, event: Dict) -> None:
        record = self._encode(event)
        with self._locked():
            self._rotate_if_needed(len(record))
            flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
            fd = os.open(self.path, flags, 0o644)
            try:
                os.write(fd, record)
                os.fsync(fd)
            finally:
                os.close(fd)

    def _encode(self, event: Dict) -> bytes:
        line = json.dumps(event, sort_keys=True, separators=(",", ":"))
        json.loads(line)
        return f"{line}\n".encode("utf-8")

    def _rotate_if_needed(self, record_size: int) -> None:
        if not self.max_bytes or not self.path.exists():
            return
        if self.path.stat().st_size == 0:
            return
        if self.path.stat().st_size + record_size <= self.max_bytes:
            return

        oldest = self._backup_path(self.backups)
        oldest.unlink(missing_ok=True)
        for index in range(self.backups - 1, 0, -1):
            src = self._backup_path(index)
            dst = self._backup_path(index + 1)
            if src.exists():
                src.replace(dst)
        self.path.replace(self._backup_path(1))

    def _backup_path(self, index: int) -> Path:
        return self.path.with_name(f"{self.path.name}.{index}")

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_path.open("a+b") as lock_file:
            self._lock_file(lock_file)
            try:
                yield
            finally:
                self._unlock_file(lock_file)

    @staticmethod
    def _lock_file(lock_file) -> None:
        if os.name == "nt":
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

    @staticmethod
    def _unlock_file(lock_file) -> None:
        if os.name == "nt":
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
