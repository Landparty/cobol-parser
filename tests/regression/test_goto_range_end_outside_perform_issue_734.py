"""Regression tests for issue #734: a GO TO onto a THRU range end that runs
outside a PERFORM of that range.

``GO TO P2`` inside ``PERFORM P1 THRU P2`` ends the range and returns (the
#381 idiom), so the paragraph after P2 stays dead. But when the jumping
paragraph is also fallen into, or lies outside every range closing on P2,
the jump lands in P2 with no PERFORM to return to and P2 falls into the
next paragraph -- which dead-code reported dead although it runs (each
source below was checked against GnuCOBOL 3.1.2).
"""

from cobolparser import parse_cobol
from cobolparser.analysis.dead_code import DeadCodeAnalyzer


def _dead(procedure: str) -> list[str]:
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. DC.\n"
        "       PROCEDURE DIVISION.\n"
        + "".join(f"       {line}\n" for line in procedure.strip("\n").split("\n"))
    )
    result = parse_cobol(source, filename="dc.cbl")
    assert result.ast is not None, result.errors
    return [item.name for item in DeadCodeAnalyzer().analyze(result.ast).dead_items]


def test_range_member_fallen_into_runs_past_the_range_end() -> None:
    # Runs P0 P1 P2 P2 P3: P0 falls into P1, whose GO TO P2 returns nowhere.
    assert _dead("""
P0.
    PERFORM P1 THRU P2.
P1.
    GO TO P2.
P2.
    DISPLAY 'P2'.
P3.
    DISPLAY 'P3'.
""") == []


def test_go_to_from_outside_the_range_runs_past_its_end() -> None:
    # Runs P0 P7 P4 P5: P7 is PERFORMed, but GO TO P4 leaves its range and
    # P4 is the end only of P2 THRU P4, which P7 is not in.
    assert "P5" not in _dead("""
P0.
    PERFORM P7
    STOP RUN.
P2.
    DISPLAY 'P2'.
P4.
    DISPLAY 'P4'.
P5.
    DISPLAY 'P5'
    PERFORM P2 THRU P4
    STOP RUN.
P7.
    GO TO P4.
""")


def test_go_to_into_a_range_end_in_another_section() -> None:
    # Runs P0 P1 P3 P4; P2 never runs.
    assert _dead("""
S0 SECTION.
P0.
    PERFORM P1 2 TIMES
    STOP RUN.
P1.
    GO TO P3.
P2.
    PERFORM P2 THRU P3
    PERFORM P1.
S1 SECTION.
P3.
    DISPLAY 'P3'.
P4.
    DISPLAY 'P4'.
""") == ["P2"]


def test_early_exit_of_a_performed_range_still_returns() -> None:
    # The #381 idiom is unchanged: P1 only ever runs under the PERFORM.
    assert _dead("""
P0.
    PERFORM P1 THRU P2
    STOP RUN.
P1.
    GO TO P2.
P2.
    DISPLAY 'P2'.
P3.
    DISPLAY 'P3'.
""") == ["P3"]
