"""Regression tests for issue #490: a BY VALUE parameter is input only.

``ProgramSignatureExtractor`` graded direction from xref roles alone, so a
``PROCEDURE DIVISION USING BY VALUE LK-N`` parameter the callee writes was
reported ``input-output`` -- telling callers (``program-signature``, MCP
``program_brief``) the callee may change an argument it receives a copy of.
Direction is graded per entry point, since the same item may be BY
REFERENCE on another.
"""

from cobolparser import parse_cobol
from cobolparser.analysis.program_signature import ProgramSignatureExtractor

_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BV.
       DATA DIVISION.
       LINKAGE SECTION.
       01  LK-N        PIC S9(9) COMP-5.
       01  LK-W        PIC S9(9) COMP-5.
       PROCEDURE DIVISION USING BY VALUE LK-N LK-W.
       MAIN-PARA.
           ADD 1 TO LK-N
           DISPLAY LK-N
           MOVE 5 TO LK-W
           GOBACK.
       ALT-PARA.
           ENTRY 'BVALT' USING BY REFERENCE LK-N.
           ADD 1 TO LK-N
           GOBACK.
"""


def _directions() -> dict[str, list[tuple[str, str, str | None]]]:
    result = parse_cobol(_SOURCE, filename="bv.cbl")
    assert result.ast is not None
    signature = ProgramSignatureExtractor().analyze(result.ast)
    return {
        entry.name: [(p.name, p.direction, p.by_clause) for p in entry.parameters]
        for entry in signature.entry_points
    }


def test_by_value_parameter_the_callee_writes_is_input() -> None:
    assert _directions()["BV"] == [
        ("LK-N", "input", "VALUE"),
        # Write-only BY VALUE: callee-local scratch, input from the caller's
        # side as well.
        ("LK-W", "input", "VALUE"),
    ]


def test_same_item_by_reference_on_another_entry_keeps_its_direction() -> None:
    assert _directions()["BVALT"] == [("LK-N", "input-output", "REFERENCE")]
