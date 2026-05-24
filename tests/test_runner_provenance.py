"""Tests for CI runner image provenance validation."""

from datetime import datetime, timezone

from src.ci.runner_provenance import main, validate


NOW = datetime(2026, 5, 24, 12, 0, tzinfo=timezone.utc)


def test_hosted_runner_is_summary_only():
    report = validate(
        {
            "AO_RUNNER_ENVIRONMENT": "github-hosted",
        },
        now=NOW,
    )

    assert report.passed
    assert not report.required
    assert report.checks[0].name == "required"


def test_strict_runner_requires_digest_timestamp_and_labels():
    report = validate(
        {
            "AO_RUNNER_ENVIRONMENT": "self-hosted",
            "AO_RUNNER_PROVENANCE_REQUIRED": "true",
        },
        now=NOW,
    )

    assert not report.passed
    assert {check.name for check in report.checks} == {
        "image_digest",
        "image_freshness",
        "runner_labels",
    }


def test_strict_runner_accepts_fresh_approved_image():
    report = validate(
        {
            "AO_RUNNER_ENVIRONMENT": "self-hosted",
            "AO_RUNNER_PROVENANCE_REQUIRED": "true",
            "AO_RUNNER_IMAGE_DIGEST": "sha256:abc",
            "AO_APPROVED_RUNNER_IMAGE_DIGESTS": "sha256:def, sha256:abc",
            "AO_RUNNER_IMAGE_BUILT_AT": "2026-05-23T18:00:00Z",
            "AO_RUNNER_LABELS": "self-hosted,linux,x64",
        },
        now=NOW,
    )

    assert report.passed


def test_strict_runner_rejects_stale_image():
    report = validate(
        {
            "AO_RUNNER_ENVIRONMENT": "self-hosted",
            "AO_RUNNER_PROVENANCE_REQUIRED": "true",
            "AO_RUNNER_IMAGE_DIGEST": "sha256:abc",
            "AO_APPROVED_RUNNER_IMAGE_DIGESTS": "sha256:abc",
            "AO_RUNNER_IMAGE_BUILT_AT": "2026-05-20T00:00:00Z",
            "AO_RUNNER_LABELS": "self-hosted,linux,x64",
        },
        now=NOW,
    )

    assert not report.passed
    assert any(
        check.name == "image_freshness" and not check.passed
        for check in report.checks
    )


def test_main_returns_failure_in_strict_mode(monkeypatch):
    monkeypatch.setenv("AO_RUNNER_ENVIRONMENT", "self-hosted")
    monkeypatch.setenv("AO_RUNNER_PROVENANCE_REQUIRED", "true")

    assert main(["--strict"]) == 1
