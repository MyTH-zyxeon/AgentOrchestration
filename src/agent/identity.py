"""Identity provider group-to-role mapping helpers."""

import time
from typing import Any, Dict, Iterable, List, Optional, Set


class IdentityGroupRoleMapper:
    """Maps identity provider groups to workspace roles by immutable IDs."""

    def __init__(self) -> None:
        self._roles_by_external_id: Dict[str, Set[str]] = {}
        self._audit_log: List[Dict[str, Any]] = []

    def register_group_role(
        self,
        external_group_id: str,
        role: str,
        display_name: Optional[str] = None,
    ) -> None:
        external_group_id = self._require_text(
            external_group_id,
            "external_group_id",
        )
        role = self._require_text(role, "role")
        roles = self._roles_by_external_id.setdefault(external_group_id, set())
        roles.add(role)
        self._audit_log.append(
            {
                "event": "identity_group_role_registered",
                "external_group_id": external_group_id,
                "display_name": display_name,
                "role": role,
                "timestamp": time.time(),
            }
        )

    def resolve_roles(
        self,
        provider_groups: Iterable[Dict[str, Any]],
    ) -> Set[str]:
        resolved: Set[str] = set()
        for group in provider_groups:
            external_group_id = group.get("external_id")
            if (
                not isinstance(external_group_id, str)
                or not external_group_id.strip()
            ):
                continue
            resolved.update(
                self._roles_by_external_id.get(external_group_id, set())
            )
        return resolved

    def repair_group_mapping(
        self,
        old_external_group_id: str,
        new_external_group_id: str,
        approved_by: str,
        reason: str,
        display_name: Optional[str] = None,
    ) -> None:
        old_external_group_id = self._require_text(
            old_external_group_id,
            "old_external_group_id",
        )
        new_external_group_id = self._require_text(
            new_external_group_id,
            "new_external_group_id",
        )
        approved_by = self._require_text(approved_by, "approved_by")
        reason = self._require_text(reason, "reason")
        roles = self._roles_by_external_id.get(old_external_group_id)
        if not roles:
            raise KeyError("old_external_group_id is not mapped")
        self._roles_by_external_id[new_external_group_id] = set(roles)
        self._audit_log.append(
            {
                "event": "identity_group_mapping_repaired",
                "old_external_group_id": old_external_group_id,
                "new_external_group_id": new_external_group_id,
                "display_name": display_name,
                "approved_by": approved_by,
                "reason": reason,
                "roles": sorted(roles),
                "timestamp": time.time(),
            }
        )

    def audit_log(self) -> List[Dict[str, Any]]:
        return [entry.copy() for entry in self._audit_log]

    @staticmethod
    def _require_text(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} is required")
        return value.strip()
