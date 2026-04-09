"""Tests for __main__.py and CLI entry points.

Covers:
- __main__.py (lines 3-5) — 0% coverage currently
- cli/parse.py error handling paths
"""

import subprocess
import sys
import tempfile


class TestMainModule:
    """Smoke tests for the ``python -m cobolparser`` entry point."""

    def test_main_module_help(self):
        """--help exits 0 and prints usage."""
        result = subprocess.run(
            [sys.executable, "-m", "cobolparser", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert "cobol" in result.stdout.lower()

    def test_main_module_no_args_exits_gracefully(self):
        result = subprocess.run(
            [sys.executable, "-m", "cobolparser"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Should not crash with a traceback
        assert "Traceback" not in result.stderr


class TestCliParseErrors:
    """cli/parse.py error handling."""

    def test_parse_nonexistent_file_fails(self):
        result = subprocess.run(
            [sys.executable, "-m", "cobolparser", "/nonexistent/file.cob"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode != 0

    def test_parse_valid_file(self):
        """Parsing a valid COBOL file outputs JSON AST."""
        cobol_src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cob", delete=False) as f:
            f.write(cobol_src)
            f.flush()
            result = subprocess.run(
                [sys.executable, "-m", "cobolparser", f.name],
                capture_output=True,
                text=True,
                timeout=30,
            )
        assert result.returncode == 0
        assert "IDENTIFICATION" in result.stdout or "{" in result.stdout
