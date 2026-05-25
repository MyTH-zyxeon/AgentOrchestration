from fastapi.testclient import TestClient

from src.api.run_status import run_status_service
from src.api.server import create_app


class TestRunStatusRoutes:
    def setup_method(self):
        run_status_service.clear()
        self.client = TestClient(create_app())
        self.headers = {
            "Authorization": "Bearer test-token",
            "X-Workspace-ID": "workspace-a",
            "X-Role": "viewer",
        }

    def test_authorized_status_polling_is_scoped_and_sanitized(self):
        run_status_service.record_run(
            "run-1",
            "workspace-a",
            "running",
            metadata={"step": "dispatch"},
        )

        response = self.client.get(
            "/api/v2/runs/run-1/status",
            headers=self.headers,
        )

        assert response.status_code == 200
        assert response.json() == {
            "run_id": "run-1",
            "workspace_id": "workspace-a",
            "status": "running",
            "metadata": {"step": "dispatch"},
        }

    def test_status_polling_rejects_cross_workspace_lookup(self):
        run_status_service.record_run("run-1", "workspace-b", "completed")

        response = self.client.get(
            "/api/v2/runs/run-1/status",
            headers=self.headers,
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "Run not found"

    def test_status_polling_rejects_role_before_lookup(self):
        run_status_service.record_run("run-1", "workspace-a", "running")
        headers = dict(self.headers)
        headers["X-Role"] = "guest"

        response = self.client.get(
            "/api/v2/runs/run-1/status",
            headers=headers,
        )

        assert response.status_code == 403
        assert response.json()["detail"] == "Role cannot poll run status"
        assert run_status_service.lookup_count == 0

    def test_status_polling_rejects_malformed_run_id_before_lookup(self):
        run_status_service.record_run("run-1", "workspace-a", "running")

        response = self.client.get(
            "/api/v2/runs/bad%20id/status",
            headers=self.headers,
        )

        assert response.status_code == 422
        assert response.json()["detail"] == "Invalid run id"
        assert run_status_service.lookup_count == 0
