"""Regression tests from the 2026-11-12 CLI/MCP rerun over a private codebase:
the analysis and CLI half (the generator half is
``test_corpus_rerun_2026_11_12.py``).

* copybooks holding PROCEDURE DIVISION code drew "no PICTURE, sized 0 bytes"
  warnings from gen-data, decode and data-items, as if they were records;
* call-check reported a group declared around an unexpanded ``COPY`` (an MQ
  structure, say) as a zero-byte argument, a length error;
* ``le-info`` with several names failed outright on the first unknown one
  (a scan of the source had passed ``PIC``).
"""

from __future__ import annotations

import json
import sys

import pytest

from cobolparser.analysis.call_interface import CallInterfaceChecker
from cobolparser.analysis.program_signature import ProgramSignatureExtractor
from cobolparser.cli.parse import main as cli_main
from cobolparser.layout.copybook import (
    parse_copybook_records,
    procedure_code_start,
    wrap_copybook_fragment,
)
from cobolparser.layout.errors import CopybookLayoutError
from cobolparser.parser import parse_cobol

PROCEDURE_MEMBER = """\
       9000-ERROR-RTN.
           MOVE 8 TO RETURN-CODE
           PERFORM 9100-LOG.
       9000-EXIT.
           EXIT.
"""

STATEMENT_MEMBER = """\
      * shared error handling
           MOVE ZERO TO WS-COUNTER.
           DISPLAY 'DONE'.
"""

DCLGEN_MEMBER = """\
      ******************************************************************
           EXEC SQL DECLARE PROD.CUSTOMER TABLE
           ( CUST_ID                        CHAR(10) NOT NULL,
             CUST_NAME                      VARCHAR(40) NOT NULL
           ) END-EXEC.
       01  DCLCUSTOMER.
           10 CUST-ID              PIC X(10).
           10 CUST-NAME.
              49 CUST-NAME-LEN     PIC S9(4) USAGE COMP.
              49 CUST-NAME-TEXT    PIC X(40).
"""


def _run(argv: list[str]) -> int:
    saved = sys.argv
    sys.argv = ["cobol-parser", *argv]
    try:
        cli_main()
    except SystemExit as exc:
        return int(exc.code or 0)
    finally:
        sys.argv = saved
    return 0


class TestProcedureCopybooks:
    @pytest.mark.parametrize("member", [PROCEDURE_MEMBER, STATEMENT_MEMBER])
    def test_is_not_read_as_a_record(self, member):
        assert procedure_code_start(member) is not None
        assert wrap_copybook_fragment(member) is None
        with pytest.raises(CopybookLayoutError, match="PROCEDURE DIVISION code"):
            parse_copybook_records(member, filename="ERRRTN.cpy")

    @pytest.mark.parametrize(
        "member",
        [
            DCLGEN_MEMBER,
            "       01  REC.\n           05  A  PIC X.\n",
            "           05  ORPHAN  PIC X(4).\n",
            "       WORKING-STORAGE SECTION.\n       01  W  PIC X.\n",
            "       COPY OTHER.\n       01  W  PIC X.\n",
        ],
    )
    def test_data_members_still_parse(self, member):
        assert procedure_code_start(member) is None
        assert parse_copybook_records(member)

    def test_gen_data_names_the_problem(self, tmp_path, capsys):
        path = tmp_path / "ERRRTN.cpy"
        path.write_text(PROCEDURE_MEMBER)
        assert _run(["gen-data", str(path), "--rows", "1"]) != 0
        err = capsys.readouterr().err
        assert "PROCEDURE DIVISION code" in err
        assert "no PICTURE" not in err


CALLER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-GMO.
           COPY CMQGMOV.
       01  WS-PART.
           05  WS-PART-VER         PIC X(4).
           COPY CMQPMOV.
       01  WS-SHORT                PIC X(5).
       PROCEDURE DIVISION.
           CALL 'CALLEE' USING WS-GMO WS-PART WS-SHORT
           STOP RUN.
"""

CALLEE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLEE.
       DATA DIVISION.
       LINKAGE SECTION.
       01  LK-GMO.
           05 LK-GMO-DATA          PIC X(100).
       01  LK-PART.
           COPY LKPART.
       01  LK-SHORT                PIC X(10).
       PROCEDURE DIVISION USING LK-GMO LK-PART LK-SHORT.
           GOBACK.
"""


class TestCallCheckUnexpandedCopy:
    def _report(self):
        programs = [
            ("CALLER.cbl", parse_cobol(CALLER, filename="CALLER.cbl").ast),
            ("CALLEE.cbl", parse_cobol(CALLEE, filename="CALLEE.cbl").ast),
        ]
        return CallInterfaceChecker().check_programs(programs)

    def test_groups_missing_a_member_are_not_length_errors(self):
        report = self._report()
        flagged = {f.argument.text for f in report.findings if f.kind == "length"}
        assert "WS-GMO" not in flagged and "WS-PART" not in flagged
        notes = "\n".join(report.unchecked)
        assert "WS-GMO: its layout holds a COPY that was not expanded" in notes
        assert "WS-PART: its layout holds a COPY that was not expanded" in notes

    def test_a_complete_short_argument_is_still_an_error(self):
        report = self._report()
        errors = [f for f in report.findings if f.kind == "length"]
        assert [f.argument.text for f in errors] == ["WS-SHORT"]
        assert errors[0].severity == "error"

    def test_signature_leaves_the_length_out(self):
        unit = parse_cobol(CALLEE, filename="CALLEE.cbl").ast
        signature = ProgramSignatureExtractor().analyze(unit)
        lengths = {p.name: p.byte_length for p in signature.entry_points[0].parameters}
        assert lengths == {"LK-GMO": 100, "LK-PART": None, "LK-SHORT": 10}
        assert any("LK-PART" in note for note in signature.unchecked)


class TestLeInfoUnknownNames:
    def test_known_names_answered_beside_an_unknown_one(self, capsys):
        assert _run(["le-info", "CEEDAYS", "PIC", "--compact"]) == 0
        captured = capsys.readouterr()
        answer = json.loads(captured.out)
        assert [e["name"] for e in answer["entries"]] == ["CEEDAYS"]
        assert answer["unknown"] == ["PIC"]
        assert "reserved word" in captured.err

    def test_only_unknown_names_still_fail(self, capsys):
        assert _run(["le-info", "PIC"]) == 1
        assert "a COBOL reserved word" in capsys.readouterr().err
