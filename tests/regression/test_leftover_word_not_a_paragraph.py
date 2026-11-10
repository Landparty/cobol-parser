"""A word a statement parser leaves behind before the period is not a
paragraph header.

``STOP RUN 33.``, ``START F FIRST.`` or ``ACCEPT X UPDATE.`` left a word
followed by a period, which looks like a header by shape alone. It opened a
phantom paragraph (``33``) that took every statement after it, with no
diagnostic (open-source corpus finding). Now the word is dropped with an
"unparsed tokens" warning and the statements stay in their paragraph.
"""

import pytest

from cobolparser import CobolParser, ErrorRecoveryMode
from cobolparser.models.walk import all_paragraphs

TEMPLATE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO "F" ORGANIZATION INDEXED
               RECORD KEY IS F-KEY.
       DATA DIVISION.
       FILE SECTION.
       FD F.
       01 F-REC.
          05 F-KEY PIC X.
       WORKING-STORAGE SECTION.
       01 A PIC X.
       PROCEDURE DIVISION.
       MAIN-PARA.
           {stmt}.
           DISPLAY "AFTER".
       NEXT-PARA.
           DISPLAY "N".
"""


def _parse(src):
    result = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL).parse(src)
    assert result.ast is not None
    paragraphs = [
        (p.paragraph_name, len(p.statements))
        for p in all_paragraphs(result.ast.get_division("PROCEDURE"))
    ]
    return result, paragraphs


@pytest.mark.parametrize(
    ("stmt", "word"),
    [
        ("STOP RUN 33", "33"),
        ("START F FIRST", "FIRST"),
        ("ACCEPT A UPDATE", "UPDATE"),
        ("STOP ERROR", "ERROR"),
    ],
)
def test_leftover_word_is_dropped_with_a_warning(stmt, word):
    result, paragraphs = _parse(TEMPLATE.format(stmt=stmt))
    assert paragraphs == [("MAIN-PARA", 2), ("NEXT-PARA", 1)]
    assert any(f"'{word}'" in w for w in result.warnings), result.warnings


def test_leftover_word_in_implicit_paragraph():
    src = TEMPLATE.replace("       MAIN-PARA.\n", "").format(stmt="STOP RUN 33")
    result, paragraphs = _parse(src)
    assert paragraphs == [("", 2), ("NEXT-PARA", 1)]
    assert any("'33'" in w for w in result.warnings)


def test_header_after_period_on_same_line_is_still_a_paragraph():
    src = TEMPLATE.format(stmt="DISPLAY A. SAME-LINE")
    result, paragraphs = _parse(src)
    assert paragraphs == [("MAIN-PARA", 1), ("SAME-LINE", 1), ("NEXT-PARA", 1)]
    assert not result.warnings


def test_header_after_period_less_statement_on_previous_line():
    # A missing period before the next header is tolerated, as before (with
    # its own "missing its terminating period" warning).
    src = TEMPLATE.format(stmt="DISPLAY A\n       OTHER-PARA")
    result, paragraphs = _parse(src)
    assert paragraphs == [("MAIN-PARA", 1), ("OTHER-PARA", 1), ("NEXT-PARA", 1)]
    assert not any("Unparsed tokens" in w for w in result.warnings)


def test_accept_count_without_message():
    src = TEMPLATE.format(stmt="ACCEPT A COUNT")
    result, paragraphs = _parse(src)
    assert paragraphs == [("MAIN-PARA", 2), ("NEXT-PARA", 1)]
    assert not result.warnings
