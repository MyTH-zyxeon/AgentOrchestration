import pytest

from src.common.webhooks import (
    WebhookEndpointStore,
    WebhookOwnershipError,
    WebhookPrincipal,
)


class TestWebhookEndpointStore:
    def setup_method(self):
        self.owner = WebhookPrincipal(
            workspace_id="workspace-a",
            subject_id="owner-a",
            role="owner",
        )
        self.admin = WebhookPrincipal(
            workspace_id="workspace-a",
            subject_id="admin-a",
            role="admin",
        )
        self.viewer = WebhookPrincipal(
            workspace_id="workspace-a",
            subject_id="viewer-a",
            role="viewer",
        )
        self.other_workspace = WebhookPrincipal(
            workspace_id="workspace-b",
            subject_id="owner-b",
            role="owner",
        )
        self.store = WebhookEndpointStore()
        self.store.register_endpoint(
            endpoint_id="endpoint-1",
            workspace_id="workspace-a",
            owner_subject_id="owner-a",
            url="https://hooks.example.test/endpoint",
            secret_version="v1",
            principal=self.owner,
        )

    def test_valid_delivery_returns_sanitized_record(self):
        record = self.store.deliver(
            "endpoint-1",
            event_type="task.completed",
            payload={"token": "private", "result": "done"},
            secret_version="v1",
            idempotency_key="delivery-1",
            principal=self.admin,
        )

        public = record.public_dict()
        assert public["status"] == "delivered"
        assert public["reason"] == "ok"
        assert "payload" not in public
        assert "secret" not in public

    def test_rejects_cross_workspace_delivery(self):
        record = self.store.deliver(
            "endpoint-1",
            event_type="task.completed",
            payload={"result": "done"},
            secret_version="v1",
            idempotency_key="delivery-2",
            principal=self.other_workspace,
        )

        assert record.status == "rejected"
        assert record.reason == "workspace_scope_mismatch"

    def test_delivery_retry_is_idempotent(self):
        first = self.store.deliver(
            "endpoint-1",
            event_type="task.completed",
            payload={"result": "done"},
            secret_version="v1",
            idempotency_key="retry-key",
            principal=self.owner,
        )
        second = self.store.deliver(
            "endpoint-1",
            event_type="task.completed",
            payload={"result": "changed"},
            secret_version="v1",
            idempotency_key="retry-key",
            principal=self.owner,
        )

        assert second.delivery_id == first.delivery_id
        assert second.attempt == 1
        assert self.store.delivery_count() == 1

    def test_rotation_requires_same_workspace_owner_role(self):
        with pytest.raises(WebhookOwnershipError):
            self.store.rotate_secret(
                "endpoint-1",
                new_secret_version="v2",
                principal=self.other_workspace,
            )

        with pytest.raises(WebhookOwnershipError):
            self.store.rotate_secret(
                "endpoint-1",
                new_secret_version="v2",
                principal=self.viewer,
            )

    def test_rotated_secret_blocks_stale_delivery(self):
        self.store.rotate_secret(
            "endpoint-1",
            new_secret_version="v2",
            principal=self.owner,
        )

        stale = self.store.deliver(
            "endpoint-1",
            event_type="task.completed",
            payload={"result": "done"},
            secret_version="v1",
            idempotency_key="stale-version",
            principal=self.owner,
        )
        current = self.store.deliver(
            "endpoint-1",
            event_type="task.completed",
            payload={"result": "done"},
            secret_version="v2",
            idempotency_key="current-version",
            principal=self.owner,
        )

        assert stale.status == "rejected"
        assert stale.reason == "stale_secret_version"
        assert current.status == "delivered"

    def test_disabled_endpoint_blocks_delivery(self):
        self.store.disable_endpoint("endpoint-1", principal=self.admin)

        record = self.store.deliver(
            "endpoint-1",
            event_type="task.completed",
            payload={"result": "done"},
            secret_version="v1",
            idempotency_key="disabled-endpoint",
            principal=self.owner,
        )

        assert record.status == "rejected"
        assert record.reason == "endpoint_disabled"
