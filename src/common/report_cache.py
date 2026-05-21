"""Authorization-aware report result cache."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Tuple


AccessValidator = Callable[["AuthorizationContext"], bool]


@dataclass(frozen=True)
class AuthorizationContext:
    user_id: str
    workspace_id: str
    roles: Tuple[str, ...] = ()
    scopes: Tuple[str, ...] = ()
    access_version: str = ""

    @classmethod
    def from_values(
        cls,
        *,
        user_id: str,
        workspace_id: str,
        roles: Iterable[str] = (),
        scopes: Iterable[str] = (),
        access_version: str = "",
    ) -> "AuthorizationContext":
        return cls(
            user_id=user_id,
            workspace_id=workspace_id,
            roles=tuple(sorted(set(roles))),
            scopes=tuple(sorted(set(scopes))),
            access_version=access_version,
        )


class ReportingResultCache:
    """Cache report results without reusing stale authorization state."""

    def __init__(self, access_validator: AccessValidator):
        self._access_validator = access_validator
        self._entries: Dict[Tuple[Any, ...], Any] = {}

    def get(
        self,
        report_id: str,
        params: Mapping[str, Any],
        auth_context: AuthorizationContext,
    ) -> Optional[Any]:
        self._ensure_authorized(auth_context)
        key = self._cache_key(report_id, params, auth_context)
        if key not in self._entries:
            return None
        return deepcopy(self._entries[key])

    def set(
        self,
        report_id: str,
        params: Mapping[str, Any],
        auth_context: AuthorizationContext,
        result: Any,
    ) -> None:
        self._ensure_authorized(auth_context)
        key = self._cache_key(report_id, params, auth_context)
        self._entries[key] = deepcopy(result)

    def get_or_compute(
        self,
        report_id: str,
        params: Mapping[str, Any],
        auth_context: AuthorizationContext,
        compute: Callable[[], Any],
    ) -> Any:
        cached = self.get(report_id, params, auth_context)
        if cached is not None:
            return cached

        result = compute()
        self.set(report_id, params, auth_context, result)
        return deepcopy(result)

    def _ensure_authorized(self, auth_context: AuthorizationContext) -> None:
        if not self._access_validator(auth_context):
            raise PermissionError("report cache access denied")

    def _cache_key(
        self,
        report_id: str,
        params: Mapping[str, Any],
        auth_context: AuthorizationContext,
    ) -> Tuple[Any, ...]:
        return (
            report_id,
            self._freeze_mapping(params),
            auth_context.user_id,
            auth_context.workspace_id,
            auth_context.roles,
            auth_context.scopes,
            auth_context.access_version,
        )

    def _freeze_mapping(
        self, value: Mapping[str, Any]
    ) -> Tuple[Tuple[str, Any], ...]:
        return tuple(
            sorted((key, self._freeze(value)) for key, value in value.items())
        )

    def _freeze(self, value: Any) -> Any:
        if isinstance(value, Mapping):
            return self._freeze_mapping(value)
        if isinstance(value, (list, tuple)):
            return tuple(self._freeze(item) for item in value)
        if isinstance(value, set):
            return tuple(sorted(self._freeze(item) for item in value))
        return value
