import pytest

from src.common.identity_lifecycle import (
    DeprovisionedIdentityError,
    IdentityLifecycleStore,
    TokenRefreshError,
)


def test_active_user_can_refresh_api_token_once():
    store = IdentityLifecycleStore()
    store.register_session("user-1", "session-1", "token-1")

    assert (
        store.refresh_api_token(
            "user-1",
            "session-1",
            "token-1",
            "token-2",
        )
        == "token-2"
    )

    with pytest.raises(TokenRefreshError):
        store.refresh_api_token(
            "user-1",
            "session-1",
            "token-1",
            "token-3",
        )


def test_deprovisioned_user_cannot_refresh_during_cache_lag():
    store = IdentityLifecycleStore()
    store.register_session("user-1", "cached-session", "cached-token")

    result = store.apply_scim_deprovision("user-1")

    assert result.revoked_sessions == 1
    assert result.revoked_api_tokens == 1
    with pytest.raises(DeprovisionedIdentityError):
        store.refresh_api_token(
            "user-1",
            "cached-session",
            "cached-token",
            "new-token",
        )


def test_scim_deprovision_revokes_sessions_and_tokens():
    store = IdentityLifecycleStore()
    store.register_session("user-1", "session-1", "token-1")
    store.register_session("user-1", "session-2", "token-2")

    result = store.apply_scim_deprovision("user-1")

    assert result.to_dict() == {
        "user_id": "user-1",
        "already_deprovisioned": False,
        "revoked_sessions": 2,
        "revoked_api_tokens": 2,
    }
    assert store.is_deprovisioned("user-1") is True


def test_repeated_scim_deprovision_events_are_idempotent():
    store = IdentityLifecycleStore()
    store.register_session("user-1", "session-1", "token-1")

    first_result = store.apply_scim_deprovision("user-1")
    second_result = store.apply_scim_deprovision("user-1")

    assert first_result.revoked_sessions == 1
    assert first_result.revoked_api_tokens == 1
    assert second_result.already_deprovisioned is True
    assert second_result.revoked_sessions == 0
    assert second_result.revoked_api_tokens == 0


def test_deprovisioned_user_cannot_register_new_cached_session():
    store = IdentityLifecycleStore()
    store.apply_scim_deprovision("user-1")

    with pytest.raises(DeprovisionedIdentityError):
        store.register_session("user-1", "session-1", "token-1")
