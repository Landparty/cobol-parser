"""Issue #582: gen-fixtures listed every CALL argument that is not a data item
-- numeric literals, figurative constants, ``OMITTED``, ``LENGTH OF x`` and
``ADDRESS OF x`` -- as "argument X not resolvable in layout index", burying
real gaps and contradicting ``coverage.unresolved_boundaries == 0``. The
boundary inventory also gave ``OMITTED`` a data direction.
"""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.boundary_inventory import (
    BoundaryInventoryAnalyzer,
    call_argument_data_name,
)
from cobolparser.generators import ProgramFixtureGenerator, ProgramLayoutIndex

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-K PIC 9(4).
       PROCEDURE DIVISION.
           CALL 'SUBV' USING BY VALUE 0 BY CONTENT 12 WS-K
           CALL 'SUBL' USING BY CONTENT LENGTH OF WS-K
                             BY REFERENCE ADDRESS OF WS-K
           CALL 'SUBO' USING OMITTED WS-K
           CALL 'SUBZ' USING BY CONTENT ZERO SPACES
           CALL 'SUBN' USING WS-NOPE
           GOBACK.
"""


def _ast():
    result = parse_cobol(SOURCE, filename="CALLS.cbl")
    assert result.ast is not None and result.errors == [], result.errors
    return result.ast


def _call_args() -> dict[str, list]:
    ast = _ast()
    report = BoundaryInventoryAnalyzer().analyze(ast, ProgramLayoutIndex.build(ast))
    return {b.ref.key: b.call_args for b in report.boundaries}


def test_only_the_genuinely_missing_data_name_is_unresolved(tmp_path) -> None:
    path = tmp_path / "CALLS.cbl"
    path.write_text(SOURCE)
    bundle = ProgramFixtureGenerator().generate_from_file(str(path), seed=1)
    argument_gaps = [u for u in bundle.unresolved if "argument" in u]
    assert argument_gaps == [
        "CALL SUBN: argument WS-NOPE not resolvable in layout index"
    ]


def test_omitted_keeps_its_position_with_no_direction() -> None:
    omitted, ws_k = _call_args()["SUBO"]
    assert (omitted.name, omitted.direction, omitted.provenance) == (
        "OMITTED",
        "NONE",
        "omitted",
    )
    assert ws_k.name == "WS-K"


def test_address_of_resolves_against_its_field() -> None:
    _, address = _call_args()["SUBL"]
    assert address.name == "ADDRESS OF WS-K"
    assert address.provenance != "assumed-bidirectional"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0", None),
        ("-12.5", None),
        ("'A'", None),
        ("X'00'", None),
        ("ZERO", None),
        ("spaces", None),
        ("ALL '*'", None),
        ("OMITTED", None),
        ("LENGTH OF WS-K", None),
        ("FUNCTION UPPER-CASE(WS-K)", None),
        ("ADDRESS OF WS-K", "WS-K"),
        ("WS-K", "WS-K"),
        ("WS-K OF WS-REC", "WS-K OF WS-REC"),
    ],
)
def test_call_argument_data_name(text: str, expected: str | None) -> None:
    assert call_argument_data_name(text) == expected
