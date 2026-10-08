"""DD -> dataset bindings from parsed JCL (``analysis.lineage_jcl``).

``bindings_from_jobs`` is duck-typed over jcl-parser's model, so most tests
feed it plain namespaces; the end-to-end test runs jcl-parser itself and is
skipped where it is not installed (cobol-parser does not depend on it).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from cobolparser.analysis.lineage_jcl import (
    _sum_ranges,
    bindings_from_jobs,
    jobs_from_sources,
    load_jobs,
)

SAMPLES = Path(__file__).resolve().parents[2] / "samples" / "lineage"


def dd(name: str, dsn: str | None = None, data: str | None = None) -> NS:
    return NS(name=name, dataset_name=dsn, inline_data=data)


def step(program: str, *dds: NS, name: str = "S1") -> NS:
    return NS(name=name, program=program, dd_statements=list(dds))


def job(*steps: NS, name: str = "J1") -> NS:
    return NS(name=name, steps=list(steps))


class TestOrdinarySteps:
    def test_every_dsn_dd_is_bound_to_the_program(self) -> None:
        bindings, passthroughs = bindings_from_jobs(
            [job(step("PAYROLL", dd("IN", "A.B"), dd("OUT", "&&T"), dd("SYSOUT")))]
        )
        assert [(b.program, b.ddname, b.dataset, b.job) for b in bindings] == [
            ("PAYROLL", "IN", "A.B", "J1"),
            ("PAYROLL", "OUT", "&&T", "J1"),
        ]
        assert passthroughs == []

    def test_conditional_blocks_are_flattened(self) -> None:
        block = NS(
            then_steps=[step("P1", dd("A", "X.A"))],
            else_steps=[step("P2", dd("B", "X.B"))],
        )
        bindings, _ = bindings_from_jobs([job(block)])
        assert {b.program for b in bindings} == {"P1", "P2"}

    def test_tso_batch_binds_the_run_program(self) -> None:
        tso = step(
            "IKJEFT01",
            dd("SYSTSIN", data=" DSN SYSTEM(DB2P)\n RUN PROGRAM(ACCTUPD) PLAN(P)"),
            dd("ACCTIN", "PROD.ACCT"),
        )
        bindings, _ = bindings_from_jobs([job(tso)])
        assert [(b.program, b.ddname) for b in bindings] == [("ACCTUPD", "ACCTIN")]

    def test_tso_without_run_program_binds_nothing(self) -> None:
        bindings, _ = bindings_from_jobs([job(step("IKJEFT01", dd("X", "A")))])
        assert bindings == []

    def test_step_without_program_is_skipped(self) -> None:
        bindings, _ = bindings_from_jobs([job(step("", dd("X", "A")))])
        assert bindings == []


class TestUtilities:
    def test_sort_copy_with_sum(self) -> None:
        sort = step(
            "SORT",
            dd("SORTIN", "A.IN"),
            dd("SORTIN01", "A.IN2"),
            dd("SORTOUT", "A.OUT"),
            dd("SYSIN", data=" SORT FIELDS=(1,10,CH,A)\n SUM FIELDS=(20,7,ZD)"),
        )
        _, passthroughs = bindings_from_jobs([job(sort)])
        assert [(p.input, p.output, p.kind) for p in passthroughs] == [
            ("A.IN", "A.OUT", "copy"),
            ("A.IN2", "A.OUT", "copy"),
        ]
        assert passthroughs[0].aggregate_ranges == ((19, 7),)

    def test_sort_reformat_and_outfil(self) -> None:
        sort = step(
            "DFSORT",
            dd("SORTIN", "A.IN"),
            dd("OUT1", "A.OUT1"),
            dd("SYSIN", data=" SORT FIELDS=COPY\n OUTFIL FNAMES=OUT1,BUILD=(1,10)"),
        )
        _, passthroughs = bindings_from_jobs([job(sort)])
        assert [(p.output, p.kind) for p in passthroughs] == [("A.OUT1", "reformat")]

    def test_iebgener(self) -> None:
        gener = step("IEBGENER", dd("SYSUT1", "A"), dd("SYSUT2", "B"), dd("SYSIN"))
        _, passthroughs = bindings_from_jobs([job(gener)])
        assert [(p.input, p.output, p.kind) for p in passthroughs] == [
            ("A", "B", "copy")
        ]

    def test_iebgener_with_record_statement_reformats(self) -> None:
        gener = step(
            "IEBGENER",
            dd("SYSUT1", "A"),
            dd("SYSUT2", "B"),
            dd("SYSIN", data=" GENERATE MAXFLDS=1\n RECORD FIELD=(10,1,,1)"),
        )
        _, passthroughs = bindings_from_jobs([job(gener)])
        assert passthroughs[0].kind == "reformat"

    def test_idcams_repro_by_dd_and_by_name(self) -> None:
        idcams = step(
            "IDCAMS",
            dd("IN", "A.KSDS"),
            dd("OUT", "A.BACKUP"),
            dd(
                "SYSIN",
                data=" REPRO INFILE(IN) OUTFILE(OUT)\n"
                " REPRO INDATASET(A.ONE) OUTDATASET(A.TWO)",
            ),
        )
        _, passthroughs = bindings_from_jobs([job(idcams)])
        assert [(p.input, p.output) for p in passthroughs] == [
            ("A.KSDS", "A.BACKUP"),
            ("A.ONE", "A.TWO"),
        ]


class TestConcatenationAndOperands:
    def test_concatenated_dds_inherit_the_name_before_them(self) -> None:
        reader = step("READER", dd("INFILE", "PROD.ONE"), dd("", "PROD.TWO"))
        sort = step(
            "SORT",
            dd("SORTIN", "PROD.ONE"),
            dd("", "PROD.THREE"),
            dd("SORTOUT", "PROD.SORTED"),
            dd("SYSIN", data=" SORT FIELDS=(1,10,CH,A)"),
            name="S2",
        )
        bindings, passthroughs = bindings_from_jobs([job(reader, sort)])
        assert [(b.ddname, b.dataset) for b in bindings] == [
            ("INFILE", "PROD.ONE"),
            ("INFILE", "PROD.TWO"),
        ]
        assert [p.input for p in passthroughs] == ["PROD.ONE", "PROD.THREE"]

    def test_dummy_and_nullfile_bind_nothing(self) -> None:
        # jcl-parser keeps DUMMY as the first positional parameter.
        dummy = NS(
            name="OUT1",
            dataset_name="A.B",
            inline_data=None,
            parameters={"_pos_0": "DUMMY", "DSN": "A.B"},
        )
        writer = step("WRITER", dummy, dd("OUT2", "NULLFILE"), dd("OUT3", "A.C"))
        bindings, _ = bindings_from_jobs([job(writer)])
        assert [b.ddname for b in bindings] == ["OUT3"]

    def test_referback_names_the_earlier_dataset(self) -> None:
        writer = step("WRITER", dd("OUT", "A.B.C"), name="S1")
        reader = step("READER", dd("IN", "*.S1.OUT"), name="S2")
        bindings, _ = bindings_from_jobs([job(writer, reader)])
        assert ("READER", "IN", "A.B.C") in {
            (b.program, b.ddname, b.dataset) for b in bindings
        }

    def test_idcams_repro_operands_in_any_order(self) -> None:
        idcams = step(
            "IDCAMS",
            dd("IN", "A.IN"),
            dd("OUT", "A.OUT"),
            dd(
                "SYSIN",
                data="  REPRO OUTFILE(OUT) INFILE(IN)\n"
                "  REPRO -\n    INDATASET(B.IN) -\n    OUTDATASET(B.OUT)\n",
            ),
        )
        _, passthroughs = bindings_from_jobs([job(idcams)])
        assert [(p.input, p.output) for p in passthroughs] == [
            ("A.IN", "A.OUT"),
            ("B.IN", "B.OUT"),
        ]

    def test_keywords_inside_literals_are_not_reformats(self) -> None:
        sort = step(
            "SORT",
            dd("SORTIN", "C.IN"),
            dd("SORTOUT", "C.OUT"),
            dd(
                "SYSIN",
                data="  SORT FIELDS=(1,5,CH,A)\n"
                "  INCLUDE COND=(10,5,CH,EQ,C'BUILD')",
            ),
        )
        _, passthroughs = bindings_from_jobs([job(sort)])
        assert [(p.input, p.output, p.kind) for p in passthroughs] == [
            ("C.IN", "C.OUT", "copy")
        ]


@pytest.mark.parametrize(
    ("control", "expected"),
    [
        (" SUM FIELDS=(20,7,ZD)", ((19, 7),)),
        (" SUM FIELDS=(1,4,BI,9,8,PD)", ((0, 4), (8, 8))),
        (" SUM FIELDS=(1,4,9,8),FORMAT=ZD", ((0, 4), (8, 8))),
        (" SUM FIELDS=NONE", ()),
        (" SUM FIELDS=(NONE)", ()),
    ],
)
def test_sum_ranges(control, expected) -> None:
    assert _sum_ranges(control) == expected


def test_load_jobs_with_jcl_parser(tmp_path) -> None:
    pytest.importorskip("jclparser")
    procs = tmp_path / "proc"
    procs.mkdir()
    (procs / "RUNPGM.prc").write_text(
        "//RUNPGM   PROC\n//RUN      EXEC PGM=&PROG\n//INFILE   DD DSN=&DSN,DISP=SHR\n"
    )
    (tmp_path / "PROCJOB.jcl").write_text(
        "//PROCJOB  JOB (A),'X',CLASS=A\n"
        "//STEP1    EXEC RUNPGM,PROG=WRITER,DSN=PROD.TRAN.DAILY\n"
    )
    jobs, problems = load_jobs([SAMPLES / "FEEJOB.jcl", tmp_path], proc_path=procs)
    assert problems == []
    bindings, passthroughs = bindings_from_jobs(jobs)
    found = {(b.job, b.program, b.ddname, b.dataset) for b in bindings}
    assert ("FEEJOB", "READER", "FEEIN", "PROD.FEE.SUMMARY(+1)") in found
    assert ("PROCJOB", "WRITER", "INFILE", "PROD.TRAN.DAILY") in found
    assert [(p.input, p.aggregate_ranges) for p in passthroughs] == [
        ("&&FEES", ((19, 7),))
    ]


def test_load_jobs_reports_unreadable_files(tmp_path) -> None:
    pytest.importorskip("jclparser")
    jobs, problems = load_jobs([tmp_path / "NOPE.jcl"])
    assert jobs == []
    assert len(problems) == 1 and "NOPE.jcl" in problems[0]


def test_jobs_from_sources_in_memory() -> None:
    pytest.importorskip("jclparser")
    jobs, problems = jobs_from_sources(
        {
            "PROCJOB": "//PROCJOB  JOB (A),'X',CLASS=A\n"
            "//STEP1    EXEC RUNPGM,PROG=WRITER\n",
            "BROKEN": "this is not JCL",
        },
        {
            "RUNPGM": "//RUNPGM   PROC\n//RUN      EXEC PGM=&PROG\n"
            "//INFILE   DD DSN=PROD.IN,DISP=SHR\n"
        },
    )
    bindings, _ = bindings_from_jobs(jobs)
    assert ("WRITER", "INFILE", "PROD.IN") in {
        (b.program, b.ddname, b.dataset) for b in bindings
    }
    assert len(jobs) + len(problems) >= 2
