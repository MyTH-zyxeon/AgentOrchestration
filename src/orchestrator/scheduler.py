"""Task Scheduler — Priority-based task queuing and dispatch."""

import heapq
import time
from typing import Any, Dict, Optional
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
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._max_retries = 3
        self.audit_records = []

    def enqueue(
        self,
        task: Dict,
        queue: str = "default",
        priority: int = 0,
    ) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0
        task["priority"] = priority

        self._queue_task(task, queue, priority)
        return task_id

    def _queue_task(self, task: Dict, queue: str, priority: int = 0) -> None:
        task.pop("reserved_at", None)
        task.pop("reserved_by", None)
        task.pop("reservation_expires_at", None)
        task.pop("reservation_token", None)
        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)

    def schedule(
        self,
        task: Dict,
        delay: float,
        queue: str = "default",
        priority: int = 0,
    ) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        self._scheduled[task_id] = time.time() + delay
        return task_id

    async def dequeue(
        self,
        queue: str = "default",
        timeout: float = 1.0,
        worker_id: Optional[str] = None,
        reservation_ttl: float = 30.0,
    ) -> Optional[Dict]:
        now = time.time()
        self.reclaim_expired_reservations(queue=queue, now=now)
        expired = [tid for tid, t in self._scheduled.items() if t <= now]
        for tid in expired:
            task = self._scheduled.pop(tid)
            if task:
                self.enqueue(task, queue)

        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            if task:
                token = str(uuid4())
                task["reserved_at"] = now
                task["reserved_by"] = worker_id
                task["reservation_expires_at"] = now + reservation_ttl
                task["reservation_token"] = token
                task["queue"] = queue
                self._in_flight[task["id"]] = task
                return task
        return None

    def complete(
        self,
        task_id: str,
        worker_id: Optional[str] = None,
        reservation_token: Optional[str] = None,
    ) -> bool:
        if not self._reservation_matches(
            task_id,
            worker_id,
            reservation_token,
        ):
            return False
        self._in_flight.pop(task_id, None)
        self._audit("task_completed", task_id, worker_id, "ack")
        return True

    def fail(
        self,
        task_id: str,
        queue: str = "default",
        worker_id: Optional[str] = None,
        reservation_token: Optional[str] = None,
    ) -> bool:
        if not self._reservation_matches(
            task_id,
            worker_id,
            reservation_token,
        ):
            return False
        task = self._in_flight.pop(task_id, None)
        if task:
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                self._queue_task(
                    task,
                    queue,
                    priority=task.get("priority", 0),
                )
                self._audit("task_requeued", task_id, worker_id, "failure")
                return True
        return False

    def worker_disconnect(self, worker_id: str, queue: str = "default") -> int:
        reclaimed = 0
        for task_id, task in list(self._in_flight.items()):
            if task.get("reserved_by") != worker_id:
                continue
            self._in_flight.pop(task_id)
            task["reclaim_count"] = task.get("reclaim_count", 0) + 1
            self._queue_task(
                task,
                task.get("queue", queue),
                task.get("priority", 0),
            )
            self._audit(
                "reservation_reclaimed",
                task_id,
                worker_id,
                "worker_disconnect",
            )
            reclaimed += 1
        if reclaimed == 0:
            self._audit("reclaim_noop", "", worker_id, "worker_disconnect")
        return reclaimed

    def reclaim_expired_reservations(
        self,
        queue: str = "default",
        now: Optional[float] = None,
    ) -> int:
        current_time = time.time() if now is None else now
        reclaimed = 0
        for task_id, task in list(self._in_flight.items()):
            expires_at = task.get("reservation_expires_at", 0)
            if expires_at > current_time:
                continue
            worker_id = task.get("reserved_by")
            self._in_flight.pop(task_id)
            task["reclaim_count"] = task.get("reclaim_count", 0) + 1
            self._queue_task(
                task,
                task.get("queue", queue),
                task.get("priority", 0),
            )
            self._audit("reservation_reclaimed", task_id, worker_id, "expired")
            reclaimed += 1
        return reclaimed

    def _reservation_matches(
        self,
        task_id: str,
        worker_id: Optional[str],
        reservation_token: Optional[str],
    ) -> bool:
        task = self._in_flight.get(task_id)
        if task is None:
            self._audit("ack_rejected", task_id, worker_id, "not_in_flight")
            return False
        if worker_id is not None and task.get("reserved_by") != worker_id:
            self._audit("ack_rejected", task_id, worker_id, "worker_mismatch")
            return False
        if (
            reservation_token is not None
            and task.get("reservation_token") != reservation_token
        ):
            self._audit("ack_rejected", task_id, worker_id, "token_mismatch")
            return False
        return True

    def _audit(
        self,
        event: str,
        task_id: str,
        worker_id: Optional[str],
        reason: str,
    ) -> None:
        self.audit_records.append(
            {
                "event": event,
                "task_id": task_id,
                "worker_id": worker_id,
                "reason": reason,
            }
        )

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
