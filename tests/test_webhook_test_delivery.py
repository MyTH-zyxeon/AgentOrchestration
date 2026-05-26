import pytest

from src.api.webhooks import WebhookDeliveryRejected, WebhookEndpointStore


def test_test_delivery_uses_test_secret_and_redacts_internal_payload():
    store = WebhookEndpointStore()
    endpoint = store.register_endpoint(
        workspace_id="workspace-a",
        url="https://example.test/webhook",
        secret="real-production-secret",
        events=["agent.started"],
        created_by="owner-a",
    )

    record = store.test_delivery(
        endpoint_id=endpoint["id"],
        workspace_id="workspace-a",
        event_type="agent.started",
        payload={
            "agent_id": "agent-1",
            "_internal_trace": "hidden",
            "api_token": "hidden",
            "webhook_secret": "hidden",
        },
        idempotency_key="retry-1",
    )

    assert record["mode"] == "test"
    assert record["secret_scope"] == "test"
    assert record["signature"].startswith("test-sha256=")
    assert "real-production-secret" not in str(record)
    assert record["payload"] == {"agent_id": "agent-1"}


def test_test_delivery_retry_is_idempotent():
    store = WebhookEndpointStore()
    endpoint = store.register_endpoint(
        workspace_id="workspace-a",
        url="https://example.test/webhook",
        secret="real-production-secret",
        events=["agent.started"],
        created_by="owner-a",
    )

    first = store.test_delivery(
        endpoint_id=endpoint["id"],
        workspace_id="workspace-a",
        event_type="agent.started",
        payload={"agent_id": "agent-1"},
        idempotency_key="retry-1",
    )
    second = store.test_delivery(
        endpoint_id=endpoint["id"],
        workspace_id="workspace-a",
        event_type="agent.started",
        payload={"agent_id": "agent-1"},
        idempotency_key="retry-1",
    )

    assert second == first
    assert len(store.delivery_records()) == 1


def test_test_delivery_rejects_disabled_endpoint_before_dispatch():
    store = WebhookEndpointStore()
    endpoint = store.register_endpoint(
        workspace_id="workspace-a",
        url="https://example.test/webhook",
        secret="real-production-secret",
        events=["agent.started"],
        created_by="owner-a",
    )
    store.disable_endpoint(endpoint["id"], workspace_id="workspace-a")

    with pytest.raises(WebhookDeliveryRejected, match="endpoint_disabled"):
        store.test_delivery(
            endpoint_id=endpoint["id"],
            workspace_id="workspace-a",
            event_type="agent.started",
            payload={"agent_id": "agent-1"},
            idempotency_key="retry-1",
        )

    assert store.delivery_records() == []
    assert store.audit_records()[-1]["reason"] == "endpoint_disabled"


def test_test_delivery_enforces_workspace_isolation():
    store = WebhookEndpointStore()
    endpoint = store.register_endpoint(
        workspace_id="workspace-a",
        url="https://example.test/webhook",
        secret="real-production-secret",
        events=["agent.started"],
        created_by="owner-a",
    )

    with pytest.raises(WebhookDeliveryRejected, match="endpoint_not_found"):
        store.test_delivery(
            endpoint_id=endpoint["id"],
            workspace_id="workspace-b",
            event_type="agent.started",
            payload={"agent_id": "agent-1"},
            idempotency_key="retry-1",
        )

    assert store.delivery_records() == []
    audit = store.audit_records()[-1]
    assert audit["event"] == "test_delivery_rejected"
    assert audit["reason"] == "endpoint_not_found"


def test_test_delivery_ignores_real_secret_rotation():
    store = WebhookEndpointStore()
    endpoint = store.register_endpoint(
        workspace_id="workspace-a",
        url="https://example.test/webhook",
        secret="old-real-secret",
        events=["agent.started"],
        created_by="owner-a",
    )
    store.rotate_secret(
        endpoint_id=endpoint["id"],
        workspace_id="workspace-a",
        new_secret="new-real-secret",
    )

    record = store.test_delivery(
        endpoint_id=endpoint["id"],
        workspace_id="workspace-a",
        event_type="agent.started",
        payload={"agent_id": "agent-1"},
        idempotency_key="after-rotation",
    )

    assert record["secret_scope"] == "test"
    assert "old-real-secret" not in str(record)
    assert "new-real-secret" not in str(record)
