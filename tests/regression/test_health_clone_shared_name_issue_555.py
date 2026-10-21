"""Regression tests for issue #555: a clone offender matched by bare name.

``TechnicalDebtAnalyzer._top_offenders`` tested ``proc.name`` against the
bare names of every clone-group member, so a paragraph ``CALC`` in one
section that was a clone made every other section's ``CALC`` a "member of a
duplicate-paragraph clone group" too. Clone members now carry the same
``qualified_name`` (``"CALC OF S1"``) the flow graph and dead-code items
use, and the match is by that key.
"""

from cobolparser import parse_cobol
from cobolparser.analysis.redundancy import RedundancyAnalyzer
from cobolparser.analysis.technical_debt import TechnicalDebtAnalyzer

_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A PIC 9.
       01 B PIC 9.
       01 C PIC 9.
       PROCEDURE DIVISION.
       MAIN SECTION.
       M1.
           PERFORM S1
           PERFORM S2
           PERFORM S3
           STOP RUN.
       S1 SECTION.
       CALC.
           ADD 1 TO A
           ADD 2 TO B
           ADD 3 TO C
           DISPLAY A B C.
       S2 SECTION.
       CALC.
           DISPLAY 'UNIQUE'.
       S3 SECTION.
       OTHER-CALC.
           ADD 1 TO A
           ADD 2 TO B
           ADD 3 TO C
           DISPLAY A B C.
"""

_CLONE_REASON = "member of a duplicate-paragraph clone group"


def _ast():  # type: ignore[no-untyped-def]
    result = parse_cobol(_SOURCE, filename="hd.cbl")
    assert result.ast is not None
    return result.ast


def test_clone_member_carries_qualified_name_for_a_shared_name() -> None:
    report = RedundancyAnalyzer().analyze(_ast())
    assert len(report.clone_groups) == 1
    members = report.clone_groups[0].members
    by_name = {m.name: m for m in members}
    assert set(by_name) == {"CALC", "OTHER-CALC"}
    assert by_name["CALC"].qualified_name == "CALC OF S1"
    assert by_name["CALC"].to_dict()["qualified_name"] == "CALC OF S1"
    # A unique name stays unqualified, and its dict shape is unchanged.
    assert by_name["OTHER-CALC"].qualified_name is None
    assert "qualified_name" not in by_name["OTHER-CALC"].to_dict()


def test_namesake_in_another_section_is_not_a_clone_offender() -> None:
    report = TechnicalDebtAnalyzer().analyze(_ast())
    cloned = [
        (o.name, o.location.line)
        for o in report.top_offenders
        if _CLONE_REASON in o.reasons
    ]
    assert cloned == [("CALC", 16), ("OTHER-CALC", 25)]
