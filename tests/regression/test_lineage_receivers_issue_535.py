"""Issue #535: field lineage linked the receivers of one statement to each
other. ``ADD 1 TO CNT-READ CNT-ERR`` is ``CNT-READ = CNT-READ + 1; CNT-ERR =
CNT-ERR + 1``, yet CNT-READ was reported as feeding CNT-ERR (and back). The
same for SUBTRACT / MULTIPLY / DIVIDE without GIVING, INSPECT TALLYING
counters and a STRING / UNSTRING POINTER or TALLYING IN item. Each receiver
is now fed only by the sending operands.
"""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.field_lineage import FieldFlowAnalyzer


def _edges(procedure: str) -> set[tuple[str, str]]:
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. L2.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        + "".join(
            f"       01  {name} PIC {pic}.\n"
            for name, pic in (
                ("IN-AMT", "9(5)"),
                ("A", "9(5)"),
                ("B", "9(5)"),
                ("S1", "X(20)"),
                ("OUT1", "X(20)"),
                ("W1", "X(5)"),
                ("W2", "X(5)"),
                ("P1", "99"),
                ("T1", "99"),
                ("CA", "9(3)"),
                ("CB", "9(3)"),
            )
        )
        + "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        "           ACCEPT IN-AMT\n"
        "           ACCEPT S1\n"
        + "".join(f"           {line}\n" for line in procedure.strip().splitlines())
        + "           STOP RUN.\n"
    )
    result = parse_cobol(source, "L2.cbl")
    assert result.ast is not None
    report = FieldFlowAnalyzer().analyze(result.ast)
    out: set[tuple[str, str]] = set()
    for edge in report.edges:
        data = edge.to_dict()
        src, tgt = data["source"], data["target"]
        if src.get("kind") == "item" and tgt.get("kind") == "item":
            out.add((src["name"], tgt["name"]))
    return out


@pytest.mark.parametrize(
    "statement, sources",
    [
        ("ADD 1 TO A B", set()),
        ("ADD IN-AMT TO A B", {"IN-AMT"}),
        ("SUBTRACT IN-AMT FROM A B", {"IN-AMT"}),
        ("MULTIPLY IN-AMT BY A B", {"IN-AMT"}),
        ("MULTIPLY 3 BY A B", set()),
        ("DIVIDE IN-AMT INTO A B", {"IN-AMT"}),
    ],
)
def test_arithmetic_receivers_do_not_feed_each_other(statement, sources) -> None:
    edges = _edges(statement)
    assert ("A", "B") not in edges
    assert ("B", "A") not in edges
    for source in sources:
        assert {(source, "A"), (source, "B")} <= edges


def test_inspect_counters_do_not_feed_each_other() -> None:
    edges = _edges("INSPECT S1 TALLYING CA FOR ALL 'A' CB FOR ALL 'B'")
    assert {("S1", "CA"), ("S1", "CB")} <= edges
    assert ("CA", "CB") not in edges
    assert ("CB", "CA") not in edges


def test_string_pointer_feeds_nothing_else() -> None:
    edges = _edges("STRING S1 DELIMITED BY SIZE INTO OUT1 WITH POINTER P1")
    assert ("S1", "OUT1") in edges
    assert ("P1", "OUT1") not in edges


def test_unstring_pointer_and_tally_feed_nothing_else() -> None:
    edges = _edges(
        "UNSTRING S1 DELIMITED BY ',' INTO W1 W2\n    WITH POINTER P1 TALLYING IN T1"
    )
    assert {("S1", "W1"), ("S1", "W2")} <= edges
    for rw in ("P1", "T1"):
        for other in ("W1", "W2", "P1", "T1"):
            if other != rw:
                assert (rw, other) not in edges


def test_compute_and_giving_still_link_operands() -> None:
    # COMPUTE A B = A + 1 does put A's value into B.
    assert ("A", "B") in _edges("COMPUTE A B = A + 1")
    # GIVING: A is read, B is the receiver.
    assert ("A", "B") in _edges("ADD IN-AMT A GIVING B")
    # A receiver that is also a sending operand feeds the other receivers.
    assert ("A", "B") in _edges("ADD A TO A B")
