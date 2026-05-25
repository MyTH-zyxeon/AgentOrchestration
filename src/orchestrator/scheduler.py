"""Task Scheduler — Priority-based task queuing and dispatch."""

import heapq
import inspect
import time
from typing import Any, Callable, Dict, List, Optional
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


class QueuePausedError(RuntimeError):
    """Raised when queue intake is paused for maintenance."""


class TaskScheduler:
    def __init__(self):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._in_flight_queues: Dict[str, str] = {}
        self._paused_queues: Dict[str, Dict[str, Any]] = {}
        self.audit_log: List[Dict[str, Any]] = []
        self.operator_alerts: List[Dict[str, Any]] = []
        self._max_retries = 3

    def enqueue(
        self,
        task: Dict,
        queue: str = "default",
        priority: int = 0,
    ) -> str:
        if queue in self._paused_queues:
            self._record_queue_decision(
                "rejected",
                queue,
                "intake_paused",
            )
            raise QueuePausedError(f"queue intake is paused: {queue}")

        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        return task_id

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
    ) -> Optional[Dict]:
        if queue in self._paused_queues:
            self._record_queue_decision(
                "deferred",
                queue,
                "intake_paused",
            )
            return None

        now = time.time()
        expired = [tid for tid, t in self._scheduled.items() if t <= now]
        for tid in expired:
            task = self._scheduled.pop(tid)
            if task:
                self.enqueue(task, queue)

        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            if task:
                self._in_flight[task["id"]] = task
                self._in_flight_queues[task["id"]] = queue
                return task
        return None

    def pause_intake(
        self,
        queue: str = "default",
        reason: str = "maintenance",
    ) -> Dict[str, Any]:
        status = {
            "queue": queue,
            "state": "paused",
            "reason": reason,
            "paused_at": time.time(),
        }
        self._paused_queues[queue] = status
        self._record_queue_decision("paused", queue, reason)
        return dict(status)

    def resume_intake(self, queue: str = "default") -> bool:
        paused = self._paused_queues.pop(queue, None)
        if paused is None:
            return False
        self._record_queue_decision("resumed", queue, paused["reason"])
        return True

    def queue_status(self, queue: str = "default") -> Dict[str, Any]:
        paused = self._paused_queues.get(queue)
        state = "paused" if paused else "active"
        return {
            "queue": queue,
            "state": state,
            "reason": paused["reason"] if paused else None,
            "queued": len(self._queues.get(queue, [])),
            "in_flight": self._count_in_flight(queue),
        }

    async def drain(
        self,
        queue: str = "default",
        timeout: float = 1.0,
        poll_interval: float = 0.01,
    ) -> bool:
        if timeout < 0:
            raise ValueError("timeout must be non-negative")
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")

        deadline = time.time() + timeout
        while self._count_in_flight(queue) > 0:
            if time.time() >= deadline:
                self._record_queue_decision(
                    "drain_timeout",
                    queue,
                    "leased_tasks",
                )
                return False
            await self._sleep(poll_interval)
        self._record_queue_decision("drained", queue, "leased_tasks")
        return True

    async def run_maintenance(
        self,
        migration: Callable[[], Any],
        queue: str = "default",
        drain_timeout: float = 1.0,
    ) -> Any:
        self.pause_intake(queue=queue, reason="maintenance")
        drained = await self.drain(queue=queue, timeout=drain_timeout)
        if not drained:
            self._operator_alert(queue, "drain_timeout")
            raise TimeoutError(f"queue did not drain before timeout: {queue}")

        try:
            result = migration()
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            self._operator_alert(queue, "migration_failed")
            raise exc

        self.resume_intake(queue)
        return result

    def complete(self, task_id: str) -> bool:
        completed = self._in_flight.pop(task_id, None) is not None
        if completed:
            self._in_flight_queues.pop(task_id, None)
        return completed

    def fail(self, task_id: str, queue: str = "default") -> bool:
        task = self._in_flight.pop(task_id, None)
        self._in_flight_queues.pop(task_id, None)
        if task:
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                self.enqueue(task, queue, priority=task.get("priority", 0))
                return True
        return False

    async def _sleep(self, delay: float) -> None:
        import asyncio
        await asyncio.sleep(delay)

    def _count_in_flight(self, queue: str) -> int:
        return sum(
            1
            for task_queue in self._in_flight_queues.values()
            if task_queue == queue
        )

    def _record_queue_decision(
        self,
        decision: str,
        queue: str,
        reason: str,
    ) -> None:
        self.audit_log.append(
            {
                "decision": decision,
                "queue": queue,
                "reason": reason,
            }
        )

    def _operator_alert(self, queue: str, reason: str) -> None:
        self.operator_alerts.append(
            {
                "queue": queue,
                "reason": reason,
                "state": "paused",
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
