"""#747: ``WHEN +100`` reached business-rules as the string ``'+ 100'``.

The parser joined the sign token and the number with a space, so the
condition text read ``IN-N = '+ 100'`` (a string compare the program never
makes) and the IF form read ``IN-N = - 7``. A leading sign is now folded
into the number it signs, in WHEN values, THRU ranges and conditions.
"""

from __future__ import annotations

from cobolparser import BusinessRuleExtractor, parse_cobol
from cobolparser.parsers.statements._conditions import join_operand

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. Q.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-F ASSIGN TO INDD.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-F.
       01  IN-REC.
           05  IN-N    PIC S9(4).
       WORKING-STORAGE SECTION.
       01  WS-R    PIC X.
       PROCEDURE DIVISION.
           OPEN INPUT IN-F
           READ IN-F
           EVALUATE IN-N
               WHEN +100   MOVE 'A' TO WS-R
               WHEN -5 THRU +5 MOVE 'B' TO WS-R
               WHEN OTHER  MOVE 'E' TO WS-R
           END-EVALUATE
           IF IN-N = -7 MOVE 'F' TO WS-R END-IF
           DISPLAY WS-R
           CLOSE IN-F
           GOBACK.
"""


def _conditions() -> list[list[str]]:
    ast = parse_cobol(SOURCE, filename="Q.cbl").ast
    report = BusinessRuleExtractor().analyze(ast)
    return [[b.condition for b in rule.branches] for rule in report.rules]


def test_signed_when_values_are_numeric_comparisons() -> None:
    evaluate = _conditions()[0]
    assert evaluate[:2] == ["IN-N = +100", "IN-N >= -5 AND IN-N <= +5"]


def test_signed_if_operand_has_no_stray_space() -> None:
    assert _conditions()[1] == ["IN-N = -7"]


def test_parse_output_carries_the_signed_value() -> None:
    ast = parse_cobol(SOURCE, filename="Q.cbl").ast
    dump = str(ast.to_dict())
    assert "'+100'" in dump
    assert "'+ 100'" not in dump and "'- 5'" not in dump


def test_join_operand_folds_only_a_leading_sign() -> None:
    assert join_operand(["+", "100"]) == "+100"
    assert "- 5" not in join_operand(["(", "-", "5", ")"])
    assert join_operand(["A", "-", "5"]) == "A - 5"
