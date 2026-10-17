"""#584: every ``RUN PROGRAM`` of an IKJEFT01 SYSTSIN is bound to the step.

A DB2 batch step often runs several programs one after another from one
SYSTSIN. Only the first ``RUN PROGRAM(...)`` was bound; every later program
read as "DD not bound to any dataset" and the flow through it was lost.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from cobolparser.analysis.lineage_jcl import bindings_from_jobs
from cobolparser.cli.parse import main

SAMPLES = Path(__file__).resolve().parents[1] / "samples" / "lineage"


def dd(name: str, dsn: str | None = None, data: str | None = None) -> NS:
    return NS(name=name, dataset_name=dsn, inline_data=data)


@pytest.mark.parametrize("program", ["IKJEFT01", "IKJEFT1A", "IKJEFT1B"])
def test_every_run_program_is_bound(program: str) -> None:
    tso = NS(
        name="STEP2",
        program=program,
        dd_statements=[
            dd("SYSTSPRT"),
            dd("OUTFILE", "PROD.AMT.FILE"),
            dd(
                "SYSTSIN",
                data=" DSN SYSTEM(DB2P)\n RUN PROGRAM(PGMX) PLAN(PLANX)\n"
                " RUN PROGRAM(PGMB) PLAN(PLANB)\n RUN PROGRAM(PGMX) PLAN(PLANX)\n END\n",
            ),
        ],
    )
    bindings, _ = bindings_from_jobs([NS(name="J1", steps=[tso])])
    assert [(b.program, b.ddname, b.dataset, b.step) for b in bindings] == [
        ("PGMX", "OUTFILE", "PROD.AMT.FILE", "STEP2"),
        ("PGMB", "OUTFILE", "PROD.AMT.FILE", "STEP2"),
    ]


def test_field_impact_reaches_the_second_run_program(
    monkeypatch, capsys, tmp_path
) -> None:
    pytest.importorskip("jclparser")
    jcl = tmp_path / "job.jcl"
    jcl.write_text(
        "//JOB1     JOB (ACCT),'X',CLASS=A\n"
        "//STEP1    EXEC PGM=WRITER\n"
        "//INFILE   DD DSN=PROD.TRAN.DAILY,DISP=SHR\n"
        "//OUTFILE  DD DSN=PROD.AMT.FILE,DISP=(NEW,CATLG)\n"
        "//STEP2    EXEC PGM=IKJEFT01\n"
        "//SYSTSPRT DD SYSOUT=*\n"
        "//FEEIN    DD DSN=PROD.AMT.FILE,DISP=SHR\n"
        "//MASTER   DD DSN=PROD.MASTER,DISP=SHR\n"
        "//SYSTSIN  DD *\n"
        " DSN SYSTEM(DB2P)\n"
        " RUN PROGRAM(PGMX) PLAN(PLANX)\n"
        " RUN PROGRAM(READER) PLAN(PLANB)\n"
        " END\n"
        "/*\n"
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cobol-parser",
            "--no-config",
            "field-impact",
            "WS-AMT",
            str(SAMPLES / "WRITER.cbl"),
            str(SAMPLES / "READER.cbl"),
            "--program",
            "WRITER",
            "--jcl",
            str(jcl),
            "--workers",
            "1",
        ],
    )
    main()
    out = json.loads(capsys.readouterr().out)
    assert "PROD.AMT.FILE" in out["datasets"]
    assert not any(u.startswith("READER:") for u in out["graph"]["unjoined"])
