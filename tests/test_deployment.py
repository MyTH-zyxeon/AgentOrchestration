from src.orchestrator.deployment import MigrationRolloutGate


def test_rollout_waits_for_successful_migrations():
    decision = MigrationRolloutGate().evaluate(
        {
            "deployment": {
                "requires_migrations": True,
                "migrations": [
                    {
                        "name": "add-task-state-index",
                        "status": "pending",
                        "backward_compatible": True,
                    }
                ],
            }
        }
    )

    assert not decision.traffic_allowed
    assert decision.migration_required
    assert "add-task-state-index has not completed successfully" in (
        decision.reasons
    )


def test_rollout_blocks_failed_migration_and_keeps_prior_version_serving():
    decision = MigrationRolloutGate().evaluate(
        {
            "deployment": {
                "migrations": [
                    {
                        "name": "alter-run-state",
                        "status": "failed",
                        "backward_compatible": True,
                    }
                ],
            }
        }
    )

    assert not decision.traffic_allowed
    assert decision.reasons == [
        "alter-run-state has not completed successfully"
    ]


def test_rollout_requires_backward_compatibility_metadata():
    missing_metadata = MigrationRolloutGate().evaluate(
        {
            "deployment": {
                "migrations": [
                    {"name": "add-worker-column", "status": "completed"}
                ],
            }
        }
    )
    incompatible = MigrationRolloutGate().evaluate(
        {
            "deployment": {
                "migrations": [
                    {
                        "name": "drop-worker-column",
                        "status": "completed",
                        "backward_compatible": False,
                    }
                ],
            }
        }
    )

    assert not missing_metadata.traffic_allowed
    assert not missing_metadata.compatibility_checked
    assert "add-worker-column is missing compatibility metadata" in (
        missing_metadata.reasons
    )
    assert not incompatible.traffic_allowed
    assert incompatible.compatibility_checked
    assert incompatible.reasons == [
        "drop-worker-column is not backward compatible"
    ]


def test_rollout_allows_traffic_after_migrations_pass_checks():
    decision = MigrationRolloutGate().evaluate(
        {
            "deployment": {
                "requires_migrations": True,
                "migrations": [
                    {
                        "name": "expand-task-state",
                        "status": "completed",
                        "backward_compatible": True,
                    }
                ],
            }
        }
    )

    assert decision.traffic_allowed
    assert decision.migration_required
    assert decision.compatibility_checked
    assert decision.reasons == []
