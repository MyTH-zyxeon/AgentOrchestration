"""Database advisory locks for orchestration state transitions."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from threading import Lock
from typing import Callable, Dict, Iterator, Optional

logger = logging.getLogger(__name__)


class LockManagerError(Exception):
    """Base error for advisory lock failures."""


class LockTimeoutError(LockManagerError):
    """Raised when an advisory lock cannot be acquired before the deadline."""


class LockAcquisitionError(LockManagerError):
    """Raised when the database rejects lock acquisition."""


class LockReleaseError(LockManagerError):
    """Raised when the database rejects lock release."""


@dataclass
class AdvisoryLock:
    """One held PostgreSQL advisory lock."""

    key: str
    lock_id: int
    connection: object
    acquired_at: float


class LockManager:
    """Acquire PostgreSQL advisory locks and always release them on exit."""

    def __init__(
        self,
        connection_factory: Callable[[], object],
        *,
        default_timeout: float = 30.0,
        poll_interval: float = 0.05,
    ) -> None:
        self._connection_factory = connection_factory
        self._default_timeout = default_timeout
        self._poll_interval = poll_interval
        self._active_locks: Dict[str, AdvisoryLock] = {}
        self._active_lock = Lock()

    @staticmethod
    def lock_id_for(key: str) -> int:
        """Return a stable signed 64-bit advisory lock id."""
        digest = hashlib.sha256(key.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], byteorder="big", signed=True)

    def active_lock_count(self) -> int:
        with self._active_lock:
            return len(self._active_locks)

    def is_locked(self, key: str) -> bool:
        with self._active_lock:
            return key in self._active_locks

    @contextmanager
    def lock(
        self,
        key: str,
        *,
        timeout: Optional[float] = None,
    ) -> Iterator[AdvisoryLock]:
        """Acquire a lock and release it even if the protected block raises."""
        connection = self._connection_factory()
        advisory_lock: Optional[AdvisoryLock] = None

        try:
            lock_id = self.lock_id_for(key)
            self._acquire(connection, lock_id, key, self._timeout(timeout))
            advisory_lock = AdvisoryLock(
                key=key,
                lock_id=lock_id,
                connection=connection,
                acquired_at=time.time(),
            )
            with self._active_lock:
                self._active_locks[key] = advisory_lock
            yield advisory_lock
        finally:
            if advisory_lock is not None:
                try:
                    self._release(connection, advisory_lock.lock_id)
                finally:
                    with self._active_lock:
                        self._active_locks.pop(key, None)
            self._close(connection)

    @asynccontextmanager
    async def lock_async(
        self,
        key: str,
        *,
        timeout: Optional[float] = None,
    ) -> Iterator[AdvisoryLock]:
        """Async wrapper for the synchronous PostgreSQL advisory lock calls."""
        connection = self._connection_factory()
        advisory_lock: Optional[AdvisoryLock] = None

        try:
            lock_id = self.lock_id_for(key)
            await asyncio.to_thread(
                self._acquire,
                connection,
                lock_id,
                key,
                self._timeout(timeout),
            )
            advisory_lock = AdvisoryLock(
                key=key,
                lock_id=lock_id,
                connection=connection,
                acquired_at=time.time(),
            )
            with self._active_lock:
                self._active_locks[key] = advisory_lock
            yield advisory_lock
        finally:
            if advisory_lock is not None:
                try:
                    await asyncio.to_thread(
                        self._release,
                        connection,
                        advisory_lock.lock_id,
                    )
                finally:
                    with self._active_lock:
                        self._active_locks.pop(key, None)
            await asyncio.to_thread(self._close, connection)

    def _timeout(self, timeout: Optional[float]) -> float:
        return self._default_timeout if timeout is None else timeout

    def _acquire(
        self,
        connection: object,
        lock_id: int,
        key: str,
        timeout: float,
    ) -> None:
        deadline = time.monotonic() + timeout
        while True:
            try:
                if self._execute_scalar(
                    connection,
                    "SELECT pg_try_advisory_lock(%s)",
                    (lock_id,),
                ):
                    return
            except Exception as exc:
                raise LockAcquisitionError(
                    f"Failed to acquire advisory lock for {key!r}"
                ) from exc

            if time.monotonic() >= deadline:
                raise LockTimeoutError(
                    f"Timed out acquiring advisory lock for {key!r}"
                )
            time.sleep(self._poll_interval)

    def _release(self, connection: object, lock_id: int) -> None:
        try:
            released = self._execute_scalar(
                connection,
                "SELECT pg_advisory_unlock(%s)",
                (lock_id,),
            )
        except Exception as exc:
            raise LockReleaseError(
                f"Failed to release advisory lock {lock_id}"
            ) from exc
        if not released:
            raise LockReleaseError(f"Advisory lock {lock_id} was not held")

    @staticmethod
    def _execute_scalar(
        connection: object,
        sql: str,
        params: tuple[int],
    ) -> bool:
        cursor = connection.cursor()
        try:
            cursor.execute(sql, params)
            row = cursor.fetchone()
            return bool(row[0])
        finally:
            cursor.close()

    @staticmethod
    def _close(connection: object) -> None:
        try:
            connection.close()
        except Exception:
            logger.warning(
                "Failed to close advisory lock connection",
                exc_info=True,
            )
