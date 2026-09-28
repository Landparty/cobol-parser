"""Level-88 ``VALUE ALL 'X'`` is one value, not two.

Before: ``88 A-ALLX VALUE ALL 'X'.`` stored ``values == ['ALL', 'X']`` --
two separate values, the second of which the generators and the
constraint extractor read as the one-character value ``X``. Now the entry is
stored the way a non-88 ``VALUE ALL`` is (``ALL "X"`` / ``ALL SPACES``), and
the consumers that know the field's width fill it (``XXX`` for PIC X(3)).
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.constraints import ConstraintExtractor
from cobolparser.generators import (
    CopybookDataGenerator,
    DataGeneratorOptions,
    ProgramLayoutIndex,
)
from cobolparser.generators.data.layout import (
    condition_values_exhaustive,
    expand_condition_values,
    fill_all_literal,
)

PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. V88ALL.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO INDD.
       DATA DIVISION.
       FILE SECTION.
       FD IN-FILE.
       01 IN-REC.
          05 IN-A PIC X(3).
             88 A-ALLX VALUE ALL 'X'.
             88 A-MIX VALUE 'ABC' ALL '-' SPACES.
             88 A-SP VALUE ALL SPACES.
       WORKING-STORAGE SECTION.
       01 WS-B PIC X(4) VALUE ALL '*'.
       PROCEDURE DIVISION.
           OPEN INPUT IN-FILE.
           READ IN-FILE.
           IF A-ALLX
               DISPLAY 'ALLX'
           END-IF.
           CLOSE IN-FILE.
           STOP RUN.
"""


def _conditions(result):
    item = next(
        i for i in result.ast.find_all_by_type("CobolDataItem") if i.name == "IN-A"
    )
    return {c["name"]: c["values"] for c in item.to_dict()["condition_names"]}


def test_parsed_as_one_value():
    result = parse_cobol(PROGRAM)
    assert result.success, result.errors
    assert not result.warnings
    conditions = _conditions(result)
    assert conditions["A-ALLX"] == ['ALL "X"']
    assert conditions["A-MIX"] == ["ABC", 'ALL "-"', "SPACES"]
    assert conditions["A-SP"] == ["ALL SPACES"]
    # the same spelling a non-88 VALUE ALL uses
    ws_b = next(
        i for i in result.ast.find_all_by_type("CobolDataItem") if i.name == "WS-B"
    )
    assert ws_b.value_clause == 'ALL "*"'


def test_layout_helpers():
    assert fill_all_literal('ALL "AB"', 5) == "ABABA"
    assert fill_all_literal("ALL SPACES", 5) is None
    assert expand_condition_values(['ALL "X"']) == ['ALL "X"']
    assert expand_condition_values(['ALL "X"'], 3) == ["XXX"]
    assert expand_condition_values(["ALL SPACES"], 3) == ["SPACES"]
    assert condition_values_exhaustive(['ALL "X"'], 0)
    assert not condition_values_exhaustive(["ALL SPACES"], 0)


def test_program_layout_and_generated_values():
    result = parse_cobol(PROGRAM)
    index = ProgramLayoutIndex.build(result.ast)
    assert index.condition_values("A-ALLX") == ("XXX",)
    assert index.condition_values("A-MIX") == ("ABC", "---", "SPACES")
    assert index.condition_raw_values("A-ALLX") == ('ALL "X"',)
    spec = index.resolve("IN-A").spec
    assert "X" not in spec.condition_values
    assert "ALL" not in spec.condition_values
    assert "XXX" in spec.condition_values


def test_generator_never_emits_the_keyword(tmp_path):
    path = tmp_path / "V88ALL.cbl"
    path.write_text(PROGRAM)
    dataset = CopybookDataGenerator(
        DataGeneratorOptions(rows=40, seed=1)
    ).generate_from_file(str(path), record="IN-REC")
    column = [f.name for f in dataset.fields].index("IN-A")
    values = {row[column] for row in dataset.rows}
    assert "XXX" in values
    assert not values & {"ALL", "X", "AL"}


def test_constraint_is_the_filled_value():
    result = parse_cobol(PROGRAM)
    index = ProgramLayoutIndex.build(result.ast)
    boundaries = BoundaryInventoryAnalyzer().analyze(result.ast, index)
    report = ConstraintExtractor().extract(result.ast, index, boundaries)
    assert not any("VALUE ALL" in u for u in report.unsupported)
    (branch,) = report.branches
    (constraint,) = branch.arms["THEN"]
    assert constraint.op == "in_set"
    assert constraint.values == ("XXX",)
