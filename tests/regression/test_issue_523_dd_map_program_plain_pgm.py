"""#523: ``jcl --dd-map --program X`` filtered the DD names to X's steps but
kept every other step's datasets under them, so PAYCALC appeared to read
PAYRPT's input (its own output). Fixed by #493, which builds the map from the
matching steps' DDs only; this pins the issue's plain ``PGM=`` deck.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from cobolparser.cli.parse import main

pytest.importorskip("jclparser")

DECK = """\
//PAYJOB   JOB (ACCT),'PAY',CLASS=A
//STEP1    EXEC PGM=PAYCALC
//INFILE   DD DSN=PROD.PAY.INPUT,DISP=SHR
//OUTFILE  DD DSN=PROD.PAY.OUT(+1),DISP=(NEW,CATLG),
//            SPACE=(CYL,(1,1)),DCB=(RECFM=FB,LRECL=80)
//STEP2    EXEC PGM=PAYRPT,COND=(4,LT,STEP1)
//INFILE   DD DSN=PROD.PAY.OUT(+1),DISP=SHR
//         DD DSN=PROD.PAY.EXTRA,DISP=SHR
"""


def _dd_map(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    program: str,
) -> dict[str, list[str]]:
    path = tmp_path / "j1.jcl"
    path.write_text(DECK)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cobol-parser",
            "--no-config",
            "jcl",
            str(path),
            "--dd-map",
            "--program",
            program,
        ],
    )
    try:
        main()
    except SystemExit as exc:
        assert not exc.code
    dd_map: dict[str, list[str]] = json.loads(capsys.readouterr().out)["dd_map"]
    return dd_map


def test_shared_ddname_keeps_only_this_programs_datasets(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    assert _dd_map(monkeypatch, capsys, tmp_path, "PAYCALC") == {
        "INFILE": ["PROD.PAY.INPUT"],
        "OUTFILE": ["PROD.PAY.OUT(+1)"],
    }


def test_the_other_step_keeps_its_concatenation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    assert _dd_map(monkeypatch, capsys, tmp_path, "PAYRPT") == {
        "INFILE": ["PROD.PAY.OUT(+1)", "PROD.PAY.EXTRA"],
    }
