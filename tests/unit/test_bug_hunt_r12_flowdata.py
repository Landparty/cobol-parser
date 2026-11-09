"""Bug hunt round 12: program flow, dynamic CALL values, layouts, generators.

Each test reproduces one defect found in round 12 and pins the fix.
"""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.complexity import ComplexityAnalyzer
from cobolparser.analysis.constraints import ConstraintExtractor, FieldConstraint
from cobolparser.analysis.program_flow import FlowEdgeType, ProgramFlowAnalyzer
from cobolparser.analysis.value_tracker import DynamicCallAnalyzer
from cobolparser.generators import ProgramLayoutIndex
from cobolparser.generators.data.copybook import CopybookDataGenerator
from cobolparser.generators.data.decoding import RecordDecoder, RecordDecodingError
from cobolparser.generators.data.encoding import EncodingOptions, RecordFormat
from cobolparser.generators.scenarios import ScenarioPlanner
from cobolparser.generators.verification import satisfies
from cobolparser.layout.fields import FieldCategory, FieldSpec
from cobolparser.layout.options import DataGeneratorOptions
from cobolparser.layout.program import ResolvedField


def _ast(source: str):
    result = parse_cobol(source)
    assert result.ast is not None, result.errors
    return result.ast


# ---------------------------------------------------------------------------
# program_flow: sentences before the first paragraph are the entry
# ---------------------------------------------------------------------------

LEADING = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 X PIC 9.
       PROCEDURE DIVISION.
           IF X = 1 PERFORM P2 END-IF
           STOP RUN.
       P1.
           DISPLAY 'A'
           STOP RUN.
       P2.
           DISPLAY 'B'.
"""


def test_leading_sentences_are_the_flow_entry_and_keep_their_performs():
    report = ProgramFlowAnalyzer().analyze(_ast(LEADING))
    assert report.entry_points == ["PROCEDURE DIVISION"]
    assert report.nodes[0].name == "PROCEDURE DIVISION"
    assert report.nodes[0].is_entry_point
    assert any(
        e.source == "PROCEDURE DIVISION"
        and e.target == "P2"
        and e.edge_type is FlowEdgeType.PERFORM
        for e in report.edges
    )
    # P2 is PERFORMed from the leading sentences; P1 follows a STOP RUN.
    assert report.unreachable_nodes == ["P1"]
    assert not report.nodes[1].is_entry_point


def test_leading_sentences_complexity_counts_their_decisions():
    report = ComplexityAnalyzer().analyze(_ast(LEADING))
    by_name = {p.name: p for p in report.procedures}
    assert by_name["PROCEDURE DIVISION"].cyclomatic_complexity == 2
    assert by_name["PROCEDURE DIVISION"].fan_out == 1


def test_section_leading_sentences_count_toward_section_complexity():
    source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 X PIC 9.
       PROCEDURE DIVISION.
       MAIN-S SECTION.
           IF X = 1 DISPLAY 'A' END-IF
           IF X = 2 DISPLAY 'B' END-IF
           STOP RUN.
       P1.
           DISPLAY 'Z'.
"""
    report = ComplexityAnalyzer().analyze(_ast(source))
    by_name = {p.name: p for p in report.procedures}
    assert by_name["MAIN-S"].cyclomatic_complexity == 3
    assert by_name["P1"].cyclomatic_complexity == 1


def test_branches_in_an_unreachable_sections_leading_sentences_are_missed():
    source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO INF.
       DATA DIVISION.
       FILE SECTION.
       FD IN-FILE.
       01 IN-REC.
          05 IN-CODE PIC X.
       PROCEDURE DIVISION.
       MAIN-S SECTION.
       M1.
           OPEN INPUT IN-FILE
           READ IN-FILE AT END CONTINUE END-READ
           IF IN-CODE = 'A' DISPLAY 'A' END-IF
           STOP RUN.
       DEAD-S SECTION.
           IF IN-CODE = 'B' DISPLAY 'B' END-IF
           STOP RUN.
"""
    ast = _ast(source)
    index = ProgramLayoutIndex.build(ast)
    boundaries = BoundaryInventoryAnalyzer().analyze(ast, index)
    constraints = ConstraintExtractor().extract(ast, index, boundaries)
    flow = ProgramFlowAnalyzer().analyze(ast)
    assert flow.unreachable_nodes == ["DEAD-S"]
    plan = ScenarioPlanner().plan(constraints, flow, boundaries, mode="branches")
    dead = [d for d in plan.coverage.details if d.arm_key.startswith("?@20:")]
    assert len(dead) == 2
    assert all(d.status == "missed" and d.reason == "unreachable" for d in dead)
    live = [d for d in plan.coverage.details if d.arm_key.startswith("M1@")]
    assert all(d.status == "targeted" for d in live)


# ---------------------------------------------------------------------------
# DynamicCallAnalyzer: each program unit on its own names
# ---------------------------------------------------------------------------

NESTED = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. OUTER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-PGM PIC X(8) VALUE 'OUTPGM'.
       01 WS-G PIC X(8) GLOBAL VALUE 'GPGM'.
       PROCEDURE DIVISION.
           CALL WS-PGM
           GOBACK.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INNER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-PGM PIC X(8) VALUE 'INPGM'.
       PROCEDURE DIVISION.
           CALL WS-PGM
           CALL WS-G
           GOBACK.
       END PROGRAM INNER.
       END PROGRAM OUTER.
"""


def _calls(unit):
    return [
        s
        for s in unit.get_all_statements()
        if s.statement_type == "CALL" and s not in _inner_calls(unit)
    ]


def _inner_calls(unit):
    return [
        s
        for inner in unit.contained_programs
        for s in inner.get_all_statements()
        if s.statement_type == "CALL"
    ]


def test_dynamic_call_values_do_not_cross_program_units():
    ast = _ast(NESTED)
    DynamicCallAnalyzer().analyze(ast)
    (outer_call,) = _calls(ast)
    inner_pgm, inner_global = _inner_calls(ast)
    assert outer_call.possible_values == ["OUTPGM"]
    assert not outer_call.get_metadata("possible_values_incomplete")
    assert inner_pgm.possible_values == ["INPGM"]
    assert not inner_pgm.get_metadata("possible_values_incomplete")
    # A container's GLOBAL item: not tracked in the inner unit, so not exact.
    assert inner_global.possible_values == []
    assert inner_global.get_metadata("possible_values_incomplete") is True


def test_reanalysing_a_unit_clears_stale_values_and_flag():
    ast = _ast(NESTED)
    inner = ast.contained_programs[0]
    inner_pgm = _inner_calls(ast)[0]
    inner_pgm.set_possible_values(["STALE"])
    inner_pgm.set_metadata("possible_values_incomplete", True)
    DynamicCallAnalyzer().analyze(inner)
    assert inner_pgm.possible_values == ["INPGM"]
    assert not inner_pgm.has_metadata("possible_values_incomplete")
    # Outer, then inner (codebase.py's order) agrees with a single outer pass.
    DynamicCallAnalyzer().analyze(ast)
    DynamicCallAnalyzer().analyze(inner)
    assert inner_pgm.possible_values == ["INPGM"]


# ---------------------------------------------------------------------------
# ProgramLayoutIndex: an OCCURS table element is not an ambiguity
# ---------------------------------------------------------------------------


def test_table_element_resolves_to_nothing_without_a_bogus_ambiguity():
    source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-TAB.
          05 WS-ENT OCCURS 3 TIMES.
             10 WS-ITEM PIC X(2).
                88 WS-ITEM-OK VALUE 'OK'.
       01 WS-X PIC 9.
       PROCEDURE DIVISION.
           STOP RUN.
"""
    index = ProgramLayoutIndex.build(_ast(source))
    assert index.resolve("WS-ITEM") is None
    assert index.resolve("WS-ITEM OF WS-ENT") is None
    # The condition name tests every occurrence, not occurrence 1.
    assert index.resolve("WS-ITEM-OK") is None
    assert index.ambiguities == {}
    assert index.resolve("WS-X") is not None


# ---------------------------------------------------------------------------
# verification.satisfies: figurative constants fill the field
# ---------------------------------------------------------------------------


def _text_field(size: int, category=FieldCategory.ALPHANUMERIC, usage="DISPLAY"):
    spec = FieldSpec(
        name="F",
        path=("F",),
        column="F",
        level=1,
        picture=f"X({size})",
        usage=usage,
        category=category,
        size=size,
        integer_digits=0,
        decimal_digits=0,
        is_signed=False,
    )
    return ResolvedField(spec=spec, section="working_storage", record=None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("figurative", "value", "expected"),
    [
        ("QUOTE", '"""', True),
        ("QUOTE", '"', False),
        ("QUOTE", '"  ', False),
        ("ZERO", "000", True),
        ("ZERO", "0", False),
    ],
)
def test_figurative_satisfaction_honours_field_width(figurative, value, expected):
    constraint = FieldConstraint(_text_field(3), "figurative", (figurative,), "t")
    assert satisfies(constraint, value) is expected


# ---------------------------------------------------------------------------
# National / DBCS values are sized in characters, not bytes
# ---------------------------------------------------------------------------


def test_national_and_dbcs_values_hold_character_positions():
    source = (
        "       01 REC.\n"
        "          05 N1 PIC N(2).\n"
        "          05 G1 PIC G(3).\n"
        "          05 X1 PIC X(2).\n"
    )
    dataset = CopybookDataGenerator(
        DataGeneratorOptions(rows=20, seed=1)
    ).generate_from_source(source)
    by_name = {spec.name: spec for spec in dataset.fields}
    assert by_name["N1"].size == 4 and by_name["N1"].character_positions == 2
    assert by_name["G1"].size == 6 and by_name["G1"].character_positions == 3
    assert by_name["X1"].character_positions == 2
    columns = [spec.column for spec in dataset.fields]
    for row in dataset.rows:
        cells = dict(zip(columns, row, strict=True))
        assert 1 <= len(cells["N1"]) <= 2
        assert 1 <= len(cells["G1"]) <= 3


# ---------------------------------------------------------------------------
# RECFM=V: a truncated last record is trailing, as in the other formats
# ---------------------------------------------------------------------------


def test_variable_truncated_last_record_is_trailing_not_an_error():
    source = "       01 REC.\n          05 A PIC X(4).\n          05 B PIC 9(3).\n"
    dataset = CopybookDataGenerator(
        DataGeneratorOptions(rows=3, seed=2).for_record_image()
    ).generate_from_source(source)
    opts = EncodingOptions(record_format=RecordFormat.VARIABLE)
    raw = dataset.to_records(opts)
    decoder = RecordDecoder.from_copybook_source(source, opts=opts)
    result = decoder.decode_bytes(raw[:-3], opts=opts)
    assert len(result.records) == 2
    assert result.trailing == raw[result.bytes_read : -3]
    assert len(result.trailing) > 0
    # A first RDW longer than the whole file still says "not RECFM=V".
    with pytest.raises(RecordDecodingError):
        decoder.decode_bytes(b"\xff\xff\x00\x00abc", opts=opts)


# ---------------------------------------------------------------------------
# DECIMAL-POINT IS COMMA: a digit-comma-digit picture run keeps its comma
# ---------------------------------------------------------------------------


def test_decimal_point_comma_float_picture_keeps_its_decimal_comma():
    source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SPECIAL-NAMES.
           DECIMAL-POINT IS COMMA.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 F1 PIC -9,9(5)E-99.
       01 F2 PIC 9,99.
       PROCEDURE DIVISION.
           STOP RUN.
"""
    ast = _ast(source)
    items = ast.get_division("DATA").get_section_by_name("WORKING-STORAGE").data_items
    f1, f2 = (item.picture_clause for item in items)
    assert f1.pattern == "-9,9(5)E-99"
    assert (f1.integer_digits, f1.decimal_digits) == (1, 5)
    assert f2.pattern == "9,99"
    assert (f2.integer_digits, f2.decimal_digits) == (1, 2)


def test_contained_unit_analysed_alone_still_flags_a_container_global():
    ast = _ast(NESTED)
    inner = ast.contained_programs[0]
    DynamicCallAnalyzer().analyze(inner)
    inner_global = _inner_calls(ast)[1]
    assert inner_global.possible_values == []
    assert inner_global.get_metadata("possible_values_incomplete") is True
