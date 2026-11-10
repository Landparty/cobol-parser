"""The source census behind the open-source corpus harness (tools/corpus).

The census is the oracle the AST is checked against, so its own counts are
pinned here: if it miscounts, the harness reports parser bugs that are not
there (or misses ones that are).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "corpus"))

from ast_census import ast_census  # noqa: E402
from census import census  # noqa: E402

from cobolparser import CobolParser, ErrorRecoveryMode  # noqa: E402

HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A        PIC 9(4).
           88 WS-A-ON  VALUE 1.
       01  WS-B.
           05 WS-B1    PIC Z,ZZ9.99.
           05 WS-B2    PIC X(10) VALUE 'MOVE IT. '.
       77  WS-C        PIC X.
       PROCEDURE DIVISION.
"""


def _both(body: str):
    source = HEADER + body
    result = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL).parse(source)
    return census(source), ast_census(result.ast)


def test_counts_data_entries_and_ignores_picture_and_literal_periods() -> None:
    want, got = _both("           STOP RUN.\n")
    assert dict(want.data_entries_by_level) == {1: 2, 88: 1, 5: 2, 77: 1}
    assert want.data_entries == got.data_entries == 6


def test_counts_verbs_including_nested_ones() -> None:
    want, got = _both("""\
       MAIN-PARA.
           IF WS-A = 1
              MOVE 2 TO WS-A
              PERFORM SUB-PARA
           ELSE
              NEXT SENTENCE
           END-IF.
           EXEC SQL SELECT 1 INTO :WS-A FROM T END-EXEC.
           STOP RUN.
       SUB-PARA.
           DISPLAY 'IF MOVE PERFORM'.
""")
    assert dict(want.verbs) == {
        "IF": 1,
        "MOVE": 1,
        "PERFORM": 1,
        "NEXT SENTENCE": 1,
        "EXEC": 1,
        "STOP": 1,
        "DISPLAY": 1,
    }
    assert want.verbs == got.verbs
    assert [name for name, _ in want.paragraphs] == ["MAIN-PARA", "SUB-PARA"]
    assert got.paragraphs == ["MAIN-PARA", "SUB-PARA"]


@pytest.mark.parametrize(
    ("body", "verbs"),
    [
        # EXIT PERFORM is one EXIT statement, not a PERFORM.
        (
            "           PERFORM 2 TIMES\n              EXIT PERFORM\n"
            "           END-PERFORM.\n",
            {"PERFORM": 1, "EXIT": 1},
        ),
        # SET ... TO ENTRY names a program, it is not an ENTRY statement.
        ("           SET WS-A TO ENTRY 'X'.\n", {"SET": 1}),
        # A scope terminator closing a sentence is not a paragraph header.
        (
            "           IF WS-A = 1 DISPLAY 'X'\n           END-IF.\n",
            {"IF": 1, "DISPLAY": 1},
        ),
    ],
)
def test_phrases_that_reuse_verb_words(body: str, verbs: dict) -> None:
    want = census(HEADER + body)
    assert dict(want.verbs) == verbs
    assert want.paragraphs == []


def test_area_a_header_after_a_missing_period_is_still_a_paragraph() -> None:
    want = census(
        HEADER
        + "       P1.\n           DISPLAY 'A'\n       P2.\n           STOP RUN.\n"
    )
    assert [name for name, _ in want.paragraphs] == ["P1", "P2"]


def test_multiline_pseudo_text_is_not_counted() -> None:
    source = HEADER.replace(
        "       PROCEDURE DIVISION.\n",
        "       REPLACE ==X-A== BY\n           ==01 FAKE PIC X.\n           MOVE A TO B==.\n"
        "       PROCEDURE DIVISION.\n",
    )
    want = census(source + "           STOP RUN.\n")
    assert want.data_entries == 6
    assert dict(want.verbs) == {"STOP": 1}
    assert any("REPLACE" in c for c in want.caveats)


def test_headerless_program_id_opens_a_unit():
    src = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. T.\n"
        "       PROCEDURE DIVISION.\n"
        "           DISPLAY 'T'.\n"
        "       PROGRAM-ID. P2.\n"
        "       PROCEDURE DIVISION.\n"
        "       P2-MAIN.\n"
        "           DISPLAY 'P2'.\n"
    )
    result = census(src)
    assert result.units == 2
    assert result.paragraphs == [("P2-MAIN", 7)]
