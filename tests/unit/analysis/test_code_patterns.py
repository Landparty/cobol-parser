"""Code-pattern lint rules (analysis/code_patterns.py).

Each rule gets a program that holds the pattern and the look-alike it must
stay quiet on, so a rule that starts over-reporting fails here first.
"""

from __future__ import annotations

import textwrap

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.code_patterns import (
    CODE_PATTERN_DESCRIPTIONS,
    CODE_PATTERN_RULES,
    MAX_NESTING,
    CodePatternAnalyzer,
)
from cobolparser.analysis.lint import RULES, LintAnalyzer
from cobolparser.analysis.sarif import RULE_DESCRIPTIONS


def _program(data: str, procedure: str, *, using: str = "", linkage: str = "") -> str:
    def block(text: str, indent: int) -> str:
        return textwrap.indent(textwrap.dedent(text).strip("\n"), " " * indent)

    parts = [
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. T.",
        "       DATA DIVISION.",
        "       WORKING-STORAGE SECTION.",
        block(data, 7),
    ]
    if linkage:
        parts += ["       LINKAGE SECTION.", block(linkage, 7)]
    parts.append(
        f"       PROCEDURE DIVISION USING {using}."
        if using
        else "       PROCEDURE DIVISION."
    )
    parts.append(block(procedure, 7))
    return "\n".join(parts) + "\n"


def _kinds(source: str, rule: str) -> list[str]:
    result = parse_cobol(source)
    assert result.ast is not None, result.errors
    assert not result.errors, result.errors
    return [f.kind for f in CodePatternAnalyzer([rule]).analyze(result.ast).findings]


_DATA = """
01 WS-A PIC X(3).
01 WS-B PIC X(3).
01 WS-N PIC 99.
01 WS-I PIC 9(4) COMP.
01 WS-J PIC 9(4) COMP.
01 WS-P PIC 99.
01 WS-OUT PIC X(20).
"""


def test_rules_are_lint_rules_with_descriptions() -> None:
    for rule in CODE_PATTERN_RULES:
        assert rule in RULES
        assert RULE_DESCRIPTIONS[rule] == CODE_PATTERN_DESCRIPTIONS[rule]


def test_unknown_rule_rejected() -> None:
    with pytest.raises(ValueError):
        CodePatternAnalyzer(["nope"])


# -- constant-condition -------------------------------------------------------


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ("WS-A = WS-A", ["IDENTICAL_OPERANDS"]),
        ("WS-N > WS-N", ["IDENTICAL_OPERANDS"]),
        ("WS-OUT (1:2) = WS-OUT(1:2)", ["IDENTICAL_OPERANDS"]),
        ("WS-A = 'X' AND WS-A = 'Y'", ["CONTRADICTORY_AND"]),
        ("WS-N = 1 AND 2", ["CONTRADICTORY_AND"]),
        ("NOT (WS-N = 1 AND WS-N = 2)", ["CONTRADICTORY_AND"]),
        ("WS-A = WS-B", []),
        ("WS-A = 'X' OR WS-A = 'Y'", []),
        ("WS-A = 'X' AND WS-B = 'Y'", []),
        ("WS-A = 'X' AND WS-A = 'X '", []),
        ("WS-N = 1 AND WS-N = 01", []),
        ("WS-A NOT = 'X' AND WS-A NOT = 'Y'", []),
        ("FUNCTION RANDOM = FUNCTION RANDOM", []),
    ],
)
def test_constant_condition(condition: str, expected: list[str]) -> None:
    source = _program(
        _DATA, f"MAIN.\n    IF {condition} DISPLAY 'X' END-IF.\n    STOP RUN."
    )
    assert _kinds(source, "constant-condition") == expected


def test_constant_condition_in_perform_until() -> None:
    source = _program(
        _DATA,
        """
        MAIN.
            PERFORM UNTIL WS-N = WS-N
               DISPLAY 'X'
            END-PERFORM.
            STOP RUN.
        """,
    )
    assert _kinds(source, "constant-condition") == ["IDENTICAL_OPERANDS"]


# -- duplicate-branch ---------------------------------------------------------


def test_duplicate_when_literal_and_condition() -> None:
    source = _program(
        _DATA,
        """
        MAIN.
            EVALUATE WS-A
              WHEN 'A' DISPLAY 1
              WHEN 'B' THRU 'C' DISPLAY 2
              WHEN 'A' DISPLAY 3
            END-EVALUATE
            EVALUATE TRUE
              WHEN WS-N = 1 DISPLAY 1
              WHEN WS-N  =  1 DISPLAY 2
              WHEN OTHER CONTINUE
            END-EVALUATE
            EVALUATE WS-N
              WHEN 1 DISPLAY 1
              WHEN 01 DISPLAY 2
            END-EVALUATE.
            STOP RUN.
        """,
    )
    assert _kinds(source, "duplicate-branch") == ["DUPLICATE_WHEN"] * 3


def test_duplicate_when_in_one_shared_group_is_quiet() -> None:
    # CardDemo COCRDLIC: WHEN X WHEN X <statements> shares one body.
    source = _program(
        _DATA,
        """
        MAIN.
            EVALUATE TRUE
              WHEN WS-N = 1
              WHEN WS-N = 1
                 DISPLAY 1
              WHEN WS-N = 2
                 DISPLAY 2
            END-EVALUATE
            EVALUATE WS-A ALSO WS-B
              WHEN 'A' ALSO 'B' DISPLAY 1
              WHEN 'A' ALSO 'C' DISPLAY 2
              WHEN WS-B ALSO 'B' DISPLAY 3
              WHEN WS-B ALSO 'B' DISPLAY 4
            END-EVALUATE.
            STOP RUN.
        """,
    )
    assert _kinds(source, "duplicate-branch") == []


def test_duplicate_else_if() -> None:
    source = _program(
        _DATA,
        """
        MAIN.
            IF WS-A = 'A'
               DISPLAY 1
            ELSE IF WS-A = 'B'
               DISPLAY 2
            ELSE IF WS-A = 'A'
               DISPLAY 3
            END-IF.
            IF WS-A = 'A'
               DISPLAY 1
            ELSE
               DISPLAY 0
               IF WS-A = 'A' DISPLAY 2 END-IF
            END-IF.
            STOP RUN.
        """,
    )
    assert _kinds(source, "duplicate-branch") == ["DUPLICATE_CONDITION"]


# -- self-assignment ----------------------------------------------------------


def test_self_move() -> None:
    source = _program(
        _DATA,
        """
        MAIN.
            MOVE WS-A TO WS-B WS-A
            MOVE WS-A TO WS-B
            MOVE 'X' TO WS-A
            MOVE WS-OUT(1:2) TO WS-OUT(3:2).
            STOP RUN.
        """,
    )
    assert _kinds(source, "self-assignment") == ["SELF_MOVE"]


# -- stop-run-in-subprogram ---------------------------------------------------


def test_stop_run_in_called_program() -> None:
    called = _program(
        _DATA, "MAIN.\n    STOP RUN.", using="LK-X", linkage="01 LK-X PIC X."
    )
    assert _kinds(called, "stop-run-in-subprogram") == ["STOP_RUN_IN_CALLED_PROGRAM"]
    main = _program(_DATA, "MAIN.\n    STOP RUN.")
    assert _kinds(main, "stop-run-in-subprogram") == []
    goback = _program(
        _DATA, "MAIN.\n    GOBACK.", using="LK-X", linkage="01 LK-X PIC X."
    )
    assert _kinds(goback, "stop-run-in-subprogram") == []


def test_stop_run_in_nested_program_via_lint() -> None:
    source = textwrap.dedent("""\
               IDENTIFICATION DIVISION.
               PROGRAM-ID. OUTER.
               PROCEDURE DIVISION.
               MAIN.
                   CALL 'INNER'
                   STOP RUN.
               IDENTIFICATION DIVISION.
               PROGRAM-ID. INNER.
               PROCEDURE DIVISION.
               P1.
                   STOP RUN.
               END PROGRAM INNER.
               END PROGRAM OUTER.
        """)
    result = parse_cobol(source)
    assert result.ast is not None
    report = LintAnalyzer(rules=["stop-run-in-subprogram"]).analyze(result.ast)
    assert [f.kind for f in report.findings] == ["STOP_RUN_IN_CALLED_PROGRAM"]
    assert report.findings[0].location.line == 11


# -- string-pointer -----------------------------------------------------------


def test_pointer_set_to_zero_before_string() -> None:
    source = _program(
        _DATA,
        """
        MAIN.
            MOVE ZERO TO WS-P
            STRING WS-A DELIMITED BY SIZE INTO WS-OUT WITH POINTER WS-P
            MOVE 0 TO WS-P
            ADD 1 TO WS-P
            STRING WS-A DELIMITED BY SIZE INTO WS-OUT WITH POINTER WS-P
            MOVE 1 TO WS-P
            STRING WS-A DELIMITED BY SIZE INTO WS-OUT WITH POINTER WS-P
            INITIALIZE WS-P
            UNSTRING WS-OUT DELIMITED BY ',' INTO WS-A WITH POINTER WS-P.
            STOP RUN.
        """,
    )
    assert _kinds(source, "string-pointer") == ["POINTER_BELOW_ONE"] * 2


def test_pointer_too_small() -> None:
    data = """
    01 WS-A PIC X(3).
    01 WS-P1 PIC 9.
    01 WS-P2 PIC 99.
    01 WS-OUT9 PIC X(9).
    01 WS-OUT20 PIC X(20).
    01 WS-GRP.
       05 WS-G1 PIC X(10).
       05 WS-G2 PIC X(10).
    """
    source = _program(
        data,
        """
        MAIN.
            MOVE 1 TO WS-P1 WS-P2
            STRING WS-A DELIMITED BY SIZE INTO WS-OUT20 WITH POINTER WS-P1
            STRING WS-A DELIMITED BY SIZE INTO WS-OUT9 WITH POINTER WS-P1
            STRING WS-A DELIMITED BY SIZE INTO WS-OUT20 WITH POINTER WS-P2
            UNSTRING WS-GRP DELIMITED BY ',' INTO WS-A WITH POINTER WS-P1.
            STOP RUN.
        """,
    )
    assert _kinds(source, "string-pointer") == ["POINTER_TOO_SMALL"] * 2


# -- loop-variable ------------------------------------------------------------


def test_loop_variable_inline_and_out_of_line() -> None:
    source = _program(
        _DATA,
        """
        MAIN.
            PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 10
               IF WS-N = 1
                  ADD 1 TO WS-I
               END-IF
               ADD 1 TO WS-J
            END-PERFORM
            PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 10
               MOVE 99 TO WS-I
            END-PERFORM
            PERFORM BODY VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 3
               AFTER WS-J FROM 1 BY 1 UNTIL WS-J > 3
            PERFORM UNTIL WS-I > 10
               ADD 1 TO WS-I
            END-PERFORM.
            STOP RUN.
        BODY.
            COMPUTE WS-J = WS-J + 2
            DIVIDE 2 INTO WS-N GIVING WS-I.
        """,
    )
    assert _kinds(source, "loop-variable") == [
        "VARYING_VARIABLE_STEPPED",
        "VARYING_VARIABLE_ASSIGNED",
        "VARYING_VARIABLE_STEPPED",
        "VARYING_VARIABLE_ASSIGNED",
    ]


# -- evaluate-other / nesting-depth -------------------------------------------


def test_evaluate_other() -> None:
    source = _program(
        _DATA,
        """
        MAIN.
            EVALUATE WS-N
              WHEN 1 DISPLAY 1
            END-EVALUATE
            EVALUATE WS-N
              WHEN 1 DISPLAY 1
              WHEN OTHER CONTINUE
            END-EVALUATE.
            STOP RUN.
        """,
    )
    assert _kinds(source, "evaluate-other") == ["EVALUATE_WITHOUT_OTHER"]


def test_nesting_depth_and_else_if_chain() -> None:
    deep = (
        "\n".join("    " * i + f"IF WS-N = {i}" for i in range(MAX_NESTING + 1))
        + "\nDISPLAY 1\n"
        + "\n".join("END-IF" for _ in range(MAX_NESTING + 1))
    )
    source = _program(
        _DATA, "MAIN.\n" + textwrap.indent(deep, "    ") + ".\n    STOP RUN."
    )
    assert _kinds(source, "nesting-depth") == ["NESTING_TOO_DEEP"]

    chain = (
        "IF WS-N = 0 DISPLAY 0\n"
        + "".join(f"ELSE IF WS-N = {i} DISPLAY {i}\n" for i in range(1, 12))
        + "END-IF"
    )
    source = _program(
        _DATA, "MAIN.\n" + textwrap.indent(chain, "    ") + ".\n    STOP RUN."
    )
    assert _kinds(source, "nesting-depth") == []


def test_lint_runs_code_patterns_by_default() -> None:
    source = _program(_DATA, "MAIN.\n    MOVE WS-A TO WS-A.\n    STOP RUN.")
    result = parse_cobol(source)
    assert result.ast is not None
    report = LintAnalyzer().analyze(result.ast)
    assert "self-assignment" in report.rules_run
    assert any(f.rule == "self-assignment" for f in report.findings)
    assert report.failed_rules == []


def test_no_procedure_division_is_quiet() -> None:
    source = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. T.\n"
    result = parse_cobol(source)
    assert result.ast is not None
    assert CodePatternAnalyzer().analyze(result.ast).findings == []


# -- #852: JCL PARM linkage is no CALL ------------------------------------------


@pytest.mark.parametrize("usage", ["COMP", "COMP-5", "BINARY", "COMPUTATIONAL"])
def test_stop_run_with_jcl_parm_using_is_silent(usage: str) -> None:
    linkage = f"""
    01 PARM-AREA.
       05 PARM-LEN  PIC S9(4) {usage}.
       05 PARM-TEXT PIC X(100).
    """
    main = _program(_DATA, "MAIN.\n    STOP RUN.", using="PARM-AREA", linkage=linkage)
    assert _kinds(main, "stop-run-in-subprogram") == []


@pytest.mark.parametrize(
    "linkage, using",
    [
        # First item is no binary halfword.
        ("01 LK-A.\n   05 LK-LEN PIC 9(4).\n   05 LK-T PIC X(9).", "LK-A"),
        ("01 LK-A.\n   05 LK-LEN PIC S9(9) COMP.\n   05 LK-T PIC X(9).", "LK-A"),
        # Two USING items: a CALL interface.
        (
            "01 LK-A.\n   05 LK-LEN PIC S9(4) COMP.\n   05 LK-T PIC X(9).\n"
            "01 LK-B PIC X.",
            "LK-A LK-B",
        ),
        # An elementary USING item.
        ("01 LK-A PIC S9(4) COMP.", "LK-A"),
    ],
)
def test_stop_run_with_call_shaped_using_is_flagged(linkage: str, using: str) -> None:
    called = _program(_DATA, "MAIN.\n    STOP RUN.", using=using, linkage=linkage)
    assert _kinds(called, "stop-run-in-subprogram") == ["STOP_RUN_IN_CALLED_PROGRAM"]


# -- #853: COMP-5 holds its native binary range --------------------------------


def test_comp5_pointer_is_judged_by_native_capacity() -> None:
    data = """
    01 WS-A PIC X(3).
    01 P5 PIC 9(2) COMP-5.
    01 P2 PIC 9(2) COMP.
    01 BUF PIC X(99).
    01 BIG PIC X(20000).
    """
    source = _program(
        data,
        """
        MAIN.
            MOVE 1 TO P5 P2
            STRING WS-A DELIMITED BY SIZE INTO BUF WITH POINTER P5
            STRING WS-A DELIMITED BY SIZE INTO BUF WITH POINTER P2
            STRING WS-A DELIMITED BY SIZE INTO BIG WITH POINTER P5.
            STOP RUN.
        """,
    )
    # P2 (COMP, TRUNC(STD)) is too small for BUF; a halfword COMP-5 holds 100
    # but not 20001.
    assert _kinds(source, "string-pointer") == ["POINTER_TOO_SMALL"] * 2
