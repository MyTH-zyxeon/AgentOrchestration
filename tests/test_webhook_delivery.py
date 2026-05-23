import pytest

from src.webhook import (
    DeliveryRejected,
    DeliveryResponse,
    WebhookDeliveryService,
    WebhookEndpoint,
    WebhookEvent,
)


def test_valid_delivery_records_public_payload_only():
    service = WebhookDeliveryService()
    endpoint = WebhookEndpoint(
        endpoint_id="events",
        workspace_id="workspace-a",
        url="https://example.com/webhook",
    )
    service.register_endpoint(endpoint)
    event = WebhookEvent(
        event_id="evt-1",
        workspace_id="workspace-a",
        event_type="task.completed",
        payload={
            "task_id": "task-1",
            "internal_run_id": "run-secret",
            "_trace": "trace-secret",
        },
    )

    result = service.deliver(
        "workspace-a",
        "events",
        event,
        lambda _endpoint, _payload: DeliveryResponse(status_code=204),
    )

    assert result.status == "delivered"
    assert result.public_payload == {
        "task_id": "task-1",
        "event_id": "evt-1",
        "event_type": "task.completed",
    }


def test_workspace_mismatch_rejects_before_dispatch_or_recording():
    service = WebhookDeliveryService()
    service.register_endpoint(
        WebhookEndpoint(
            endpoint_id="events",
            workspace_id="workspace-a",
            url="https://example.com/webhook",
        )
    )
    calls = []

    with pytest.raises(DeliveryRejected, match="workspace"):
        service.deliver(
            "workspace-a",
            "events",
            WebhookEvent(
                event_id="evt-2",
                workspace_id="workspace-b",
                event_type="task.completed",
                payload={"task_id": "task-2"},
            ),
            lambda endpoint, payload: calls.append((endpoint, payload)),
        )

    assert calls == []
    assert service.deliveries == {}


def test_retryable_failure_can_be_retried_idempotently():
    service = WebhookDeliveryService()
    service.register_endpoint(
        WebhookEndpoint(
            endpoint_id="events",
            workspace_id="workspace-a",
            url="https://example.com/webhook",
        )
    )
    responses = iter([
        DeliveryResponse(status_code=503),
        DeliveryResponse(status_code=200),
    ])
    event = WebhookEvent(
        event_id="evt-3",
        workspace_id="workspace-a",
        event_type="task.completed",
        payload={"task_id": "task-3"},
    )

    first = service.deliver(
        "workspace-a",
        "events",
        event,
        lambda _endpoint, _payload: next(responses),
    )
    second = service.deliver(
        "workspace-a",
        "events",
        event,
        lambda _endpoint, _payload: next(responses),
    )

    assert first.status == "failed"
    assert first.retryable is True
    assert second.status == "delivered"
    assert second.attempt_count == 2


def test_delivered_event_is_not_dispatched_twice():
    service = WebhookDeliveryService()
    service.register_endpoint(
        WebhookEndpoint(
            endpoint_id="events",
            workspace_id="workspace-a",
            url="https://example.com/webhook",
        )
    )
    calls = []
    event = WebhookEvent(
        event_id="evt-4",
        workspace_id="workspace-a",
        event_type="task.completed",
        payload={"task_id": "task-4"},
    )

    first = service.deliver(
        "workspace-a",
        "events",
        event,
        lambda endpoint, payload: (
            calls.append((endpoint.endpoint_id, payload)),
            DeliveryResponse(status_code=200),
        )[1],
    )
    second = service.deliver(
        "workspace-a",
        "events",
        event,
        lambda endpoint, payload: (
            calls.append((endpoint.endpoint_id, payload)),
            DeliveryResponse(status_code=200),
        )[1],
    )

    assert first == second
    assert len(calls) == 1


def test_410_gone_disables_endpoint_without_retrying():
    service = WebhookDeliveryService()
    endpoint = WebhookEndpoint(
        endpoint_id="events",
        workspace_id="workspace-a",
        url="https://example.com/webhook",
    )
    service.register_endpoint(endpoint)
    event = WebhookEvent(
        event_id="evt-5",
        workspace_id="workspace-a",
        event_type="task.completed",
        payload={"task_id": "task-5"},
    )

    result = service.deliver(
        "workspace-a",
        "events",
        event,
        lambda _endpoint, _payload: DeliveryResponse(status_code=410),
    )

    assert result.status == "gone"
    assert result.retryable is False
    assert result.disabled_endpoint is True
    assert endpoint.enabled is False
    assert endpoint.disabled_reason == "410 gone"
