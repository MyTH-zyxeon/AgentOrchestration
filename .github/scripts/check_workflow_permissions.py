"""Check GitHub Actions workflows for broad write permissions."""

from __future__ import annotations

import re
import sys
from pathlib import Path


WORKFLOW_DIR = Path(".github/workflows")
WRITE_PATTERN = re.compile(r"^\s*[\w-]+:\s*write\s*(?:#.*)?$")
ALLOW_WRITE_JOB = re.compile(r"(publish|release|deploy)", re.IGNORECASE)


def indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def key_name(line: str) -> str:
    return line.strip().split(":", 1)[0].strip("'\"")


def workflow_files() -> list[Path]:
    return sorted(
        path
        for pattern in ("*.yml", "*.yaml")
        for path in WORKFLOW_DIR.glob(pattern)
        if path.is_file()
    )


def find_jobs_start(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        if indent_of(line) == 0 and line.strip() == "jobs:":
            return index
    return None


def find_job_for_line(
    lines: list[str],
    index: int,
    jobs_start: int,
) -> str | None:
    job_name = None
    for line in lines[jobs_start + 1: index + 1]:
        if indent_of(line) == 2 and line.strip().endswith(":"):
            job_name = key_name(line)
    return job_name


def permissions_block(lines: list[str], start: int) -> list[tuple[int, str]]:
    block_indent = indent_of(lines[start])
    entries = []
    for index in range(start + 1, len(lines)):
        line = lines[index]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if indent_of(line) <= block_indent:
            break
        entries.append((index + 1, line))
    return entries


def check_file(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    jobs_start = find_jobs_start(lines)
    errors = []

    for index, line in enumerate(lines):
        stripped = line.strip()
        line_number = index + 1
        if jobs_start is None:
            job_name = None
        else:
            job_name = find_job_for_line(lines, index, jobs_start)
        write_allowed = (
            job_name is not None
            and ALLOW_WRITE_JOB.search(job_name)
        )

        if stripped == "permissions: write-all":
            errors.append(
                f"{path}:{line_number}: replace write-all with explicit "
                "least-privilege scopes"
            )

        if stripped == "permissions:":
            for entry_line, entry in permissions_block(lines, index):
                if WRITE_PATTERN.match(entry) and not write_allowed:
                    scope = key_name(entry)
                    errors.append(
                        f"{path}:{entry_line}: {scope}: write is only "
                        "allowed on publish/release/deploy jobs"
                    )

    return errors


def main() -> int:
    errors = []
    for path in workflow_files():
        errors.extend(check_file(path))

    if errors:
        print("Workflow permissions policy failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Workflow permissions policy passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
