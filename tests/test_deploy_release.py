from src.deploy import (
    ApplicationRolloutSpec,
    MigrationCompatibility,
    MigrationJobResult,
    check_migration_compatibility,
    evaluate_release_gate,
)


def test_rollout_waits_until_migration_completes():
    decision = evaluate_release_gate(
        ApplicationRolloutSpec(
            release_id="release-1",
            previous_version="app:v1",
            target_version="app:v2",
        ),
        MigrationJobResult(
            name="add-task-state-index",
            completed=False,
            succeeded=False,
            compatibility=MigrationCompatibility(
                backward_compatible=True,
                reversible=True,
            ),
        ),
    )

    assert decision.allow_new_version is False
    assert decision.serving_version == "app:v1"
    assert "not completed" in decision.blocked_reason


def test_migration_failure_keeps_prior_version_serving():
    decision = evaluate_release_gate(
        ApplicationRolloutSpec(
            release_id="release-2",
            previous_version="app:v1",
            target_version="app:v2",
        ),
        MigrationJobResult(
            name="alter-task-state",
            completed=True,
            succeeded=False,
            compatibility=MigrationCompatibility(
                backward_compatible=True,
                reversible=True,
            ),
        ),
    )

    assert decision.allow_new_version is False
    assert decision.serving_version == "app:v1"
    assert "failed" in decision.blocked_reason


def test_incompatible_reversible_release_is_blocked_and_reported():
    decision = evaluate_release_gate(
        ApplicationRolloutSpec(
            release_id="release-3",
            previous_version="app:v1",
            target_version="app:v2",
        ),
        MigrationJobResult(
            name="drop-legacy-task-column",
            completed=True,
            succeeded=True,
            compatibility=MigrationCompatibility(
                backward_compatible=False,
                reversible=False,
                details="drops a column still read by v1 workers",
            ),
        ),
    )

    assert decision.allow_new_version is False
    assert decision.serving_version == "app:v1"
    assert decision.checks["backward_compatible"] is False
    assert decision.checks["reversible"] is False
    assert "not backward compatible" in decision.blocked_reason


def test_successful_compatible_migration_allows_target_traffic():
    decision = evaluate_release_gate(
        ApplicationRolloutSpec(
            release_id="release-4",
            previous_version="app:v1",
            target_version="app:v2",
        ),
        MigrationJobResult(
            name="add-nullable-task-state-column",
            completed=True,
            succeeded=True,
            compatibility=MigrationCompatibility(
                backward_compatible=True,
                reversible=True,
            ),
        ),
    )

    assert decision.allow_new_version is True
    assert decision.serving_version == "app:v2"
    assert decision.blocked_reason is None


def test_release_checks_identify_backward_compatibility():
    checks = check_migration_compatibility(
        MigrationJobResult(
            name="rename-task-state-column",
            completed=True,
            succeeded=True,
            compatibility=MigrationCompatibility(
                backward_compatible=False,
                reversible=True,
                details="rename needs a dual-read release first",
            ),
        )
    )

    assert checks["migration_completed"] is True
    assert checks["migration_succeeded"] is True
    assert checks["backward_compatible"] is False
    assert checks["details"] == "rename needs a dual-read release first"
