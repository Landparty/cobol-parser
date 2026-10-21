"""#493: ``jcl --program X`` never found a program run by IKJEFT01 / DFSRRC00.

``steps_running`` compared only ``PGM=``, so a DB2 program (``RUN
PROGRAM(X)`` under IKJEFT01) or an IMS batch program (``DFSRRC00
PARM='DLI,X,...'``) was "not run" by the JCL, and ``--program``,
``--dd-map --program`` and ``--bindings --program`` all came back empty with
exit 0, while field lineage resolved both forms. A dataset SYSTSIN is now an
``unresolved`` note, and a ``--program`` that matches nothing exits 1.
"""

from __future__ import annotations

import json
import sys

import pytest

from cobolparser.cli.parse import main
from cobolparser.jcl.programs import ims_program, run_programs

jclparser = pytest.importorskip("jclparser")

from cobolparser.jcl import parse_jcl  # noqa: E402

DECK = """\
//MYJOB    JOB (ACCT),'TEST',CLASS=A
//STEP1    EXEC PGM=PAYRTN
//INFILE   DD DSN=PROD.PAY.INPUT,DISP=SHR
//STEP2    EXEC PGM=IKJEFT01
//DBIN     DD DSN=PROD.DB.IN,DISP=SHR
//SYSTSIN  DD *
  DSN SYSTEM(DB2P)
  RUN PROGRAM(PAYDB2) PLAN(PAYPLAN)
  RUN PROGRAM(PAYRPT) PLAN(PAYPLAN)
/*
//STEP3    EXEC PGM=DFSRRC00,PARM='DLI,IMSPGM,IMSPSB'
//IMSIN    DD DSN=PROD.IMS.IN,DISP=SHR
//STEP4    EXEC PGM=IKJEFT01
//SYSTSIN  DD DSN=PROD.CNTL(RUNRDR),DISP=SHR
"""


@pytest.mark.parametrize(
    ("program", "step"),
    [
        ("PAYRTN", "STEP1"),
        ("PAYDB2", "STEP2"),
        ("PAYRPT", "STEP2"),
        ("imspgm", "STEP3"),
    ],
)
def test_steps_running_sees_through_launchers(program: str, step: str) -> None:
    result = parse_jcl(DECK)
    assert [s.name for s in result.steps_running(program)] == [step]


def test_launcher_name_still_matches_its_own_steps() -> None:
    result = parse_jcl(DECK)
    assert [s.name for s in result.steps_running("IKJEFT01")] == ["STEP2", "STEP4"]
    assert result.jobs[0].step("STEP2").effective_programs() == ["PAYDB2", "PAYRPT"]


def test_a_dataset_systsin_is_unresolved() -> None:
    result = parse_jcl(DECK)
    assert any(
        "STEP4" in note and "reads SYSTSIN from PROD.CNTL(RUNRDR)" in note
        for note in result.unresolved
    ), result.unresolved


def test_shared_rules() -> None:
    assert run_programs(
        " run program(a1) plan(p)\n RUN PROGRAM( B2 )\n RUN PROGRAM(A1)"
    ) == [
        "A1",
        "B2",
    ]
    assert ims_program("BMP,LOANPMT,LOANPSB") == "LOANPMT"
    assert ims_program(["MPP", "X"]) is None


def _cli(monkeypatch, capsys, tmp_path, *argv: str) -> tuple[int, dict, str]:
    path = tmp_path / "j1.jcl"
    path.write_text(DECK)
    monkeypatch.setattr(
        sys, "argv", ["cobol-parser", "--no-config", "jcl", str(path), *argv]
    )
    code = 0
    try:
        main()
    except SystemExit as exc:
        code = int(exc.code or 0)
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.err


def test_dd_map_program_under_ikjeft01(monkeypatch, capsys, tmp_path) -> None:
    code, out, _ = _cli(
        monkeypatch, capsys, tmp_path, "--dd-map", "--program", "PAYDB2"
    )
    assert code == 0
    # Only STEP2's DDs, and only STEP2's datasets for them: STEP4's SYSTSIN
    # dataset is not PAYDB2's.
    assert out["dd_map"] == {"DBIN": ["PROD.DB.IN"], "SYSTSIN": []}


def test_bindings_program_under_dfsrrc00(monkeypatch, capsys, tmp_path) -> None:
    code, out, _ = _cli(
        monkeypatch, capsys, tmp_path, "--bindings", "--program", "IMSPGM"
    )
    assert code == 0
    assert [(b["step"], b["ddname"]) for b in out["bindings"]] == [("STEP3", "IMSIN")]


def test_program_matching_nothing_exits_1(monkeypatch, capsys, tmp_path) -> None:
    code, out, err = _cli(monkeypatch, capsys, tmp_path, "--program", "NOPE")
    assert code == 1
    assert out["steps"] == []
    assert "--program NOPE: no step" in err
