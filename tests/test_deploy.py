import json

import pytest

from src.cli.deploy import (
    DeploymentVerificationError,
    deploy_manifest,
    sign_manifest_payload,
    verify_deployment_bundle,
)


def _signed_manifest(key):
    manifest = {
        "name": "worker-agent",
        "version": "2026.5.26",
        "environment": "production",
        "artifact": {"image": "registry.example.com/worker@sha256:abc123"},
    }
    manifest["signature"] = {
        "algorithm": "hmac-sha256",
        "key_id": "release-2026-05",
        "value": sign_manifest_payload(manifest, key),
    }
    return manifest


def test_signed_bundle_is_verified_and_recorded(tmp_path):
    key = "release-key"
    manifest_path = tmp_path / "manifest.json"
    history_path = tmp_path / "deploy-history.jsonl"
    manifest_path.write_text(
        json.dumps(_signed_manifest(key)),
        encoding="utf-8",
    )

    result = verify_deployment_bundle(
        str(manifest_path),
        verification_key=key,
        history_path=str(history_path),
    )

    history = [
        json.loads(line)
        for line in history_path.read_text(encoding="utf-8").splitlines()
    ]
    assert result.signature_verified is True
    assert result.bundle_digest == history[0]["bundle_digest"]
    assert history[0]["signature_verified"] is True
    assert history[0]["signature_key_id"] == "release-2026-05"


def test_unsigned_bundle_is_rejected_before_credentials(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    history_path = tmp_path / "deploy-history.jsonl"
    manifest_path.write_text(
        json.dumps({"name": "worker-agent"}),
        encoding="utf-8",
    )

    def credential_loader():
        raise AssertionError(
            "credentials should not be requested before signature verification"
        )

    with pytest.raises(DeploymentVerificationError, match="unsigned"):
        deploy_manifest(
            str(manifest_path),
            credential_loader=credential_loader,
            verification_key="release-key",
            history_path=str(history_path),
        )

    history = [
        json.loads(line)
        for line in history_path.read_text(encoding="utf-8").splitlines()
    ]
    assert history[0]["signature_verified"] is False
    assert history[0]["reason"] == "deployment bundle is unsigned"


def test_tampered_bundle_is_rejected_and_recorded(tmp_path):
    key = "release-key"
    manifest = _signed_manifest(key)
    manifest["artifact"]["image"] = (
        "registry.example.com/worker@sha256:tampered"
    )
    manifest_path = tmp_path / "manifest.json"
    history_path = tmp_path / "deploy-history.jsonl"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(
        DeploymentVerificationError,
        match="could not be verified",
    ):
        verify_deployment_bundle(
            str(manifest_path),
            verification_key=key,
            history_path=str(history_path),
        )

    history = [
        json.loads(line)
        for line in history_path.read_text(encoding="utf-8").splitlines()
    ]
    assert history[0]["signature_verified"] is False
    assert history[0]["bundle_digest"]
