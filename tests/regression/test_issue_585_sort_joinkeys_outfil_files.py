"""#585: DFSORT JOINKEYS steps and ``OUTFIL FILES=nn`` outputs were dropped.

A JOINKEYS step reads ``SORTJNF1`` / ``SORTJNF2`` (or the DDs named by
``JOINKEYS F1=`` / ``F2=``), not ``SORTIN``, and ``OUTFIL FILES=01`` writes
DD ``SORTOF01``, not ``SORTOUT``. Neither was read, so the step produced no
pass-through and no caveat: ``field-impact`` stopped at the sort's input as
if nothing read it. A sort step whose inputs or outputs are still not
recognised now says so.
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


def sort_job(*dds: NS) -> list[NS]:
    return [
        NS(name="J1", steps=[NS(name="STEP2", program="SORT", dd_statements=list(dds))])
    ]


JOIN_CONTROL = (
    "  JOINKEYS FILE=F1,FIELDS=(1,5,A)\n"
    "  JOINKEYS FILE=F2,FIELDS=(1,5,A)\n"
    "  REFORMAT FIELDS=(F1:1,5)\n"
    "  SORT FIELDS=COPY\n"
)


class TestJoinkeys:
    def test_sortjnf_inputs_are_a_reformat(self) -> None:
        caveats: list[str] = []
        _, passthroughs = bindings_from_jobs(
            sort_job(
                dd("SORTJNF1", "PROD.AMT.FILE"),
                dd("SORTJNF2", "PROD.OTHER"),
                dd("SORTOUT", "PROD.JOINED"),
                dd("SYSIN", data=JOIN_CONTROL),
            ),
            caveats,
        )
        assert [(p.input, p.output, p.kind) for p in passthroughs] == [
            ("PROD.AMT.FILE", "PROD.JOINED", "reformat"),
            ("PROD.OTHER", "PROD.JOINED", "reformat"),
        ]
        assert caveats == []

    def test_f1_f2_name_the_input_dds(self) -> None:
        _, passthroughs = bindings_from_jobs(
            sort_job(
                dd("LEFT", "PROD.L"),
                dd("RIGHT", "PROD.R"),
                dd("SORTOUT", "PROD.JOINED"),
                dd(
                    "SYSIN",
                    data="  JOINKEYS F1=LEFT,FIELDS=(1,5,A)\n"
                    "  JOINKEYS F2=RIGHT,FIELDS=(1,5,A)\n"
                    "  REFORMAT FIELDS=(F1:1,5,F2:6,4)\n",
                ),
            )
        )
        assert {(p.input, p.kind) for p in passthroughs} == {
            ("PROD.L", "reformat"),
            ("PROD.R", "reformat"),
        }


class TestOutfilFiles:
    @pytest.mark.parametrize(
        ("control", "outputs"),
        [
            (" OUTFIL FILES=01\n", ["PROD.ONE"]),
            (" OUTFIL FILES=(01,A)\n", ["PROD.ONE", "PROD.A"]),
            (" OUTFIL FILES=A\n", ["PROD.A"]),
        ],
    )
    def test_sortof_dds_are_outputs(self, control: str, outputs: list[str]) -> None:
        _, passthroughs = bindings_from_jobs(
            sort_job(
                dd("SORTIN", "PROD.IN"),
                dd("SORTOF01", "PROD.ONE"),
                dd("SORTOFA", "PROD.A"),
                dd("SYSIN", data=" SORT FIELDS=(1,5,CH,A)\n" + control),
            )
        )
        assert [(p.input, p.output, p.kind) for p in passthroughs] == [
            ("PROD.IN", out, "copy") for out in outputs
        ]


def test_unrecognised_sort_step_is_a_caveat() -> None:
    caveats: list[str] = []
    _, passthroughs = bindings_from_jobs(
        sort_job(dd("WEIRDIN", "PROD.IN"), dd("SYSIN", data=" SORT FIELDS=COPY\n")),
        caveats,
    )
    assert passthroughs == []
    assert caveats == [
        "SORT step STEP2 in job J1: inputs and outputs not recognised; "
        "the flow through it is not traced"
    ]


JCL_HEAD = """\
//J1       JOB (ACCT),'X',CLASS=A
//STEP1    EXEC PGM=WRITER
//INFILE   DD DSN=PROD.TRAN.DAILY,DISP=SHR
//OUTFILE  DD DSN=PROD.AMT.FILE,DISP=(NEW,CATLG)
"""
JCL_TAIL = """\
//STEP3    EXEC PGM=READER
//FEEIN    DD DSN=PROD.JOINED,DISP=SHR
"""


def _impact(monkeypatch, capsys, tmp_path: Path, jcl: str) -> dict:
    pytest.importorskip("jclparser")
    path = tmp_path / "job.jcl"
    path.write_text(jcl)
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
            str(path),
            "--workers",
            "1",
        ],
    )
    main()
    return json.loads(capsys.readouterr().out)


def test_field_impact_follows_outfil_files(monkeypatch, capsys, tmp_path) -> None:
    out = _impact(
        monkeypatch,
        capsys,
        tmp_path,
        JCL_HEAD
        + "//STEP2    EXEC PGM=SORT\n"
        + "//SORTIN   DD DSN=PROD.AMT.FILE,DISP=SHR\n"
        + "//SORTOF01 DD DSN=PROD.JOINED,DISP=(NEW,CATLG)\n"
        + "//SYSIN    DD *\n  SORT FIELDS=(1,5,CH,A)\n  OUTFIL FILES=01\n/*\n"
        + JCL_TAIL,
    )
    assert "READER" in out["programs"]
    assert "PROD.JOINED" in out["datasets"]


def test_field_impact_stops_at_a_join_with_a_caveat(
    monkeypatch, capsys, tmp_path
) -> None:
    out = _impact(
        monkeypatch,
        capsys,
        tmp_path,
        JCL_HEAD
        + "//STEP2    EXEC PGM=SORT\n"
        + "//SORTJNF1 DD DSN=PROD.AMT.FILE,DISP=SHR\n"
        + "//SORTJNF2 DD DSN=PROD.OTHER,DISP=SHR\n"
        + "//SORTOUT  DD DSN=PROD.JOINED,DISP=(NEW,CATLG)\n"
        + "//SYSIN    DD *\n"
        + JOIN_CONTROL
        + "/*\n"
        + JCL_TAIL,
    )
    assert "PROD.JOINED" not in out["datasets"]
    assert any(
        "reformats PROD.AMT.FILE into PROD.JOINED" in c for c in out["caveats"]
    ), out["caveats"]


def test_field_impact_reports_an_unread_sort_step(
    monkeypatch, capsys, tmp_path
) -> None:
    out = _impact(
        monkeypatch,
        capsys,
        tmp_path,
        JCL_HEAD
        + "//STEP2    EXEC PGM=SORT\n"
        + "//SORTIN   DD DSN=PROD.AMT.FILE,DISP=SHR\n"
        + "//SORTOUT  DD SYSOUT=*\n"
        + "//SYSIN    DD *\n  SORT FIELDS=COPY\n/*\n"
        + JCL_TAIL,
    )
    assert any(
        "SORT step STEP2 in job J1: outputs not recognised" in c for c in out["caveats"]
    ), out["caveats"]


def test_join_caveats_are_kept_by_a_fresh_graph() -> None:
    # Without stored join edges, LineageGraph used to ignore join_caveats;
    # the JCL caveats must reach the graph and its exported join state.
    from cobolparser.analysis.lineage_graph import LineageGraph

    graph = LineageGraph([], join_caveats=["SORT step S in job J: x"])
    assert graph.caveats == ["SORT step S in job J: x"]
    assert graph.join_state()["caveats"] == ["SORT step S in job J: x"]
