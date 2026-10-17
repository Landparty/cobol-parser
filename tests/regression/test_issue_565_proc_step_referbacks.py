"""#565: a JCL referback into or inside a PROC was never resolved.

jcl-parser names an expanded PROC's steps ``INVOCATION.PROCSTEP``
(``RUNB.S1``), but the referback lookup only ever tried the last two parts
of ``*.RUNB.S1.OUT`` (``S1.OUT``), and an in-PROC ``*.S1.OUT`` from
``RUNA.S2`` never had its invocation prefix added. The DD was bound to the
literal ``*.`` text and the join was silently lost. A referback that names
no earlier DD now binds nothing and is a caveat.
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


def dd(name: str, dsn: str | None = None) -> NS:
    return NS(name=name, dataset_name=dsn, inline_data=None)


def step(name: str, program: str, *dds: NS) -> NS:
    return NS(name=name, program=program, dd_statements=list(dds))


# What jcl-parser hands over once MYPROC (S1 writes &OUTDS, S2 reads
# *.S1.OUT) is expanded twice, as RUNA and RUNB.
EXPANDED = [
    step("RUNA.S1", "WRITER", dd("OUT", "PROD.A.FILE")),
    step("RUNA.S2", "READER", dd("IN", "*.S1.OUT")),
    step("RUNB.S1", "WRITER", dd("OUT", "PROD.B.FILE")),
    step("RUNB.S2", "READER", dd("IN", "*.S1.OUT")),
    step("READB", "READER", dd("IN", "*.RUNB.S1.OUT")),
]


def test_referbacks_into_and_inside_a_proc() -> None:
    caveats: list[str] = []
    bindings, _ = bindings_from_jobs([NS(name="J2", steps=EXPANDED)], caveats)
    assert [(b.step, b.dataset) for b in bindings if b.program == "READER"] == [
        ("RUNA.S2", "PROD.A.FILE"),
        ("RUNB.S2", "PROD.B.FILE"),
        ("READB", "PROD.B.FILE"),
    ]
    assert caveats == []


def test_plain_referbacks_still_resolve() -> None:
    steps = [
        step("S1", "WRITER", dd("OUT", "PROD.X")),
        step("S2", "READER", dd("IN", "*.S1.OUT"), dd("ALSO", "*.IN")),
    ]
    bindings, _ = bindings_from_jobs([NS(name="J", steps=steps)])
    assert [(b.ddname, b.dataset) for b in bindings if b.step == "S2"] == [
        ("IN", "PROD.X"),
        ("ALSO", "PROD.X"),
    ]


def test_unresolved_referback_binds_nothing_and_is_a_caveat() -> None:
    caveats: list[str] = []
    bindings, _ = bindings_from_jobs(
        [NS(name="J2", steps=[step("READC", "READER", dd("IN", "*.NOPE.OUT"))])],
        caveats,
    )
    assert bindings == []
    assert caveats == [
        "step READC in job J2: DD IN refers back to *.NOPE.OUT, which names "
        "no earlier DD; it is not bound to any dataset"
    ]


@pytest.mark.parametrize(
    "reader",
    [
        "//READB    EXEC PGM=READER\n//FEEIN    DD DSN=*.RUNB.S1.OUTFILE,DISP=SHR\n",
        "",  # the in-PROC S2 step below reads *.S1.OUTFILE
    ],
)
def test_field_impact_joins_through_a_proc_referback(
    monkeypatch, capsys, tmp_path, reader: str
) -> None:
    pytest.importorskip("jclparser")
    in_proc = (
        ""
        if reader
        else "//S2       EXEC PGM=READER\n//FEEIN    DD DSN=*.S1.OUTFILE,DISP=SHR\n"
    )
    jcl = tmp_path / "j2.jcl"
    jcl.write_text(
        "//J2       JOB (ACCT),'X',CLASS=A\n"
        "//MYPROC   PROC OUTDS=\n"
        "//S1       EXEC PGM=WRITER\n"
        "//INFILE   DD DSN=PROD.TRAN.DAILY,DISP=SHR\n"
        "//OUTFILE  DD DSN=&OUTDS,DISP=(NEW,CATLG)\n" + in_proc + "//         PEND\n"
        "//RUNA     EXEC MYPROC,OUTDS=PROD.A.FILE\n"
        "//RUNB     EXEC MYPROC,OUTDS=PROD.B.FILE\n" + reader
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
    assert "PROD.B.FILE" in out["datasets"]
    assert not any("FEEIN" in u for u in out["graph"]["unjoined"])
    hits = [h for h in out["hits"] if h["program"] == "READER"]
    assert any("PROD.B.FILE" in json.dumps(h) for h in hits), hits
