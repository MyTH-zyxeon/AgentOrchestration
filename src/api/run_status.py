"""Scoped orchestration run status lookups."""

import re
from typing import Dict, Optional, Tuple


class RunStatusError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class RunStatusService:
    _RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    _WORKSPACE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    _READ_ROLES = {"admin", "operator", "viewer"}

    def __init__(self):
        self._runs: Dict[Tuple[str, str], Dict] = {}
        self.lookup_count = 0

    def clear(self) -> None:
        self._runs.clear()
        self.lookup_count = 0

    def record_run(
        self,
        run_id: str,
        workspace_id: str,
        status: str,
        metadata: Optional[Dict] = None,
    ) -> None:
        self._runs[(workspace_id, run_id)] = {
            "run_id": run_id,
            "workspace_id": workspace_id,
            "status": status,
            "metadata": metadata or {},
            "internal_trace": "redacted",
        }

    def get_status(self, run_id: str, workspace_id: str, role: str) -> Dict:
        self._validate_request(run_id, workspace_id, role)

        self.lookup_count += 1
        run = self._runs.get((workspace_id, run_id))
        if run is None:
            raise RunStatusError(404, "Run not found")

        return {
            "run_id": run["run_id"],
            "workspace_id": run["workspace_id"],
            "status": run["status"],
            "metadata": dict(run["metadata"]),
        }

    def _validate_request(
        self,
        run_id: str,
        workspace_id: str,
        role: str,
    ) -> None:
        if not self._RUN_ID_PATTERN.match(run_id):
            raise RunStatusError(422, "Invalid run id")
        if not self._WORKSPACE_PATTERN.match(workspace_id):
            raise RunStatusError(422, "Invalid workspace id")
        if role not in self._READ_ROLES:
            raise RunStatusError(403, "Role cannot poll run status")


run_status_service = RunStatusService()
