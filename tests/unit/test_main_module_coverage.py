"""Coverage for the ``python -m cobolparser`` entry point.

Targets cobolparser/__main__.py which simply imports and invokes the
CLI ``main`` function.
"""

import runpy
import subprocess
import sys
from unittest.mock import patch


def test_main_module_invokes_cli_in_process():
    """Importing/executing __main__ in-process calls cli.main exactly once.

    Uses runpy so the module body (the ``main()`` call) is executed under the
    coverage tracer, which a subprocess invocation would not be.
    """
    with patch("cobolparser.cli.main") as mock_main:
        runpy.run_module("cobolparser", run_name="__main__", alter_sys=True)
    mock_main.assert_called_once()


def test_run_as_module_shows_usage():
    """``python -m cobolparser`` with no args runs the CLI and exits non-zero."""
    result = subprocess.run(
        [sys.executable, "-m", "cobolparser"],
        capture_output=True,
        text=True,
    )
    # argparse prints usage to stderr/stdout and exits with a non-zero code
    # when no subcommand is supplied.
    combined = result.stdout + result.stderr
    assert "usage" in combined.lower()
    assert result.returncode != 0


def test_run_as_module_help():
    """``python -m cobolparser parse -h`` reaches the CLI help path."""
    result = subprocess.run(
        [sys.executable, "-m", "cobolparser", "parse", "-h"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "usage" in (result.stdout + result.stderr).lower()
