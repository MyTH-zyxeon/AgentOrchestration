"""Identity lifecycle guards for sessions and API tokens."""

from dataclasses import dataclass
from threading import RLock
from typing import Dict, Set


class DeprovisionedIdentityError(PermissionError):
    """Raised when a deprovisioned identity attempts access."""


class TokenRefreshError(PermissionError):
    """Raised when token refresh cannot be authorized."""


@dataclass(frozen=True)
class DeprovisionResult:
    user_id: str
    already_deprovisioned: bool
    revoked_sessions: int
    revoked_api_tokens: int

    def to_dict(self) -> Dict[str, object]:
        return {
            "user_id": self.user_id,
            "already_deprovisioned": self.already_deprovisioned,
            "revoked_sessions": self.revoked_sessions,
            "revoked_api_tokens": self.revoked_api_tokens,
        }


class IdentityLifecycleStore:
    """Tracks SCIM deprovision markers before cached token refresh state."""

    def __init__(self):
        self._lock = RLock()
        self._deprovisioned_users: Set[str] = set()
        self._sessions: Dict[str, str] = {}
        self._api_tokens: Dict[str, str] = {}
        self._revoked_api_tokens: Set[str] = set()

    def register_session(
        self,
        user_id: str,
        session_id: str,
        api_token: str,
    ) -> None:
        with self._lock:
            self._raise_if_deprovisioned(user_id)
            self._sessions[session_id] = user_id
            self._api_tokens[api_token] = user_id
            self._revoked_api_tokens.discard(api_token)

    def refresh_api_token(
        self,
        user_id: str,
        session_id: str,
        current_token: str,
        new_token: str,
    ) -> str:
        with self._lock:
            self._raise_if_deprovisioned(user_id)
            if self._sessions.get(session_id) != user_id:
                raise TokenRefreshError("Session is not active for user")
            if self._api_tokens.get(current_token) != user_id:
                raise TokenRefreshError("API token is not active for user")
            if current_token in self._revoked_api_tokens:
                raise TokenRefreshError("API token has been revoked")

            self._api_tokens.pop(current_token, None)
            self._revoked_api_tokens.add(current_token)
            self._api_tokens[new_token] = user_id
            return new_token

    def apply_scim_deprovision(self, user_id: str) -> DeprovisionResult:
        with self._lock:
            already_deprovisioned = user_id in self._deprovisioned_users
            self._deprovisioned_users.add(user_id)

            revoked_sessions = self._remove_values(self._sessions, user_id)
            revoked_tokens = [
                token
                for token, token_user_id in self._api_tokens.items()
                if token_user_id == user_id
            ]
            for token in revoked_tokens:
                self._api_tokens.pop(token, None)
                self._revoked_api_tokens.add(token)

            return DeprovisionResult(
                user_id=user_id,
                already_deprovisioned=already_deprovisioned,
                revoked_sessions=revoked_sessions,
                revoked_api_tokens=len(revoked_tokens),
            )

    def is_deprovisioned(self, user_id: str) -> bool:
        with self._lock:
            return user_id in self._deprovisioned_users

    def _raise_if_deprovisioned(self, user_id: str) -> None:
        if user_id in self._deprovisioned_users:
            raise DeprovisionedIdentityError(
                "User is deprovisioned and cannot refresh tokens"
            )

    @staticmethod
    def _remove_values(store: Dict[str, str], value: str) -> int:
        keys = [
            key
            for key, stored_value in store.items()
            if stored_value == value
        ]
        for key in keys:
            store.pop(key, None)
        return len(keys)
