from src.orchestrator.event_dispatcher import (
    DispatchDecision,
    EventDispatcher,
    OrchestratorEvent,
    QuarantineReason,
)


def _dispatcher():
    dispatcher = EventDispatcher({"task.started", "task.completed"})
    dispatcher.register_attempt("task-1", "attempt-a")
    return dispatcher


def _event(
    event_type="task.started",
    attempt_id="attempt-a",
    revision=1,
    lifecycle_state="running",
    payload=None,
):
    return OrchestratorEvent(
        event_type=event_type,
        stream_id="task-1",
        attempt_id=attempt_id,
        revision=revision,
        lifecycle_state=lifecycle_state,
        payload=payload or {"secret": "do-not-log"},
    )


def test_unknown_event_type_is_quarantined_without_payload_in_audit():
    dispatcher = _dispatcher()

    result = dispatcher.dispatch(_event(event_type="task.force-delete"))

    assert result.decision == DispatchDecision.QUARANTINED
    assert result.reason == QuarantineReason.UNKNOWN_EVENT_TYPE
    assert dispatcher.lifecycle_state("task-1") is None
    assert dispatcher.audit_records[-1] == {
        "decision": "quarantined",
        "event_type": "task.force-delete",
        "stream_id": "task-1",
        "revision": 1,
        "reason": "unknown_event_type",
    }


def test_attempt_mismatch_is_quarantined_and_preserves_state():
    dispatcher = _dispatcher()

    result = dispatcher.dispatch(_event(attempt_id="attempt-b"))

    assert result.decision == DispatchDecision.QUARANTINED
    assert result.reason == QuarantineReason.ATTEMPT_MISMATCH
    assert dispatcher.lifecycle_state("task-1") is None


def test_invalid_duplicate_lifecycle_transition_is_quarantined():
    dispatcher = _dispatcher()
    accepted = dispatcher.dispatch(_event(revision=1))
    assert accepted.decision == DispatchDecision.ACCEPTED

    result = dispatcher.dispatch(_event(revision=2, lifecycle_state="running"))

    assert result.decision == DispatchDecision.QUARANTINED
    assert result.reason == QuarantineReason.INVALID_LIFECYCLE_TRANSITION
    assert dispatcher.lifecycle_state("task-1") == "running"


def test_stale_revision_is_quarantined():
    dispatcher = _dispatcher()
    accepted = dispatcher.dispatch(_event(revision=2))
    assert accepted.decision == DispatchDecision.ACCEPTED

    result = dispatcher.dispatch(
        _event(revision=1, lifecycle_state="completed"),
    )

    assert result.decision == DispatchDecision.QUARANTINED
    assert result.reason == QuarantineReason.STALE_REVISION
    assert dispatcher.lifecycle_state("task-1") == "running"


def test_rolling_upgrade_defers_future_revision_until_completion():
    dispatcher = _dispatcher()
    dispatcher.begin_rolling_upgrade(current_revision=4)

    result = dispatcher.dispatch(_event(revision=5))

    assert result.decision == DispatchDecision.DEFERRED
    assert dispatcher.lifecycle_state("task-1") is None
    assert len(dispatcher.deferred) == 1

    replayed = dispatcher.complete_rolling_upgrade(current_revision=5)

    assert [item.decision for item in replayed] == [DispatchDecision.ACCEPTED]
    assert dispatcher.lifecycle_state("task-1") == "running"
    assert dispatcher.deferred == []
