"""Deployment rollout checks."""

from dataclasses import dataclass
from typing import Any, Dict, List


SUCCESSFUL_MIGRATION_STATUSES = {"completed", "succeeded", "success"}


@dataclass(frozen=True)
class RolloutDecision:
    traffic_allowed: bool
    migration_required: bool
    compatibility_checked: bool
    reasons: List[str]


class MigrationRolloutGate:
    def evaluate(self, manifest: Dict[str, Any]) -> RolloutDecision:
        deployment = manifest.get("deployment", {})
        migrations = deployment.get("migrations", [])
        migration_required = bool(
            deployment.get("requires_migrations") or migrations
        )
        reasons: List[str] = []

        if migration_required and not migrations:
            reasons.append("required migrations are missing")

        for index, migration in enumerate(migrations, start=1):
            name = str(migration.get("name") or f"migration-{index}")
            status = str(migration.get("status") or "").lower()
            if status not in SUCCESSFUL_MIGRATION_STATUSES:
                reasons.append(f"{name} has not completed successfully")

            if "backward_compatible" not in migration:
                reasons.append(f"{name} is missing compatibility metadata")
            elif not migration.get("backward_compatible"):
                reasons.append(f"{name} is not backward compatible")

        compatibility_checked = bool(migrations) and all(
            "backward_compatible" in migration for migration in migrations
        )
        return RolloutDecision(
            traffic_allowed=not reasons,
            migration_required=migration_required,
            compatibility_checked=compatibility_checked,
            reasons=reasons,
        )
