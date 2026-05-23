"""Agent Registry — Manages agent lifecycle and metadata."""

import copy
import json
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional


class AgentStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    FAILED = "failed"
    TERMINATED = "terminated"


class CapabilityContractError(ValueError):
    """Raised when a capability contract change is incompatible."""


class AgentRegistry:
    def __init__(self, storage_backend: str = "memory"):
        self.storage_backend = storage_backend
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._index: Dict[str, List[str]] = {}
        self._capability_contracts: Dict[str, Dict[str, Any]] = {}
        self._schema_cache: Dict[str, Dict[str, Any]] = {}
        self._audit_log: List[Dict[str, Any]] = []

    def register(
        self,
        name: str,
        agent_type: str,
        config: Optional[Dict] = None,
        capability_contract: Optional[Dict[str, Any]] = None,
        schema: Optional[Dict[str, Any]] = None,
    ) -> str:
        agent_id = str(uuid.uuid4())
        timestamp = time.time()
        self._agents[agent_id] = {
            "id": agent_id,
            "name": name,
            "type": agent_type,
            "status": AgentStatus.PENDING.value,
            "config": config or {},
            "created_at": timestamp,
            "updated_at": timestamp,
            "version": "1.0.0",
            "metrics": {"tasks_completed": 0, "errors": 0, "uptime": 0},
        }
        if capability_contract:
            self._capability_contracts[agent_id] = copy.deepcopy(
                capability_contract
            )
        if schema is not None:
            self.cache_schema(agent_id, schema, capability_contract)
        group = agent_type.split(".")[0]
        if group not in self._index:
            self._index[group] = []
        self._index[group].append(agent_id)
        return agent_id

    def get(self, agent_id: str) -> Optional[Dict[str, Any]]:
        return self._agents.get(agent_id)

    def list(
        self,
        status: Optional[AgentStatus] = None,
        group: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        agents = self._agents.values()
        if status:
            agents = [a for a in agents if a["status"] == status.value]
        if group:
            agent_ids = self._index.get(group, [])
            agents = [a for a in agents if a["id"] in agent_ids]
        return list(agents)

    def update_status(self, agent_id: str, status: AgentStatus) -> bool:
        if agent_id not in self._agents:
            return False
        self._agents[agent_id]["status"] = status.value
        self._agents[agent_id]["updated_at"] = time.time()
        return True

    def delete(self, agent_id: str) -> bool:
        if agent_id not in self._agents:
            return False
        agent = self._agents.pop(agent_id)
        self._capability_contracts.pop(agent_id, None)
        self._schema_cache.pop(agent_id, None)
        group = agent["type"].split(".")[0]
        if group in self._index and agent_id in self._index[group]:
            self._index[group].remove(agent_id)
        return True

    def count(self) -> int:
        return len(self._agents)

    def cache_schema(
        self,
        agent_id: str,
        schema: Dict[str, Any],
        capability_contract: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if agent_id not in self._agents:
            return False
        contract = capability_contract or self._capability_contracts.get(
            agent_id, {}
        )
        self._schema_cache[agent_id] = {
            "contract_fingerprint": self._contract_fingerprint(contract),
            "schema": copy.deepcopy(schema),
        }
        self._record_audit(
            agent_id,
            "schema_cached",
            "capability_contract_active",
        )
        return True

    def get_schema(self, agent_id: str) -> Optional[Dict[str, Any]]:
        cached = self._schema_cache.get(agent_id)
        if not cached:
            return None
        contract = self._capability_contracts.get(agent_id, {})
        if cached["contract_fingerprint"] != self._contract_fingerprint(
            contract
        ):
            self._schema_cache.pop(agent_id, None)
            self._record_audit(agent_id, "schema_rejected", "stale_contract")
            return None
        return copy.deepcopy(cached["schema"])

    def update_capability_contract(
        self,
        agent_id: str,
        contract: Dict[str, Any],
    ) -> bool:
        if agent_id not in self._agents:
            return False
        current = self._capability_contracts.get(agent_id, {})
        self._validate_contract_change(current, contract)
        self._capability_contracts[agent_id] = copy.deepcopy(contract)
        self._schema_cache.pop(agent_id, None)
        self._agents[agent_id]["updated_at"] = time.time()
        self._record_audit(
            agent_id,
            "contract_updated",
            "schema_cache_invalidated",
        )
        return True

    def get_registry_audit(self, limit: int = 50) -> List[Dict[str, Any]]:
        return copy.deepcopy(self._audit_log[-limit:])

    def _validate_contract_change(
        self, current: Dict[str, Any], updated: Dict[str, Any]
    ) -> None:
        if not current:
            return
        current_name = current.get("name") or current.get("capability")
        updated_name = updated.get("name") or updated.get("capability")
        if current_name and updated_name and current_name != updated_name:
            raise CapabilityContractError("capability name cannot change")
        if self._version_tuple(updated.get("version")) < self._version_tuple(
            current.get("version")
        ):
            raise CapabilityContractError(
                "capability contract version cannot downgrade"
            )
        removed_required = (
            self._required_fields(current) - self._required_fields(updated)
        )
        if removed_required:
            raise CapabilityContractError("required fields cannot be removed")

    def _record_audit(self, agent_id: str, decision: str, reason: str) -> None:
        self._audit_log.append(
            {
                "agent_id": agent_id,
                "decision": decision,
                "reason": reason,
                "timestamp": time.time(),
            }
        )

    @staticmethod
    def _contract_fingerprint(contract: Dict[str, Any]) -> str:
        return json.dumps(
            contract or {},
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _required_fields(contract: Dict[str, Any]) -> set:
        required = set(contract.get("required", []))
        schema = contract.get("schema")
        if isinstance(schema, dict):
            required.update(schema.get("required", []))
        return required

    @staticmethod
    def _version_tuple(version: Any) -> tuple:
        if version is None:
            return ()
        parts = []
        for part in str(version).split("."):
            if not part.isdigit():
                break
            parts.append(int(part))
        return tuple(parts)

# 2019-01-29T11:24:49 update

# 2019-04-09T13:38:38 update

# 2019-04-11T11:24:12 update

# 2019-06-26T17:03:48 update

# 2019-07-03T14:55:48 update

# 2019-07-18T18:18:47 update

# 2019-11-05T11:27:19 update

# 2019-11-20T11:35:05 update

# 2019-11-23T15:28:54 update

# 2020-03-13T09:23:07 update

# 2020-03-30T19:31:18 update

# 2020-04-22T15:03:30 update

# 2020-07-21T10:00:48 update

# 2020-09-10T09:02:08 update

# 2020-09-10T13:39:12 update

# 2020-09-22T16:27:52 update

# 2020-10-15T10:33:14 update

# 2021-05-13T11:15:56 update

# 2021-07-07T14:57:13 update

# 2021-07-13T15:15:19 update

# 2021-07-27T10:18:16 update

# 2022-03-11T15:24:11 update

# 2022-09-22T13:24:20 update

# 2022-11-01T12:20:40 update

# 2023-01-30T12:32:27 update

# 2023-03-10T09:43:50 update

# 2023-05-10T14:28:01 update

# 2023-05-11T20:04:46 update

# 2023-05-30T17:00:59 update

# 2023-07-13T17:54:32 update

# 2023-07-20T19:04:20 update

# 2023-07-31T17:00:02 update

# 2023-09-05T19:42:07 update

# 2024-01-02T10:29:47 update

# 2024-09-17T12:45:29 update

# 2024-09-17T11:51:01 update

# 2024-11-06T18:20:15 update

# 2025-01-12T15:13:14 update

# 2025-01-14T20:24:39 update

# 2025-03-26T20:21:27 update

# 2025-04-10T18:27:06 update

# 2025-06-19T20:34:58 update

# 2025-06-21T20:23:53 update

# 2025-06-24T20:30:30 update

# 2025-07-03T13:28:03 update

# 2025-07-24T17:42:21 update

# 2025-08-19T17:42:23 update

# 2025-08-21T11:06:52 update

# 2025-10-24T09:10:08 update

# 2025-12-18T19:34:38 update

# 2026-02-06T11:22:22 update

# 2026-02-13T15:42:04 update

# 2026-04-10T08:16:30 update

# 2026-04-29T18:16:11 update
