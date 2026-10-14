"""CALL ... USING with a passing-mode word and no BY (issue #388).

IBM CALL syntax makes BY optional in front of REFERENCE / CONTENT / VALUE,
the same as the PROCEDURE DIVISION header. A bare mode word switches the
passing mode; it is never an argument itself.
"""

import pytest

from cobolparser import parse_cobol

_PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. T388.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 X PIC X.
       01 Y PIC X.
       01 Z PIC 9.
       PROCEDURE DIVISION.
           {call}
           GOBACK.
"""


def _params(call: str) -> list[tuple[str, str]]:
    result = parse_cobol(_PROGRAM.format(call=call))
    assert result.success, result.errors
    assert not result.warnings, result.warnings
    (stmt,) = result.ast.find_all_by_type("CallStatement")
    return [(p.name, p.passing_mode) for p in stmt.using_parameters]


@pytest.mark.parametrize(
    ("call", "expected"),
    [
        (
            "CALL 'SUB' USING CONTENT X REFERENCE Y.",
            [("X", "CONTENT"), ("Y", "REFERENCE")],
        ),
        ("CALL 'SUB' USING VALUE X.", [("X", "VALUE")]),
        ("CALL 'SUB' USING REFERENCE X.", [("X", "REFERENCE")]),
        (
            "CALL 'SUB' USING X CONTENT Y, Z VALUE 5.",
            [("X", "REFERENCE"), ("Y", "CONTENT"), ("Z", "CONTENT"), ("5", "VALUE")],
        ),
        # BY on the first phrase only: the later bare word still switches.
        (
            "CALL 'SUB' USING BY CONTENT X REFERENCE Y.",
            [("X", "CONTENT"), ("Y", "REFERENCE")],
        ),
        (
            "CALL 'SUB' USING CONTENT 'A' BY VALUE Z.",
            [('"A"', "CONTENT"), ("Z", "VALUE")],
        ),
        (
            "CALL 'SUB' USING CONTENT ZERO, X.",
            [("ZERO", "CONTENT"), ("X", "CONTENT")],
        ),
    ],
)
def test_mode_word_without_by_switches_mode(
    call: str, expected: list[tuple[str, str]]
) -> None:
    assert _params(call) == expected


def test_by_forms_unchanged() -> None:
    assert _params("CALL 'SUB' USING BY CONTENT X BY VALUE Z.") == [
        ("X", "CONTENT"),
        ("Z", "VALUE"),
    ]
