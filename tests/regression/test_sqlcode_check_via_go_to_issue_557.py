"""Regression tests for issue #557: SQL_NO_SQLCODE_CHECK and ``GO TO``.

The search for a status-code check covered the statement's paragraph and the
paragraphs it PERFORMs, but not an unconditional ``GO TO`` straight after
the statement -- so "SQL statement, then GO TO the check paragraph" was
reported as never checked.
"""

from cobolparser import LintAnalyzer, parse_cobol
from cobolparser.analysis.sql_cics_lint import KIND_NO_SQLCODE_CHECK, SqlCicsAnalyzer

_HEAD = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-N PIC S9(9) COMP.
       01 WS-K PIC 9.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       PROCEDURE DIVISION.
"""


def _unchecked_lines(body: str) -> list[int]:
    result = parse_cobol(_HEAD + body)
    assert result.errors == []
    report = SqlCicsAnalyzer().analyze(result.ast)
    return [
        v.location.line for v in report.violations if v.kind == KIND_NO_SQLCODE_CHECK
    ]


def test_go_to_the_check_paragraph_counts_as_checked():
    body = """\
       MAIN-PARA.
           EXEC SQL SELECT C INTO :WS-N FROM T END-EXEC
           PERFORM CHK
           EXEC SQL SELECT C INTO :WS-N FROM T END-EXEC
           GO TO CHK.
       CHK.
           IF SQLCODE < 0 DISPLAY 'BAD' END-IF
           STOP RUN.
"""
    assert _unchecked_lines(body) == []
    result = parse_cobol(_HEAD + body)
    findings = LintAnalyzer(["sql-cics-check"]).analyze(result.ast).findings
    assert [f for f in findings if f.kind == KIND_NO_SQLCODE_CHECK] == []


def test_go_to_a_section_counts_as_checked():
    body = """\
       MAIN SECTION.
       M1.
           EXEC SQL SELECT C INTO :WS-N FROM T END-EXEC
           GO TO CHK-SEC.
       CHK-SEC SECTION.
       C1.
           IF SQLCODE < 0 DISPLAY 'BAD' END-IF
           STOP RUN.
"""
    assert _unchecked_lines(body) == []


def test_go_to_a_paragraph_that_runs_sql_first_is_still_reported():
    body = """\
       MAIN-PARA.
           EXEC SQL SELECT C INTO :WS-N FROM T END-EXEC
           GO TO NEXT-PARA.
       NEXT-PARA.
           EXEC SQL DELETE FROM T END-EXEC
           IF SQLCODE < 0 DISPLAY 'BAD' END-IF
           STOP RUN.
"""
    assert _unchecked_lines(body) == [10]


def test_go_to_depending_on_and_conditional_go_to_stay_conservative():
    body = """\
       MAIN-PARA.
           EXEC SQL SELECT C INTO :WS-N FROM T END-EXEC
           GO TO CHK OTHER-PARA DEPENDING ON WS-K
           EXEC SQL SELECT C INTO :WS-N FROM T END-EXEC
           IF WS-K = 1 GO TO CHK END-IF
           STOP RUN.
       OTHER-PARA.
           STOP RUN.
       CHK.
           IF SQLCODE < 0 DISPLAY 'BAD' END-IF
           STOP RUN.
"""
    assert _unchecked_lines(body) == [10, 12]


def test_go_to_cycle_terminates():
    body = """\
       A-PARA.
           EXEC SQL SELECT C INTO :WS-N FROM T END-EXEC
           GO TO B-PARA.
       B-PARA.
           GO TO A-PARA.
"""
    assert _unchecked_lines(body) == [10]
