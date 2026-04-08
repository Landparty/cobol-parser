"""Unit tests for cobolparser.cli.coverage CLI commands."""

import argparse
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cobolparser.cli.coverage import (
    cmd_generate,
    cmd_status,
    create_parser,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_ARTIFACT = {
    "variations": [
        {
            "id": "READ-SEQ-001",
            "verb": "READ",
            "status": "covered",
            "tests": ["t1"],
            "notes": "",
        },
        {
            "id": "OPEN-INPUT-001",
            "verb": "OPEN",
            "status": "gap",
            "tests": [],
            "notes": "",
        },
        {
            "id": "WRITE-001",
            "verb": "WRITE",
            "status": "partial",
            "tests": ["t2"],
            "notes": "long note here",
        },
    ]
}


def make_status_args(**kwargs):
    defaults = {
        "artifact": "io-coverage.json",
        "verb": None,
        "qualifier": None,
        "format": "table",
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# cmd_status tests
# ---------------------------------------------------------------------------


class TestCmdStatus:
    def test_status_missing_artifact(self, tmp_path, capsys):
        """Exit code 1 and error message when artifact file not found."""
        args = make_status_args(artifact=str(tmp_path / "nonexistent.json"))
        # Override fallback too by patching Path.exists to always return False
        with patch("cobolparser.cli.coverage.Path") as mock_path_cls:
            mock_instance = MagicMock()
            mock_instance.exists.return_value = False
            mock_path_cls.return_value = mock_instance
            result = cmd_status(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.out.lower() or "Error" in captured.out

    def test_status_with_valid_artifact_table(self, tmp_path, capsys):
        """Exit code 0 and table output for valid artifact."""
        artifact = tmp_path / "io-coverage.json"
        artifact.write_text(json.dumps(SAMPLE_ARTIFACT))
        args = make_status_args(artifact=str(artifact))

        result = cmd_status(args)

        assert result == 0
        out = capsys.readouterr().out
        assert "Total variations: 3" in out

    def test_status_verb_filter(self, tmp_path, capsys):
        """--verb OPEN filters to only OPEN variations."""
        artifact = tmp_path / "io-coverage.json"
        artifact.write_text(json.dumps(SAMPLE_ARTIFACT))
        args = make_status_args(artifact=str(artifact), verb="OPEN")

        result = cmd_status(args)

        assert result == 0
        out = capsys.readouterr().out
        assert "Total variations: 1" in out
        assert "READ" not in out

    def test_status_qualifier_filter(self, tmp_path, capsys):
        """--qualifier filters by qualifier substring."""
        artifact_data = {
            "variations": [
                {
                    "id": "READ-AT-END",
                    "verb": "READ",
                    "qualifiers": "AT END",
                    "status": "covered",
                    "tests": [],
                },
                {
                    "id": "READ-KEY",
                    "verb": "READ",
                    "qualifiers": "INVALID KEY",
                    "status": "gap",
                    "tests": [],
                },
            ]
        }
        artifact = tmp_path / "io-coverage.json"
        artifact.write_text(json.dumps(artifact_data))
        args = make_status_args(artifact=str(artifact), qualifier="AT END")

        result = cmd_status(args)

        assert result == 0
        out = capsys.readouterr().out
        assert "Total variations: 1" in out

    def test_status_json_format(self, tmp_path, capsys):
        """--format json outputs valid JSON with expected keys."""
        artifact = tmp_path / "io-coverage.json"
        artifact.write_text(json.dumps(SAMPLE_ARTIFACT))
        args = make_status_args(artifact=str(artifact), format="json")

        result = cmd_status(args)

        assert result == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "filtered_variations" in data
        assert "count" in data
        assert data["count"] == 3
        assert data["covered"] == 1
        assert data["gap"] == 1
        assert data["partial"] == 1

    def test_status_corrupt_json(self, tmp_path):
        """JSONDecodeError on corrupt artifact raises or returns error."""
        artifact = tmp_path / "bad.json"
        artifact.write_text("{not valid json")
        args = make_status_args(artifact=str(artifact))

        with pytest.raises(json.JSONDecodeError):
            cmd_status(args)


# ---------------------------------------------------------------------------
# cmd_generate tests
# ---------------------------------------------------------------------------


class TestCmdGenerate:
    def test_generate_success(self, tmp_path, capsys):
        """cmd_generate returns 0 and prints output when reporter succeeds."""
        args = argparse.Namespace(
            pytest_results="results.json",
            output=str(tmp_path / "out.json"),
            catalog=None,
            schema=None,
        )
        mock_reporter = MagicMock()
        mock_reporter.generate_report.return_value = {
            "success": True,
            "coverage_percent": 75.0,
            "covered_variations": 15,
            "total_variations": 20,
            "gap_variations": 5,
        }

        with patch(
            "cobolparser.cli.coverage.IOCoverageReporter", return_value=mock_reporter
        ):
            result = cmd_generate(args)

        assert result == 0
        out = capsys.readouterr().out
        assert "generated" in out.lower()
        assert "75.0%" in out

    def test_generate_reporter_failure(self, tmp_path, capsys):
        """cmd_generate returns 1 when reporter reports failure."""
        args = argparse.Namespace(
            pytest_results="results.json",
            output=str(tmp_path / "out.json"),
            catalog=None,
            schema=None,
        )
        mock_reporter = MagicMock()
        mock_reporter.generate_report.return_value = {
            "success": False,
            "validation_errors": ["Schema mismatch", "Missing field"],
        }

        with patch(
            "cobolparser.cli.coverage.IOCoverageReporter", return_value=mock_reporter
        ):
            result = cmd_generate(args)

        assert result == 1
        out = capsys.readouterr().out
        assert "Error" in out

    def test_generate_file_not_found(self, tmp_path, capsys):
        """cmd_generate returns 1 on FileNotFoundError from reporter."""
        args = argparse.Namespace(
            pytest_results="missing.json",
            output=str(tmp_path / "out.json"),
            catalog=None,
            schema=None,
        )
        mock_reporter = MagicMock()
        mock_reporter.generate_report.side_effect = FileNotFoundError(
            "missing.json not found"
        )

        with patch(
            "cobolparser.cli.coverage.IOCoverageReporter", return_value=mock_reporter
        ):
            result = cmd_generate(args)

        assert result == 1
        out = capsys.readouterr().out
        assert "Error" in out


# ---------------------------------------------------------------------------
# cmd_render tests
# ---------------------------------------------------------------------------


class TestCmdRender:
    def _make_render_args(
        self, fmt="markdown", output=None, input_file="coverage.json"
    ):
        return argparse.Namespace(input=input_file, output=output, format=fmt)

    def _mock_renderer(self, md="# Report", csv_data="a,b", summary="Summary"):
        renderer = MagicMock()
        renderer.render_markdown.return_value = md
        renderer.render_csv.return_value = csv_data
        renderer.render_summary.return_value = summary
        return renderer

    def test_render_markdown_to_stdout(self, capsys):
        """--format markdown prints markdown to stdout."""
        renderer = self._mock_renderer()
        args = self._make_render_args(fmt="markdown")

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
            from cobolparser.cli.coverage import cmd_render as _cr

            # Re-import to pick up patched module
            result = _cr(args)

        assert result == 0

    def test_render_csv_format(self, capsys):
        """--format csv calls render_csv."""
        renderer = self._mock_renderer()
        args = self._make_render_args(fmt="csv")

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
            from cobolparser.cli.coverage import cmd_render as _cr

            result = _cr(args)

        assert result == 0

    def test_render_file_not_found(self, capsys):
        """cmd_render returns 1 on FileNotFoundError."""
        mock_renderer_cls = MagicMock(side_effect=FileNotFoundError("not found"))
        args = self._make_render_args()

        with (
            patch("cobolparser.cli.coverage.sys.path"),
            patch.dict(
                sys.modules,
                {"render_markdown": MagicMock(CoverageRenderer=mock_renderer_cls)},
            ),
        ):
            from cobolparser.cli.coverage import cmd_render as _cr

            result = _cr(args)

        assert result == 1
        out = capsys.readouterr().out
        assert "Error" in out

    def test_render_json_decode_error(self, capsys):
        """cmd_render returns 1 on JSONDecodeError."""
        mock_renderer_cls = MagicMock(side_effect=json.JSONDecodeError("err", "", 0))
        args = self._make_render_args()

        with (
            patch("cobolparser.cli.coverage.sys.path"),
            patch.dict(
                sys.modules,
                {"render_markdown": MagicMock(CoverageRenderer=mock_renderer_cls)},
            ),
        ):
            from cobolparser.cli.coverage import cmd_render as _cr

            result = _cr(args)

        assert result == 1
        out = capsys.readouterr().out
        assert "Error" in out

    def test_render_to_file(self, tmp_path, capsys):
        """--output writes rendered content to file."""
        output_file = str(tmp_path / "report.md")
        renderer = self._mock_renderer(md="# Generated Report")
        args = self._make_render_args(fmt="markdown", output=output_file)

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
            from cobolparser.cli.coverage import cmd_render as _cr

            result = _cr(args)

        assert result == 0
        assert Path(output_file).read_text() == "# Generated Report"


# ---------------------------------------------------------------------------
# Argument parser tests
# ---------------------------------------------------------------------------


class TestCreateParser:
    def test_parser_no_command_exits(self):
        """Parser with no subcommand prints help and calling main returns 1."""
        from cobolparser.cli.coverage import main

        with patch("sys.argv", ["coverage"]):
            result = main()
        assert result == 1

    def test_status_command_parsed(self):
        """status subcommand is recognized."""
        parser = create_parser()
        args = parser.parse_args(["status", "--verb", "READ"])
        assert args.command == "status"
        assert args.verb == "READ"

    def test_generate_requires_pytest_results(self):
        """generate subcommand requires --pytest-results."""
        parser = create_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["generate"])

    def test_validate_requires_artifact(self):
        """validate subcommand requires --artifact."""
        parser = create_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["validate"])

    def test_render_requires_input(self):
        """render subcommand requires --input."""
        parser = create_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["render"])

    def test_render_format_choices(self):
        """render --format accepts markdown, csv, summary."""
        parser = create_parser()
        for fmt in ("markdown", "csv", "summary"):
            args = parser.parse_args(["render", "--input", "x.json", "--format", fmt])
            assert args.format == fmt

    def test_status_format_choices(self):
        """status --format accepts table, json."""
        parser = create_parser()
        for fmt in ("table", "json"):
            args = parser.parse_args(["status", "--format", fmt])
            assert args.format == fmt
