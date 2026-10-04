"""Regression tests for issue #258: same-named items merged by name.

Two records carrying the same field names (the shape ``MOVE CORRESPONDING``
relies on), and paragraph names such as ``X1`` reused across sections, are
ordinary COBOL. The analyzers keyed them by bare name, so one entry stood
for both: unused fields and dead paragraphs were hidden, and program-flow
dropped the second paragraph and pointed ``PERFORM X1 OF S2`` at S1's.

Each item now keeps its bare ``name`` and, when the name is shared, gains a
``qualified_name`` (``"X1 OF S2"``, ``"AMT OF OUT-REC"``). A program with no
shared names produces exactly the output it did before.
"""

from cobolparser import (
    ComplexityAnalyzer,
    DeadCodeAnalyzer,
    ProgramFlowAnalyzer,
    UnusedVariableAnalyzer,
    parse_cobol,
)
from cobolparser.analysis._names import qualified_references
from cobolparser.analysis.unused_variables import _NON_IDENTIFIER_WORDS
from cobolparser.analysis.xref import XrefAnalyzer
from cobolparser.generators.flowchart import MermaidFlowchartGenerator

_RECORDS = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ANA8.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 IN-REC.
          05 CUST-ID   PIC X(4).
          05 AMT       PIC 9(4).
       01 OUT-REC.
          05 CUST-ID   PIC X(4).
          05 AMT       PIC 9(4).
       01 WS-X         PIC 9(4).
       PROCEDURE DIVISION.
{body}
           STOP RUN.
"""

_SECTIONS = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ANA3.
       PROCEDURE DIVISION.
       MAIN-SEC SECTION.
       MAIN-PARA.
{body}
           STOP RUN.
       S1 SECTION.
       X1.
           DISPLAY 'S1 X1 NEVER RUNS'.
       S1-EXIT.
           EXIT.
       S2 SECTION.
       X1.
           DISPLAY 'S2 X1'.
"""


def _ast(source: str):  # type: ignore[no-untyped-def]
    result = parse_cobol(source, filename="issue258.cbl")
    assert result.ast is not None
    return result.ast


def _records(body: str):  # type: ignore[no-untyped-def]
    return _ast(_RECORDS.format(body=body))


def _sections(body: str):  # type: ignore[no-untyped-def]
    return _ast(_SECTIONS.format(body=body))


class TestQualifiedReferences:
    def test_qualifiers_are_kept_and_each_qualifier_is_its_own_reference(self):
        refs = qualified_references("A OF B IN C", _NON_IDENTIFIER_WORDS)
        assert refs == {"A OF B OF C", "B OF C", "C"}

    def test_subscripts_never_qualify_and_keywords_never_take_a_qualifier(self):
        refs = qualified_references(
            "WS-TAB OF GRP (WS-I OF IDX-GRP) LENGTH OF WS-Y", _NON_IDENTIFIER_WORDS
        )
        assert refs == {
            "WS-TAB OF GRP",
            "GRP",
            "WS-I OF IDX-GRP",
            "IDX-GRP",
            "WS-Y",
        }


class TestUnusedVariables:
    def test_issue_repro_reports_the_unreferenced_output_field(self):
        ast = _records(
            "           MOVE CUST-ID OF IN-REC TO CUST-ID OF OUT-REC\n"
            "           ADD AMT IN IN-REC TO WS-X"
        )
        report = UnusedVariableAnalyzer().analyze(ast)
        assert [(i.name, i.location.line) for i in report.unused_items] == [("AMT", 10)]
        assert report.unused_items[0].qualified_name == "AMT OF OUT-REC"
        assert report.to_dict()["unused_variables"][0]["qualified_name"] == (
            "AMT OF OUT-REC"
        )

    def test_unqualified_reference_to_a_shared_name_keeps_every_candidate(self):
        ast = _records("           MOVE AMT TO WS-X")
        report = UnusedVariableAnalyzer().analyze(ast)
        assert "AMT" not in {i.name for i in report.unused_items}

    def test_unresolvable_qualifier_keeps_every_candidate(self):
        ast = _records("           MOVE AMT OF NO-SUCH-REC TO WS-X")
        report = UnusedVariableAnalyzer().analyze(ast)
        assert "AMT" not in {i.name for i in report.unused_items}

    def test_qualified_condition_name(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COND88.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 IN-REC.
          05 REC-STATUS PIC X.
             88 REC-OK VALUE 'Y'.
       01 OUT-REC.
          05 REC-STATUS PIC X.
             88 REC-OK VALUE 'Y'.
       PROCEDURE DIVISION.
           IF REC-OK OF IN-REC DISPLAY 'OK' END-IF
           STOP RUN.
"""
        report = UnusedVariableAnalyzer().analyze(_ast(source))
        assert [i.qualified_name for i in report.unused_items] == [
            None,
            "REC-STATUS OF OUT-REC",
        ]
        assert report.unused_items[0].name == "OUT-REC"

    def test_redefines_resolves_to_its_own_sibling(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. REDEF.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 IN-REC.
          05 KEY-AREA  PIC X(4).
          05 KEY-NUM REDEFINES KEY-AREA PIC 9(4).
       01 OUT-REC.
          05 KEY-AREA  PIC X(4).
       PROCEDURE DIVISION.
           DISPLAY KEY-NUM
           STOP RUN.
"""
        report = UnusedVariableAnalyzer().analyze(_ast(source))
        assert [i.qualified_name for i in report.unused_items] == [
            None,
            "KEY-AREA OF OUT-REC",
        ]

    def test_unique_names_carry_no_qualified_name(self):
        ast = _records("           MOVE CUST-ID OF IN-REC TO CUST-ID OF OUT-REC")
        report = UnusedVariableAnalyzer().analyze(ast)
        ws_x = next(i for i in report.unused_items if i.name == "WS-X")
        assert ws_x.qualified_name is None
        assert "qualified_name" not in ws_x.to_dict()


class TestXref:
    def test_each_record_has_its_own_entry_and_references(self):
        ast = _records(
            "           MOVE CUST-ID OF IN-REC TO CUST-ID OF OUT-REC\n"
            "           ADD AMT IN IN-REC TO WS-X"
        )
        report = XrefAnalyzer().analyze(ast)
        refs = {
            e.qualified_name: [r.role for r in e.references]
            for e in report.entries
            if e.qualified_name
        }
        assert refs == {
            "AMT OF IN-REC": ["read"],
            "AMT OF OUT-REC": [],
            "CUST-ID OF IN-REC": ["read"],
            "CUST-ID OF OUT-REC": ["write"],
        }
        assert report.duplicate_declarations == []


class TestDeadCode:
    def test_issue_repro_reports_the_shadowed_paragraph(self):
        report = DeadCodeAnalyzer().analyze(_sections("           PERFORM X1 OF S2"))
        dead = [(i.name, i.location.line, i.qualified_name) for i in report.dead_items]
        assert dead == [
            ("S1", 8, None),
            ("X1", 9, "X1 OF S1"),
            ("S1-EXIT", 11, None),
        ]
        assert report.dead_items[1].to_dict()["qualified_name"] == "X1 OF S1"

    def test_unqualified_reference_resolves_within_its_own_section(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SAMESEC.
       PROCEDURE DIVISION.
       MAIN-SEC SECTION.
       MAIN-PARA.
           PERFORM S2
           STOP RUN.
       S1 SECTION.
       X1.
           DISPLAY 'S1 X1'.
       S2 SECTION.
       S2-START.
           PERFORM X1
           GO TO S2-END.
       X1.
           DISPLAY 'S2 X1'.
       S2-END.
           EXIT.
"""
        report = DeadCodeAnalyzer().analyze(_ast(source))
        assert [(i.name, i.qualified_name) for i in report.dead_items] == [
            ("S1", None),
            ("X1", "X1 OF S1"),
        ]

    def test_ambiguous_reference_keeps_every_candidate_alive(self):
        report = DeadCodeAnalyzer().analyze(_sections("           PERFORM X1"))
        assert [i.name for i in report.dead_items] == ["S1-EXIT"]


class TestProgramFlow:
    def test_issue_repro_has_both_paragraphs_and_the_right_perform_target(self):
        report = ProgramFlowAnalyzer().analyze(_sections("           PERFORM X1 OF S2"))
        nodes = [(n.name, n.qualified_name, n.location.line) for n in report.nodes]
        assert nodes == [
            ("MAIN-SEC", None, 4),
            ("MAIN-PARA", None, 5),
            ("S1", None, 8),
            ("X1", "X1 OF S1", 9),
            ("S1-EXIT", None, 11),
            ("S2", None, 13),
            ("X1", "X1 OF S2", 14),
        ]
        performs = [
            (e.source, e.target) for e in report.edges if e.edge_type.value == "PERFORM"
        ]
        assert performs == [("MAIN-PARA", "X1 OF S2")]
        assert "X1 OF S1" in report.unreachable_nodes
        assert "X1 OF S2" not in report.unreachable_nodes
        # Each paragraph is scanned into its own node.
        assert [n.statement_count for n in report.nodes if n.name == "X1"] == [1, 1]

    def test_to_dict_adds_qualified_name_only_where_the_name_is_shared(self):
        data = (
            ProgramFlowAnalyzer()
            .analyze(_sections("           PERFORM X1 OF S2"))
            .to_dict()
        )
        by_line = {n["location"]["line"]: n for n in data["nodes"]}
        assert by_line[14]["name"] == "X1"
        assert by_line[14]["qualified_name"] == "X1 OF S2"
        assert "qualified_name" not in by_line[5]

    def test_ambiguous_perform_targets_every_candidate(self):
        report = ProgramFlowAnalyzer().analyze(_sections("           PERFORM X1"))
        performs = sorted(
            e.target for e in report.edges if e.edge_type.value == "PERFORM"
        )
        assert performs == ["X1 OF S1", "X1 OF S2"]

    def test_complexity_measures_each_paragraph_on_its_own(self):
        report = ComplexityAnalyzer().analyze(_sections("           PERFORM X1 OF S2"))
        x1 = {p.qualified_name: p for p in report.procedures if p.name == "X1"}
        assert set(x1) == {"X1 OF S1", "X1 OF S2"}
        assert x1["X1 OF S2"].fan_in == 1
        assert x1["X1 OF S1"].fan_in == 0

    def test_flowchart_draws_both_paragraphs(self):
        report = ProgramFlowAnalyzer().analyze(_sections("           PERFORM X1 OF S2"))
        chart = MermaidFlowchartGenerator().generate(report)
        assert "X1_OF_S1" in chart and "X1_OF_S2" in chart
