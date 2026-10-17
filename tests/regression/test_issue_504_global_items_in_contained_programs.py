"""A contained program sees its container's GLOBAL items (#504).

unused-variables already honoured GLOBAL, but xref (and through it MCP
``explain_symbol``), field lineage and move-type-check resolved a contained
program's references against its own DATA DIVISION only: a GLOBAL item read
in the inner program was "undefined", lineage dropped its edges, and a MOVE
to it was unresolved. move-type-check also walked contained programs from
the outer unit, so an inner namesake poisoned an outer item's category and
the outer unit reported the inner unit's MOVEs.
"""

from __future__ import annotations

from pathlib import Path

from cobolparser import MoveTypeChecker, parse_cobol
from cobolparser.analysis.field_lineage import FieldFlowAnalyzer
from cobolparser.analysis.unused_variables import inherited_data_records
from cobolparser.analysis.xref import XrefAnalyzer
from cobolparser.mcp import CobolTools, Workspace


def _program(*lines: str) -> str:
    return "".join(f"       {line}\n" for line in lines)


ISSUE_REPRO = _program(
    "IDENTIFICATION DIVISION.",
    "PROGRAM-ID. OUTERP.",
    "DATA DIVISION.",
    "WORKING-STORAGE SECTION.",
    "01  A   PIC X(5) GLOBAL.",
    "01  B   PIC X(5).",
    "PROCEDURE DIVISION.",
    "    CALL 'INNER1' USING A B.",
    "    GOBACK.",
    "IDENTIFICATION DIVISION.",
    "PROGRAM-ID. INNER1.",
    "DATA DIVISION.",
    "LINKAGE SECTION.",
    "01  LX  PIC X(5).",
    "PROCEDURE DIVISION USING LX.",
    "    DISPLAY LX A.",
    "    GOBACK.",
    "END PROGRAM INNER1.",
    "END PROGRAM OUTERP.",
)


def _units(source: str):
    result = parse_cobol(source)
    assert result.success, result.errors
    return result.ast, result.ast.contained_programs[0]


class TestXref:
    def test_inner_unit_resolves_the_global_item(self):
        _, inner = _units(ISSUE_REPRO)
        report = XrefAnalyzer().analyze(inner)
        assert report.undefined == []
        entry = report.entry_for("A")
        assert entry is not None and entry.definition.line == 5
        assert [r.location.line for r in entry.references] == [16]
        # Only GLOBAL records are visible: B is not.
        assert report.entry_for("B") is None

    def test_outer_unit_lists_the_inner_read(self):
        outer, _ = _units(ISSUE_REPRO)
        entry = XrefAnalyzer().analyze(outer).entry_for("A")
        assert [(r.location.line, r.role) for r in entry.references] == [
            (8, "call-argument"),
            (16, "read"),
        ]

    def test_a_redeclared_name_hides_the_global_one(self):
        source = ISSUE_REPRO.replace(
            "       01  LX  PIC X(5).\n",
            "       01  LX  PIC X(5).\n       01  A   PIC X(5).\n",
        )
        outer, inner = _units(source)
        assert inherited_data_records(inner) == []
        inner_a = XrefAnalyzer().analyze(inner).entry_for("A")
        assert inner_a.definition.line == 15
        outer_a = XrefAnalyzer().analyze(outer).entry_for("A")
        assert [r.location.line for r in outer_a.references] == [8]


def test_mcp_explain_symbol_declares_it(tmp_path: Path):
    (tmp_path / "G.cbl").write_text(ISSUE_REPRO)
    result = CobolTools(Workspace(tmp_path)).explain_symbol(
        "G.cbl", "A", program="INNER1"
    )
    (symbol,) = result["answer"]["symbols"]
    assert symbol["declared"] is True
    assert symbol["declared_at"]["line"] == 5
    assert [r["location"]["line"] for r in symbol["references"]] == [16]
    assert result["caveats"] == []


def test_lineage_traces_the_global_item():
    _, inner = _units(ISSUE_REPRO)
    report = FieldFlowAnalyzer().analyze(inner)
    assert not any("not declared" in c for c in report.caveats)
    assert ("A", "SYSOUT") in {(e.source.name, e.target.name) for e in report.edges}


class TestMoveTypeCheck:
    def test_move_to_a_global_field_is_checked_in_the_inner_unit(self):
        outer, inner = _units(
            _program(
                "IDENTIFICATION DIVISION.",
                "PROGRAM-ID. OUTERP.",
                "DATA DIVISION.",
                "WORKING-STORAGE SECTION.",
                "01  G GLOBAL.",
                "    05 G-SUB PIC 9(3).",
                "PROCEDURE DIVISION.",
                "    CALL 'INNER1'.",
                "    GOBACK.",
                "IDENTIFICATION DIVISION.",
                "PROGRAM-ID. INNER1.",
                "PROCEDURE DIVISION.",
                "    MOVE 'ABC' TO G-SUB.",
                "    GOBACK.",
                "END PROGRAM INNER1.",
                "END PROGRAM OUTERP.",
            )
        )
        inner_report = MoveTypeChecker().check(inner)
        assert [v.target_name for v in inner_report.violations] == ["G-SUB"]
        assert inner_report.unresolved_count == 0
        # The inner MOVE belongs to the inner unit, not the outer one.
        assert MoveTypeChecker().check(outer).violations == []

    def test_an_inner_namesake_does_not_poison_the_outer_item(self):
        outer, inner = _units(
            _program(
                "IDENTIFICATION DIVISION.",
                "PROGRAM-ID. OUTERP.",
                "DATA DIVISION.",
                "WORKING-STORAGE SECTION.",
                "01  WS-X PIC 9(3).",
                "PROCEDURE DIVISION.",
                "    MOVE 'ABC' TO WS-X.",
                "    GOBACK.",
                "IDENTIFICATION DIVISION.",
                "PROGRAM-ID. INNER1.",
                "DATA DIVISION.",
                "WORKING-STORAGE SECTION.",
                "01  WS-X PIC X(3).",
                "PROCEDURE DIVISION.",
                "    MOVE 'ABC' TO WS-X.",
                "    GOBACK.",
                "END PROGRAM INNER1.",
                "END PROGRAM OUTERP.",
            )
        )
        outer_report = MoveTypeChecker().check(outer)
        assert [(v.target_name, v.location.line) for v in outer_report.violations] == [
            ("WS-X", 7)
        ]
        assert outer_report.unresolved_count == 0
        assert MoveTypeChecker().check(inner).violations == []
