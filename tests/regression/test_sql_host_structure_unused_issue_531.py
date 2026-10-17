"""Regression tests for issue #531: SQL host structures and VARCHAR groups.

DB2 reads or writes a group named as a host variable one column per
elementary field (a host structure), and a VARCHAR group through both of
its 49-level parts. ``unused-variables`` (and ``lint``) reported every one
of those fields unused -- advice that breaks the precompile or shifts the
column mapping -- and missed a host variable named only in a DECLARE CURSOR
written in WORKING-STORAGE.
"""

from cobolparser import LintAnalyzer, UnusedVariableAnalyzer, parse_cobol

_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HV.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL DECLARE C1 CURSOR FOR
               SELECT A FROM T WHERE K = :WS-KEY
           END-EXEC.
       01 WS-KEY.
          05 WS-KEY-A PIC X(3).
       01 HV.
          49 HV-LEN PIC S9(4) COMP.
          49 HV-TXT PIC X(30).
       01 HV2.
          05 HV2-A PIC X(3).
          05 HV2-B PIC X(3).
       01 HV2-IND.
          05 HV2-IND-A PIC S9(4) COMP.
          05 HV2-IND-B PIC S9(4) COMP.
       01 WS-GRP.
          05 WS-GRP-A PIC X.
       01 WS-UNUSED PIC X.
       PROCEDURE DIVISION.
           EXEC SQL SELECT NAME INTO :HV FROM T END-EXEC
           EXEC SQL SELECT A, B INTO :HV2:HV2-IND FROM T END-EXEC
           MOVE SPACES TO WS-GRP
           GOBACK.
"""


def _ast():
    result = parse_cobol(_SOURCE)
    assert result.errors == []
    return result.ast


def test_host_structure_varchar_and_indicator_fields_are_used():
    unused = {i.name for i in UnusedVariableAnalyzer().analyze(_ast()).unused_items}
    for name in (
        "HV-LEN",
        "HV-TXT",
        "HV2-A",
        "HV2-B",
        "HV2-IND-A",
        "HV2-IND-B",
        "WS-KEY",
        "WS-KEY-A",
    ):
        assert name not in unused
    # Still assessed: a plain group reference does not use its fields, and
    # an item nothing names stays unused.
    assert {"WS-GRP-A", "WS-UNUSED"} <= unused


def test_lint_does_not_warn_on_the_varchar_pair():
    report = LintAnalyzer(["unused-variables"]).analyze(_ast())
    symbols = {f.symbol for f in report.findings}
    assert "HV-LEN" not in symbols
    assert "HV-TXT" not in symbols
    assert "WS-UNUSED" in symbols
