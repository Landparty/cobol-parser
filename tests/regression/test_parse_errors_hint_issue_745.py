"""#745: ``parse --errors`` still told the user to re-run with ``--errors``.

A partial parse exits 2 and warns on stderr. With ``--errors`` the errors
are already in the JSON, so the warning says so instead of the re-run hint.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from cobolparser.cli.parse import main

BAD = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BAD1.
       PROCEDURE DIVISION.
           MOVE TO .
           DISPLAY "X".
           STOP RUN.
"""


def _run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *flags: str
) -> tuple[int, str]:
    src = tmp_path / "bad.cbl"
    src.write_text(BAD)
    out = tmp_path / "out.json"
    monkeypatch.setattr(
        sys, "argv", ["cobol-parser", "parse", str(src), *flags, "-o", str(out)]
    )
    with pytest.raises(SystemExit) as exc:
        main()
    return int(exc.value.code or 0), out.read_text()


def test_with_errors_the_warning_points_at_the_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    code, out = _run(tmp_path, monkeypatch, "--errors")
    err = capsys.readouterr().err
    assert code == 2
    assert "re-run with --errors" not in err
    assert "they are in the JSON output's errors" in err
    assert json.loads(out)["errors"]


def test_without_errors_the_rerun_hint_stays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    code, out = _run(tmp_path, monkeypatch)
    assert code == 2
    assert "re-run with --errors" in capsys.readouterr().err
    assert "errors" not in json.loads(out)
