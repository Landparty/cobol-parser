"""Regression tests for issue #487: ``PERFORM 1000-INIT`` is not a reference to ``INIT``.

``_names.IDENTIFIER_TOKEN_RE`` could not match a digit-then-hyphen word such
as ``1000-CUST-TOTAL`` from its first character, so it matched the tail
(``CUST-TOTAL``) -- and with ``1000-xxx`` the dominant mainframe paragraph
convention, any data item sharing a paragraph's tail read as used in
``unused-variables``, ``lint`` and ``xref``. Separately, unused-variables
read a PERFORM / GO TO target as a data reference, so a paragraph named
like a data item (``PERFORM INIT``) also marked it used.
"""

import pytest

from cobolparser import LintAnalyzer, UnusedVariableAnalyzer, parse_cobol
from cobolparser.analysis._names import IDENTIFIER_TOKEN_RE
from cobolparser.analysis.xref import XrefAnalyzer

_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. X2.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  CUST-TOTAL  PIC 9(5).
       01  INIT        PIC X.
       01  1ST-NAME    PIC X.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'A' TO 1ST-NAME
           PERFORM 1000-INIT THRU 1000-CUST-TOTAL
           PERFORM 2000-INIT
           GO TO 1000-CUST-TOTAL.
       1000-INIT.
           DISPLAY 'R'.
       1000-CUST-TOTAL.
           EXIT.
       2000-INIT.
           STOP RUN.
"""

_SAME_NAME = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. X3.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  INIT        PIC X.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM INIT
           GO TO P-END.
       INIT.
           EXIT.
       P-END.
           STOP RUN.
"""


def _ast(source: str = _SOURCE):
    result = parse_cobol(source)
    assert result.errors == []
    return result.ast


@pytest.mark.parametrize(
    "text, tokens",
    [
        ("1000-INIT", ["1000-INIT"]),
        ("1000-CUST-TOTAL", ["1000-CUST-TOTAL"]),
        ("1ST-NAME OF 2ND-REC", ["1ST-NAME", "OF", "2ND-REC"]),
        ("WS-A (1:5)", ["WS-A"]),
        ("1.5E+3", []),
        ("12345", []),
    ],
)
def test_token_regex_takes_whole_words(text, tokens):
    assert IDENTIFIER_TOKEN_RE.findall(text) == tokens


def test_unused_variables_reports_the_tail_named_items():
    unused = {i.name for i in UnusedVariableAnalyzer().analyze(_ast()).unused_items}
    assert {"CUST-TOTAL", "INIT"} <= unused
    assert "1ST-NAME" not in unused


def test_lint_reports_them_too():
    report = LintAnalyzer(["unused-variables"]).analyze(_ast())
    assert {"CUST-TOTAL", "INIT"} <= {f.symbol for f in report.findings}


def test_xref_gives_the_data_items_no_references():
    report = XrefAnalyzer().analyze(_ast())
    data = {
        e["name"]: e["reference_count"]
        for e in report.to_dict()["entries"]
        if e["kind"] == "data-item"
    }
    assert data["CUST-TOTAL"] == 0
    assert data["INIT"] == 0
    assert report.to_dict()["undefined"] == []


def test_a_paragraph_named_like_a_data_item_does_not_use_it():
    unused = {
        i.name for i in UnusedVariableAnalyzer().analyze(_ast(_SAME_NAME)).unused_items
    }
    assert "INIT" in unused
