"""Authorization guard for live-update websocket token minting."""

import secrets
import time
from dataclasses import dataclass, field
from threading import RLock
from typing import Dict, Optional, Set


class LiveUpdateAuthError(PermissionError):
    """Raised when live-update token minting must fail closed."""


@dataclass(frozen=True)
class LiveUpdateCredential:
    principal_id: str
    workspace_id: str
    roles: Set[str] = field(default_factory=set)
    scopes: Set[str] = field(default_factory=set)
    expires_at: float = 0.0
    not_before: float = 0.0
    revoked: bool = False


@dataclass(frozen=True)
class LiveUpdateToken:
    token: str
    principal_id: str
    workspace_id: str
    expires_at: float

    def to_dict(self) -> Dict[str, object]:
        return {
            "token": self.token,
            "principal_id": self.principal_id,
            "workspace_id": self.workspace_id,
            "expires_at": self.expires_at,
        }


class LiveUpdateAuthService:
    """Validates credentials before minting websocket tokens."""

    REQUIRED_SCOPE = "live_updates:mint"
    ALLOWED_ROLES = {"owner", "admin", "operator"}

    def __init__(self, token_ttl_seconds: int = 300):
        self.token_ttl_seconds = token_ttl_seconds
        self._lock = RLock()
        self._bearer_credentials: Dict[str, LiveUpdateCredential] = {}
        self._browser_credentials: Dict[str, LiveUpdateCredential] = {}
        self._minted_tokens: Dict[str, LiveUpdateToken] = {}

    def register_bearer_token(
        self,
        token: str,
        credential: LiveUpdateCredential,
    ) -> None:
        with self._lock:
            self._bearer_credentials[token] = credential

    def register_browser_session(
        self,
        session_id: str,
        credential: LiveUpdateCredential,
    ) -> None:
        with self._lock:
            self._browser_credentials[session_id] = credential

    def revoke_bearer_token(self, token: str) -> None:
        with self._lock:
            credential = self._bearer_credentials.get(token)
            if credential:
                self._bearer_credentials[token] = self._revoked(credential)

    def revoke_browser_session(self, session_id: str) -> None:
        with self._lock:
            credential = self._browser_credentials.get(session_id)
            if credential:
                self._browser_credentials[session_id] = self._revoked(
                    credential
                )

    def reset(self) -> None:
        with self._lock:
            self._bearer_credentials.clear()
            self._browser_credentials.clear()
            self._minted_tokens.clear()

    def mint_websocket_token(
        self,
        workspace_id: str,
        authorization_header: str = "",
        browser_session: str = "",
        now: Optional[float] = None,
    ) -> LiveUpdateToken:
        now = time.time() if now is None else now
        credential = self._resolve_credential(
            authorization_header,
            browser_session,
        )
        self._validate_credential(credential, workspace_id, now)

        minted = LiveUpdateToken(
            token=f"wst_{secrets.token_urlsafe(24)}",
            principal_id=credential.principal_id,
            workspace_id=workspace_id,
            expires_at=now + self.token_ttl_seconds,
        )
        with self._lock:
            self._minted_tokens[minted.token] = minted
        return minted

    def _resolve_credential(
        self,
        authorization_header: str,
        browser_session: str,
    ) -> LiveUpdateCredential:
        with self._lock:
            if authorization_header:
                prefix = "Bearer "
                if not authorization_header.startswith(prefix):
                    raise LiveUpdateAuthError("Malformed authorization header")
                token = authorization_header[len(prefix):].strip()
                if not token:
                    raise LiveUpdateAuthError("Bearer token is empty")
                credential = self._bearer_credentials.get(token)
                if not credential:
                    raise LiveUpdateAuthError("Bearer token is not active")
                return credential

            if browser_session:
                credential = self._browser_credentials.get(browser_session)
                if not credential:
                    raise LiveUpdateAuthError("Browser session is not active")
                return credential

        raise LiveUpdateAuthError("Live update authentication is required")

    def _validate_credential(
        self,
        credential: LiveUpdateCredential,
        workspace_id: str,
        now: float,
    ) -> None:
        if not credential.principal_id:
            raise LiveUpdateAuthError(
                "Anonymous principals cannot mint tokens"
            )
        if credential.revoked:
            raise LiveUpdateAuthError("Credential has been revoked")
        if credential.not_before and credential.not_before > now:
            raise LiveUpdateAuthError("Credential is not active yet")
        if credential.expires_at and credential.expires_at <= now:
            raise LiveUpdateAuthError("Credential has expired")
        if credential.workspace_id != workspace_id:
            raise LiveUpdateAuthError("Credential workspace does not match")
        if self.REQUIRED_SCOPE not in credential.scopes:
            raise LiveUpdateAuthError("Credential lacks live-update scope")
        if not credential.roles.intersection(self.ALLOWED_ROLES):
            raise LiveUpdateAuthError("Credential lacks workspace role")

    @staticmethod
    def _revoked(credential: LiveUpdateCredential) -> LiveUpdateCredential:
        return LiveUpdateCredential(
            principal_id=credential.principal_id,
            workspace_id=credential.workspace_id,
            roles=set(credential.roles),
            scopes=set(credential.scopes),
            expires_at=credential.expires_at,
            not_before=credential.not_before,
            revoked=True,
        )
