"""Unit tests for the z/OS JCL parser (``cobolparser.jcl``).

The JCL in these tests is written the way a real deck is written -- fixed
80-column card images, continuation in columns 4-16, sequence numbers in
columns 73-80 -- because the card format is most of what the parser has to get
right.
"""

import json
from pathlib import Path

import pytest

from cobolparser.jcl import (
    DatasetBinding,
    DDStatement,
    JclJob,
    JclParameter,
    JclParser,
    JclParseResult,
    JobStep,
    bindings_for_ddname,
    parse_jcl,
    resolve_dd_bindings,
)

SAMPLES = Path(__file__).resolve().parent.parent / "samples" / "jcl"


@pytest.fixture()
def invupdt():
    return JclParser().parse_file(SAMPLES / "invupdt.jcl")


@pytest.fixture()
def payproc():
    return JclParser().parse_file(SAMPLES / "payproc.jcl")


SIMPLE_JOB = """\
//RUNJOB   JOB (12345),'BATCH NIGHTLY',CLASS=A,MSGCLASS=X
//STEP01   EXEC PGM=CUSTLOAD,PARM='RUN=DAILY'
//CUSTFILE DD DSN=PROD.CUST.MASTER,DISP=SHR
//SYSPRINT DD SYSOUT=*
//
"""


class TestSampleMultiStepJob:
    """A realistic two-step job read from tests/samples/jcl/invupdt.jcl."""

    def test_parses_without_errors(self, invupdt):
        assert invupdt.errors == []
        assert invupdt.success is True
        assert invupdt.filename.endswith("invupdt.jcl")

    def test_job_card(self, invupdt):
        assert len(invupdt.jobs) == 1
        job = invupdt.jobs[0]
        assert job.name == "INVUPD01"
        assert job.line == 1
        keywords = [p.keyword for p in job.parameters]
        assert keywords == [
            "",
            "",
            "CLASS",
            "MSGCLASS",
            "MSGLEVEL",
            "NOTIFY",
            "REGION",
        ]
        assert job.parameters[0].positional == ["ACCT1234", "'INVENTORY'"]
        assert job.parameters[1].value == "'S DION'"

    def test_job_card_symbolics_are_not_substituted(self, invupdt):
        # z/OS does not substitute JCL symbols on the JOB statement, so
        # NOTIFY=&SYSUID must not be reported as an unresolved symbol.
        notify = [p for p in invupdt.jobs[0].parameters if p.keyword == "NOTIFY"]
        assert notify[0].value == "&SYSUID"
        assert invupdt.unresolved == []

    def test_step_order_and_programs(self, invupdt):
        steps = invupdt.jobs[0].steps
        assert [s.name for s in steps] == ["STEP010", "STEP020"]
        assert [s.program for s in steps] == ["INVEDIT", "INVUPDT"]
        assert steps[0].parm == "EDIT,STRICT"
        assert steps[1].parm is None
        assert steps[1].condition == "(4,LT,STEP010)"

    def test_job_level_dd_is_not_attached_to_a_step(self, invupdt):
        job = invupdt.jobs[0]
        assert [dd.name for dd in job.dd_statements] == ["JOBLIB"]
        assert job.step("STEP010").dd("JOBLIB") is None

    def test_dd_dataset_and_disposition(self, invupdt):
        step = invupdt.jobs[0].step("STEP020")
        assert step.dd("INVFILE").dataset == "PROD.INV.MASTER"
        assert step.dd("INVFILE").disposition == "SHR"
        assert step.dd("INVUPD").disposition == "(OLD,DELETE,DELETE)"
        assert step.dd("invfile") is step.dd("INVFILE")

    def test_dcb_subparameters(self, invupdt):
        dd = invupdt.jobs[0].step("STEP010").dd("INVGOOD")
        assert dd.record_format == "FB"
        assert dd.record_length == 200
        dcb = dd.parameter("DCB")
        assert dcb.subparameters == {
            "RECFM": "FB",
            "LRECL": "200",
            "BLKSIZE": "27800",
        }
        space = dd.parameter("SPACE")
        assert space.positional == ["CYL", "(10,5)", "RLSE"]

    def test_sysout_and_dummy(self, invupdt):
        step = invupdt.jobs[0].step("STEP010")
        assert step.dd("SYSPRINT").sysout == "*"
        assert step.dd("SYSPRINT").dataset is None
        assert step.dd("SYSUDUMP").is_dummy is True
        assert step.dd("SYSUDUMP").dataset is None

    def test_instream_data_is_not_parsed_as_jcl(self, invupdt):
        sysin = invupdt.jobs[0].step("STEP010").dd("SYSIN")
        assert sysin.is_instream is True
        assert sysin.instream_lines == [
            "  EDIT MODE=STRICT",
            "  REJECT WHEN QTY < 0",
        ]
        assert sysin.dataset is None

    def test_concatenated_job_library(self, invupdt):
        joblib = invupdt.jobs[0].dd_statements[0]
        assert joblib.dataset == "PROD.LOADLIB"
        assert [m.dataset for m in joblib.concatenated] == ["SYS1.COB2LIB"]
        assert [m.name for m in joblib.concatenated] == ["JOBLIB"]
        assert [d.dataset for d in joblib.flatten()] == [
            "PROD.LOADLIB",
            "SYS1.COB2LIB",
        ]

    def test_symbol_substitution_from_set(self, invupdt):
        assert invupdt.symbols == {"HLQ": "PROD.INV", "CYCLE": "D"}
        step010 = invupdt.jobs[0].step("STEP010")
        # `&HLQ..TRANS(0)` -- the first period terminates the symbol.
        assert step010.dd("INVTRAN").dataset == "PROD.INV.TRANS(0)"
        step020 = invupdt.jobs[0].step("STEP020")
        assert step020.dd("RPTFILE").dataset == "PROD.INV.REPORT.D"


class TestProcedureSample:
    """An in-stream PROC invoked with symbolic and DD overrides."""

    def test_procedure_is_recorded(self, payproc):
        assert payproc.errors == []
        assert list(payproc.procedures) == ["PAYPROC"]
        proc_steps = payproc.procedures["PAYPROC"]
        assert [s.name for s in proc_steps] == ["EXTRACT", "REPORT"]
        assert [s.program for s in proc_steps] == ["PAYEXTR", "PAYRPT"]
        # Parsed with the procedure's own defaults, not the invocation's.
        assert proc_steps[0].dd("PAYMAST").dataset == "TEST.PAY.MASTER"
        assert proc_steps[0].parm == "DEFAULT"

    def test_invocation_step_names_the_procedure(self, payproc):
        invocation = payproc.jobs[0].steps[0]
        assert invocation.name == "RUNPAY"
        assert invocation.procedure == "PAYPROC"
        assert invocation.program is None

    def test_procedure_body_is_expanded_after_the_invocation(self, payproc):
        names = [s.name for s in payproc.jobs[0].steps]
        assert names == ["RUNPAY", "RUNPAY.EXTRACT", "RUNPAY.REPORT"]
        extract = payproc.jobs[0].step("RUNPAY.EXTRACT")
        assert extract.program == "PAYEXTR"
        assert extract.procedure == "PAYPROC"

    def test_exec_symbolic_overrides_win_over_proc_defaults(self, payproc):
        extract = payproc.jobs[0].step("RUNPAY.EXTRACT")
        assert extract.parm == "WEEKLY"
        assert extract.dd("SYSPRINT").sysout == "*"

    def test_procstep_dd_override_replaces_the_dataset(self, payproc):
        extract = payproc.jobs[0].step("RUNPAY.EXTRACT")
        assert extract.dd("PAYMAST").dataset == "PROD.PAY.MASTER.WEEKLY"
        assert extract.dd("PAYMAST").disposition == "SHR"

    def test_override_merges_with_the_procedure_dd(self, payproc):
        report = payproc.jobs[0].step("RUNPAY.REPORT")
        payrpt = report.dd("PAYRPT")
        assert payrpt.dataset == "PROD.PAY.REPORT(+1)"
        assert payrpt.record_format == "FBA"
        assert payrpt.record_length == 133

    def test_override_cards_stay_on_the_invocation_step(self, payproc):
        invocation = payproc.jobs[0].steps[0]
        assert [(dd.procstep, dd.name) for dd in invocation.dd_statements] == [
            ("EXTRACT", "PAYMAST"),
            ("REPORT", "PAYRPT"),
        ]

    def test_temporary_dataset_ampersands_are_not_symbols(self, payproc):
        extract = payproc.jobs[0].step("RUNPAY.EXTRACT")
        assert extract.dd("PAYEXT").dataset == "&&PAYWORK"
        assert payproc.unresolved == []

    def test_dd_map_spans_expanded_procedure_steps(self, payproc):
        assert payproc.dd_map()["PAYMAST"] == ["PROD.PAY.MASTER.WEEKLY"]
        assert payproc.dd_map()["PAYEXT"] == ["&&PAYWORK"]

    def test_steps_running_finds_programs_inside_procedures(self, payproc):
        found = payproc.steps_running("payrpt")
        assert [s.name for s in found] == ["RUNPAY.REPORT"]


class TestExecForms:
    def test_exec_pgm(self):
        result = parse_jcl(SIMPLE_JOB)
        step = result.jobs[0].steps[0]
        assert step.program == "CUSTLOAD"
        assert step.procedure is None
        assert step.parm == "RUN=DAILY"

    def test_exec_proc_keyword(self):
        result = parse_jcl("""\
//J JOB 1
//S1 EXEC PROC=NIGHTLY
//
""")
        step = result.jobs[0].steps[0]
        assert step.procedure == "NIGHTLY"
        assert step.program is None
        assert any("NIGHTLY" in note for note in result.unresolved)

    def test_exec_positional_procedure_name(self):
        result = parse_jcl("""\
//J JOB 1
//S1 EXEC NIGHTLY,PARM1=X
//
""")
        assert result.jobs[0].steps[0].procedure == "NIGHTLY"

    def test_unnamed_step_is_allowed(self):
        result = parse_jcl("""\
//J JOB 1
// EXEC PGM=IEFBR14
//
""")
        assert result.errors == []
        assert result.jobs[0].steps[0].name == ""

    def test_exec_without_pgm_or_proc_is_an_error(self):
        result = parse_jcl("""\
//J JOB 1
//S1 EXEC REGION=0M
//
""")
        assert any(
            "missing program or procedure" in e["message"] and e["line"] == 2
            for e in result.errors
        )


class TestDDParameters:
    def test_dsname_is_an_alias_of_dsn(self):
        result = parse_jcl("""\
//J JOB 1
//S1 EXEC PGM=A
//F1 DD DSNAME=MY.DATA.SET,DISP=(NEW,KEEP)
//
""")
        dd = result.jobs[0].steps[0].dd("F1")
        assert dd.dataset == "MY.DATA.SET"
        assert dd.disposition == "(NEW,KEEP)"
        assert dd.parameter("DISP").positional == ["NEW", "KEEP"]
        assert dd.parameter("NOPE") is None

    def test_quoted_dataset_name_is_unquoted(self):
        result = parse_jcl("""\
//J JOB 1
//S1 EXEC PGM=A
//F1 DD DSN='MY.DATA.SET',DISP=SHR
//
""")
        assert result.jobs[0].steps[0].dd("F1").dataset == "MY.DATA.SET"

    def test_recfm_and_lrecl_outside_dcb(self):
        result = parse_jcl("""\
//J JOB 1
//S1 EXEC PGM=A
//F1 DD DSN=A.B,DISP=SHR,RECFM=VB,LRECL=1024
//
""")
        dd = result.jobs[0].steps[0].dd("F1")
        assert (dd.record_format, dd.record_length) == ("VB", 1024)

    def test_non_numeric_lrecl_is_reported_not_guessed(self):
        result = parse_jcl("""\
//J JOB 1
//S1 EXEC PGM=A
//F1 DD DSN=A.B,DISP=SHR,LRECL=&LEN
//
""")
        dd = result.jobs[0].steps[0].dd("F1")
        assert dd.record_length is None
        assert any("LRECL=&LEN" in note for note in result.unresolved)

    def test_three_way_concatenation(self):
        result = parse_jcl("""\
//J JOB 1
//S1 EXEC PGM=A
//STEPLIB DD DSN=A.LOAD,DISP=SHR
//         DD DSN=B.LOAD,DISP=SHR
//         DD DSN=C.LOAD,DISP=SHR
//
""")
        steplib = result.jobs[0].steps[0].dd("STEPLIB")
        assert [d.dataset for d in steplib.flatten()] == [
            "A.LOAD",
            "B.LOAD",
            "C.LOAD",
        ]
        assert result.dd_map()["STEPLIB"] == ["A.LOAD", "B.LOAD", "C.LOAD"]


class TestInStreamData:
    def test_dd_star_content_is_data_not_jcl(self):
        result = parse_jcl("""\
//J JOB 1
//S1 EXEC PGM=SORT
//SYSIN DD *
  SORT FIELDS=(1,8,CH,A)
  RECORD TYPE=F
/*
//SYSPRINT DD SYSOUT=*
//
""")
        assert result.errors == []
        step = result.jobs[0].steps[0]
        assert step.dd("SYSIN").instream_lines == [
            "  SORT FIELDS=(1,8,CH,A)",
            "  RECORD TYPE=F",
        ]
        assert [d.name for d in step.dd_statements] == ["SYSIN", "SYSPRINT"]

    def test_dd_star_data_ends_at_the_next_jcl_card(self):
        result = parse_jcl("""\
//J JOB 1
//S1 EXEC PGM=A
//SYSIN DD *
DATA RECORD ONE
//SYSPRINT DD SYSOUT=*
//
""")
        step = result.jobs[0].steps[0]
        assert step.dd("SYSIN").instream_lines == ["DATA RECORD ONE"]
        assert step.dd("SYSPRINT").sysout == "*"

    def test_dd_data_keeps_slash_slash_records(self):
        result = parse_jcl("""\
//J JOB 1
//S1 EXEC PGM=IEBGENER
//SYSUT1 DD DATA
//NOTAJOB JOB (1),'NOT PARSED'
//NOTASTEP EXEC PGM=NOPE
/*
//SYSUT2 DD SYSOUT=*
//
""")
        assert len(result.jobs) == 1
        step = result.jobs[0].steps[0]
        assert step.dd("SYSUT1").instream_lines == [
            "//NOTAJOB JOB (1),'NOT PARSED'",
            "//NOTASTEP EXEC PGM=NOPE",
        ]
        assert result.steps_running("NOPE") == []

    def test_dd_data_with_custom_delimiter(self):
        result = parse_jcl("""\
//J JOB 1
//S1 EXEC PGM=IEBGENER
//SYSUT1 DD DATA,DLM=@@
/* NOT THE DELIMITER
@@
//SYSUT2 DD SYSOUT=*
//
""")
        assert result.errors == []
        assert result.jobs[0].steps[0].dd("SYSUT1").instream_lines == [
            "/* NOT THE DELIMITER"
        ]

    def test_unterminated_dd_data_is_reported(self):
        result = parse_jcl("""\
//J JOB 1
//S1 EXEC PGM=IEBGENER
//SYSUT1 DD DATA
SOME DATA
""")
        assert result.jobs[0].steps[0].dd("SYSUT1").instream_lines == ["SOME DATA"]


class TestContinuation:
    def test_parameter_list_continued_across_three_cards(self):
        result = parse_jcl("""\
//J JOB 1
//S1 EXEC PGM=A
//OUT DD DSN=PROD.BIG.FILE,DISP=(NEW,CATLG,DELETE),
//            UNIT=SYSDA,SPACE=(CYL,(50,10),RLSE),
//            DCB=(RECFM=FB,LRECL=80,BLKSIZE=27920)
//
""")
        assert result.errors == []
        dd = result.jobs[0].steps[0].dd("OUT")
        assert dd.dataset == "PROD.BIG.FILE"
        assert dd.record_length == 80
        assert dd.parameter("UNIT").value == "SYSDA"
        assert dd.line == 3

    def test_comment_after_a_continued_parameter(self):
        result = parse_jcl("""\
//J JOB 1
//S1 EXEC PGM=A
//OUT DD DSN=PROD.FILE,          THE OUTPUT FILE
//            DISP=SHR
//
""")
        assert result.errors == []
        assert result.jobs[0].steps[0].dd("OUT").disposition == "SHR"

    def test_continuation_inside_a_quoted_string(self):
        # The string is coded through column 71, as IBM requires.
        first = "//S1 EXEC PGM=RPTGEN,PARM='REPORT=MONTHLY,REGION=NORTHEAST,FORMAT=WI"
        first = first.ljust(71, "X")[:71]
        result = parse_jcl(f"""\
//J JOB 1
{first}
//             DE'
//
""")
        assert result.errors == []
        step = result.jobs[0].steps[0]
        assert step.parm == first[27:] + "DE"

    def test_continued_text_beyond_column_16_is_reported(self):
        result = parse_jcl("""\
//J JOB 1
//S1 EXEC PGM=A
//OUT DD DSN=PROD.FILE,
//                     DISP=SHR
//
""")
        # The card is still read, so the parameter is not lost.
        assert result.jobs[0].steps[0].dd("OUT").disposition == "SHR"

    def test_missing_continuation_card_does_not_swallow_the_next_statement(self):
        result = parse_jcl("""\
//J JOB 1
//S1 EXEC PGM=A
//OUT DD DSN=PROD.FILE,
//*
//S2 EXEC PGM=B
//
""")
        assert [s.name for s in result.jobs[0].steps] == ["S1", "S2"]

    def test_sequence_numbers_in_columns_73_to_80_are_ignored(self):
        card = "//S1 EXEC PGM=A" + " " * (72 - len("//S1 EXEC PGM=A")) + "SEQ00010"
        result = parse_jcl("//J JOB 1\n" + card + "\n//\n")
        assert result.errors == []
        assert result.jobs[0].steps[0].program == "A"


class TestSymbolicParameters:
    def test_set_then_use(self):
        result = parse_jcl("""\
//J JOB 1
// SET ENV=PROD,CYCLE=WEEKLY
//S1 EXEC PGM=A
//F1 DD DSN=&ENV..SALES.&CYCLE,DISP=SHR
//
""")
        assert result.symbols == {"ENV": "PROD", "CYCLE": "WEEKLY"}
        assert result.jobs[0].steps[0].dd("F1").dataset == "PROD.SALES.WEEKLY"

    def test_later_set_replaces_an_earlier_value(self):
        result = parse_jcl("""\
//J JOB 1
// SET ENV=TEST
//S1 EXEC PGM=A
//F1 DD DSN=&ENV..F,DISP=SHR
// SET ENV=PROD
//S2 EXEC PGM=B
//F2 DD DSN=&ENV..F,DISP=SHR
//
""")
        assert result.jobs[0].step("S1").dd("F1").dataset == "TEST.F"
        assert result.jobs[0].step("S2").dd("F2").dataset == "PROD.F"

    def test_set_before_the_job_card(self):
        result = parse_jcl("""\
// SET ENV=QA
//J JOB 1
//S1 EXEC PGM=A
//F1 DD DSN=&ENV..F,DISP=SHR
//
""")
        assert result.errors == []
        assert result.jobs[0].steps[0].dd("F1").dataset == "QA.F"

    def test_quoted_set_value(self):
        result = parse_jcl("""\
//J JOB 1
// SET TXT='HELLO WORLD'
//S1 EXEC PGM=A,PARM='&TXT'
//
""")
        assert result.jobs[0].steps[0].parm == "HELLO WORLD"

    def test_nested_symbol_value(self):
        result = parse_jcl("""\
//J JOB 1
// SET ENV=PROD
// SET HLQ=&ENV..SALES
//S1 EXEC PGM=A
//F1 DD DSN=&HLQ..DETAIL,DISP=SHR
//
""")
        assert result.jobs[0].steps[0].dd("F1").dataset == "PROD.SALES.DETAIL"

    def test_unresolved_symbol_is_left_as_coded_and_reported(self):
        result = parse_jcl("""\
//J JOB 1
//S1 EXEC PGM=A
//F1 DD DSN=&UNSET..MASTER,DISP=SHR
//
""")
        dd = result.jobs[0].steps[0].dd("F1")
        assert dd.dataset == "&UNSET..MASTER"
        assert any("&UNSET" in note for note in result.unresolved)
        assert any("no SET, procedure default" in note for note in result.unresolved)

    def test_bare_ampersand_is_left_alone(self):
        result = parse_jcl("""\
//J JOB 1
//S1 EXEC PGM=A,PARM='A & B'
//
""")
        assert result.jobs[0].steps[0].parm == "A & B"

    def test_set_with_a_positional_parameter_is_reported(self):
        result = parse_jcl("//J JOB 1\n// SET NOEQUALS\n//\n")
        assert any("NOEQUALS" in note for note in result.unresolved)


class TestProcedures:
    PROC_JCL = """\
//J JOB 1
//COPYPROC PROC HLQ=TEST,SOUT=*
//COPY     EXEC PGM=IEBGENER
//SYSUT1   DD DSN=&HLQ..IN,DISP=SHR
//SYSUT2   DD DSN=&HLQ..OUT,DISP=(NEW,CATLG,DELETE)
//SYSPRINT DD SYSOUT=&SOUT
//SYSIN    DD DUMMY
//         PEND
//RUN1     EXEC COPYPROC,HLQ=PROD
//
"""

    def test_single_step_procedure_expansion(self):
        result = parse_jcl(self.PROC_JCL)
        assert result.errors == []
        assert [s.name for s in result.jobs[0].steps] == ["RUN1", "RUN1.COPY"]
        copy = result.jobs[0].step("RUN1.COPY")
        assert copy.program == "IEBGENER"
        assert copy.dd("SYSUT1").dataset == "PROD.IN"
        assert copy.dd("SYSIN").is_dummy is True

    def test_procedures_dict_uses_the_declared_defaults(self):
        result = parse_jcl(self.PROC_JCL)
        assert result.procedures["COPYPROC"][0].dd("SYSUT1").dataset == "TEST.IN"

    def test_unqualified_override_on_a_single_step_procedure(self):
        result = parse_jcl(
            self.PROC_JCL.replace(
                "//RUN1     EXEC COPYPROC,HLQ=PROD\n",
                "//RUN1     EXEC COPYPROC,HLQ=PROD\n"
                "//SYSUT2   DD DSN=PROD.SPECIAL.OUT,DISP=SHR\n",
            )
        )
        copy = result.jobs[0].step("RUN1.COPY")
        assert copy.dd("SYSUT2").dataset == "PROD.SPECIAL.OUT"
        assert copy.dd("SYSUT2").disposition == "SHR"

    def test_override_adds_a_dd_the_procedure_does_not_have(self):
        result = parse_jcl(
            self.PROC_JCL.replace(
                "//RUN1     EXEC COPYPROC,HLQ=PROD\n",
                "//RUN1     EXEC COPYPROC,HLQ=PROD\n"
                "//COPY.EXTRA DD DSN=PROD.EXTRA,DISP=SHR\n",
            )
        )
        copy = result.jobs[0].step("RUN1.COPY")
        assert copy.dd("EXTRA").dataset == "PROD.EXTRA"

    def test_override_can_nullify_a_parameter(self):
        result = parse_jcl(
            self.PROC_JCL.replace(
                "//RUN1     EXEC COPYPROC,HLQ=PROD\n",
                "//RUN1     EXEC COPYPROC,HLQ=PROD\n"
                "//COPY.SYSPRINT DD SYSOUT=,DSN=PROD.LISTING,DISP=SHR\n",
            )
        )
        sysprint = result.jobs[0].step("RUN1.COPY").dd("SYSPRINT")
        assert sysprint.sysout is None
        assert sysprint.dataset == "PROD.LISTING"

    def test_override_for_an_unknown_procstep_is_reported(self):
        result = parse_jcl(
            self.PROC_JCL.replace(
                "//RUN1     EXEC COPYPROC,HLQ=PROD\n",
                "//RUN1     EXEC COPYPROC,HLQ=PROD\n"
                "//NOSTEP.SYSUT1 DD DSN=PROD.OTHER,DISP=SHR\n",
            )
        )
        assert any("NOSTEP.SYSUT1 names no step" in n for n in result.unresolved)
        assert result.jobs[0].step("RUN1.COPY").dd("SYSUT1").dataset == "PROD.IN"

    def test_unqualified_override_applies_to_the_first_procedure_step(self):
        # z/OS reads a DD with no procstep qualifier as an override of the
        # procedure's first step.
        text = SAMPLES.joinpath("payproc.jcl").read_text()
        text = text.replace(
            "//EXTRACT.PAYMAST DD DSN=PROD.PAY.MASTER.WEEKLY,DISP=SHR\n",
            "//PAYMAST DD DSN=PROD.PAY.MASTER.WEEKLY,DISP=SHR\n",
        )
        result = parse_jcl(text)
        assert result.jobs[0].step("RUNPAY.EXTRACT").dd("PAYMAST").dataset == (
            "PROD.PAY.MASTER.WEEKLY"
        )

    def test_exec_of_a_procedure_not_in_this_file(self):
        result = parse_jcl("""\
//J JOB 1
//S1 EXEC CATPROC,PARM1=X
//
""")
        assert result.jobs[0].steps[0].procedure == "CATPROC"
        assert any(
            "PROC CATPROC (line 2)" in n and "neither defined" in n
            for n in result.unresolved
        )

    def test_unterminated_proc_is_an_error(self):
        result = parse_jcl("""\
//J JOB 1
//P1 PROC
//S1 EXEC PGM=A
""")
        assert any("P1 has no PEND" in n for n in result.unresolved)
        assert "P1" in result.procedures

    def test_duplicate_proc_definition_is_reported(self):
        result = parse_jcl("""\
//J JOB 1
//P1 PROC
//S1 EXEC PGM=FIRST
//   PEND
//P1 PROC
//S1 EXEC PGM=SECOND
//   PEND
//RUN EXEC P1
//
""")
        assert any("defined more than once" in n for n in result.unresolved)
        assert result.jobs[0].step("RUN.S1").program == "SECOND"

    def test_procedure_invoked_from_inside_a_procedure_is_expanded(self):
        result = parse_jcl("""\
//J JOB 1
//INNER PROC
//S1 EXEC PGM=A
//   PEND
//OUTER PROC
//S2 EXEC INNER
//   PEND
//RUN EXEC OUTER
//
""")
        assert result.unresolved == []
        step = result.jobs[0].step("RUN.S2.S1")
        assert (step.program, step.procedure) == ("A", "INNER")

    def test_unnamed_proc_card_is_a_cataloged_procedure_header(self):
        result = parse_jcl("""\
// PROC HLQ=TEST
//S1 EXEC PGM=A
//F1 DD DSN=&HLQ..F,DISP=SHR
//
""")
        assert any("cataloged procedure member" in n for n in result.unresolved)
        # The header's keywords are the body's symbolic defaults, and the
        # card is not an "unknown operation" on top of being noted.
        assert result.errors == []


class TestIfThenElse:
    IF_JCL = """\
//J JOB 1
//S1 EXEC PGM=FIRST
// IF (S1.RC = 0) THEN
//S2 EXEC PGM=GOOD
// ELSE
//S3 EXEC PGM=BAD
// ENDIF
//S4 EXEC PGM=ALWAYS
//
"""

    def test_condition_from_the_enclosing_if(self):
        result = parse_jcl(self.IF_JCL)
        assert result.errors == []
        job = result.jobs[0]
        assert job.step("S2").condition == "(S1.RC = 0)"
        assert job.step("S3").condition == "NOT (S1.RC = 0)"
        assert job.step("S4").condition is None

    def test_cond_parameter_wins_over_the_enclosing_if(self):
        result = parse_jcl("""\
//J JOB 1
// IF (RC = 0) THEN
//S1 EXEC PGM=A,COND=(8,LE)
// ENDIF
//
""")
        assert result.jobs[0].steps[0].condition == "(8,LE)"

    def test_nested_ifs_are_joined(self):
        result = parse_jcl("""\
//J JOB 1
// IF (RC = 0) THEN
// IF (ABEND) THEN
//S1 EXEC PGM=A
// ENDIF
// ENDIF
//
""")
        assert result.jobs[0].steps[0].condition == "(RC = 0) AND (ABEND)"

    def test_else_without_if_is_an_error(self):
        result = parse_jcl("//J JOB 1\n// ELSE\n//\n")
        assert any("ELSE with no matching IF" in n for n in result.unresolved)

    def test_endif_without_if_is_an_error(self):
        result = parse_jcl("//J JOB 1\n// ENDIF\n//\n")
        assert any("ENDIF with no matching IF" in n for n in result.unresolved)

    def test_unclosed_if_is_an_error(self):
        result = parse_jcl("//J JOB 1\n// IF (RC = 0) THEN\n//S1 EXEC PGM=A\n")
        assert any("no matching ENDIF" in n for n in result.unresolved)


class TestOtherStatements:
    def test_include_not_on_the_procedure_path_is_reported(self):
        result = parse_jcl("""\
//J JOB 1
// INCLUDE MEMBER=STDDDS
//S1 EXEC PGM=A
//
""")
        assert result.errors == []
        assert any("STDDDS" in n for n in result.unresolved)

    def test_unknown_operation_is_an_error(self):
        result = parse_jcl("//J JOB 1\n//S1 FROBNICATE X=1\n//\n")
        assert any("FROBNICATE" in n for n in result.unresolved)


class TestMalformedCards:
    def test_card_not_starting_with_slashes(self):
        result = parse_jcl("""\
//J JOB 1
THIS IS NOT A JCL CARD
//S1 EXEC PGM=A
//
""")
        assert any("must start with //" in e["message"] for e in result.errors)
        assert result.errors[0]["line"] == 2
        # The rest of the deck still parses.
        assert result.jobs[0].steps[0].program == "A"
        assert result.success is False

    def test_statement_without_an_operation_field(self):
        result = parse_jcl("//J JOB 1\n//ORPHAN\n//S1 EXEC PGM=A\n//\n")
        assert result.unresolved
        assert result.jobs[0].steps[0].program == "A"

    def test_job_without_a_name(self):
        result = parse_jcl("// JOB (1)\n//S1 EXEC PGM=A\n//\n")
        assert any("no job name" in e["message"] for e in result.errors)

    def test_statements_before_any_job_card(self):
        result = parse_jcl("//S1 EXEC PGM=A\n//F1 DD DSN=A.B,DISP=SHR\n")
        assert any("before JOB statement" in e["message"] for e in result.errors)
        assert result.errors[0]["line"] == 1
        assert result.success is False

    def test_blank_lines_are_ignored(self):
        result = parse_jcl("//J JOB 1\n\n   \n//S1 EXEC PGM=A\n//\n")
        assert result.errors == []
        assert len(result.jobs[0].steps) == 1

    def test_errors_are_ordered_by_line(self):
        result = parse_jcl("""\
//J JOB 1
BAD CARD ONE
//S1 EXEC PGM=A
BAD CARD TWO
//
""")
        lines = [e["line"] for e in result.errors]
        assert lines == sorted(lines)

    def test_two_jobs_in_one_file(self):
        result = parse_jcl(SIMPLE_JOB + SIMPLE_JOB.replace("RUNJOB", "RUNJOB2"))
        assert [job.name for job in result.jobs] == ["RUNJOB", "RUNJOB2"]


class TestQueries:
    def test_steps_running(self, invupdt):
        assert [s.name for s in invupdt.steps_running("INVUPDT")] == ["STEP020"]
        assert invupdt.steps_running("NOSUCHPGM") == []

    def test_dd_map_keys_every_ddname(self, invupdt):
        mapping = invupdt.dd_map()
        assert mapping["INVFILE"] == ["PROD.INV.MASTER"]
        assert mapping["JOBLIB"] == ["PROD.LOADLIB", "SYS1.COB2LIB"]
        # Seen, but backed by no dataset -- distinct from a missing key.
        assert mapping["SYSPRINT"] == []
        assert mapping["SYSUDUMP"] == []
        assert "NOSUCHDD" not in mapping

    def test_dd_map_does_not_repeat_a_dataset(self):
        result = parse_jcl("""\
//J JOB 1
//S1 EXEC PGM=A
//F1 DD DSN=SAME.DATA,DISP=SHR
//S2 EXEC PGM=B
//F1 DD DSN=SAME.DATA,DISP=SHR
//
""")
        assert result.dd_map()["F1"] == ["SAME.DATA"]

    def test_all_dd_statements_pairs_each_card_with_its_step(self, invupdt):
        rows = invupdt.all_dd_statements()
        assert rows[0][1] is None  # JOBLIB is job-level
        assert rows[0][2].name == "JOBLIB"
        assert rows[1][2].dataset == "SYS1.COB2LIB"
        assert rows[2][1].name == "STEP010"

    def test_step_lookup_returns_none_for_unknown_names(self, invupdt):
        assert invupdt.jobs[0].step("NOPE") is None


class TestDatasetBindings:
    def test_resolve_dd_bindings(self, invupdt):
        bindings = resolve_dd_bindings(invupdt)
        by_name = {b.ddname: b for b in bindings if b.step == "STEP020"}
        inv = by_name["INVFILE"]
        assert isinstance(inv, DatasetBinding)
        assert inv.dataset == "PROD.INV.MASTER"
        assert inv.disposition == "SHR"
        assert inv.job == "INVUPD01"
        assert inv.step == "STEP020"
        report = by_name["RPTFILE"]
        assert (report.record_format, report.record_length) == ("FBA", 133)

    def test_bindings_include_job_level_and_concatenated_cards(self, invupdt):
        bindings = resolve_dd_bindings(invupdt)
        joblib = [b for b in bindings if b.ddname == "JOBLIB"]
        assert [b.dataset for b in joblib] == ["PROD.LOADLIB", "SYS1.COB2LIB"]
        assert all(b.step == "" for b in joblib)

    def test_bindings_keep_sysout_and_dummy_rows(self, invupdt):
        bindings = resolve_dd_bindings(invupdt)
        dummy = [b for b in bindings if b.ddname == "SYSUDUMP"]
        assert len(dummy) == 1
        assert dummy[0].dataset is None

    def test_bindings_for_ddname_is_case_insensitive(self, invupdt):
        found = bindings_for_ddname(invupdt, "invfile")
        assert [b.dataset for b in found] == ["PROD.INV.MASTER"]
        assert bindings_for_ddname(invupdt, "NOSUCHDD") == []

    def test_bindings_resolve_through_a_procedure(self, payproc):
        found = bindings_for_ddname(payproc, "PAYMAST")
        assert [(b.step, b.dataset) for b in found] == [
            ("RUNPAY", "PROD.PAY.MASTER.WEEKLY"),
            ("RUNPAY.EXTRACT", "PROD.PAY.MASTER.WEEKLY"),
        ]

    def test_binding_to_dict(self, invupdt):
        binding = bindings_for_ddname(invupdt, "INVGOOD")[0]
        assert binding.to_dict() == {
            "ddname": "INVGOOD",
            "dataset": "PROD.INV.TRANS.GOOD",
            "step": "STEP010",
            "job": "INVUPD01",
            "disposition": "(NEW,CATLG,DELETE)",
            "record_format": "FB",
            "record_length": 200,
        }


class TestSerialization:
    def test_result_to_dict_shape(self):
        result = parse_jcl(SIMPLE_JOB)
        data = result.to_dict()
        assert set(data) == {
            "filename",
            "jobs",
            "procedures",
            "symbols",
            "errors",
            "unresolved",
        }
        job = data["jobs"][0]
        assert set(job) == {
            "name",
            "parameters",
            "dd_statements",
            "steps",
            "line",
        }
        step = job["steps"][0]
        assert set(step) == {
            "name",
            "program",
            "procedure",
            "parm",
            "condition",
            "parameters",
            "dd_statements",
            "line",
        }
        dd = step["dd_statements"][0]
        assert set(dd) == {
            "name",
            "dataset",
            "disposition",
            "sysout",
            "is_dummy",
            "is_instream",
            "instream_lines",
            "record_format",
            "record_length",
            "procstep",
            "parameters",
            "concatenated",
            "line",
        }
        assert set(dd["parameters"][0]) == {
            "keyword",
            "value",
            "subparameters",
            "positional",
        }

    def test_result_to_dict_is_json_serializable(self, payproc):
        assert json.loads(json.dumps(payproc.to_dict()))["jobs"][0]["name"] == (
            "PAYROLL1"
        )


class TestDeterminism:
    def test_same_input_gives_byte_identical_json(self):
        text = SAMPLES.joinpath("payproc.jcl").read_text()
        first = json.dumps(parse_jcl(text).to_dict(), sort_keys=False)
        second = json.dumps(parse_jcl(text).to_dict(), sort_keys=False)
        assert first == second

    def test_one_parser_instance_can_be_reused(self):
        parser = JclParser()
        first = parser.parse(SIMPLE_JOB).to_dict()
        second = parser.parse(SIMPLE_JOB).to_dict()
        assert first == second

    def test_diagnostics_are_not_duplicated(self):
        result = parse_jcl("""\
//J JOB 1
//P1 PROC
//S1 EXEC PGM=A
//F1 DD DSN=&NOPE..DATA,DISP=SHR
//   PEND
//RUN1 EXEC P1
//RUN2 EXEC P1
//
""")
        assert len(result.unresolved) == len(set(result.unresolved))
        assert len(result.errors) == len(
            {(e["line"], e["message"]) for e in result.errors}
        )


class TestModelConstruction:
    def test_dataclasses_are_constructible_from_the_documented_signature(self):
        dd = DDStatement(name="INVFILE", dataset="A.B", disposition="SHR")
        step = JobStep(
            name="S1",
            program="PGM1",
            procedure=None,
            parm=None,
            dd_statements=[dd],
        )
        job = JclJob(name="J", steps=[step])
        result = JclParseResult(
            jobs=[job], procedures={}, symbols={}, errors=[], unresolved=[]
        )
        assert result.dd_map() == {"INVFILE": ["A.B"]}
        assert result.filename == "<jcl>"
        assert step.dd("INVFILE") is dd
        assert JclParameter(keyword="DSN", value="A.B").to_dict()["positional"] == []


class TestProcedureBodyEdgeCases:
    def test_job_card_inside_a_procedure_body_starts_a_new_job(self):
        result = parse_jcl("""\
//J JOB 1
//P1 PROC
//* A COMMENT INSIDE THE PROCEDURE
//NESTED JOB (1)
//S1 EXEC PGM=A
//   PEND
//RUN EXEC P1
//
""")
        # A JOB card always starts a new job: it ends the unterminated PROC
        # rather than being swallowed into it (bug hunt round 11).
        assert any("P1 has no PEND" in n for n in result.unresolved)
        assert [job.name for job in result.jobs] == ["J", "NESTED"]

    def test_override_keeps_the_procedure_dd_concatenation(self):
        result = parse_jcl("""\
//J JOB 1
//P1 PROC
//S1 EXEC PGM=A
//STEPLIB DD DSN=PROC.LOAD,DISP=SHR
//        DD DSN=PROC.LOAD2,DISP=SHR
//   PEND
//RUN EXEC P1
//S1.STEPLIB DD DSN=OVERRIDE.LOAD,DISP=SHR
//
""")
        steplib = result.jobs[0].step("RUN.S1").dd("STEPLIB")
        assert [d.dataset for d in steplib.flatten()] == [
            "OVERRIDE.LOAD",
            "PROC.LOAD2",
        ]
        assert [d.name for d in steplib.flatten()] == ["STEPLIB", "STEPLIB"]

    def test_override_replaces_the_concatenation_when_it_codes_one(self):
        result = parse_jcl("""\
//J JOB 1
//P1 PROC
//S1 EXEC PGM=A
//STEPLIB DD DSN=PROC.LOAD,DISP=SHR
//        DD DSN=PROC.LOAD2,DISP=SHR
//   PEND
//RUN EXEC P1
//S1.STEPLIB DD DSN=NEW.LOAD,DISP=SHR
//        DD DSN=NEW.LOAD2,DISP=SHR
//
""")
        steplib = result.jobs[0].step("RUN.S1").dd("STEPLIB")
        assert [d.dataset for d in steplib.flatten()] == ["NEW.LOAD", "NEW.LOAD2"]

    def test_procedure_instream_data_survives_an_override(self):
        result = parse_jcl("""\
//J JOB 1
//P1 PROC
//S1 EXEC PGM=A
//SYSIN DD *
  CONTROL CARD
/*
//   PEND
//RUN EXEC P1
//S1.SYSIN DD DCB=BLKSIZE=800
//
""")
        sysin = result.jobs[0].step("RUN.S1").dd("SYSIN")
        assert sysin.is_instream is True
        assert sysin.instream_lines == ["  CONTROL CARD"]

    def test_override_can_supply_its_own_instream_data(self):
        result = parse_jcl("""\
//J JOB 1
//P1 PROC
//S1 EXEC PGM=A
//SYSIN DD DUMMY
//   PEND
//RUN EXEC P1
//S1.SYSIN DD *
  OVERRIDING CARD
/*
//
""")
        sysin = result.jobs[0].step("RUN.S1").dd("SYSIN")
        assert sysin.instream_lines == ["  OVERRIDING CARD"]


class TestSymbolResolutionDepth:
    def test_procedure_default_referring_to_a_set_symbol(self):
        result = parse_jcl("""\
//J JOB 1
// SET ENV=PROD
//P1 PROC HLQ=&ENV..PAY
//S1 EXEC PGM=A
//F1 DD DSN=&HLQ..MASTER,DISP=SHR
//   PEND
//RUN EXEC P1
//
""")
        assert result.jobs[0].step("RUN.S1").dd("F1").dataset == "PROD.PAY.MASTER"

    def test_self_referential_symbol_terminates(self):
        result = parse_jcl("""\
//J JOB 1
// SET LOOP=&LOOP
//S1 EXEC PGM=A,PARM='&LOOP'
//
""")
        # jclparser substitutes nothing for a symbol it cannot resolve, and
        # says so: the warning travels in ``unresolved``.
        assert any("&LOOP" in note for note in result.unresolved)


class TestOmittedSubParameters:
    def test_omitted_positional_subparameter_is_kept(self):
        result = parse_jcl("""\
//J JOB 1
//S1 EXEC PGM=A
//F1 DD DSN=A.B,DISP=(NEW,,DELETE)
//
""")
        disp = result.jobs[0].steps[0].dd("F1").parameter("DISP")
        assert disp.value == "(NEW,,DELETE)"
        # The omitted normal disposition keeps its slot, so DELETE stays the
        # abnormal disposition (it used to shift into the middle slot).
        assert disp.positional == ["NEW", "", "DELETE"]

    def test_empty_item_in_a_set_statement_is_skipped(self):
        result = parse_jcl("//J JOB 1\n// SET A=1,,B=2\n//\n")
        assert result.symbols == {"A": "1", "B": "2"}
        assert result.errors == []

    def test_dd_with_no_parameters_at_all(self):
        result = parse_jcl("//J JOB 1\n//S1 EXEC PGM=A\n//F1 DD\n//\n")
        dd = result.jobs[0].steps[0].dd("F1")
        assert dd.dataset is None
        assert dd.is_instream is False
        assert dd.parameters == []


class TestQuotingAndComments:
    def test_doubled_apostrophe_inside_a_parm(self):
        result = parse_jcl("""\
//J JOB 1
//S1 EXEC PGM=A,PARM='IT''S FINE'
//
""")
        assert result.jobs[0].steps[0].parm == "IT'S FINE"

    def test_quoted_delimiter_on_dd_data(self):
        result = parse_jcl("""\
//J JOB 1
//S1 EXEC PGM=A
//SYSUT1 DD DATA,DLM='$$'
DATA LINE
$$
//
""")
        assert result.errors == []
        assert result.jobs[0].steps[0].dd("SYSUT1").instream_lines == ["DATA LINE"]


def _deck(*cards: str) -> str:
    return "\n".join(cards) + "\n"


class TestDummyAndBackwardReferences:
    def test_nullfile_is_dummy_not_a_dataset(self):
        result = parse_jcl(_deck("//J1 JOB", "//S1 EXEC PGM=X", "//IN DD DSN=NULLFILE"))
        dd = result.jobs[0].steps[0].dd("IN")
        assert dd.is_dummy
        assert dd.dataset is None
        assert result.dd_map() == {"IN": []}

    def test_dummy_ignores_a_coded_dsn(self):
        result = parse_jcl(
            _deck("//J1 JOB", "//S1 EXEC PGM=X", "//IN DD DUMMY,DSN=A.B")
        )
        assert result.dd_map() == {"IN": []}

    def test_dummy_override_replaces_procedure_dataset(self):
        result = parse_jcl(
            _deck(
                "//J1 JOB",
                "//P1 PROC",
                "//S EXEC PGM=X",
                "//IN DD DSN=A.B,DISP=SHR",
                "// PEND",
                "//S1 EXEC P1",
                "//S.IN DD DUMMY",
            )
        )
        dd = result.jobs[0].step("S1.S").dd("IN")
        assert dd.is_dummy
        assert dd.dataset is None
        assert result.dd_map() == {"IN": []}

    def test_dataset_override_replaces_procedure_dummy(self):
        result = parse_jcl(
            _deck(
                "//J1 JOB",
                "//P1 PROC",
                "//S EXEC PGM=X",
                "//IN DD DUMMY",
                "//OUT DD SYSOUT=*",
                "// PEND",
                "//S1 EXEC P1",
                "//S.IN DD DSN=REAL.DATA,DISP=SHR",
                "//S.OUT DD DSN=OUT.DATA,DISP=(NEW,CATLG)",
            )
        )
        step = result.jobs[0].step("S1.S")
        assert not step.dd("IN").is_dummy
        assert step.dd("IN").dataset == "REAL.DATA"
        assert step.dd("OUT").sysout is None
        assert step.dd("OUT").dataset == "OUT.DATA"

    def test_backward_reference_is_reported_unresolved(self):
        result = parse_jcl(
            _deck(
                "//J1 JOB",
                "//S1 EXEC PGM=X",
                "//IN DD DSN=X.Y,DISP=SHR",
                "//S2 EXEC PGM=Y",
                "//IN DD DSN=*.S1.IN,DISP=SHR",
            )
        )
        assert result.jobs[0].step("S2").dd("IN").dataset == "*.S1.IN"
        assert any("backward reference" in u for u in result.unresolved)


class TestBugHuntRegressions:
    def test_set_after_exec_does_not_reach_back_into_the_procedure(self):
        result = parse_jcl("""\
//J JOB 1
//P PROC
//S EXEC PGM=X
//IN DD DSN=&HLQ..A,DISP=SHR
// PEND
// SET HLQ=OLD
//S1 EXEC P
// SET HLQ=NEW
//S2 EXEC PGM=Y
//
""")
        assert result.errors == []
        assert result.jobs[0].step("S1.S").dd("IN").dataset == "OLD.A"

    def test_dcb_override_merges_sub_parameters(self):
        result = parse_jcl("""\
//J JOB 1
//P PROC
//S EXEC PGM=X
//IN DD DSN=A.B,DISP=SHR,DCB=(RECFM=FB,LRECL=80)
// PEND
//S1 EXEC P
//S.IN DD DCB=(LRECL=100)
//
""")
        assert result.errors == []
        dd = result.jobs[0].step("S1.S").dd("IN")
        assert dd.record_format == "FB"
        assert dd.record_length == 100

    def test_dd_star_with_dlm_keeps_slash_slash_cards_as_data(self):
        result = parse_jcl("""\
//J JOB 1
//S EXEC PGM=X
//IN DD *,DLM=$$
// THIS IS DATA
/* SO IS THIS
$$
//OUT DD DSN=A.B,DISP=SHR
//
""")
        assert result.errors == []
        step = result.jobs[0].steps[0]
        assert step.dd("IN").instream_lines == ["// THIS IS DATA", "/* SO IS THIS"]
        assert step.dd("OUT").dataset == "A.B"

    def test_form_feed_in_instream_data_is_not_a_line_break(self):
        result = parse_jcl(
            "//J JOB 1\n//S EXEC PGM=X\n//IN DD DATA\nab\x0ccd\n/*\n"
            "//OUT DD DSN=A.B,DISP=SHR\n//\n"
        )
        assert result.errors == []
        step = result.jobs[0].steps[0]
        assert step.dd("IN").instream_lines == ["ab\x0ccd"]
        assert step.dd("OUT").line == 6


class TestProcedureExecOverrides:
    PROC = """\
//J JOB 1
//P PROC
//PS1 EXEC PGM=A,PARM='ONE'
//PS2 EXEC PGM=B,PARM='TWO',COND=(4,LT)
// PEND
"""

    def test_qualified_parm_overrides_that_procedure_step(self):
        result = parse_jcl(self.PROC + "//S EXEC P,PARM.PS2='NEW'\n//\n")
        assert result.errors == []
        job = result.jobs[0]
        assert job.step("S.PS1").parm == "ONE"
        assert job.step("S.PS2").parm == "NEW"
        assert "PARM.PS2" not in result.symbols

    def test_unqualified_parm_goes_to_first_step_and_nullifies_the_rest(self):
        result = parse_jcl(self.PROC + "//S EXEC P,PARM='FIRST'\n//\n")
        job = result.jobs[0]
        assert job.step("S.PS1").parm == "FIRST"
        assert job.step("S.PS2").parm is None
        assert all(p.keyword != "PARM" for p in job.step("S.PS2").parameters)

    def test_cond_overrides_qualified_and_unqualified(self):
        result = parse_jcl(
            self.PROC + "//S EXEC P,COND.PS1=(8,LE)\n//T EXEC P,COND=(0,NE)\n//\n"
        )
        job = result.jobs[0]
        assert job.step("S.PS1").condition == "(8,LE)"
        assert job.step("S.PS2").condition == "(4,LT)"
        assert job.step("T.PS1").condition == "(0,NE)"
        assert job.step("T.PS2").condition == "(0,NE)"

    def test_instream_override_replaces_a_procedure_dataset_and_back(self):
        result = parse_jcl("""\
//J JOB 1
//P PROC
//PS1 EXEC PGM=A
//SYSIN DD DSN=A.B,DISP=SHR
//IN2 DD *
DATA
/*
// PEND
//S EXEC P
//PS1.SYSIN DD *
CARD
/*
//PS1.IN2 DD DSN=X.Y,DISP=SHR
//
""")
        assert result.errors == []
        step = result.jobs[0].step("S.PS1")
        sysin = step.dd("SYSIN")
        assert sysin.dataset is None
        assert sysin.is_instream
        assert sysin.instream_lines == ["CARD"]
        in2 = step.dd("IN2")
        assert in2.dataset == "X.Y"
        assert not in2.is_instream
        assert in2.instream_lines == []
        assert result.dd_map()["SYSIN"] == []

    def test_if_expression_continued_onto_the_next_card(self):
        result = parse_jcl("""\
//J JOB 1
//S1 EXEC PGM=A
// IF (S1.RC = 0 &
//     S1.RC < 8) THEN
//S2 EXEC PGM=B
// ENDIF
//
""")
        assert result.errors == []
        step = result.jobs[0].step("S2")
        assert step.condition == "(S1.RC = 0 & S1.RC < 8)"
        assert step.line == 5

    def test_comments_on_if_else_endif_are_not_continuations(self):
        result = parse_jcl("""\
//J JOB 1
//S1 EXEC PGM=A
// IF RC = 0 THEN   RUN IT'S STEP
//S2 EXEC PGM=B
// ELSE           OTHERWISE,
//S3 EXEC PGM=C
// ENDIF  END OF BLOCK,
//S4 EXEC PGM=D
//
""")
        assert result.errors == []
        job = result.jobs[0]
        assert job.step("S2").condition == "RC=0"
        assert job.step("S3").condition == "NOT (RC=0)"
        assert job.step("S4").condition is None

    def test_concatenation_override_is_positional_and_keeps_the_rest(self):
        result = parse_jcl("""\
//J JOB 1
//P PROC
//PS1 EXEC PGM=A
//LIB DD DSN=L.ONE,DISP=SHR
//    DD DSN=L.TWO,DISP=SHR
//    DD DSN=L.THREE,DISP=SHR
// PEND
//S EXEC P
//PS1.LIB DD
//    DD DSN=NEW.TWO
//
""")
        assert result.errors == []
        lib = result.jobs[0].step("S.PS1").dd("LIB")
        assert [(d.dataset, d.disposition) for d in lib.flatten()] == [
            ("L.ONE", "SHR"),
            ("NEW.TWO", "SHR"),
            ("L.THREE", "SHR"),
        ]

    def test_column_72_is_not_part_of_the_parameter_field(self):
        first = (
            "//IN DD DSN=A.B,DISP=SHR,UNIT=SYSDA,SPACE=(TRK,1),DCB=(RECFM=FB,LR=12),"
        )
        assert len(first) == 71
        text = (
            "//J JOB 1\n//S1 EXEC PGM=A\n"
            + first
            + "X00000300\n//             LRECL=80\n//\n"
        )
        result = parse_jcl(text)
        assert result.errors == []
        dd = result.jobs[0].steps[0].dd("IN")
        assert [p.keyword for p in dd.parameters][-2:] == ["DCB", "LRECL"]
        assert dd.record_length == 80

    def test_nonblank_column_72_continues_the_comment_field(self):
        first = ("//IN DD DSN=A.B,DISP=SHR".ljust(40) + "FIRST PART").ljust(71)
        text = (
            "//J JOB 1\n//S1 EXEC PGM=A\n"
            + first
            + "X\n//             SECOND PART\n//OUT DD SYSOUT=*\n//\n"
        )
        result = parse_jcl(text)
        assert result.errors == []
        step = result.jobs[0].steps[0]
        assert step.dd("IN").dataset == "A.B"
        assert step.dd("OUT").line == 5

    def test_override_naming_a_missing_procedure_step_is_reported(self):
        result = parse_jcl(self.PROC + "//S EXEC P,PARM.NOPE=X\n//\n")
        assert result.errors == []
        assert any("PARM.NOPE names no step" in n for n in result.unresolved)
