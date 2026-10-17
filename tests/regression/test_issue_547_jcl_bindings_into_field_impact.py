"""#547: ``jcl --bindings`` output could not be fed to ``field-impact --bindings``.

The rows carried no ``program`` (``KeyError`` traceback), a malformed row
crashed the same way, and an ``EXEC proc`` step listed every DD override a
second time although it runs no program.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from cobolparser.cli.parse import main

pytest.importorskip("jclparser")

SAMPLES = Path(__file__).resolve().parents[1] / "samples" / "lineage"

GDG_JOB = """\
//JOB1     JOB (ACCT),'X'
//STEP1    EXEC PGM=WRITER
//INFILE   DD DSN=PROD.TRAN.DAILY,DISP=SHR
//OUTFILE  DD DSN=PROD.AMT.GDG(+1),DISP=(NEW,CATLG)
//STEP2    EXEC PGM=READER
//FEEIN    DD DSN=PROD.AMT.GDG(0),DISP=SHR
//SYSPRINT DD SYSOUT=*
"""

PROC_JOB = """\
//JOB3     JOB (ACCT),'X'
//MYPROC   PROC
//S1       EXEC PGM=WRT
//OUTDD    DD DSN=PROD.AMT.FILE,DISP=(NEW,CATLG)
//         PEND
//STEPA    EXEC MYPROC
//S1.OUTDD DD DSN=OVR.AMT.FILE,DISP=(NEW,CATLG)
//STEPB    EXEC NOPROC
//S1.OUTDD DD DSN=OVR.B.FILE,DISP=(NEW,CATLG)
"""


def _main(monkeypatch, *argv: str) -> None:
    monkeypatch.setattr(sys, "argv", ["cobol-parser", "--no-config", *argv])
    main()


def _jcl_bindings(monkeypatch, capsys, tmp_path: Path, text: str) -> dict:
    jcl = tmp_path / "job.jcl"
    jcl.write_text(text)
    _main(monkeypatch, "jcl", str(jcl), "--bindings")
    return json.loads(capsys.readouterr().out)


def test_jcl_bindings_rows_name_their_program(monkeypatch, capsys, tmp_path) -> None:
    rows = _jcl_bindings(monkeypatch, capsys, tmp_path, GDG_JOB)["bindings"]
    assert [(r["program"], r["ddname"]) for r in rows] == [
        ("WRITER", "INFILE"),
        ("WRITER", "OUTFILE"),
        ("READER", "FEEIN"),
        ("READER", "SYSPRINT"),
    ]


def test_jcl_bindings_output_feeds_field_impact(monkeypatch, capsys, tmp_path) -> None:
    data = _jcl_bindings(monkeypatch, capsys, tmp_path, GDG_JOB)
    path = tmp_path / "b.json"
    path.write_text(json.dumps(data))
    _main(
        monkeypatch,
        "field-impact",
        "WS-AMT",
        str(SAMPLES / "WRITER.cbl"),
        str(SAMPLES / "READER.cbl"),
        "--program",
        "WRITER",
        "--bindings",
        str(path),
        "--workers",
        "1",
    )
    out = json.loads(capsys.readouterr().out)
    assert "PROD.AMT.GDG" in out["datasets"]
    assert not any("FEEIN" in u for u in out["graph"]["unjoined"])


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"bindings": "A.B"}, '"bindings" must be a list'),
        ({"bindings": [["WRT", "OUTDD", "A.B"]]}, '"bindings"[0] is not an object'),
        ({"bindings": [{"program": "W", "dataset": "A"}]}, 'has no "ddname"'),
        ({"bindings": [{"program": 1, "ddname": "D", "dataset": "A"}]}, '"program"'),
        ({"passthroughs": [{"input": "A"}]}, 'needs a string "output"'),
        (
            {"passthroughs": [{"input": "A", "output": "B", "aggregate_ranges": [1]}]},
            '"aggregate_ranges"',
        ),
    ],
)
def test_malformed_rows_are_a_one_line_error(
    monkeypatch, capsys, tmp_path, payload: dict, message: str
) -> None:
    path = tmp_path / "b.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(SystemExit) as exc:
        _main(
            monkeypatch,
            "field-impact",
            "WS-AMT",
            str(SAMPLES / "WRITER.cbl"),
            "--bindings",
            str(path),
            "--workers",
            "1",
        )
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("error: --bindings") and message in err
    assert "Traceback" not in err


def test_override_is_listed_once_under_the_procedure_step(
    monkeypatch, capsys, tmp_path
) -> None:
    rows = _jcl_bindings(monkeypatch, capsys, tmp_path, PROC_JOB)["bindings"]
    assert [(r["step"], r["program"], r["dataset"]) for r in rows] == [
        ("STEPA.S1", "WRT", "OVR.AMT.FILE"),
        # NOPROC was never expanded: its override has nowhere else to live.
        ("STEPB", None, "OVR.B.FILE"),
    ]
