"""Reducer state guards and diagnostics for orchestrator events."""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


TERMINAL_LIFECYCLES = {"completed", "failed", "cancelled"}
VALID_TRANSITIONS = {
    "pending": {"running", "failed", "cancelled"},
    "running": {"completed", "failed", "cancelled"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}


@dataclass
class ReducerState:
    run_id: str
    revision: int = 0
    lifecycle: str = "pending"
    attempt_id: Optional[str] = None
    values: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReducerError:
    run_id: str
    event_id: str
    reason: str
    expected_revision: Optional[int]
    actual_revision: int
    attempted_lifecycle: Optional[str]
    current_lifecycle: str
    attempt_id: Optional[str]
    created_at: float


@dataclass(frozen=True)
class ReducerDecision:
    applied: bool
    error: Optional[ReducerError] = None


class ReducerErrorStore:
    def __init__(self, max_errors_per_run: int = 100):
        self.max_errors_per_run = max_errors_per_run
        self._errors: Dict[str, List[ReducerError]] = {}

    def record(self, error: ReducerError) -> None:
        run_errors = self._errors.setdefault(error.run_id, [])
        run_errors.append(error)
        overflow = len(run_errors) - self.max_errors_per_run
        if overflow > 0:
            del run_errors[:overflow]

    def list(self, run_id: Optional[str] = None) -> List[ReducerError]:
        if run_id is not None:
            return list(self._errors.get(run_id, []))
        errors: List[ReducerError] = []
        for run_errors in self._errors.values():
            errors.extend(run_errors)
        return errors

    def latest(self, run_id: str) -> Optional[ReducerError]:
        run_errors = self._errors.get(run_id, [])
        if not run_errors:
            return None
        return run_errors[-1]


class OrchestratorReducer:
    def __init__(self, error_store: Optional[ReducerErrorStore] = None):
        self.error_store = error_store or ReducerErrorStore()

    def reduce(
        self,
        state: ReducerState,
        event: Dict[str, Any],
    ) -> ReducerDecision:
        error = self._validate(state, event)
        if error is not None:
            self.error_store.record(error)
            return ReducerDecision(applied=False, error=error)

        next_lifecycle = event.get("lifecycle")
        if next_lifecycle:
            state.lifecycle = next_lifecycle
        state.revision += 1
        state.attempt_id = event.get("attempt_id", state.attempt_id)
        state.values.update(event.get("state_update", {}))
        return ReducerDecision(applied=True)

    def _validate(
        self,
        state: ReducerState,
        event: Dict[str, Any],
    ) -> Optional[ReducerError]:
        reason: Optional[str] = None
        expected_revision = event.get("expected_revision")
        event_attempt = event.get("attempt_id")
        next_lifecycle = event.get("lifecycle")

        if event.get("run_id") != state.run_id:
            reason = "run_id_mismatch"
        elif (
            expected_revision is not None
            and expected_revision != state.revision
        ):
            reason = "stale_revision"
        elif (
            state.attempt_id
            and event_attempt
            and event_attempt != state.attempt_id
        ):
            reason = "attempt_mismatch"
        elif state.lifecycle in TERMINAL_LIFECYCLES:
            reason = "terminal_lifecycle"
        elif (
            next_lifecycle
            and next_lifecycle
            not in VALID_TRANSITIONS.get(state.lifecycle, set())
        ):
            reason = "invalid_lifecycle_transition"

        if reason is None:
            return None

        return ReducerError(
            run_id=state.run_id,
            event_id=str(event.get("id", "unknown")),
            reason=reason,
            expected_revision=expected_revision,
            actual_revision=state.revision,
            attempted_lifecycle=next_lifecycle,
            current_lifecycle=state.lifecycle,
            attempt_id=event_attempt,
            created_at=time.time(),
        )
