"""Coverage gap tests for cobolparser/cli/coverage.py.

Targets specific missing lines/branches from the 2026-05-18 analysis:
  - Line 82: long-notes truncation in cmd_status table output
  - Lines 121-133: cmd_validate happy path and error path
  - Line 149: cmd_render summary format (renderer.render_summary())
  - Lines 263, 270: main() dispatch
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from cobolparser.cli import coverage as coverage_cli


def _write_artifact(path: Path, variations) -> None:
    path.write_text(json.dumps({"variations": variations}))


class TestCmdStatusLongNotesTruncation:
    """Cover line 82: notes longer than 30 chars get truncated to 27 + '...'"""

    def test_long_notes_truncated(self, tmp_path, capsys):
        artifact = tmp_path / "io-coverage.json"
        long_note = "x" * 50  # 50 chars triggers the truncation branch
        _write_artifact(
            artifact,
            [
                {
                    "id": "READ-001",
                    "verb": "READ",
                    "status": "covered",
                    "tests": ["t1"],
                    "notes": long_note,
                }
            ],
        )
        args = argparse.Namespace(
            artifact=str(artifact), verb=None, qualifier=None, format="table"
        )
        rc = coverage_cli.cmd_status(args)
        assert rc == 0
        out = capsys.readouterr().out
        # Truncated form should be present (27 chars + ellipsis)
        assert "x" * 27 + "..." in out


class TestCmdValidate:
    """Cover cmd_validate happy and error paths (lines 119-133)."""

    def test_validate_success(self, tmp_path, capsys):
        artifact = tmp_path / "io-coverage.json"
        artifact.write_text("{}")

        mock_validator = MagicMock()
        mock_validator.validate.return_value = True
        mock_validator.errors = []

        with patch.dict(
            sys.modules,
            {
                "scripts": MagicMock(),
                "scripts.validate_io_coverage": MagicMock(
                    CoverageSchemaValidator=MagicMock(return_value=mock_validator)
                ),
            },
        ):
            args = argparse.Namespace(artifact=str(artifact))
            rc = coverage_cli.cmd_validate(args)

        assert rc == 0
        out = capsys.readouterr().out
        assert "valid" in out.lower()

    def test_validate_failure_lists_errors(self, tmp_path, capsys):
        artifact = tmp_path / "io-coverage.json"
        artifact.write_text("{}")

        mock_validator = MagicMock()
        mock_validator.validate.return_value = False
        mock_validator.errors = ["schema mismatch", "missing field 'verb'"]

        with patch.dict(
            sys.modules,
            {
                "scripts": MagicMock(),
                "scripts.validate_io_coverage": MagicMock(
                    CoverageSchemaValidator=MagicMock(return_value=mock_validator)
                ),
            },
        ):
            args = argparse.Namespace(artifact=str(artifact))
            rc = coverage_cli.cmd_validate(args)

        assert rc == 1
        out = capsys.readouterr().out
        assert "schema mismatch" in out
        assert "missing field" in out


class TestCmdRenderSummaryFormat:
    """Cover line 149: renderer.render_summary() for default format."""

    def test_summary_format_calls_render_summary(self, tmp_path, capsys):
        artifact = tmp_path / "io-coverage.json"
        artifact.write_text(json.dumps({"variations": []}))

        mock_renderer = MagicMock()
        mock_renderer.render_summary.return_value = "summary output goes here"

        # Note: cmd_render adds tools/io_coverage to sys.path then imports
        # render_markdown. We patch the import to return our mock.
        with patch.dict(
            sys.modules,
            {
                "render_markdown": MagicMock(
                    CoverageRenderer=MagicMock(return_value=mock_renderer)
                )
            },
        ):
            args = argparse.Namespace(
                input=str(artifact), output=None, format="summary"
            )
            rc = coverage_cli.cmd_render(args)

        assert rc == 0
        mock_renderer.render_summary.assert_called_once()
        out = capsys.readouterr().out
        assert "summary output goes here" in out


class TestMainDispatch:
    """Cover main() dispatch (lines 263, 270)."""

    def test_main_no_command_prints_help_and_returns_1(self, capsys):
        with patch.object(sys, "argv", ["coverage"]):
            rc = coverage_cli.main()
        assert rc == 1

    def test_main_dispatches_to_status_command(self, tmp_path, capsys, monkeypatch):
        artifact = tmp_path / "io-coverage.json"
        artifact.write_text(json.dumps({"variations": []}))

        monkeypatch.setattr(
            sys, "argv", ["coverage", "status", "--artifact", str(artifact)]
        )
        rc = coverage_cli.main()
        assert rc == 0
