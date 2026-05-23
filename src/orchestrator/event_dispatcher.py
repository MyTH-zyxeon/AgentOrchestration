"""Event dispatch guards for rolling orchestrator upgrades."""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Set

logger = logging.getLogger(__name__)


class DispatchDecision(Enum):
    ACCEPTED = "accepted"
    DEFERRED = "deferred"
    QUARANTINED = "quarantined"


class QuarantineReason(Enum):
    ATTEMPT_MISMATCH = "attempt_mismatch"
    INVALID_LIFECYCLE_TRANSITION = "invalid_lifecycle_transition"
    STALE_REVISION = "stale_revision"
    UNKNOWN_EVENT_TYPE = "unknown_event_type"


@dataclass(frozen=True)
class OrchestratorEvent:
    event_type: str
    stream_id: str
    attempt_id: str
    revision: int
    lifecycle_state: Optional[str] = None
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DispatchResult:
    decision: DispatchDecision
    event: OrchestratorEvent
    reason: Optional[QuarantineReason] = None


class EventDispatcher:
    """Guards event commits during rolling version upgrades."""

    _ALLOWED_TRANSITIONS = {
        None: {"pending", "running"},
        "pending": {"running", "cancelled"},
        "running": {"completed", "failed", "cancelled"},
    }

    _TERMINAL_STATES = {"cancelled", "completed", "failed"}

    def __init__(
        self,
        known_event_types: Iterable[str],
        handlers: Optional[
            Mapping[str, Callable[[OrchestratorEvent], None]]
        ] = None,
    ):
        self._known_event_types: Set[str] = set(known_event_types)
        self._handlers = dict(handlers or {})
        self._attempts: Dict[str, str] = {}
        self._lifecycle_state: Dict[str, str] = {}
        self._quarantine: List[DispatchResult] = []
        self._deferred: List[OrchestratorEvent] = []
        self._audit: List[Dict[str, Any]] = []
        self._current_revision = 0
        self._rolling_upgrade = False

    @property
    def current_revision(self) -> int:
        return self._current_revision

    @property
    def quarantine(self) -> List[DispatchResult]:
        return list(self._quarantine)

    @property
    def deferred(self) -> List[OrchestratorEvent]:
        return list(self._deferred)

    @property
    def audit_records(self) -> List[Dict[str, Any]]:
        return list(self._audit)

    def register_attempt(self, stream_id: str, attempt_id: str) -> None:
        self._attempts[stream_id] = attempt_id

    def lifecycle_state(self, stream_id: str) -> Optional[str]:
        return self._lifecycle_state.get(stream_id)

    def begin_rolling_upgrade(self, current_revision: int) -> None:
        self._current_revision = max(self._current_revision, current_revision)
        self._rolling_upgrade = True

    def complete_rolling_upgrade(
        self,
        current_revision: int,
    ) -> List[DispatchResult]:
        self._current_revision = max(self._current_revision, current_revision)
        self._rolling_upgrade = False
        deferred = self._deferred
        self._deferred = []
        return [self.dispatch(event) for event in deferred]

    def dispatch(self, event: OrchestratorEvent) -> DispatchResult:
        rejection = self._rejection_reason(event)
        if rejection:
            return self._quarantine_event(event, rejection)

        if self._rolling_upgrade and event.revision > self._current_revision:
            self._deferred.append(event)
            result = DispatchResult(DispatchDecision.DEFERRED, event)
            self._audit_result(result)
            logger.info(
                "Deferred orchestrator event during rolling upgrade",
                extra=self._safe_log_context(result),
            )
            return result

        if event.lifecycle_state:
            self._lifecycle_state[event.stream_id] = event.lifecycle_state
        self._current_revision = max(self._current_revision, event.revision)
        if event.event_type in self._handlers:
            self._handlers[event.event_type](event)
        result = DispatchResult(DispatchDecision.ACCEPTED, event)
        self._audit_result(result)
        return result

    def _rejection_reason(
        self,
        event: OrchestratorEvent,
    ) -> Optional[QuarantineReason]:
        if event.event_type not in self._known_event_types:
            return QuarantineReason.UNKNOWN_EVENT_TYPE
        if event.revision < self._current_revision:
            return QuarantineReason.STALE_REVISION
        expected_attempt = self._attempts.get(event.stream_id)
        if expected_attempt and event.attempt_id != expected_attempt:
            return QuarantineReason.ATTEMPT_MISMATCH
        if not self._is_lifecycle_transition_allowed(event):
            return QuarantineReason.INVALID_LIFECYCLE_TRANSITION
        return None

    def _is_lifecycle_transition_allowed(
        self,
        event: OrchestratorEvent,
    ) -> bool:
        next_state = event.lifecycle_state
        if next_state is None:
            return True
        current_state = self._lifecycle_state.get(event.stream_id)
        if current_state in self._TERMINAL_STATES:
            return False
        return next_state in self._ALLOWED_TRANSITIONS.get(
            current_state,
            set(),
        )

    def _quarantine_event(
        self,
        event: OrchestratorEvent,
        reason: QuarantineReason,
    ) -> DispatchResult:
        result = DispatchResult(DispatchDecision.QUARANTINED, event, reason)
        self._quarantine.append(result)
        self._audit_result(result)
        logger.warning(
            "Quarantined orchestrator event",
            extra=self._safe_log_context(result),
        )
        return result

    def _audit_result(self, result: DispatchResult) -> None:
        self._audit.append(
            {
                "decision": result.decision.value,
                "event_type": result.event.event_type,
                "stream_id": result.event.stream_id,
                "revision": result.event.revision,
                "reason": result.reason.value if result.reason else None,
            }
        )

    def _safe_log_context(self, result: DispatchResult) -> Dict[str, Any]:
        return {
            "event_type": result.event.event_type,
            "stream_id": result.event.stream_id,
            "revision": result.event.revision,
            "decision": result.decision.value,
            "reason": result.reason.value if result.reason else None,
        }
