"""#339: SORT / IEBGENER control statements read from a dataset.

``//SYSIN DD DSN=PROD.CNTL(SRTCARD)`` is the usual production layout, and
only in-stream SYSIN was read: empty control text was classified as an exact
``copy``, so an OUTREC / BUILD in the member was never seen and lineage
claimed fields flowed byte for byte. Decision (a): such a step is a
``reformat`` (the flow stops there) and a caveat names the control dataset.
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


def run(program: str, *dds: NS) -> tuple[list, list[str]]:
    caveats: list[str] = []
    step = NS(name="S1", program=program, dd_statements=list(dds))
    _, passthroughs = bindings_from_jobs([NS(name="J", steps=[step])], caveats)
    return passthroughs, caveats


@pytest.mark.parametrize("control_dd", ["SYSIN", "DFSPARM"])
def test_sort_control_from_a_dataset_is_a_reformat(control_dd: str) -> None:
    passthroughs, caveats = run(
        "SORT",
        dd("SORTIN", "A.IN"),
        dd("SORTOUT", "A.OUT"),
        dd(control_dd, "PROD.CNTL(REFMT)"),
    )
    assert [(p.input, p.output, p.kind) for p in passthroughs] == [
        ("A.IN", "A.OUT", "reformat")
    ]
    assert caveats == [
        "SORT step S1 in job J: control statements are read from "
        "PROD.CNTL(REFMT), which is not in-stream; the step is treated as a "
        "reformat and values are not traced through it"
    ]


def test_inline_sort_control_is_still_a_copy() -> None:
    passthroughs, caveats = run(
        "SORT",
        dd("SORTIN", "A.IN"),
        dd("SORTOUT", "A.OUT"),
        dd("SYSIN", data=" SORT FIELDS=(1,5,CH,A)\n"),
    )
    assert [p.kind for p in passthroughs] == ["copy"] and caveats == []


def test_inline_dfsparm_is_read() -> None:
    passthroughs, _ = run(
        "SORT",
        dd("SORTIN", "A.IN"),
        dd("SORTOUT", "A.OUT"),
        dd("DFSPARM", data=" OUTREC FIELDS=(1,5)\n"),
    )
    assert [p.kind for p in passthroughs] == ["reformat"]


def test_iebgener_control_from_a_dataset_is_a_reformat() -> None:
    passthroughs, caveats = run(
        "IEBGENER",
        dd("SYSUT1", "A.IN"),
        dd("SYSUT2", "A.OUT"),
        dd("SYSIN", "PROD.CNTL(GENCARD)"),
    )
    assert [p.kind for p in passthroughs] == ["reformat"]
    assert len(caveats) == 1 and "PROD.CNTL(GENCARD)" in caveats[0]


def test_iebgener_with_dummy_sysin_is_a_copy() -> None:
    passthroughs, caveats = run(
        "IEBGENER",
        dd("SYSUT1", "A.IN"),
        dd("SYSUT2", "A.OUT"),
        dd("SYSIN", "NULLFILE"),
    )
    assert [p.kind for p in passthroughs] == ["copy"] and caveats == []


def test_field_impact_stops_at_the_sort_with_a_caveat(
    monkeypatch, capsys, tmp_path
) -> None:
    pytest.importorskip("jclparser")
    jcl = tmp_path / "job.jcl"
    jcl.write_text(
        "//J1       JOB (ACCT),'X',CLASS=A\n"
        "//STEP1    EXEC PGM=WRITER\n"
        "//INFILE   DD DSN=PROD.TRAN.DAILY,DISP=SHR\n"
        "//OUTFILE  DD DSN=A.IN,DISP=(NEW,CATLG)\n"
        "//STEP2    EXEC PGM=SORT\n"
        "//SORTIN   DD DSN=A.IN,DISP=SHR\n"
        "//SORTOUT  DD DSN=A.OUT,DISP=(NEW,CATLG)\n"
        "//SYSIN    DD DSN=PROD.CNTL(REFMT),DISP=SHR\n"
        "//STEP3    EXEC PGM=READER\n"
        "//FEEIN    DD DSN=A.OUT,DISP=SHR\n"
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
    assert "A.OUT" not in out["datasets"]
    assert any("PROD.CNTL(REFMT)" in c for c in out["caveats"]), out["caveats"]
    assert any("reformats A.IN into A.OUT" in c for c in out["caveats"])
