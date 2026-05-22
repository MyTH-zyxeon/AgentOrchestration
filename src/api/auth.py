"""Central authentication and permission checks for API routes."""

from dataclasses import dataclass
from typing import Iterable, Optional, Set, Tuple

from starlette.datastructures import Headers


@dataclass(frozen=True)
class Principal:
    token: str
    state: str
    scopes: Set[str]
    workspace_role: str
    workspace_id: Optional[str]
    mfa_verified: bool
    client_type: str


@dataclass(frozen=True)
class AuthDecision:
    allowed: bool
    status_code: int
    reason: str
    principal: Optional[Principal] = None


class AuthService:
    privileged_key_paths = {
        "/api/v2/api-keys",
        "/api/v2/api-key-settings/keys",
    }
    privileged_key_scopes = {"api_keys:write", "admin"}
    privileged_workspace_roles = {"admin", "owner"}

    def authenticate(self, headers: Headers) -> AuthDecision:
        token = self._bearer_token(headers)
        if not token:
            return AuthDecision(False, 401, "missing_bearer_token")

        state = headers.get("X-Principal-State", "active").strip().lower()
        if state in {"anonymous", "stale", "revoked"}:
            return AuthDecision(False, 401, f"{state}_principal")
        if state != "active":
            return AuthDecision(False, 401, "invalid_principal_state")

        principal = Principal(
            token=token,
            state=state,
            scopes=self._parse_csv(headers.get("X-Auth-Scopes", "")),
            workspace_role=headers.get("X-Workspace-Role", "").strip().lower(),
            workspace_id=headers.get("X-Workspace-Id"),
            mfa_verified=self._is_verified_mfa(headers.get("X-MFA-Challenge")),
            client_type=headers.get("X-Client-Type", "token").strip().lower(),
        )
        return AuthDecision(True, 200, "authenticated", principal)

    def require_api_key_creation(
        self,
        principal: Principal,
        workspace_id: Optional[str],
    ) -> AuthDecision:
        if not principal.scopes.intersection(self.privileged_key_scopes):
            return AuthDecision(False, 403, "insufficient_scope", principal)

        if principal.workspace_role not in self.privileged_workspace_roles:
            return AuthDecision(
                False,
                403,
                "insufficient_workspace_role",
                principal,
            )

        if workspace_id and principal.workspace_id != workspace_id:
            return AuthDecision(False, 403, "workspace_mismatch", principal)

        if not principal.mfa_verified:
            return AuthDecision(
                False,
                403,
                "mfa_challenge_required",
                principal,
            )

        return AuthDecision(True, 200, "authorized", principal)

    def requires_privileged_key_creation(
        self,
        method: str,
        path: str,
    ) -> bool:
        return method.upper() == "POST" and path in self.privileged_key_paths

    def _bearer_token(self, headers: Headers) -> Optional[str]:
        value = headers.get("Authorization", "")
        if not value.startswith("Bearer "):
            return None
        token = value[len("Bearer "):].strip()
        return token or None

    def _parse_csv(self, value: str) -> Set[str]:
        return {part.strip() for part in value.split(",") if part.strip()}

    def _is_verified_mfa(self, value: Optional[str]) -> bool:
        return (value or "").strip().lower() in {"verified", "true", "1"}


def principal_can_create_api_key(
    headers: Headers,
    workspace_id: Optional[str],
) -> Tuple[AuthDecision, Optional[Principal]]:
    service = AuthService()
    auth = service.authenticate(headers)
    if not auth.allowed or auth.principal is None:
        return auth, None
    decision = service.require_api_key_creation(auth.principal, workspace_id)
    return decision, auth.principal


def has_any_scope(scopes: Iterable[str], allowed: Iterable[str]) -> bool:
    return bool(set(scopes).intersection(set(allowed)))
