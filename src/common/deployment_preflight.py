"""Deployment preflight checks for migration safety."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional


Clock = Callable[[], datetime]


@dataclass(frozen=True)
class MigrationMetadata:
    migration_id: str
    destructive: bool = False
    description: str = ""


@dataclass(frozen=True)
class BackupVerification:
    backup_id: str
    created_at: datetime
    restore_verified: bool


@dataclass(frozen=True)
class MigrationPreflightReport:
    migration_id: str
    destructive: bool
    allowed: bool
    restore_check_status: str
    backup_timestamp: Optional[datetime] = None
    reason: str = ""


class MigrationPreflightError(Exception):
    def __init__(self, report: MigrationPreflightReport):
        super().__init__(report.reason)
        self.report = report


class DestructiveMigrationPreflight:
    def __init__(
        self,
        *,
        max_backup_age: timedelta = timedelta(hours=24),
        clock: Clock = lambda: datetime.now(timezone.utc),
    ):
        self._max_backup_age = max_backup_age
        self._clock = clock

    def check(
        self,
        migration: MigrationMetadata,
        backup: Optional[BackupVerification] = None,
    ) -> MigrationPreflightReport:
        if not migration.destructive:
            return MigrationPreflightReport(
                migration_id=migration.migration_id,
                destructive=False,
                allowed=True,
                restore_check_status="not_required",
            )

        if backup is None:
            return self._fail(
                migration,
                None,
                "missing",
                "destructive migration requires a verified backup",
            )

        if not backup.restore_verified:
            return self._fail(
                migration,
                backup,
                "failed",
                "backup restore verification has not passed",
            )

        if self._backup_age(backup) > self._max_backup_age:
            return self._fail(
                migration,
                backup,
                "stale",
                "verified backup is older than the allowed freshness window",
            )

        return MigrationPreflightReport(
            migration_id=migration.migration_id,
            destructive=True,
            allowed=True,
            restore_check_status="verified",
            backup_timestamp=backup.created_at,
        )

    def _fail(
        self,
        migration: MigrationMetadata,
        backup: Optional[BackupVerification],
        restore_check_status: str,
        reason: str,
    ) -> MigrationPreflightReport:
        report = MigrationPreflightReport(
            migration_id=migration.migration_id,
            destructive=True,
            allowed=False,
            restore_check_status=restore_check_status,
            backup_timestamp=backup.created_at if backup else None,
            reason=reason,
        )
        raise MigrationPreflightError(report)

    def _backup_age(self, backup: BackupVerification) -> timedelta:
        created_at = backup.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return self._clock() - created_at
