"""Task Scheduler — Priority-based task queuing and dispatch."""

import heapq
import time
from typing import Any, Dict, Optional, Set
from uuid import uuid4


class PriorityQueue:
    def __init__(self):
        self._queue = []
        self._counter = 0

    def push(self, item: Any, priority: int = 0) -> None:
        heapq.heappush(self._queue, (-priority, self._counter, item))
        self._counter += 1

    def pop(self) -> Optional[Any]:
        if self._queue:
            return heapq.heappop(self._queue)[2]
        return None

    def peek(self) -> Optional[Any]:
        if self._queue:
            return self._queue[0][2]
        return None

    def __len__(self) -> int:
        return len(self._queue)


class TaskScheduler:
    def __init__(self):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, Dict[str, Any]] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._queued_task_ids: Set[str] = set()
        self._terminal_task_ids: Set[str] = set()
        self._task_ids_by_key: Dict[str, str] = {}
        self._keys_by_task_id: Dict[str, str] = {}
        self._max_retries = 3

    def enqueue(
        self,
        task: Dict,
        queue: str = "default",
        priority: int = 0,
    ) -> str:
        key = self._dedupe_key(task)
        existing_task_id = self._existing_task_id(key)
        if existing_task_id:
            return existing_task_id

        return self._queue_task(task, queue, priority, key)

    def schedule(
        self,
        task: Dict,
        delay: float,
        queue: str = "default",
        priority: int = 0,
    ) -> str:
        key = self._dedupe_key(task)
        existing_task_id = self._existing_task_id(key)
        due_at = time.time() + delay

        if existing_task_id:
            if existing_task_id in self._scheduled:
                entry = self._scheduled[existing_task_id]
                entry["due_at"] = min(entry["due_at"], due_at)
                entry["priority"] = max(entry["priority"], priority)
            return existing_task_id

        task_id = task.get("id") or str(uuid4())
        task["id"] = task_id
        task["scheduled_for"] = due_at
        task["priority"] = priority
        task.setdefault("retries", 0)
        self._register_task_key(task_id, key)
        self._scheduled[task_id] = {
            "task": task,
            "due_at": due_at,
            "queue": queue,
            "priority": priority,
            "key": key,
        }
        return task_id

    def _queue_task(
        self,
        task: Dict,
        queue: str,
        priority: int,
        key: Optional[str],
    ) -> str:
        task_id = task.get("id") or str(uuid4())
        if (
            task_id in self._queued_task_ids
            or task_id in self._in_flight
            or task_id in self._terminal_task_ids
        ):
            return task_id

        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["priority"] = priority
        task.setdefault("retries", 0)
        self._register_task_key(task_id, key)
        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        self._queued_task_ids.add(task_id)
        return task_id

    def _dedupe_key(self, task: Dict) -> Optional[str]:
        for field in ("schedule_key", "idempotency_key", "run_id"):
            value = task.get(field)
            if value is not None:
                return str(value)
        return None

    def _existing_task_id(self, key: Optional[str]) -> Optional[str]:
        if key is None:
            return None

        task_id = self._task_ids_by_key.get(key)
        if task_id is None:
            return None

        if (
            task_id in self._scheduled
            or task_id in self._queued_task_ids
            or task_id in self._in_flight
            or task_id in self._terminal_task_ids
        ):
            return task_id

        self._task_ids_by_key.pop(key, None)
        self._keys_by_task_id.pop(task_id, None)
        return None

    def _register_task_key(self, task_id: str, key: Optional[str]) -> None:
        if key is None:
            return
        self._task_ids_by_key.setdefault(key, task_id)
        self._keys_by_task_id[task_id] = key

    async def dequeue(
        self,
        queue: str = "default",
        timeout: float = 1.0,
    ) -> Optional[Dict]:
        now = time.time()
        expired = [
            tid
            for tid, entry in self._scheduled.items()
            if entry["due_at"] <= now
        ]
        for tid in expired:
            entry = self._scheduled.pop(tid)
            self._queue_task(
                entry["task"],
                entry["queue"],
                entry["priority"],
                entry["key"],
            )

        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            if task:
                self._queued_task_ids.discard(task["id"])
                self._in_flight[task["id"]] = task
                return task
        return None

    def complete(self, task_id: str) -> bool:
        task = self._in_flight.pop(task_id, None)
        if task is None:
            return False
        self._terminal_task_ids.add(task_id)
        return True

    def fail(self, task_id: str, queue: str = "default") -> bool:
        task = self._in_flight.pop(task_id, None)
        if task:
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                key = self._keys_by_task_id.get(task_id)
                self._queue_task(
                    task,
                    queue,
                    priority=task.get("priority", 0),
                    key=key,
                )
                return True
            self._terminal_task_ids.add(task_id)
        return False

# 2019-04-25T08:37:12 update

# 2019-06-04T16:40:00 update

# 2019-07-11T12:01:28 update

# 2019-08-02T12:20:21 update

# 2019-08-23T10:38:50 update

# 2019-10-31T13:55:52 update

# 2019-11-04T20:12:32 update

# 2019-12-13T12:22:36 update

# 2020-02-01T10:32:37 update

# 2020-02-26T09:44:38 update

# 2020-03-09T19:00:55 update

# 2020-05-01T18:40:34 update

# 2020-05-12T15:10:31 update

# 2020-06-30T13:24:19 update

# 2020-09-22T16:00:45 update

# 2020-10-20T10:52:48 update

# 2020-10-21T12:18:08 update

# 2020-11-06T12:35:01 update

# 2020-12-09T08:09:33 update

# 2021-01-07T08:20:36 update

# 2021-10-02T15:23:16 update

# 2021-10-06T16:14:57 update

# 2021-10-06T09:27:41 update

# 2021-11-19T08:37:40 update

# 2022-03-01T16:39:54 update

# 2022-05-26T13:43:07 update

# 2022-06-02T10:50:58 update

# 2022-06-14T10:46:48 update

# 2022-07-31T16:44:34 update

# 2022-08-30T18:20:12 update

# 2022-11-04T14:47:03 update

# 2022-12-06T10:36:49 update

# 2022-12-22T13:21:12 update

# 2022-12-26T12:24:50 update

# 2023-03-09T08:09:55 update

# 2023-05-01T10:07:37 update

# 2023-06-08T14:32:15 update

# 2023-07-14T17:24:18 update

# 2023-12-14T08:38:31 update

# 2024-02-20T13:43:58 update

# 2024-03-24T08:52:42 update

# 2024-03-28T15:27:17 update

# 2024-03-29T18:10:33 update

# 2024-04-15T20:18:31 update

# 2024-05-27T13:11:52 update

# 2024-05-27T16:42:56 update

# 2024-06-20T13:03:45 update

# 2024-06-28T12:32:58 update

# 2024-07-10T14:10:16 update

# 2024-07-26T14:18:59 update

# 2024-08-12T08:21:05 update

# 2024-08-21T16:58:40 update

# 2024-09-27T19:54:30 update

# 2024-10-21T13:47:42 update

# 2024-11-11T09:19:27 update

# 2024-12-24T08:23:41 update

# 2025-02-14T10:35:15 update

# 2025-03-31T18:09:40 update

# 2025-06-21T17:32:49 update

# 2025-07-21T16:52:28 update

# 2025-08-20T19:45:16 update

# 2025-11-04T18:54:24 update

# 2025-12-09T20:17:36 update

# 2026-01-12T15:42:32 update

# 2026-01-23T14:41:20 update

# 2026-03-18T14:43:07 update

# 2026-04-13T11:43:19 update
