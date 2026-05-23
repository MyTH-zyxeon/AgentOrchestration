import asyncio

import pytest

from src.common.locks import LockManager, LockTimeoutError


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.value = None
        self.closed = False

    def execute(self, sql, params):
        self.connection.calls.append((sql, params))
        if "pg_try_advisory_lock" in sql:
            self.value = self.connection.next_acquire_result()
        elif "pg_advisory_unlock" in sql:
            self.value = self.connection.next_release_result()
        else:
            raise AssertionError(f"unexpected SQL: {sql}")

    def fetchone(self):
        return (self.value,)

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, *, acquire_results=None, release_results=None):
        self.acquire_results = list(acquire_results or [True])
        self.release_results = list(release_results or [True])
        self.calls = []
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def close(self):
        self.closed = True

    def next_acquire_result(self):
        if self.acquire_results:
            return self.acquire_results.pop(0)
        return False

    def next_release_result(self):
        if self.release_results:
            return self.release_results.pop(0)
        return True

    @property
    def acquire_calls(self):
        return sum("pg_try_advisory_lock" in call[0] for call in self.calls)

    @property
    def release_calls(self):
        return sum("pg_advisory_unlock" in call[0] for call in self.calls)


def manager_for(connection):
    return LockManager(lambda: connection, default_timeout=0, poll_interval=0)


def test_lock_releases_after_success():
    connection = FakeConnection()
    manager = manager_for(connection)

    with manager.lock("run:123") as lock:
        assert lock.key == "run:123"
        assert manager.is_locked("run:123")

    assert connection.acquire_calls == 1
    assert connection.release_calls == 1
    assert connection.closed
    assert manager.active_lock_count() == 0


def test_lock_releases_after_exception():
    connection = FakeConnection()
    manager = manager_for(connection)

    with pytest.raises(RuntimeError):
        with manager.lock("run:123"):
            raise RuntimeError("worker failed")

    assert connection.release_calls == 1
    assert connection.closed
    assert manager.active_lock_count() == 0


def test_lock_timeout_fails_closed_without_release():
    connection = FakeConnection(acquire_results=[False])
    manager = manager_for(connection)

    with pytest.raises(LockTimeoutError):
        with manager.lock("run:busy"):
            pass

    assert connection.acquire_calls == 1
    assert connection.release_calls == 0
    assert connection.closed
    assert manager.active_lock_count() == 0


def test_async_lock_releases_after_exception():
    connection = FakeConnection()
    manager = manager_for(connection)

    async def fail_under_lock():
        async with manager.lock_async("run:async"):
            raise ValueError("transition failed")

    with pytest.raises(ValueError):
        asyncio.run(fail_under_lock())

    assert connection.acquire_calls == 1
    assert connection.release_calls == 1
    assert connection.closed
    assert manager.active_lock_count() == 0


def test_lock_id_is_stable_and_signed_64_bit():
    first = LockManager.lock_id_for("run:123")
    second = LockManager.lock_id_for("run:123")

    assert first == second
    assert -(2 ** 63) <= first < 2 ** 63
