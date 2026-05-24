from src.orchestrator.reducer import OrchestratorReducer, ReducerState


def test_reducer_applies_valid_lifecycle_transition():
    reducer = OrchestratorReducer()
    state = ReducerState(run_id="run-1", revision=0, lifecycle="pending")

    decision = reducer.reduce(
        state,
        {
            "id": "event-1",
            "run_id": "run-1",
            "expected_revision": 0,
            "attempt_id": "attempt-1",
            "lifecycle": "running",
            "state_update": {"step": "started"},
        },
    )

    assert decision.applied
    assert state.revision == 1
    assert state.lifecycle == "running"
    assert state.attempt_id == "attempt-1"
    assert state.values == {"step": "started"}
    assert reducer.error_store.list("run-1") == []


def test_reducer_persists_stale_revision_error_without_committing_state():
    reducer = OrchestratorReducer()
    state = ReducerState(
        run_id="run-1",
        revision=3,
        lifecycle="running",
        attempt_id="attempt-1",
    )

    decision = reducer.reduce(
        state,
        {
            "id": "event-2",
            "run_id": "run-1",
            "expected_revision": 2,
            "attempt_id": "attempt-1",
            "lifecycle": "completed",
            "state_update": {"result": "should-not-commit"},
        },
    )

    assert not decision.applied
    assert state.revision == 3
    assert state.lifecycle == "running"
    assert state.values == {}
    assert decision.error.reason == "stale_revision"
    assert reducer.error_store.latest("run-1") == decision.error


def test_reducer_rejects_invalid_lifecycle_after_terminal_state():
    reducer = OrchestratorReducer()
    state = ReducerState(
        run_id="run-1",
        revision=4,
        lifecycle="completed",
        attempt_id="attempt-1",
    )

    decision = reducer.reduce(
        state,
        {
            "id": "event-3",
            "run_id": "run-1",
            "expected_revision": 4,
            "attempt_id": "attempt-1",
            "lifecycle": "running",
        },
    )

    assert not decision.applied
    assert state.revision == 4
    assert state.lifecycle == "completed"
    assert decision.error.reason == "terminal_lifecycle"


def test_reducer_rejects_attempt_mismatch_without_private_payload():
    reducer = OrchestratorReducer()
    state = ReducerState(
        run_id="run-1",
        revision=1,
        lifecycle="running",
        attempt_id="attempt-1",
    )

    decision = reducer.reduce(
        state,
        {
            "id": "event-4",
            "run_id": "run-1",
            "expected_revision": 1,
            "attempt_id": "attempt-2",
            "lifecycle": "failed",
            "payload": {"api_key": "secret-value"},
            "state_update": {"private": "do-not-save"},
        },
    )

    assert not decision.applied
    assert state.values == {}
    error = reducer.error_store.latest("run-1")
    assert error.reason == "attempt_mismatch"
    assert "secret-value" not in repr(error)
    assert "do-not-save" not in repr(error)


def test_reducer_error_store_bounds_errors_per_run():
    reducer = OrchestratorReducer()
    reducer.error_store.max_errors_per_run = 2
    state = ReducerState(run_id="run-1", revision=1, lifecycle="running")

    for event_id in ["event-1", "event-2", "event-3"]:
        reducer.reduce(
            state,
            {
                "id": event_id,
                "run_id": "run-1",
                "expected_revision": 0,
                "lifecycle": "completed",
            },
        )

    assert [error.event_id for error in reducer.error_store.list("run-1")] == [
        "event-2",
        "event-3",
    ]
