import pytest

from src.cli.main import SUPPORTED_OUTPUT_MODES, build_parser


class TestCliOutputModes:
    def test_accepts_supported_output_modes_before_command(self):
        parser = build_parser()

        for mode in SUPPORTED_OUTPUT_MODES:
            args = parser.parse_args(["--output", mode, "status"])
            assert args.output == mode

    def test_accepts_supported_output_mode_after_command(self):
        parser = build_parser()
        args = parser.parse_args(["logs", "agent-123", "--output", "yaml"])

        assert args.output == "yaml"

    @pytest.mark.parametrize(
        "argv",
        [
            ["--output", "xml", "status"],
            ["status", "--output", "xml"],
        ],
    )
    def test_rejects_unsupported_output_modes(self, argv):
        parser = build_parser()

        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(argv)

        assert exc_info.value.code == 2
