"""Analyzer bugs the open-source corpus run turned up (2026-11-11)."""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.analysis.dead_code import DeadCodeAnalyzer
from cobolparser.analysis.program_flow.analyzer import ProgramFlowAnalyzer
from cobolparser.analysis.redundancy import RedundancyAnalyzer
from cobolparser.analysis.unused_variables import UnusedVariableAnalyzer
from cobolparser.analysis.value_tracker import DynamicCallAnalyzer
from cobolparser.layout.copybook import parse_copybook_records
from cobolparser.layout.fields import (
    _MAX_EXPANDED_OCCURRENCES,
    flatten_record,
    occurs_expansion_caveats,
)
from cobolparser.models import CobolProgram


def _ast(source: str) -> CobolProgram:
    result = parse_cobol(source)
    assert result.ast is not None and not result.errors, result.errors
    return result.ast


DYNAMIC_CALL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DYN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-PGM PIC X(8) VALUE 'SUBA'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           ACCEPT WS-PGM
           PERFORM CALL-PARA
           STOP RUN.
       CALL-PARA.
           MOVE 'SUBB' TO WS-PGM
           EXEC CICS XCTL PROGRAM(WS-PGM) END-EXEC
           DISPLAY 'DONE'.
       OTHER-PARA.
           MOVE 'SUBB' TO WS-PGM
           EXEC CICS XCTL PROGRAM(WS-PGM) END-EXEC
           DISPLAY 'DONE'.
"""


def test_clone_digests_ignore_xctl_target_annotations() -> None:
    fresh = RedundancyAnalyzer().analyze(_ast(DYNAMIC_CALL)).to_dict()
    annotated = _ast(DYNAMIC_CALL)
    DynamicCallAnalyzer().analyze(annotated)
    calls = annotated.find_all_by_type("ExecCicsStatement")
    assert all(call.get_metadata("possible_values_incomplete") for call in calls)
    assert RedundancyAnalyzer().analyze(annotated).to_dict() == fresh


VARYING_WITHOUT_BY = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. V.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 K PIC 99.
       01 J PIC 99.
       PROCEDURE DIVISION.
           PERFORM VARYING K FROM 1 UNTIL K > 5
               AFTER J FROM 1 UNTIL J > 2
               DISPLAY 'X'
           END-PERFORM
           STOP RUN.
"""


def test_perform_varying_without_by_implies_by_one() -> None:
    result = parse_cobol(VARYING_WITHOUT_BY)
    assert result.ast is not None and not result.errors and not result.warnings
    (perform,) = result.ast.find_all_by_type("PerformStatement")
    data = perform.to_dict()
    assert data["varying_clause"]["by_value"] == "1"
    assert data["after_clauses"][0]["by_value"] == "1"
    assert perform.get_metadata("by_implied") is True
    unused = UnusedVariableAnalyzer().analyze(result.ast).to_dict()
    assert not unused["unused_variables"]


def test_perform_varying_with_by_is_not_marked_implied() -> None:
    ast = _ast(VARYING_WITHOUT_BY.replace("FROM 1 UNTIL K", "FROM 1 BY 2 UNTIL K"))
    perform = ast.find_all_by_type("PerformStatement")[0]
    assert perform.to_dict()["varying_clause"]["by_value"] == "2"


QUALIFIED_ALTER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. A.
       PROCEDURE DIVISION.
       S1 SECTION.
       P-MAIN.
           ALTER P-A IN S1 TO PROCEED TO P-X OF S2.
           PERFORM P-A.
           STOP RUN.
       P-A.
           GO TO P-X.
       P-X.
           DISPLAY 'S1'
           STOP RUN.
       S2 SECTION.
       P-X.
           DISPLAY 'S2'.
"""


def test_alter_keeps_section_qualifiers() -> None:
    (alter,) = _ast(QUALIFIED_ALTER).find_all_by_type("AlterStatement")
    assert alter.alterations == [
        {
            "from_paragraph": "P-A",
            "to_paragraph": "P-X",
            "from_qualifier": "S1",
            "to_qualifier": "S2",
        }
    ]


def test_unqualified_alter_has_no_qualifier_keys() -> None:
    source = QUALIFIED_ALTER.replace(" IN S1", "").replace(" OF S2", "")
    (alter,) = _ast(source).find_all_by_type("AlterStatement")
    assert alter.alterations == [{"from_paragraph": "P-A", "to_paragraph": "P-X"}]


def test_qualified_alter_target_is_live_in_its_own_section() -> None:
    dead = DeadCodeAnalyzer().analyze(_ast(QUALIFIED_ALTER)).to_dict()["dead_code"]
    assert not [d for d in dead if d["name"] == "P-X"]


def test_qualified_alter_edge_points_at_the_named_section() -> None:
    flow = ProgramFlowAnalyzer().analyze(_ast(QUALIFIED_ALTER)).to_dict()
    alter_targets = {
        edge["target"] for edge in flow["edges"] if edge["type"] == "ALTER"
    }
    assert alter_targets
    assert alter_targets == {"P-X OF S2"}


NESTED_TABLES = """\
       01 REC.
          05 OUTER OCCURS 10.
             10 INNER OCCURS 2200.
{fields}
"""


def test_occurs_budget_counts_every_field_of_a_table() -> None:
    fields = "\n".join(f"                15 F{i} PIC X." for i in range(47))
    record = parse_copybook_records(NESTED_TABLES.format(fields=fields))[0]
    specs = flatten_record(record)
    assert len(specs) <= _MAX_EXPANDED_OCCURRENCES
    caveats = occurs_expansion_caveats(record)
    assert caveats and "fields across nested tables" in caveats[0]


def test_occurs_budget_leaves_small_tables_whole() -> None:
    fields = "\n".join(f"                15 F{i} PIC X." for i in range(3))
    copybook = NESTED_TABLES.format(fields=fields).replace("2200", "20")
    record = parse_copybook_records(copybook)[0]
    assert len(flatten_record(record)) == 10 * 20 * 3
    assert occurs_expansion_caveats(record) == []
