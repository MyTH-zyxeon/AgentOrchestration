import asyncio
import socket

from src.common.webhook_delivery import (
    WebhookDeliveryRuntime,
    WebhookEndpoint,
)


def resolver(host, port):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.7", port))]


def run(coro):
    return asyncio.run(coro)


def test_delivers_valid_webhook_payload_without_internal_fields():
    sent = []

    async def sender(url, payload):
        sent.append((url, payload))
        return 204

    runtime = WebhookDeliveryRuntime(resolver=resolver, sender=sender)
    endpoint = WebhookEndpoint(
        id="endpoint-1",
        workspace_id="workspace-a",
        url="https://hooks.example.test/events",
    )

    result = run(
        runtime.deliver(
            endpoint,
            "workspace-a",
            {
                "event": "task.finished",
                "_token": "hidden",
                "internal_trace": "hidden",
            },
            "delivery-1",
        )
    )

    assert result.status == "delivered"
    assert result.response_status == 204
    assert result.payload == {"event": "task.finished"}
    assert sent == [
        ("https://hooks.example.test/events", {"event": "task.finished"})
    ]


def test_rejects_disabled_endpoint_before_delivery():
    sent = []
    runtime = WebhookDeliveryRuntime(resolver=resolver, sender=sent.append)
    endpoint = WebhookEndpoint(
        id="endpoint-1",
        workspace_id="workspace-a",
        url="https://hooks.example.test/events",
        enabled=False,
    )

    result = run(
        runtime.deliver(
            endpoint,
            "workspace-a",
            {"event": "task.finished"},
            "delivery-1",
        )
    )

    assert result.status == "rejected"
    assert result.error == "endpoint_disabled"
    assert sent == []


def test_rejects_workspace_mismatch_before_delivery():
    sent = []
    runtime = WebhookDeliveryRuntime(resolver=resolver, sender=sent.append)
    endpoint = WebhookEndpoint(
        id="endpoint-1",
        workspace_id="workspace-a",
        url="https://hooks.example.test/events",
    )

    result = run(
        runtime.deliver(
            endpoint,
            "workspace-b",
            {"event": "task.finished"},
            "delivery-1",
        )
    )

    assert result.status == "rejected"
    assert result.error == "workspace_mismatch"
    assert sent == []


def test_dns_resolution_failure_retries_without_sending():
    sent = []

    def failing_resolver(host, port):
        raise socket.gaierror("no host")

    runtime = WebhookDeliveryRuntime(
        resolver=failing_resolver,
        sender=sent.append,
        max_attempts=2,
    )
    endpoint = WebhookEndpoint(
        id="endpoint-1",
        workspace_id="workspace-a",
        url="https://missing.example.test/events",
    )

    result = run(
        runtime.deliver(
            endpoint,
            "workspace-a",
            {"event": "task.finished"},
            "delivery-1",
        )
    )

    assert result.status == "retry"
    assert result.error == "dns_resolution_failed"
    assert result.retry is True
    assert sent == []


def test_delivery_records_are_idempotent():
    send_count = 0

    def sender(url, payload):
        nonlocal send_count
        send_count += 1
        return 202

    runtime = WebhookDeliveryRuntime(resolver=resolver, sender=sender)
    endpoint = WebhookEndpoint(
        id="endpoint-1",
        workspace_id="workspace-a",
        url="https://hooks.example.test/events",
    )

    first = run(
        runtime.deliver(
            endpoint,
            "workspace-a",
            {"event": "task.finished"},
            "delivery-1",
        )
    )
    second = run(
        runtime.deliver(
            endpoint,
            "workspace-a",
            {"event": "task.finished"},
            "delivery-1",
        )
    )

    assert first is second
    assert send_count == 1
