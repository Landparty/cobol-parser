"""Regression tests for issue #530: null-indicator only for output host variables.

SQLCODE -305 happens only when DB2 returns a NULL into an *output* host
variable. ``dclgen-check`` (and ``lint``) warned on every host variable
bound to a nullable column with no indicator, including pure inputs
(INSERT VALUES, UPDATE SET, WHERE), where the missing indicator only means
the program cannot write NULL.
"""

from cobolparser import DclgenChecker, LintAnalyzer, parse_cobol

_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DCL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL DECLARE CUST TABLE
             ( CUST_ID     CHAR(6) NOT NULL,
               BAL         DECIMAL(9,2),
               UPD_TS      TIMESTAMP,
               MEMO        CHAR(10),
               CODE        CHAR(2),
               FLAG        CHAR(1),
               AMT         DECIMAL(9,2)
             ) END-EXEC.
       01 CUST-ID PIC X(6).
       01 BAL PIC S9(7)V99 COMP-3.
       01 UPD-TS PIC X(26).
       01 MEMO PIC X(10).
       01 CODE PIC X(2).
       01 FLAG PIC X(1).
       01 AMT PIC S9(7)V99 COMP-3.
       01 AMT-IND PIC S9(4) COMP.
       PROCEDURE DIVISION.
           EXEC SQL
             INSERT INTO CUST (CUST_ID, BAL, UPD_TS)
               VALUES (:CUST-ID, :BAL, :UPD-TS)
           END-EXEC
           EXEC SQL
             UPDATE CUST SET BAL = :BAL WHERE CUST_ID = :CUST-ID
           END-EXEC
           EXEC SQL
             SELECT MEMO, AMT INTO :MEMO, :AMT:AMT-IND
               FROM CUST WHERE CUST_ID = :CUST-ID
           END-EXEC
           EXEC SQL SET :CODE = CURRENT SQLID END-EXEC
           EXEC SQL CALL MYPROC (:FLAG) END-EXEC
           GOBACK.
"""


def _report():
    result = parse_cobol(_SOURCE)
    assert result.errors == []
    return result.ast, DclgenChecker().check(result.ast)


def _null_indicator_findings(report) -> set[str]:
    return {v.host_variable for v in report.violations if v.kind == "null-indicator"}


def test_inputs_need_no_indicator():
    _, report = _report()
    flagged = _null_indicator_findings(report)
    assert "BAL" not in flagged
    assert "UPD-TS" not in flagged


def test_outputs_without_indicator_still_warn():
    _, report = _report()
    # SELECT INTO and SET :hv = are outputs; AMT has its indicator.
    assert _null_indicator_findings(report) == {"MEMO", "CODE"}


def test_unknown_direction_is_reported_unchecked():
    _, report = _report()
    assert "FLAG" not in _null_indicator_findings(report)
    assert "FLAG" in report.unchecked
    assert "direction" in report.unchecked["FLAG"]


def test_lint_follows():
    ast, _ = _report()
    lint = LintAnalyzer(["dclgen-check"]).analyze(ast)
    flagged = {f.symbol for f in lint.findings if "SQLCODE -305" in f.message}
    assert flagged == {"MEMO", "CODE"}
