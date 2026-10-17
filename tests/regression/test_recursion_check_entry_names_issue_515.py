"""Regression tests for issue #515: a CALL to the program's own ENTRY name.

``RecursionRiskAnalyzer`` treated a CALL as self-recursive only when its
target was the PROGRAM-ID. A CALL to one of the program's own ``ENTRY
'name'`` points re-enters the same load module just the same, and
codebase-graph already resolves ENTRY names to their program.
"""

from cobolparser import parse_cobol
from cobolparser.analysis.recursion_risk import RecursionRiskAnalyzer

_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RC1{recursive}.
       PROCEDURE DIVISION.
       P1.
           CALL 'RC1ALT'
           GOBACK.
       P2.
           ENTRY 'RC1ALT'.
           CALL 'RC1ALT'
           GOBACK.
"""

_NESTED = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OUTR.
       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL 'INR'
           GOBACK.
       ALT-PARA.
           ENTRY 'OUTRALT'.
           GOBACK.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INR.
       PROCEDURE DIVISION.
       INR-PARA.
           CALL 'OUTRALT'
           GOBACK.
       END PROGRAM INR.
       END PROGRAM OUTR.
"""


def _call_risks(source: str, unit: str | None = None):  # type: ignore[no-untyped-def]
    result = parse_cobol(source, filename="rc.cbl")
    assert result.ast is not None
    ast = result.ast
    if unit is not None:
        ast = {u.program_name: u for u in ast.program_units()}[unit]
    report = RecursionRiskAnalyzer().analyze(ast)
    return [r for r in report.risks if r.mechanism == "CALL"]


def test_call_to_own_entry_is_self_recursive() -> None:
    risks = _call_risks(_SOURCE.format(recursive=""))
    assert [(r.severity, r.program) for r in risks] == [
        ("HIGH", "RC1"),
        ("HIGH", "RC1"),
    ]
    assert "'RC1ALT', an ENTRY point of 'RC1'" in risks[0].explanation


def test_call_to_own_entry_of_recursive_program_is_low() -> None:
    risks = _call_risks(_SOURCE.format(recursive=" IS RECURSIVE"))
    assert [r.severity for r in risks] == ["LOW", "LOW"]


def test_call_to_program_id_wording_unchanged() -> None:
    source = _SOURCE.format(recursive="").replace("CALL 'RC1ALT'", "CALL 'RC1'")
    risks = _call_risks(source)
    assert len(risks) == 2
    assert "'RC1', the program's own PROGRAM-ID." in risks[0].explanation


def test_call_to_an_enclosing_programs_entry() -> None:
    risks = _call_risks(_NESTED, unit="INR")
    assert [(r.severity, r.program) for r in risks] == [("HIGH", "OUTR")]
    # The container's own unit does not claim the inner CALL.
    assert _call_risks(_NESTED, unit="OUTR") == []
