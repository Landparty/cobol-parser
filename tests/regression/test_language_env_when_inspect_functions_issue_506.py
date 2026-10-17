"""Regression tests for issue #506: language-env and intrinsic functions in
EVALUATE WHEN / SEARCH WHEN / INSPECT operands.

``_collect_text_fields`` never read an EVALUATE's WHEN selectors, a SEARCH's
WHEN conditions or an INSPECT's clause operands, so a program whose only
intrinsic sat there reported ``uses_intrinsic_functions: false``. The INSPECT
parser also split ``FUNCTION LOWER-CASE(A)`` into two operands (TALLYING),
kept only the word FUNCTION (REPLACING ... BY) or dropped the clause
(CONVERTING).
"""

from cobolparser import parse_cobol
from cobolparser.analysis import LanguageEnvironmentAnalyzer

_HEAD = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LE2.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  A   PIC X(10).
       01  N   PIC 9(5).
       01  T.
           05 TE PIC X OCCURS 5 INDEXED BY IX.
       PROCEDURE DIVISION.
"""


def _parse(body: str):
    result = parse_cobol(_HEAD + body + "           GOBACK.\n")
    assert result.errors == []
    assert result.warnings == []
    return result.ast


def _functions(body: str) -> list[tuple[str, str]]:
    report = LanguageEnvironmentAnalyzer().analyze(_parse(body))
    return [(u.function_name, u.statement_type) for u in report.intrinsic_usages]


def test_issue_repro_lists_every_intrinsic():
    body = """\
           EVALUATE TRUE
             WHEN FUNCTION LENGTH(A) > 3
               DISPLAY 'LONG'
           END-EVALUATE.
           EVALUATE N
             WHEN FUNCTION MOD(N 2)
               DISPLAY 'ODD'
           END-EVALUATE.
           SET IX TO 1.
           SEARCH TE
             WHEN TE(IX) = FUNCTION UPPER-CASE(A)
               DISPLAY 'HIT'
           END-SEARCH.
           INSPECT A TALLYING N FOR ALL FUNCTION LOWER-CASE(A).
           IF FUNCTION ORD(A) > 1
               DISPLAY 'IF'
           END-IF.
"""
    report = LanguageEnvironmentAnalyzer().analyze(_parse(body))
    assert report.unique_functions == sorted(
        ["LENGTH", "MOD", "UPPER-CASE", "LOWER-CASE", "ORD"]
    )
    lines = {u.function_name: u.location.line for u in report.intrinsic_usages}
    assert lines == {
        "LENGTH": 10,
        "MOD": 14,
        "UPPER-CASE": 19,
        "LOWER-CASE": 23,
        "ORD": 24,
    }


def test_only_intrinsic_in_a_when_still_counts():
    body = """\
           EVALUATE TRUE
             WHEN FUNCTION LENGTH(A) > 3
               DISPLAY 'LONG'
           END-EVALUATE.
"""
    report = LanguageEnvironmentAnalyzer().analyze(_parse(body))
    assert report.uses_intrinsic_functions is True


def test_evaluate_range_bounds_are_scanned_and_quoted_selectors_are_not():
    body = """\
           EVALUATE N
             WHEN 1 THRU FUNCTION MAX(N 9)
               DISPLAY 'IN'
           END-EVALUATE.
           EVALUATE A
             WHEN 'FUNCTION LENGTH(A)'
               DISPLAY 'TEXT'
           END-EVALUATE.
"""
    assert _functions(body) == [("MAX", "EVALUATE")]


def test_inspect_replacing_and_converting_operands():
    body = """\
           INSPECT A REPLACING ALL 'X' BY FUNCTION CHAR(66).
           INSPECT A CONVERTING FUNCTION TRIM(A) TO FUNCTION REVERSE(A).
           INSPECT A TALLYING N FOR CHARACTERS
               BEFORE INITIAL FUNCTION UPPER-CASE(A).
"""
    assert _functions(body) == [
        ("CHAR", "INSPECT"),
        ("TRIM", "INSPECT"),
        ("REVERSE", "INSPECT"),
        ("UPPER-CASE", "INSPECT"),
    ]


def test_inspect_parser_keeps_a_function_operand_whole():
    ast = _parse("""\
           INSPECT A TALLYING N FOR ALL FUNCTION LOWER-CASE(A).
           INSPECT A REPLACING ALL 'X' BY FUNCTION CHAR(66).
           INSPECT A CONVERTING FUNCTION TRIM(A) TO 'abc'.
""")
    tally, replace, convert = [
        s for s in ast.get_all_statements() if s.statement_type == "INSPECT"
    ]
    assert [c["value"] for c in tally.tallying_clauses] == [
        "FUNCTION LOWER-CASE ( A )"
    ]
    assert replace.replacing_clauses[0]["to_value"] == "FUNCTION CHAR ( 66 )"
    assert convert.converting_from == "FUNCTION TRIM ( A )"
    assert convert.converting_to == '"abc"'
