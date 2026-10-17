"""Issue #332: one TALLYING ``FOR`` may carry several ``CHARACTERS`` /
``ALL`` / ``LEADING`` phrases (``FOR ALL 'A' LEADING 'C'``). The parser
read only the first: ``LEADING`` became a counter name, ``ALL`` (a
FIGURATIVE_CONSTANT) was taken as a literal operand, a phrase after
``CHARACTERS`` was dropped -- with no warning -- and ``unused-variables``
then called a real operand never referenced.
"""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.unused_variables import UnusedVariableAnalyzer


def _program(statement: str) -> str:
    return (
        "IDENTIFICATION DIVISION.\n"
        "PROGRAM-ID. TALLY.\n"
        "DATA DIVISION.\n"
        "WORKING-STORAGE SECTION.\n"
        "01 WS-TEXT PIC X(10).\n"
        "01 N PIC 9(3).\n"
        "01 M PIC 9(3).\n"
        "01 WS-COMMA PIC X.\n"
        "01 WS-DOT PIC X.\n"
        "PROCEDURE DIVISION.\n"
        "MAIN-PARA.\n"
        f"    {statement}\n"
        "    DISPLAY N M\n"
        "    GOBACK.\n"
    )


def _clauses(statement: str) -> list[tuple]:
    result = parse_cobol(_program(statement), filename="tally.cbl")
    assert result.ast is not None and result.errors == [], result.errors
    assert result.warnings == [], result.warnings
    (stmt,) = result.ast.find_all_by_type("InspectStatement")
    return [
        (c["counter"], c["for_type"], c["value"], c["before"], c["after"])
        for c in stmt.tallying_clauses
    ]


@pytest.mark.parametrize(
    ("tallying", "expected"),
    [
        (
            "N FOR ALL 'A' LEADING 'C'",
            [("N", "ALL", '"A"', None, None), ("N", "LEADING", '"C"', None, None)],
        ),
        (
            "N FOR ALL ',' ALL '.'",
            [("N", "ALL", '","', None, None), ("N", "ALL", '"."', None, None)],
        ),
        (
            "N FOR CHARACTERS AFTER '*' ALL 'X'",
            [
                ("N", "CHARACTERS", None, None, '"*"'),
                ("N", "ALL", '"X"', None, None),
            ],
        ),
        (
            "N FOR ALL WS-COMMA LEADING WS-DOT",
            [
                ("N", "ALL", "WS-COMMA", None, None),
                ("N", "LEADING", "WS-DOT", None, None),
            ],
        ),
        (
            "N FOR ALL WS-COMMA WS-DOT BEFORE '*' M FOR ALL 'A'",
            [
                ("N", "ALL", "WS-COMMA", None, None),
                ("N", "ALL", "WS-DOT", '"*"', None),
                ("M", "ALL", '"A"', None, None),
            ],
        ),
        (
            "N FOR ALL 'A' 'B' M FOR CHARACTERS LEADING SPACES",
            [
                ("N", "ALL", '"A"', None, None),
                ("N", "ALL", '"B"', None, None),
                ("M", "CHARACTERS", None, None, None),
                ("M", "LEADING", "SPACES", None, None),
            ],
        ),
    ],
)
def test_every_phrase_of_one_for_is_a_clause(tallying: str, expected) -> None:
    assert _clauses(f"INSPECT WS-TEXT TALLYING {tallying}") == expected


def test_tallying_then_replacing_still_splits() -> None:
    result = parse_cobol(
        _program(
            "INSPECT WS-TEXT TALLYING N FOR ALL 'A' LEADING 'B'\n"
            "        REPLACING ALL 'A' BY 'Z'"
        ),
        filename="tally.cbl",
    )
    (stmt,) = result.ast.find_all_by_type("InspectStatement")
    assert stmt.inspect_type == "TALLYING_REPLACING"
    assert len(stmt.tallying_clauses) == 2
    assert stmt.replacing_clauses[0]["from_value"] == '"A"'


def test_second_phrase_operand_is_not_reported_unused() -> None:
    result = parse_cobol(
        _program("INSPECT WS-TEXT TALLYING N FOR ALL WS-COMMA LEADING WS-DOT"),
        filename="tally.cbl",
    )
    report = UnusedVariableAnalyzer().analyze(result.ast)
    assert "WS-DOT" not in {item.name for item in report.unused_items}


@pytest.mark.parametrize(
    "tallying",
    [
        "N FOR ALL 'A', 'B', LEADING 'C'; CHARACTERS AFTER '*', M FOR ALL WS-COMMA",
        "N FOR ALL 'A' , 'B' ; LEADING 'C' , CHARACTERS AFTER '*' ; M FOR ALL WS-COMMA",
    ],
)
def test_separators_between_operands_and_phrases(tallying: str) -> None:
    # #569 x #332: a separator is a space between ALL / LEADING operands,
    # between phrases of one FOR, and before the next counter.
    assert _clauses(f"INSPECT WS-TEXT TALLYING {tallying}") == [
        ("N", "ALL", '"A"', None, None),
        ("N", "ALL", '"B"', None, None),
        ("N", "LEADING", '"C"', None, None),
        ("N", "CHARACTERS", None, None, '"*"'),
        ("M", "ALL", "WS-COMMA", None, None),
    ]
