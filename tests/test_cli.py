import argparse
import sys

import pytest

from src.cli.main import cli, non_negative_int


class TestNonNegativeInt:
    def test_accepts_zero_and_positive_values(self):
        assert non_negative_int("0") == 0
        assert non_negative_int("25") == 25

    def test_rejects_negative_values(self):
        with pytest.raises(argparse.ArgumentTypeError, match="non-negative"):
            non_negative_int("-5")

    def test_rejects_non_integer_values(self):
        with pytest.raises(argparse.ArgumentTypeError, match="invalid int"):
            non_negative_int("4.5")


class TestCliLogsTail:
    def test_rejects_negative_tail_argument(self, monkeypatch, capsys):
        monkeypatch.setattr(
            sys,
            "argv",
            ["ao", "logs", "agent-1", "--tail", "-5"],
        )

        with pytest.raises(SystemExit) as exc_info:
            cli()

        assert exc_info.value.code == 2
        assert "non-negative" in capsys.readouterr().err

    def test_accepts_zero_tail_argument(self, monkeypatch, capsys):
        monkeypatch.setattr(
            sys,
            "argv",
            ["ao", "logs", "agent-1", "--tail", "0"],
        )

        cli()

        assert "Fetching logs for agent: agent-1" in capsys.readouterr().out
