"""Validate GitHub Actions references are pinned to immutable SHAs."""

from pathlib import Path
import re
import sys


USES_PATTERN = re.compile(r"^\s*(?:-\s*)?uses:\s*([^#\s]+)")
FULL_SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")


def iter_workflow_files(root: Path):
    workflows_dir = root / ".github" / "workflows"
    for pattern in ("*.yml", "*.yaml"):
        yield from workflows_dir.glob(pattern)


def is_external_action(reference: str) -> bool:
    return not (
        reference.startswith("./")
        or reference.startswith("../")
        or reference.startswith("docker://")
    )


def validate_action_pins(root: Path) -> list[str]:
    failures = []
    for workflow in iter_workflow_files(root):
        lines = workflow.read_text().splitlines()
        for line_number, line in enumerate(lines, 1):
            match = USES_PATTERN.match(line)
            if not match:
                continue
            reference = match.group(1).strip("'\"")
            if not is_external_action(reference):
                continue
            _, separator, revision = reference.rpartition("@")
            if not separator or not FULL_SHA_PATTERN.fullmatch(revision):
                failures.append(f"{workflow}:{line_number}: {reference}")
    return failures


def main() -> int:
    failures = validate_action_pins(Path.cwd())
    if failures:
        print("Mutable GitHub Actions references found:")
        for failure in failures:
            print(f" - {failure}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
