"""Regression tests for issue #737: ``scan`` given a directory.

A directory argument failed as "Encoding error ... Is a directory"; it now
stops with a message that names the directory and the ``--glob`` to use,
and a ``**`` glob no longer offers the directories it walks through as
files.
"""

import json
import subprocess
import sys
from pathlib import Path

_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ONE.
       PROCEDURE DIVISION.
       MAIN.
           STOP RUN.
"""


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "cobolparser.cli.parse", "scan", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def test_directory_argument_is_rejected_plainly(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "one.cbl").write_text(_PROGRAM)
    proc = _run("src", cwd=tmp_path)
    assert proc.returncode == 1
    assert "src is a directory" in proc.stderr
    assert "--glob" in proc.stderr
    assert "Encoding error" not in proc.stderr


def test_double_star_glob_skips_directories(tmp_path: Path) -> None:
    (tmp_path / "src" / "sub").mkdir(parents=True)
    (tmp_path / "src" / "sub" / "one.cbl").write_text(_PROGRAM)
    proc = _run("--glob", "src/**", "--analyzer", "complexity", cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    summary = json.loads(proc.stdout)["summary"]
    assert summary["file_count"] == 1
    assert summary["failed_file_count"] == 0
