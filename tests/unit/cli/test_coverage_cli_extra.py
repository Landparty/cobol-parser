"""Additional coverage for cobolparser/cli/coverage.py.

Targets paths not exercised by test_coverage_cli.py:
  - cmd_status long-notes truncation
  - cmd_validate success and failure branches
  - cmd_render summary format
  - main() command dispatch to a real handler
"""

import argparse
import json
import sys
from unittest.mock import MagicMock, patch

from cobolparser.cli.coverage import cmd_render, cmd_status, cmd_validate, main


def _status_args(**kwargs):
    defaults = {
        "artifact": "io-coverage.json",
        "verb": None,
        "qualifier": None,
        "format": "table",
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


class TestStatusLongNotes:
    def test_long_notes_truncated(self, tmp_path, capsys):
        """Notes longer than 30 chars are truncated with an ellipsis."""
        artifact = tmp_path / "io-coverage.json"
        artifact.write_text(
            json.dumps(
                {
                    "variations": [
                        {
                            "id": "READ-001",
                            "verb": "READ",
                            "status": "covered",
                            "tests": ["t1"],
                            "notes": "this is a very long note that exceeds the limit",
                        }
                    ]
                }
            )
        )
        result = cmd_status(_status_args(artifact=str(artifact)))
        assert result == 0
        out = capsys.readouterr().out
        assert "..." in out


class TestCmdValidate:
    def test_validate_success(self, capsys):
        args = argparse.Namespace(artifact="io-coverage.json")
        validator = MagicMock()
        validator.validate.return_value = True

        with patch(
            "scripts.validate_io_coverage.CoverageSchemaValidator",
            return_value=validator,
        ):
            result = cmd_validate(args)

        assert result == 0
        assert "valid" in capsys.readouterr().out.lower()

    def test_validate_failure_lists_errors(self, capsys):
        args = argparse.Namespace(artifact="bad.json")
        validator = MagicMock()
        validator.validate.return_value = False
        validator.errors = ["missing field", "bad type"]

        with patch(
            "scripts.validate_io_coverage.CoverageSchemaValidator",
            return_value=validator,
        ):
            result = cmd_validate(args)

        assert result == 1
        out = capsys.readouterr().out
        assert "missing field" in out
        assert "bad type" in out


class TestCmdRenderSummary:
    def test_render_summary_format(self, capsys):
        renderer = MagicMock()
        renderer.render_summary.return_value = "SUMMARY OUTPUT"
        args = argparse.Namespace(input="c.json", output=None, format="summary")

        with (
            patch("cobolparser.cli.coverage.sys.path"),
            patch.dict(
                sys.modules,
                {
                    "render_markdown": MagicMock(
                        CoverageRenderer=MagicMock(return_value=renderer)
                    )
                },
            ),
        ):
            result = cmd_render(args)

        assert result == 0
        renderer.render_summary.assert_called_once()
        assert "SUMMARY OUTPUT" in capsys.readouterr().out


class TestMainDispatch:
    def test_main_dispatches_status(self, tmp_path):
        """main() routes a recognised subcommand to its handler."""
        artifact = tmp_path / "io-coverage.json"
        artifact.write_text(json.dumps({"variations": []}))

        argv = ["coverage", "status", "--artifact", str(artifact)]
        with patch("sys.argv", argv):
            result = main()
        assert result == 0
