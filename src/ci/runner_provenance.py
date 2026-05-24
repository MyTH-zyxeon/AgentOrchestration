"""Validate self-hosted CI runner image provenance before build steps."""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

MAX_IMAGE_AGE_HOURS = 48
REQUIRED_LABELS = ("self-hosted",)


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass
class RunnerProvenance:
    runner_environment: str
    image_digest: Optional[str]
    image_built_at: Optional[str]
    runner_labels: List[str]
    required: bool
    strict: bool
    checks: List[CheckResult]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def to_dict(self) -> Dict[str, object]:
        return {
            "passed": self.passed,
            "runner_environment": self.runner_environment,
            "image_digest_present": bool(self.image_digest),
            "image_built_at": self.image_built_at,
            "runner_labels": self.runner_labels,
            "required": self.required,
            "strict": self.strict,
            "checks": [check.to_dict() for check in self.checks],
        }


def split_csv(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_built_at(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_required(env: Dict[str, str], strict: bool) -> bool:
    configured = env.get("AO_RUNNER_PROVENANCE_REQUIRED", "").lower()
    if configured in {"1", "true", "yes", "strict"}:
        return True
    return strict or env.get("AO_RUNNER_ENVIRONMENT") == "self-hosted"


def has_all_labels(labels: Iterable[str], required: Iterable[str]) -> bool:
    label_set = set(labels)
    return all(label in label_set for label in required)


def validate(
    env: Optional[Dict[str, str]] = None,
    now: Optional[datetime] = None,
    strict: bool = False,
) -> RunnerProvenance:
    env = env or dict(os.environ)
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    runner_environment = env.get("AO_RUNNER_ENVIRONMENT", "")
    image_digest = env.get("AO_RUNNER_IMAGE_DIGEST")
    image_built_at = env.get("AO_RUNNER_IMAGE_BUILT_AT")
    runner_labels = split_csv(env.get("AO_RUNNER_LABELS"))
    approved_digests = split_csv(env.get("AO_APPROVED_RUNNER_IMAGE_DIGESTS"))
    required = is_required(env, strict)
    checks: List[CheckResult] = []

    if not required:
        checks.append(
            CheckResult(
                "required",
                True,
                "Runner provenance is summary-only for this hosted runner",
            )
        )
        return RunnerProvenance(
            runner_environment=runner_environment,
            image_digest=image_digest,
            image_built_at=image_built_at,
            runner_labels=runner_labels,
            required=False,
            strict=strict,
            checks=checks,
        )

    if not image_digest:
        checks.append(
            CheckResult("image_digest", False, "Image digest missing")
        )
    elif image_digest not in approved_digests:
        checks.append(
            CheckResult("image_digest", False, "Image digest is not approved")
        )
    else:
        checks.append(
            CheckResult("image_digest", True, "Image digest approved")
        )

    if not image_built_at:
        checks.append(
            CheckResult(
                "image_freshness", False, "Image build timestamp missing"
            )
        )
    else:
        built_at = parse_built_at(image_built_at)
        age_hours = (now - built_at).total_seconds() / 3600
        checks.append(
            CheckResult(
                "image_freshness",
                age_hours <= MAX_IMAGE_AGE_HOURS,
                f"Image age is {age_hours:.1f} hours",
            )
        )

    checks.append(
        CheckResult(
            "runner_labels",
            has_all_labels(runner_labels, REQUIRED_LABELS),
            "Required runner labels are present"
            if has_all_labels(runner_labels, REQUIRED_LABELS)
            else "Required runner labels missing",
        )
    )

    return RunnerProvenance(
        runner_environment=runner_environment,
        image_digest=image_digest,
        image_built_at=image_built_at,
        runner_labels=runner_labels,
        required=required,
        strict=strict,
        checks=checks,
    )


def write_summary(report: RunnerProvenance) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with open(summary_path, "a", encoding="utf-8") as summary:
        summary.write("### Runner image provenance\n\n")
        summary.write(f"- Required: `{str(report.required).lower()}`\n")
        summary.write(f"- Runner environment: `{report.runner_environment}`\n")
        summary.write(
            f"- Image digest present: `{bool(report.image_digest)}`\n"
        )
        for check in report.checks:
            status = "pass" if check.passed else "fail"
            summary.write(f"- {check.name}: `{status}` - {check.detail}\n")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)

    report = validate(strict=args.strict)
    write_summary(report)
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
