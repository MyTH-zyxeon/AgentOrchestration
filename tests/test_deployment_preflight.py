from datetime import datetime, timedelta, timezone

import pytest

from src.common.deployment_preflight import (
    BackupVerification,
    DestructiveMigrationPreflight,
    MigrationMetadata,
    MigrationPreflightError,
)


NOW = datetime(2026, 5, 21, 9, 53, tzinfo=timezone.utc)


def _preflight():
    return DestructiveMigrationPreflight(clock=lambda: NOW)


def _destructive_migration():
    return MigrationMetadata(
        migration_id="drop-legacy-events",
        destructive=True,
        description="Drops legacy event rows after compaction",
    )


def test_destructive_migration_fails_without_verified_backup():
    with pytest.raises(MigrationPreflightError) as error:
        _preflight().check(_destructive_migration())

    assert error.value.report.allowed is False
    assert error.value.report.restore_check_status == "missing"
    assert error.value.report.backup_timestamp is None


def test_destructive_migration_reports_failed_restore_check():
    backup = BackupVerification(
        backup_id="backup-1",
        created_at=NOW - timedelta(hours=1),
        restore_verified=False,
    )

    with pytest.raises(MigrationPreflightError) as error:
        _preflight().check(_destructive_migration(), backup)

    assert error.value.report.restore_check_status == "failed"
    assert error.value.report.backup_timestamp == backup.created_at


def test_destructive_migration_rejects_stale_verified_backup():
    backup = BackupVerification(
        backup_id="backup-1",
        created_at=NOW - timedelta(hours=25),
        restore_verified=True,
    )

    with pytest.raises(MigrationPreflightError) as error:
        _preflight().check(_destructive_migration(), backup)

    assert error.value.report.restore_check_status == "stale"
    assert error.value.report.backup_timestamp == backup.created_at


def test_destructive_migration_accepts_recent_verified_backup():
    backup = BackupVerification(
        backup_id="backup-1",
        created_at=NOW - timedelta(hours=2),
        restore_verified=True,
    )

    report = _preflight().check(_destructive_migration(), backup)

    assert report.allowed is True
    assert report.destructive is True
    assert report.restore_check_status == "verified"
    assert report.backup_timestamp == backup.created_at


def test_non_destructive_metadata_does_not_require_backup():
    migration = MigrationMetadata(
        migration_id="add-events-index",
        destructive=False,
    )

    report = _preflight().check(migration)

    assert report.allowed is True
    assert report.destructive is False
    assert report.restore_check_status == "not_required"
