"""diff compares VALUE clauses by value, not spelling (#543).

``ProgramDiffer`` compared ``value_clause`` as raw text, so ``ZERO`` ->
``ZEROES``, ``HIGH-VALUE`` -> ``HIGH-VALUES``, ``SPACES`` -> ``SPACE``,
``7`` -> ``007`` and ``+5`` -> ``5.0`` were all reported as
``value-changed``. The comparison is now on a canonical form; the message
still quotes the text as coded.
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.analysis.ast_diff import ProgramDiffer


def _program(values: dict[str, str]) -> str:
    pics = {
        "WS-A": "9(3)",
        "WS-B": "X(3)",
        "WS-C": "9(3)",
        "WS-D": "X(3)",
        "WS-E": "S9(3)V9",
        "WS-F": "X(3)",
        "WS-G": "X(3)",
    }
    lines = [
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. V1.",
        "DATA DIVISION.",
        "WORKING-STORAGE SECTION.",
        *(
            f"01 {name} PIC {pics[name]} VALUE {value}."
            for name, value in values.items()
        ),
        "PROCEDURE DIVISION.",
        "MAIN-PARA.",
        "    IF WS-A = ZERO DISPLAY 'Z' END-IF",
        "    STOP RUN.",
    ]
    return "".join(f"       {line}\n" for line in lines)


V1 = {
    "WS-A": "ZERO",
    "WS-B": "SPACES",
    "WS-C": "7",
    "WS-D": "HIGH-VALUE",
    "WS-E": "+5",
    "WS-F": "ALL LOW-VALUES",
    "WS-G": "X'0a0B'",
}
V2 = {
    "WS-A": "ZEROES",
    "WS-B": "SPACE",
    "WS-C": "007",
    "WS-D": "HIGH-VALUES",
    "WS-E": "5.0",
    "WS-F": "ALL LOW-VALUE",
    "WS-G": "X'0A0b'",
}


def _diff(old: str, new: str):
    old_result, new_result = parse_cobol(old), parse_cobol(new)
    assert old_result.success and new_result.success
    return ProgramDiffer().diff(old_result.ast, new_result.ast)


def test_equivalent_spellings_are_not_changes():
    report = _diff(_program(V1), _program(V2))
    assert report.changes == [], report.to_text()


def test_real_value_changes_are_still_reported():
    changed = dict(V2, **{"WS-C": "8", "WS-A": "SPACE", "WS-E": "5.1"})
    report = _diff(_program(V1), _program(changed))
    found = {(c.kind, c.symbol) for c in report.changes}
    assert found == {
        ("value-changed", "WS-A"),
        ("value-changed", "WS-C"),
        ("value-changed", "WS-E"),
    }
    # The message quotes the clauses as coded.
    assert "WS-C VALUE changed from 7 to 8" in report.to_text()


def test_all_and_literal_case_are_significant():
    report = _diff(
        _program(dict(V1, **{"WS-B": "'ab'", "WS-F": "LOW-VALUES"})),
        _program(dict(V1, **{"WS-B": "'AB'", "WS-F": "ALL LOW-VALUES"})),
    )
    assert {c.symbol for c in report.changes} == {"WS-B", "WS-F"}
