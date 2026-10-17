"""Issue #534: ``MULTIPLY n BY a b`` / ``DIVIDE n INTO c d`` with no GIVING
mean ``a = a * n; b = b * n`` -- every BY/INTO receiver is read *and*
written. xref read only ``operands[:2]`` (the multiplier and the first
receiver), so every later receiver was graded write-only: program-signature
called a modified LINKAGE parameter ``output`` and business-rules left it
out of the rule's ``inputs``. Field lineage, built on the same roles, also
let one receiver feed the next (``A -> B``) although neither reads the other.
"""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.business_rules import BusinessRuleExtractor
from cobolparser.analysis.field_lineage import FieldFlowAnalyzer
from cobolparser.analysis.program_signature import ProgramSignatureExtractor
from cobolparser.analysis.xref import XrefAnalyzer

SIGNATURE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. S2.
       DATA DIVISION.
       LINKAGE SECTION.
       01  LK-A    PIC 9(5).
       01  LK-B    PIC 9(5).
       01  LK-C    PIC 9(5).
       01  LK-D    PIC 9(5).
       01  LK-E    PIC 9(5).
       01  LK-F    PIC 9(5).
       01  LK-G    PIC 9(5).
       PROCEDURE DIVISION USING LK-A LK-B LK-C LK-D LK-E LK-F LK-G.
       MAIN-PARA.
           MULTIPLY 3 BY LK-A LK-B
           DIVIDE 2 INTO LK-C LK-D
           DIVIDE LK-E BY 2 GIVING LK-F
           MULTIPLY LK-E BY 2 GIVING LK-G
           GOBACK.
"""

RULES = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  A    PIC 9(5).
       01  B    PIC 9(5).
       01  C    PIC 9(5).
       01  D    PIC 9(5).
       01  N    PIC 9(5).
       PROCEDURE DIVISION.
       MAIN-PARA.
           ACCEPT A
           ACCEPT B
           ACCEPT N
           MULTIPLY N BY A B
           MOVE 12 TO C D
           DIVIDE 2 INTO C D
           ADD N TO C D
           DISPLAY A B C D
           GOBACK.
"""


def _ast(source: str):
    result = parse_cobol(source, filename="t.cbl")
    assert result.ast is not None and result.errors == [], result.errors
    return result.ast


def test_every_receiver_is_input_output() -> None:
    primary = ProgramSignatureExtractor().analyze(_ast(SIGNATURE)).primary
    assert primary is not None
    directions = {p.name: p.direction for p in primary.parameters}
    assert directions == {
        "LK-A": "input-output",
        "LK-B": "input-output",
        "LK-C": "input-output",
        "LK-D": "input-output",
        "LK-E": "input",
        "LK-F": "output",  # GIVING: written only
        "LK-G": "output",
    }


@pytest.mark.parametrize("name", ["LK-B", "LK-D"])
def test_xref_reads_every_receiver(name: str) -> None:
    entry = XrefAnalyzer().analyze(_ast(SIGNATURE)).entry_for(name)
    assert entry is not None
    assert {r.role for r in entry.references} == {"read", "write"}


def test_business_rule_inputs_list_every_receiver() -> None:
    report = BusinessRuleExtractor().analyze(_ast(RULES))
    by_line = {rule.location.line: rule for rule in report.rules}
    assert set(by_line[15].inputs) >= {"A", "B", "N"}
    assert set(by_line[17].inputs) >= {"C", "D"}


def test_one_receiver_never_feeds_another() -> None:
    edges = FieldFlowAnalyzer().analyze(_ast(RULES)).to_dict()["edges"]
    arith = {
        (e["source"]["name"], e["target"]["name"])
        for e in edges
        if e["kind"] == "arith"
    }
    for a, b in (("A", "B"), ("B", "A"), ("C", "D"), ("D", "C")):
        assert (a, b) not in arith, arith
    # ... while the sending operand still feeds every receiver
    assert {("N", "A"), ("N", "B"), ("N", "C"), ("N", "D")} <= arith
