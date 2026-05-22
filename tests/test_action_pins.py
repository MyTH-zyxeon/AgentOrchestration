from pathlib import Path

from scripts.validate_action_pins import validate_action_pins


def write_workflow(root: Path, content: str) -> None:
    workflows_dir = root / ".github" / "workflows"
    workflows_dir.mkdir(parents=True)
    (workflows_dir / "ci.yml").write_text(content)


def test_validate_action_pins_rejects_mutable_external_refs(tmp_path):
    write_workflow(
        tmp_path,
        """
name: CI
jobs:
  test:
    steps:
      - uses: actions/checkout@v4
""",
    )

    assert validate_action_pins(tmp_path) == [
        f"{tmp_path}/.github/workflows/ci.yml:6: actions/checkout@v4"
    ]


def test_validate_action_pins_allows_full_sha_refs(tmp_path):
    write_workflow(
        tmp_path,
        """
name: CI
jobs:
  test:
    steps:
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
      - uses: ./local-action
      - uses: docker://alpine:3.20
""",
    )

    assert validate_action_pins(tmp_path) == []
