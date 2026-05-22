#!/usr/bin/env python3
"""Validate dependency review exception metadata for CI."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Iterable, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.common.dependency_review import (  # noqa: E402
    load_manifest,
    render_summary,
    validation_errors_for,
)


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate dependency review exception metadata."
    )
    parser.add_argument(
        "--manifest",
        default=".github/dependency-review-exceptions.yml",
        type=Path,
        help="Path to the tracked exception manifest.",
    )
    parser.add_argument(
        "--override",
        action="append",
        default=[],
        help="Dependency review override coordinate or manifest id.",
    )
    parser.add_argument(
        "--overrides-file",
        type=Path,
        help="JSON array or newline-delimited override coordinates.",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        help="Markdown summary output path. Defaults to $GITHUB_STEP_SUMMARY.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    manifest = load_manifest(args.manifest)
    overrides = _collect_overrides(args.override, args.overrides_file)
    manifest_errors, override_errors = validation_errors_for(
        manifest,
        overrides,
    )
    errors = manifest_errors + override_errors

    summary = render_summary(
        manifest,
        repository=os.environ.get("GITHUB_REPOSITORY"),
        server_url=os.environ.get("GITHUB_SERVER_URL", "https://github.com"),
        ref=os.environ.get("GITHUB_SHA"),
        validation_errors=errors,
    )
    summary_path = args.summary or _github_step_summary_path()
    if summary_path:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        with summary_path.open("a", encoding="utf-8") as summary_file:
            summary_file.write(summary)

    if errors:
        for error in errors:
            print(
                f"dependency review exception error: {error}",
                file=sys.stderr,
            )
        return 1

    print(f"validated {len(manifest.records)} dependency review exception(s)")
    return 0


def _collect_overrides(
    override_args: Iterable[str],
    overrides_file: Optional[Path],
) -> List[str]:
    overrides = list(override_args)
    env_overrides = os.environ.get("DEPENDENCY_REVIEW_OVERRIDES")
    if env_overrides:
        overrides.append(env_overrides)

    if overrides_file:
        content = overrides_file.read_text(encoding="utf-8").strip()
        if content:
            if content.startswith("["):
                loaded = json.loads(content)
                if not isinstance(loaded, list):
                    raise ValueError("overrides file JSON must be a list")
                overrides.extend(str(item) for item in loaded)
            else:
                overrides.extend(content.splitlines())

    return overrides


def _github_step_summary_path() -> Optional[Path]:
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary:
        return None
    return Path(summary)


if __name__ == "__main__":
    raise SystemExit(main())
