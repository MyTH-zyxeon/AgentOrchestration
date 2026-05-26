"""Deployment bundle verification helpers."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional


SIGNATURE_KEY_ENV = "AO_DEPLOY_SIGNATURE_KEY"
HISTORY_PATH_ENV = "AO_DEPLOY_HISTORY"
SUPPORTED_ALGORITHM = "hmac-sha256"


class DeploymentVerificationError(ValueError):
    """Raised when a deployment bundle cannot be verified."""


@dataclass(frozen=True)
class DeploymentVerification:
    bundle_digest: str
    signature_algorithm: str
    signature_key_id: str
    signature_verified: bool
    history_path: str


def canonical_bundle_payload(manifest: Dict[str, Any]) -> bytes:
    unsigned_manifest = {
        key: value
        for key, value in manifest.items()
        if key not in {"signature", "deployment_history"}
    }
    return json.dumps(
        unsigned_manifest,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sign_manifest_payload(manifest: Dict[str, Any], key: str) -> str:
    return hmac.new(
        key.encode("utf-8"),
        canonical_bundle_payload(manifest),
        hashlib.sha256,
    ).hexdigest()


def verify_deployment_bundle(
    manifest_path: str,
    *,
    verification_key: Optional[str] = None,
    history_path: Optional[str] = None,
) -> DeploymentVerification:
    path = Path(manifest_path)
    manifest = _read_manifest(path)
    signature = manifest.get("signature")
    algorithm = _signature_algorithm(signature)
    key_id = _signature_key_id(signature)
    payload = canonical_bundle_payload(manifest)
    digest = hashlib.sha256(payload).hexdigest()
    history = _history_path(path, history_path)

    try:
        _verify_signature(
            signature,
            algorithm,
            verification_key or os.environ.get(SIGNATURE_KEY_ENV),
            payload,
        )
    except DeploymentVerificationError as exc:
        _record_history(
            history,
            path,
            digest,
            algorithm,
            key_id,
            False,
            str(exc),
        )
        raise

    _record_history(history, path, digest, algorithm, key_id, True, "")
    return DeploymentVerification(
        bundle_digest=digest,
        signature_algorithm=algorithm,
        signature_key_id=key_id,
        signature_verified=True,
        history_path=str(history),
    )


def deploy_manifest(
    manifest_path: str,
    *,
    credential_loader: Callable[[], object],
    verification_key: Optional[str] = None,
    history_path: Optional[str] = None,
) -> DeploymentVerification:
    verification = verify_deployment_bundle(
        manifest_path,
        verification_key=verification_key,
        history_path=history_path,
    )
    credential_loader()
    return verification


def load_environment_credentials() -> Dict[str, Optional[str]]:
    return {
        "token": os.environ.get("AO_DEPLOY_TOKEN"),
        "environment": os.environ.get("AO_DEPLOY_ENVIRONMENT"),
    }


def _read_manifest(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DeploymentVerificationError(
            "deployment manifest is not valid JSON"
        ) from exc
    except OSError as exc:
        raise DeploymentVerificationError(
            f"deployment manifest cannot be read: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise DeploymentVerificationError(
            "deployment manifest must be a JSON object"
        )
    return data


def _verify_signature(
    signature: object,
    algorithm: str,
    verification_key: Optional[str],
    payload: bytes,
) -> None:
    if not isinstance(signature, dict):
        raise DeploymentVerificationError("deployment bundle is unsigned")
    if algorithm != SUPPORTED_ALGORITHM:
        raise DeploymentVerificationError(
            "deployment bundle uses an unsupported signature algorithm"
        )
    signature_value = signature.get("value")
    if not isinstance(signature_value, str) or not signature_value:
        raise DeploymentVerificationError(
            "deployment bundle signature is missing"
        )
    if not verification_key:
        raise DeploymentVerificationError(
            "deployment signature verification key is not configured"
        )

    expected = hmac.new(
        verification_key.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature_value):
        raise DeploymentVerificationError(
            "deployment bundle signature could not be verified"
        )


def _signature_algorithm(signature: object) -> str:
    if isinstance(signature, dict) and isinstance(
        signature.get("algorithm"), str
    ):
        return signature["algorithm"]
    return ""


def _signature_key_id(signature: object) -> str:
    if isinstance(signature, dict) and isinstance(
        signature.get("key_id"), str
    ):
        return signature["key_id"]
    return ""


def _history_path(manifest_path: Path, history_path: Optional[str]) -> Path:
    configured = history_path or os.environ.get(HISTORY_PATH_ENV)
    if configured:
        return Path(configured)
    return manifest_path.with_suffix(
        manifest_path.suffix + ".deploy-history.jsonl"
    )


def _record_history(
    history_path: Path,
    manifest_path: Path,
    digest: str,
    algorithm: str,
    key_id: str,
    verified: bool,
    reason: str,
) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "manifest": str(manifest_path),
        "bundle_digest": digest,
        "signature_algorithm": algorithm,
        "signature_key_id": key_id,
        "signature_verified": verified,
    }
    if reason:
        entry["reason"] = reason
    with history_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
