import pytest

from src.webhooks import (
    EndpointState,
    QueuedWebhookEvent,
    WebhookDeliveryRejected,
    WebhookDeliveryState,
)


def event_payload(**overrides):
    payload = {
        "event_id": "evt-1",
        "type": "task.completed",
        "workspace_id": "workspace-a",
        "data": {
            "task_id": "task-1",
            "internal_trace": "nested-trace",
        },
        "internal_metadata": {"worker": "worker-a"},
        "internal_retry_state": {"retry_at": 123.0},
        "_private": "drop-me",
        "authorization": "Bearer token",
    }
    payload.update(overrides)
    return payload


def queued_event(**overrides):
    values = {
        "event_id": "evt-1",
        "workspace_id": "workspace-a",
        "endpoint_id": "endpoint-a",
        "endpoint_version": 1,
        "payload": event_payload(),
    }
    values.update(overrides)
    return QueuedWebhookEvent(**values)


def delivery_state(state=EndpointState.ACTIVE, **endpoint_overrides):
    delivery = WebhookDeliveryState()
    values = {
        "endpoint_id": "endpoint-a",
        "workspace_id": "workspace-a",
        "target_url": "https://example.test/webhook",
        "state": state,
        "version": 1,
    }
    values.update(endpoint_overrides)
    delivery.register_endpoint(**values)
    return delivery


def test_valid_delivery_is_idempotent_and_sanitizes_callback_payload():
    delivery = delivery_state()
    event = queued_event()

    first = delivery.prepare_delivery(event, attempt=1)
    second = delivery.prepare_delivery(event, attempt=1)

    assert first is second
    assert delivery.accepted_count() == 1
    assert first.status == "ready"
    assert first.callback_payload == {
        "event_id": "evt-1",
        "type": "task.completed",
        "workspace_id": "workspace-a",
        "data": {"task_id": "task-1"},
    }


@pytest.mark.parametrize(
    "state, reason",
    [
        (EndpointState.DISABLED, "disabled"),
        (EndpointState.REVOKED, "revoked"),
        (EndpointState.EXPIRED, "expired"),
    ],
)
def test_inactive_endpoint_is_rejected_before_accepted_record(
    state,
    reason,
):
    delivery = delivery_state(state=state)

    with pytest.raises(WebhookDeliveryRejected, match=reason):
        delivery.prepare_delivery(queued_event())

    assert delivery.accepted_count() == 0


def test_expired_timestamp_blocks_delivery_even_when_state_is_active():
    delivery = delivery_state(expires_at=50.0)

    with pytest.raises(WebhookDeliveryRejected, match="expired"):
        delivery.prepare_delivery(queued_event(), now=51.0)

    assert delivery.accepted_count() == 0


def test_retry_revalidates_disabled_endpoint_and_is_terminal():
    delivery = delivery_state()
    delivery.prepare_delivery(queued_event(), attempt=1)
    delivery.set_endpoint_state(
        "workspace-a",
        "endpoint-a",
        EndpointState.DISABLED,
    )

    retry = delivery.retry_delivery(queued_event(), attempt=2)
    repeat = delivery.retry_delivery(queued_event(), attempt=2)

    assert retry is repeat
    assert retry.status == "permanently_failed"
    assert retry.reason == "endpoint is disabled"
    assert retry.callback_payload == {}
    assert delivery.accepted_count() == 1
    assert delivery.terminal_count() == 1
    assert delivery.audit_log == [
        {
            "event_id": "evt-1",
            "workspace_id": "workspace-a",
            "endpoint_id": "endpoint-a",
            "attempt": 2,
            "decision": "retry_rejected",
            "reason": "endpoint is disabled",
        }
    ]


def test_workspace_isolation_blocks_cross_workspace_delivery():
    delivery = delivery_state()

    with pytest.raises(WebhookDeliveryRejected, match="not found"):
        delivery.prepare_delivery(queued_event(workspace_id="workspace-b"))

    with pytest.raises(WebhookDeliveryRejected, match="not found"):
        delivery.prepare_delivery(queued_event(endpoint_id="endpoint-b"))

    assert delivery.accepted_count() == 0


def test_rotated_endpoint_version_rejects_stale_queued_event():
    delivery = delivery_state()
    delivery.rotate_endpoint(
        "workspace-a",
        "endpoint-a",
        target_url="https://example.test/new-webhook",
    )

    with pytest.raises(WebhookDeliveryRejected, match="version is stale"):
        delivery.prepare_delivery(queued_event(endpoint_version=1))

    fresh = delivery.prepare_delivery(queued_event(endpoint_version=2))
    assert fresh.endpoint_version == 2
    assert delivery.accepted_count() == 1
