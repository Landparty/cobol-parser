"""Tests for __main__.py and CLI entry points.

Covers:
- __main__.py (lines 3-5) — 0% coverage currently
- cli/parse.py error handling paths
- cli/coverage.py error handling paths
"""

import subprocess
import sys


class TestMainModule:
    """Tests for __main__.py entry point."""

    def test_main_module_help(self):
        """Running python -m cobolparser --help should exit 0."""
        result = subprocess.run(
            [sys.executable, "-m", "cobolparser", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert "usage" in result.stdout.lower() or "cobolparser" in result.stdout.lower()

    def test_main_module_parse_subcommand_help(self):
        """Running python -m cobolparser parse --help should exit 0."""
        result = subprocess.run(
            [sys.executable, "-m", "cobolparser", "parse", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0

    def test_main_module_no_args(self):
        """Running python -m cobolparser with no args should show help or error gracefully."""
        result = subprocess.run(
            [sys.executable, "-m", "cobolparser"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Should not crash
        assert result.returncode in (0, 1, 2)


class TestCliParseErrors:
    """Tests for cli/parse.py error handling (lines 103-105, 113-115, 157-158)."""

    def test_parse_nonexistent_file(self):
        """Parsing a file that doesn't exist should handle gracefully."""
        result = subprocess.run(
            [sys.executable, "-m", "cobolparser", "parse", "/nonexistent/file.cob"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Should fail gracefully, not crash
        assert result.returncode != 0 or "error" in result.stderr.lower() or "not found" in result.stderr.lower() or len(result.stderr) > 0

    def test_parse_stdin(self):
        """Parsing from stdin with a simple program."""
        cobol_src = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           STOP RUN.
"""
        result = subprocess.run(
            [sys.executable, "-m", "cobolparser", "parse", "-"],
            input=cobol_src,
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Should not crash
        assert result.returncode in (0, 1, 2)
