"""Regressions fixed by moving the analyzers onto one statement walker and
one name normalizer (audit 2026-09-27 §3.5).

Each analyzer used to keep its own list of nested-body attributes. The lists
had drifted: several missed RECEIVE's ``NO DATA`` / ``WITH DATA`` bodies,
``bug_patterns`` also missed ``NOT AT END-OF-PAGE`` and never entered a
SEARCH WHEN body (it read the arm's statements with ``getattr`` on a dict).
Every test here shows a statement the old private list never visited. The
name half: ``_names.base_data_name`` returned a glued ``WS-ENT(1)``
unchanged, so a lookup by the bare name missed it.
"""

from __future__ import annotations

from typing import Any

from cobolparser import parse_cobol
from cobolparser.analysis import bug_patterns
from cobolparser.analysis._names import (
    bare_item_name,
    base_data_name,
    strip_qualification,
    strip_subscripts,
)
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.business_rules import BusinessRuleExtractor
from cobolparser.analysis.complexity import ComplexityAnalyzer
from cobolparser.analysis.const_fold import ConstantFolder
from cobolparser.analysis.constraints import ConstraintExtractor
from cobolparser.analysis.program_flow import FlowEdgeType, ProgramFlowAnalyzer
from cobolparser.analysis.redundancy import RedundancyAnalyzer
from cobolparser.analysis.value_tracker import DynamicCallAnalyzer
from cobolparser.generators import ProgramLayoutIndex

_HEAD = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RECV.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-MSG PIC X(10).
       01 WS-FLAG PIC X VALUE 'N'.
       01 WS-T.
          05 WS-E PIC X OCCURS 3 INDEXED BY WS-I.
       COMMUNICATION SECTION.
       CD IN-Q FOR INPUT.
          05 IN-STATUS PIC XX.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'N' TO WS-FLAG
"""

# The IF sits on line 18, the CALL on line 21.
_NO_DATA_BODY = """\
           RECEIVE IN-Q MESSAGE INTO WS-MSG
               NO DATA
                   MOVE 'Y' TO WS-FLAG
                   IF WS-FLAG = 'Y'
                       PERFORM EMPTY-PARA
                   END-IF
                   CALL 'SUBPGM'
           END-RECEIVE
"""

_TAIL = """\
           SEARCH WS-E
               AT END DISPLAY 'NONE'
               WHEN WS-E (WS-I) = 'X'
                   DISPLAY 'FOUND'
           END-SEARCH
           DISPLAY WS-FLAG
           STOP RUN.
       EMPTY-PARA.
           DISPLAY 'EMPTY'.
"""

_PLAIN_RECEIVE = """\
           RECEIVE IN-Q MESSAGE INTO WS-MSG
           END-RECEIVE
"""


def _ast(body: str = _NO_DATA_BODY) -> Any:
    result = parse_cobol(_HEAD + body + _TAIL)
    assert result.success, result.errors
    return result.ast


def test_program_flow_follows_receive_no_data_body() -> None:
    """A PERFORM inside NO DATA made no edge, so EMPTY-PARA read unreachable."""
    edges = {
        (edge.source, edge.target, edge.edge_type)
        for edge in ProgramFlowAnalyzer().analyze(_ast()).edges
    }
    assert ("MAIN-PARA", "EMPTY-PARA", FlowEdgeType.PERFORM) in edges
    assert ("MAIN-PARA", "SUBPGM", FlowEdgeType.CALL) in edges


def test_complexity_counts_receive_no_data_as_a_decision() -> None:
    def main_complexity(body: str) -> int:
        procedures = ComplexityAnalyzer().analyze(_ast(body)).to_dict()["procedures"]
        return next(
            p["cyclomatic_complexity"] for p in procedures if p["name"] == "MAIN-PARA"
        )

    # NO DATA / WITH DATA is one decision, plus the IF nested in the body.
    assert main_complexity(_NO_DATA_BODY) == main_complexity(_PLAIN_RECEIVE) + 2


def test_bug_patterns_walk_enters_receive_and_search_when_bodies() -> None:
    statements = _ast().procedure_division.paragraphs[0].statements
    walked = list(bug_patterns.walk_statements(statements))
    types = [s.statement_type for s in walked]
    assert types[:6] == ["MOVE", "RECEIVE", "MOVE", "IF", "PERFORM", "CALL"]
    displayed = [s.operands[0] for s in walked if s.statement_type == "DISPLAY"]
    assert any("FOUND" in text for text in displayed)  # the SEARCH WHEN body


def test_bug_patterns_walk_enters_not_at_end_of_page() -> None:
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EOP.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT RPT ASSIGN TO 'RPT'.
       DATA DIVISION.
       FILE SECTION.
       FD RPT LINAGE IS 60 LINES.
       01 RPT-LINE PIC X(80).
       PROCEDURE DIVISION.
       MAIN-PARA.
           WRITE RPT-LINE
               AT END-OF-PAGE DISPLAY 'EOP'
               NOT AT END-OF-PAGE DISPLAY 'NOT-EOP'
           END-WRITE
           STOP RUN.
"""
    result = parse_cobol(source)
    write = result.ast.procedure_division.paragraphs[0].statements[0]
    assert write.not_at_eop_clause
    walked = list(bug_patterns.walk_statements([write]))
    assert any("NOT-EOP" in s.operands[0] for s in walked[1:])


def test_boundary_inventory_sees_call_in_no_data_body() -> None:
    ast = _ast()
    report = BoundaryInventoryAnalyzer().analyze(ast, ProgramLayoutIndex.build(ast))
    assert [(b.ref.category, b.ref.line) for b in report.boundaries] == [("CALL", 21)]


def test_constraints_extract_branch_in_no_data_body() -> None:
    ast = _ast()
    index = ProgramLayoutIndex.build(ast)
    boundaries = BoundaryInventoryAnalyzer().analyze(ast, index)
    branches = ConstraintExtractor().extract(ast, index, boundaries).branches
    assert "MAIN-PARA@18:13" in {branch.branch_id for branch in branches}


def test_const_fold_poisons_a_write_in_no_data_body() -> None:
    """``MOVE 'Y' TO WS-FLAG`` under NO DATA may run: WS-FLAG is not 'N'."""
    ast = _ast()
    known = ConstantFolder().fold(ast, ProgramLayoutIndex.build(ast)).to_dict()
    assert "WS-FLAG" not in known["known"]


def test_business_rules_guard_no_data_body() -> None:
    rules = BusinessRuleExtractor().analyze(_ast()).to_dict()["rules"]
    nested_if = next(r for r in rules if r["location"]["line"] == 18)
    assert nested_if["guards"] == ["NO DATA (RECEIVE IN-Q WS-MSG)"]


def test_redundancy_fingerprints_the_no_data_body() -> None:
    def count(body: str) -> int:
        report = RedundancyAnalyzer().analyze(_ast(body)).to_dict()
        main = next(
            p for p in report["paragraph_fingerprints"] if p["name"] == "MAIN-PARA"
        )
        return int(main["statement_count"])

    # The MOVE, PERFORM and CALL leaves inside NO DATA (and the IF holding
    # the PERFORM) are now part of the paragraph's fingerprint; they used to
    # count for nothing.
    assert count(_NO_DATA_BODY) == count(_PLAIN_RECEIVE) + 3


class TestNameNormalizers:
    def test_base_data_name_strips_a_glued_subscript(self) -> None:
        assert base_data_name("WS-TAB(3)") == "WS-TAB"
        assert base_data_name("T-E(IX)(1:2)") == "T-E"
        assert base_data_name("WS-TAB ( 3 )") == "WS-TAB"
        assert base_data_name("WS-N OF GRP") == "WS-N"
        assert base_data_name("ws-n in grp") == "ws-n"
        # Literals and anything else stay whole.
        assert base_data_name("'A(B'") == "'A(B'"
        assert base_data_name("ALL 'X'") == "ALL 'X'"
        assert base_data_name("FUNCTION UPPER-CASE(X)") == "FUNCTION UPPER-CASE(X)"

    def test_strip_subscripts_keeps_qualification(self) -> None:
        assert strip_subscripts("WS-T ( 1 )") == "WS-T"
        assert strip_subscripts("WS-B(1:1)") == "WS-B"
        assert strip_subscripts("A OF G (2)") == "A OF G"
        assert strip_subscripts(" X ") == "X"

    def test_strip_qualification(self) -> None:
        assert strip_qualification("AMT IN OUT-GRP OF OUT-REC") == "AMT"
        assert strip_qualification("amt\tof rec") == "amt"
        assert strip_qualification("AMT") == "AMT"

    def test_bare_item_name(self) -> None:
        assert bare_item_name("ws-stmt(1:80)") == "WS-STMT"
        assert bare_item_name("WS-STMT OF WS-REC") == "WS-STMT"
        assert bare_item_name("WS-A OF GRP(1)") == "WS-A"

    def test_dynamic_call_follows_a_glued_subscripted_source(self) -> None:
        """``MOVE WS-ENT(1) TO WS-PGM``: the MOVE parser glues the source's
        subscript on; its values were looked up under ``WS-ENT(1)`` and lost."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DYN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-PGM PIC X(8).
       01 WS-TAB.
          05 WS-ENT PIC X(8) OCCURS 3.
       PROCEDURE DIVISION.
       P1.
           MOVE 'PGMB' TO WS-ENT(1)
           MOVE WS-ENT(1) TO WS-PGM
           CALL WS-PGM
           STOP RUN.
"""
        ast = parse_cobol(source).ast
        DynamicCallAnalyzer().analyze(ast)
        call = ast.procedure_division.paragraphs[0].statements[2]
        assert call.possible_values == ["PGMB"]
        assert not call.get_metadata("possible_values_incomplete")
