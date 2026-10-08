"""What ``cobolparser.jcl`` adds on top of the ``jcl-parser`` package.

The JCL itself is read by ``jclparser``; these tests pin the adapter's own
behaviour: procedure libraries, several jobs per deck, recovering from a card
``jclparser`` rejects, and the notes that keep an unresolved name from passing
for a real one.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

from cobolparser.cli.parse import _cmd_jcl
from cobolparser.jcl import JclParser, bindings_for_ddname, parse_jcl

PROCLIB_MEMBER = """\
//NIGHTLY PROC ENV=TEST
//EXTRACT EXEC PGM=CUSTEXT
//CUSTIN  DD DSN=&ENV..CUST.MASTER,DISP=SHR
//CUSTOUT DD DSN=&&EXTRACT,DISP=(NEW,PASS)
//LOAD    EXEC PGM=CUSTLOAD
//CUSTIN  DD DSN=&&EXTRACT,DISP=(OLD,DELETE)
//        PEND
"""

CALLER = """\
//JOB1 JOB (1),'NIGHTLY'
//RUN  EXEC NIGHTLY,ENV=PROD
//LOAD.SYSOUT DD SYSOUT=*
//
"""


@pytest.fixture()
def proclib(tmp_path: Path) -> Path:
    library = tmp_path / "proclib"
    library.mkdir()
    (library / "NIGHTLY.prc").write_text(PROCLIB_MEMBER)
    (library / "STDDD.jcl").write_text("//STEPLIB DD DSN=PROD.LOADLIB,DISP=SHR\n")
    return library


class TestProcedureLibraries:
    def test_cataloged_procedure_is_expanded_from_the_procedure_path(self, proclib):
        result = parse_jcl(CALLER, proc_paths=[proclib])
        assert result.errors == []
        assert result.unresolved == []
        steps = result.jobs[0].steps
        assert [s.name for s in steps] == ["RUN", "RUN.EXTRACT", "RUN.LOAD"]
        extract = result.jobs[0].step("RUN.EXTRACT")
        assert (extract.program, extract.procedure) == ("CUSTEXT", "NIGHTLY")
        # The EXEC override wins over the procedure default.
        assert extract.dd("CUSTIN").dataset == "PROD.CUST.MASTER"
        # A library member's line numbers are its own, not the caller's.
        assert extract.line == 2
        assert [b.step for b in bindings_for_ddname(result, "CUSTIN")] == [
            "RUN.EXTRACT",
            "RUN.LOAD",
        ]

    def test_without_the_path_the_procedure_is_reported_not_guessed(self):
        result = parse_jcl(CALLER)
        assert [s.name for s in result.jobs[0].steps] == ["RUN"]
        assert any("PROC NIGHTLY (line 2)" in n for n in result.unresolved)

    def test_builtin_ibm_templates_are_not_used(self):
        # jclparser ships templates for IBM-supplied procedures; their dataset
        # names are not this shop's, so they are never substituted in.
        result = parse_jcl("//J JOB 1\n//S1 EXEC DSNUPROC,SYSTEM=DB2P\n//\n")
        assert [s.name for s in result.jobs[0].steps] == ["S1"]
        assert any("PROC DSNUPROC" in n for n in result.unresolved)

    def test_include_member_is_read_from_the_procedure_path(self, proclib):
        result = parse_jcl(
            "//J JOB 1\n//S1 EXEC PGM=A\n// INCLUDE MEMBER=STDDD\n//\n",
            proc_paths=[proclib],
        )
        assert result.unresolved == []
        assert result.dd_map()["STEPLIB"] == ["PROD.LOADLIB"]

    def test_first_directory_wins(self, proclib, tmp_path):
        override = tmp_path / "override"
        override.mkdir()
        (override / "NIGHTLY").write_text(
            PROCLIB_MEMBER.replace("PGM=CUSTEXT", "PGM=NEWEXT")
        )
        result = JclParser([override, proclib, tmp_path / "missing"]).parse(CALLER)
        assert result.jobs[0].step("RUN.EXTRACT").program == "NEWEXT"

    def test_missing_procedure_does_not_stop_the_others(self, proclib):
        result = parse_jcl(
            CALLER.replace("//\n", "//S2 EXEC NOSUCH\n//S3 EXEC NIGHTLY\n//\n"),
            proc_paths=[proclib],
        )
        names = [s.name for s in result.jobs[0].steps]
        assert "S2" in names and "S3.LOAD" in names
        assert any("PROC NOSUCH" in n for n in result.unresolved)

    def test_procedures_dict_holds_bodies_with_their_defaults(self):
        result = parse_jcl(PROCLIB_MEMBER.replace("//NIGHTLY", "//NIGHTLY", 1) + "")
        # A PROC member with no JOB card is a cataloged procedure.
        assert any("no JOB card" in n for n in result.unresolved)
        body = result.procedures["NIGHTLY"]
        assert [s.name for s in body] == ["EXTRACT", "LOAD"]
        assert body[0].dd("CUSTIN").dataset == "TEST.CUST.MASTER"


class TestSeveralJobs:
    def test_job_card_inside_in_stream_data_is_data(self):
        result = parse_jcl("""\
//SUBMIT JOB 1
//S1 EXEC PGM=IEBGENER
//SYSUT1 DD DATA,DLM=$$
//INNER JOB 2
//X EXEC PGM=Y
$$
//SYSUT2 DD SYSOUT=(A,INTRDR)
//NEXT JOB 3
//S2 EXEC PGM=Z
""")
        assert [job.name for job in result.jobs] == ["SUBMIT", "NEXT"]
        assert result.jobs[0].steps[0].dd("SYSUT1").instream_lines == [
            "//INNER JOB 2",
            "//X EXEC PGM=Y",
        ]
        # Line numbers are the deck's, not the job's.
        assert result.jobs[1].line == 8
        assert result.jobs[1].steps[0].line == 9

    def test_a_rejected_job_costs_only_that_job(self):
        result = parse_jcl("""\
//J1 JOB 1
//S1 EXEC
//J2 JOB 2
//S2 EXEC PGM=B
""")
        assert result.errors == [
            {"line": 2, "message": "EXEC statement missing program or procedure"}
        ]
        assert result.jobs[1].steps[0].program == "B"

    def test_unreadable_card_is_reported_and_the_rest_is_read(self):
        result = parse_jcl("""\
//J JOB 1
BAD CARD ONE
//S1 EXEC PGM=A
//S2 EXEC PGM=B
//S3 EXEC
//S4 EXEC PGM=D
""")
        assert [e["line"] for e in result.errors] == [2, 5]
        assert [s.program for s in result.jobs[0].steps] == ["A", "B", "D"]
        assert result.success is False


class TestUnresolvedNotes:
    def test_backward_reference_is_reported(self):
        result = parse_jcl("""\
//J JOB 1
//S1 EXEC PGM=A
//IN DD DSN=*.S0.OUT,DISP=SHR
//
""")
        assert any("backward reference" in n for n in result.unresolved)

    def test_non_numeric_lrecl_inside_dcb_is_reported(self):
        result = parse_jcl("""\
//J JOB 1
//S1 EXEC PGM=A
//IN DD DSN=A.B,DCB=(RECFM=FB,LRECL=ABC)
//
""")
        dd = result.jobs[0].steps[0].dd("IN")
        assert (dd.record_format, dd.record_length) == ("FB", None)
        assert any("LRECL=ABC" in n for n in result.unresolved)

    def test_job_without_a_name_is_an_error(self):
        result = parse_jcl("// JOB (1)\n//S1 EXEC PGM=A\n//\n")
        assert any("no job name" in e["message"] for e in result.errors)


class TestCli:
    def test_proc_path_flag(self, proclib, tmp_path, capsys):
        job = tmp_path / "JOB1.jcl"
        job.write_text(CALLER)
        _cmd_jcl(
            argparse.Namespace(
                file=str(job),
                dd_map=True,
                bindings=False,
                program=None,
                proc_path=[str(proclib)],
                strict=False,
                compact=True,
                output=None,
            )
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["dd_map"]["CUSTIN"] == ["PROD.CUST.MASTER", "&&EXTRACT"]
        assert payload["unresolved"] == []


def test_missing_jcl_parser_names_the_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "jclparser", None)
    with pytest.raises(ImportError, match=r"cobol-parser\[jcl\]"):
        parse_jcl("//J JOB 1\n")
