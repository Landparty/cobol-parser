"""Smoke tests for cobolparser.__main__ (python -m cobolparser) CLI entry point.

Verifies that:
- The module can be invoked as `python -m cobolparser` without ImportError
- Parsing a valid COBOL file exits with code 0
- Requesting help exits with code 0
- Passing a nonexistent file exits with non-zero code
- --compact flag produces single-line JSON output
- --errors flag is accepted
- --stats flag is accepted
- The subcommand `parse` works for a known sample file
"""

import json
import subprocess
import sys
from pathlib import Path

# Path to a known-good COBOL sample
_SAMPLES = Path(__file__).parent.parent / "samples"
_SIMPLE = str(_SAMPLES / "simple_calculation.cbl")
_SORT_SAMPLE = str(_SAMPLES / "sort_merge_operations.cbl")


def _run(*args: str, input_text: str | None = None) -> subprocess.CompletedProcess:
    """Run cobolparser as `python -m cobolparser <args>`."""
    cmd = [sys.executable, "-m", "cobolparser", *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        input=input_text,
        timeout=30,
    )


class TestMainModuleImport:
    """Verify the module entry point is importable and structurally valid."""

    def test_main_function_importable(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from cobolparser.cli import main; assert callable(main)",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    def test_main_module_file_exists(self):
        """__main__.py must exist so `python -m cobolparser` works."""
        import cobolparser

        pkg_dir = Path(cobolparser.__file__).parent
        assert (pkg_dir / "__main__.py").exists()


class TestMainHelpFlags:
    """Help / usage flags should exit 0 and produce output."""

    def test_help_flag_exits_zero(self):
        result = _run("--help")
        assert result.returncode == 0

    def test_help_flag_produces_output(self):
        result = _run("--help")
        assert len(result.stdout) > 0 or len(result.stderr) > 0

    def test_parse_subcommand_help(self):
        result = _run("parse", "--help")
        assert result.returncode == 0


class TestMainParseSubcommand:
    """Tests for the `parse` subcommand (or direct file parsing)."""

    def test_parse_valid_file_exits_zero(self):
        result = _run(_SIMPLE)
        assert (
            result.returncode == 0
        ), f"stdout: {result.stdout[:500]}\nstderr: {result.stderr[:500]}"

    def test_parse_valid_file_produces_json(self):
        result = _run(_SIMPLE)
        assert result.returncode == 0
        # Output should be parseable JSON
        output = result.stdout.strip()
        assert len(output) > 0
        parsed = json.loads(output)
        assert isinstance(parsed, dict)

    def test_parse_nonexistent_file_exits_nonzero(self):
        result = _run("/nonexistent/path/to/file.cbl")
        assert result.returncode != 0

    def test_parse_compact_produces_single_line(self):
        result = _run(_SIMPLE, "--compact")
        assert result.returncode == 0
        output = result.stdout.strip()
        # Compact JSON should be on a single line (no newlines within JSON)
        lines = [ln for ln in output.splitlines() if ln.strip()]
        assert len(lines) == 1

    def test_parse_pretty_produces_multiple_lines(self):
        result = _run(_SIMPLE)
        assert result.returncode == 0
        output = result.stdout.strip()
        lines = output.splitlines()
        assert len(lines) > 1

    def test_parse_errors_flag_accepted(self):
        result = _run(_SIMPLE, "--errors")
        assert result.returncode == 0

    def test_parse_stats_flag_accepted(self):
        result = _run(_SIMPLE, "--stats")
        assert result.returncode == 0

    def test_parse_sort_merge_sample(self):
        result = _run(_SORT_SAMPLE)
        assert result.returncode == 0

    def test_parse_output_contains_program_type(self):
        result = _run(_SIMPLE)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        # AST root must contain at least one of these canonical node keys
        assert any(
            k in data for k in ("node_type", "type", "program_name", "statement_type")
        )


class TestMainModuleInvocation:
    """Test `python -m cobolparser` (runs __main__.py)."""

    def test_module_invocation_with_valid_file(self):
        cmd = [sys.executable, "-m", "cobolparser", _SIMPLE]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode == 0

    def test_module_invocation_with_no_args_exits_nonzero_or_shows_help(self):
        cmd = [sys.executable, "-m", "cobolparser"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        # Either shows help (exit 0) or exits with usage error (non-zero).
        # Both are acceptable — what is NOT acceptable is an ImportError/crash.
        combined = result.stdout + result.stderr
        # Both must be absent — the process must not crash with a traceback or import error
        assert "Traceback" not in combined and "ImportError" not in combined
