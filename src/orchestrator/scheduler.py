"""Task Scheduler — Priority-based task queuing and dispatch."""

import heapq
import time
from typing import Any, Dict, List, Optional
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
        self._acked_tasks: Dict[str, Dict[str, Any]] = {}
        self._ack_audit: List[Dict[str, Any]] = []
        self._max_retries = 3

    def enqueue(
        self,
        task: Dict,
        queue: str = "default",
        priority: int = 0,
    ) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["priority"] = priority
        task["retries"] = task.get("retries", 0)

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
        worker_id: Optional[str] = None,
    ) -> Optional[Dict]:
        now = time.time()
        expired = [tid for tid, t in self._scheduled.items() if t <= now]
        for tid in expired:
            task = self._scheduled.pop(tid)
            if task:
                self.enqueue(task, queue)

        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            if task:
                if worker_id is not None:
                    task["assigned_worker"] = worker_id
                task["dequeued_at"] = now
                self._in_flight[task["id"]] = task
                return task
        return None

    def complete(self, task_id: str, worker_id: Optional[str] = None) -> bool:
        task = self._in_flight.get(task_id)
        if not task or not self._worker_owns_task(task, worker_id):
            if task:
                self._record_ack_audit(
                    task,
                    worker_id,
                    "wrong_worker",
                    "complete",
                )
            return False
        self._in_flight.pop(task_id)
        self._acked_tasks[task_id] = {
            "action": "complete",
            "worker_id": worker_id,
        }
        self._record_ack_audit(task, worker_id, "acknowledged", "complete")
        return True

    def fail(
        self,
        task_id: str,
        queue: str = "default",
        worker_id: Optional[str] = None,
    ) -> bool:
        task = self._in_flight.get(task_id)
        if not task or not self._worker_owns_task(task, worker_id):
            if task:
                self._record_ack_audit(task, worker_id, "wrong_worker", "fail")
            return False

        self._in_flight.pop(task_id)
        task["retries"] += 1
        task.pop("assigned_worker", None)
        task.pop("dequeued_at", None)
        self._acked_tasks[task_id] = {
            "action": "fail",
            "worker_id": worker_id,
        }
        self._record_ack_audit(task, worker_id, "acknowledged", "fail")
        if task["retries"] < self._max_retries:
            self.enqueue(task, queue, priority=task.get("priority", 0))
            return True
        return False

    def batch_acknowledge(
        self,
        acknowledgements: List[Dict[str, str]],
        queue: str = "default",
    ) -> List[Dict[str, Any]]:
        return [self._acknowledge_one(ack, queue) for ack in acknowledgements]

    def ack_audit(self) -> List[Dict[str, Any]]:
        return list(self._ack_audit)

    def _acknowledge_one(
        self,
        ack: Dict[str, str],
        queue: str,
    ) -> Dict[str, Any]:
        task_id = ack.get("task_id")
        worker_id = ack.get("worker_id")
        action = ack.get("action", "complete")
        if not task_id or action not in {"complete", "fail"}:
            self._record_ack_audit(
                None,
                worker_id,
                "malformed",
                action,
                task_id,
            )
            return {
                "task_id": task_id,
                "status": "malformed",
                "action": action,
            }

        if task_id in self._acked_tasks:
            self._record_ack_audit(
                None,
                worker_id,
                "duplicate",
                action,
                task_id,
            )
            return {
                "task_id": task_id,
                "status": "duplicate",
                "action": action,
            }

        task = self._in_flight.get(task_id)
        if not task:
            self._record_ack_audit(
                None,
                worker_id,
                "not_in_flight",
                action,
                task_id,
            )
            return {
                "task_id": task_id,
                "status": "not_in_flight",
                "action": action,
            }

        if not worker_id or not self._worker_owns_task(task, worker_id):
            self._record_ack_audit(task, worker_id, "wrong_worker", action)
            return {
                "task_id": task_id,
                "status": "rejected",
                "reason": "wrong_worker",
            }

        if action == "complete":
            self.complete(task_id, worker_id=worker_id)
        else:
            self.fail(task_id, queue=queue, worker_id=worker_id)
        return {
            "task_id": task_id,
            "status": "acknowledged",
            "action": action,
        }

    def _worker_owns_task(self, task: Dict, worker_id: Optional[str]) -> bool:
        assigned_worker = task.get("assigned_worker")
        return worker_id is None or assigned_worker == worker_id

    def _record_ack_audit(
        self,
        task: Optional[Dict],
        worker_id: Optional[str],
        reason: str,
        action: str,
        task_id: Optional[str] = None,
    ) -> None:
        self._ack_audit.append(
            {
                "task_id": task_id or (task or {}).get("id"),
                "worker_id": worker_id,
                "assigned_worker": (task or {}).get("assigned_worker"),
                "action": action,
                "reason": reason,
                "recorded_at": time.time(),
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
