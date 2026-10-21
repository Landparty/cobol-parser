"""#566: ICETOOL steps and IKJEFT01 steps with a dataset SYSTSIN vanished.

ICETOOL was read as a plain DFSORT step (``SORTIN`` -> ``SORTOUT``), but its
operators live in ``TOOLIN`` and name their DDs freely, so no pass-through
was ever produced. A TSO step whose ``SYSTSIN`` is a dataset (the usual
production layout) was skipped. Both were silent; now the ICETOOL operators
are followed, and whatever cannot be read is a caveat.
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


def run(*dds: NS, program: str = "ICETOOL") -> tuple[list, list, list[str]]:
    caveats: list[str] = []
    step = NS(name="S1", program=program, dd_statements=list(dds))
    bindings, passthroughs = bindings_from_jobs([NS(name="J4", steps=[step])], caveats)
    return bindings, passthroughs, caveats


class TestIcetool:
    def test_copy_from_to(self) -> None:
        _, passthroughs, caveats = run(
            dd("INDD", "PROD.D.FILE"),
            dd("OUTDD", "PROD.E.FILE"),
            dd("TOOLIN", data="  COPY FROM(INDD) TO(OUTDD)\n"),
        )
        assert [(p.input, p.output, p.kind, p.program) for p in passthroughs] == [
            ("PROD.D.FILE", "PROD.E.FILE", "copy", "ICETOOL")
        ]
        assert caveats == []

    def test_sort_using_cntl_with_sum_and_several_outputs(self) -> None:
        _, passthroughs, _ = run(
            dd("IN", "A.IN"),
            dd("O1", "A.O1"),
            dd("O2", "A.O2"),
            dd("CTL1CNTL", data="  SORT FIELDS=(1,5,CH,A)\n  SUM FIELDS=(10,4,ZD)\n"),
            dd(
                "TOOLIN",
                data="* a comment\n  SORT FROM(IN) -\n    TO(O1,O2) USING(CTL1)\n",
            ),
        )
        assert [(p.output, p.kind, p.aggregate_ranges) for p in passthroughs] == [
            ("A.O1", "copy", ((9, 4),)),
            ("A.O2", "copy", ((9, 4),)),
        ]

    def test_using_cntl_that_reformats(self) -> None:
        _, passthroughs, _ = run(
            dd("IN", "A.IN"),
            dd("OUT", "A.OUT"),
            dd("CTL1CNTL", data="  OUTREC FIELDS=(1,5)\n"),
            dd("TOOLIN", data="  COPY FROM(IN) TO(OUT) USING(CTL1)\n"),
        )
        assert [p.kind for p in passthroughs] == ["reformat"]

    def test_splice_is_a_reformat_and_select_discard_is_an_output(self) -> None:
        _, passthroughs, _ = run(
            dd("IN", "A.IN"),
            dd("KEEP", "A.KEEP"),
            dd("DROP", "A.DROP"),
            dd("SPL", "A.SPL"),
            dd(
                "TOOLIN",
                data="  SELECT FROM(IN) TO(KEEP) ON(1,5,CH) FIRST DISCARD(DROP)\n"
                "  SPLICE FROM(IN) TO(SPL) ON(1,5,CH) WITH(6,4)\n"
                "  COUNT FROM(IN)\n",
            ),
        )
        assert [(p.output, p.kind) for p in passthroughs] == [
            ("A.KEEP", "copy"),
            ("A.DROP", "copy"),
            ("A.SPL", "reformat"),
        ]

    def test_toolin_from_a_dataset_is_a_caveat(self) -> None:
        _, passthroughs, caveats = run(
            dd("IN", "A.IN"), dd("OUT", "A.OUT"), dd("TOOLIN", "PROD.CNTL(TOOL)")
        )
        assert passthroughs == []
        assert caveats == [
            "ICETOOL step S1 in job J4: TOOLIN is not in-stream (PROD.CNTL(TOOL)); "
            "the flow through it is not traced"
        ]

    def test_unknown_dd_is_a_caveat(self) -> None:
        _, passthroughs, caveats = run(
            dd("IN", "A.IN"), dd("TOOLIN", data="  COPY FROM(IN) TO(NOWHERE)\n")
        )
        assert passthroughs == []
        assert (
            caveats and "COPY operator's FROM/TO datasets not recognised" in caveats[0]
        )


class TestTsoSystsinDataset:
    @pytest.mark.parametrize("program", ["IKJEFT01", "IKJEFT1A", "IKJEFT1B"])
    def test_dataset_systsin_is_a_caveat(self, program: str) -> None:
        bindings, _, caveats = run(
            dd("IN", "PROD.H.FILE"),
            dd("SYSTSPRT"),
            dd("SYSTSIN", "PROD.CNTL(RUNRDR)"),
            program=program,
        )
        assert bindings == []
        assert caveats == [
            f"{program} step S1 in job J4: SYSTSIN is not in-stream "
            "(PROD.CNTL(RUNRDR)); the programs it runs are not known, so its "
            "DDs are not bound"
        ]

    def test_inline_systsin_without_run_program_stays_quiet(self) -> None:
        bindings, _, caveats = run(
            dd("X", "A"), dd("SYSTSIN", data=" LISTCAT\n"), program="IKJEFT01"
        )
        assert bindings == [] and caveats == []


def test_field_impact_follows_an_icetool_copy(monkeypatch, capsys, tmp_path) -> None:
    pytest.importorskip("jclparser")
    jcl = tmp_path / "j4.jcl"
    jcl.write_text(
        "//J4       JOB (ACCT),'X',CLASS=A\n"
        "//S1       EXEC PGM=WRITER\n"
        "//INFILE   DD DSN=PROD.TRAN.DAILY,DISP=SHR\n"
        "//OUTFILE  DD DSN=PROD.D.FILE,DISP=(NEW,CATLG)\n"
        "//COPY     EXEC PGM=ICETOOL\n"
        "//TOOLMSG  DD SYSOUT=*\n"
        "//DFSMSG   DD SYSOUT=*\n"
        "//INDD     DD DSN=PROD.D.FILE,DISP=SHR\n"
        "//OUTDD    DD DSN=PROD.E.FILE,DISP=(NEW,CATLG)\n"
        "//TOOLIN   DD *\n"
        "  COPY FROM(INDD) TO(OUTDD)\n"
        "/*\n"
        "//S2       EXEC PGM=READER\n"
        "//FEEIN    DD DSN=PROD.E.FILE,DISP=SHR\n"
        "//MASTER   DD DSN=PROD.MASTER,DISP=SHR\n"
        "//S3       EXEC PGM=IKJEFT01\n"
        "//IN       DD DSN=PROD.H.FILE,DISP=SHR\n"
        "//SYSTSIN  DD DSN=PROD.CNTL(RUNRDR),DISP=SHR\n"
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
    assert "PROD.E.FILE" in out["datasets"]
    assert any("READER" == p for p in out["programs"])
    assert any("SYSTSIN is not in-stream" in c for c in out["caveats"]), out["caveats"]
