"""Regression: a data entry with the word FILLER omitted is FILLER (#404).

COBOL-85 and IBM Enterprise COBOL let ``FILLER`` be left out, so
``05 PIC X(3).`` is an unnamed filler item. The parser gives it the synthetic
name ``ANONYMOUS-<level>-<line>``; it used to leave ``is_filler`` False, so
gen-data wrote it as a CSV column, data-items listed it under that name and
lineage / host-variable resolution treated it as a real field.
"""

from __future__ import annotations

from pathlib import Path

from cobolparser import parse_cobol
from cobolparser.analysis import HostVariableResolver
from cobolparser.analysis.field_lineage import FieldFlowAnalyzer
from cobolparser.generators import CopybookDataGenerator, DataGeneratorOptions
from cobolparser.generators.data.layout_offsets import compute_program_data_items
from cobolparser.models.data_items import CobolDataItem

COPYBOOK = """\
       01 G.
          05 PIC X(3) VALUE 'ABC'.
          05 Z PIC X.
          05 FILLER PIC X(2).
"""

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 G.
          05 PIC X(3) VALUE 'ABC'.
          05 Z PIC X.
          05 FILLER PIC X(2).
       PROCEDURE DIVISION.
           MOVE Z TO G.
           GOBACK.
"""


def _items(ast) -> list[CobolDataItem]:
    return [n for n in ast.find_all_by_type("DataItem") if isinstance(n, CobolDataItem)]


def test_unnamed_entry_is_filler() -> None:
    record, unnamed, named, explicit = _items(parse_cobol(PROGRAM).ast)
    assert unnamed.name.startswith("ANONYMOUS-")
    assert unnamed.is_filler and explicit.is_filler
    assert unnamed.layout_name == explicit.layout_name == "FILLER"
    assert not record.is_filler and not named.is_filler
    assert named.layout_name == "Z"


def test_unnamed_report_group_entry_is_not_filler() -> None:
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. R.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT RPT-FILE ASSIGN TO RPTOUT.
       DATA DIVISION.
       FILE SECTION.
       FD RPT-FILE REPORT IS RPT.
       REPORT SECTION.
       RD RPT.
       01 TYPE IS PAGE HEADING.
          05 LINE 1 COLUMN 1 PIC X(5) VALUE 'HELLO'.
       PROCEDURE DIVISION.
           GOBACK.
"""
    items = _items(parse_cobol(source).ast)
    assert items
    assert not any(item.is_filler for item in items)


def test_gen_data_omits_unnamed_filler_column(tmp_path: Path) -> None:
    path = tmp_path / "G.cpy"
    path.write_text(COPYBOOK)
    dataset = CopybookDataGenerator(
        DataGeneratorOptions(rows=2, seed=1)
    ).generate_from_file(path)
    assert dataset.header == ["Z"]


def test_gen_data_writes_unnamed_filler_value_into_record_image(
    tmp_path: Path,
) -> None:
    path = tmp_path / "G.cpy"
    path.write_text(COPYBOOK)
    opts = DataGeneratorOptions(rows=1, seed=1).for_record_image()
    dataset = CopybookDataGenerator(opts).generate_from_file(path)
    record = dataset.to_records()
    assert record[:3] == b"ABC"


def test_data_items_names_unnamed_entry_filler() -> None:
    data = compute_program_data_items(parse_cobol(PROGRAM).ast)
    rows = [(i["name"], i["qualified_name"], i["byte_offset"]) for i in data["items"]]
    assert ("FILLER", "G.FILLER", 0) in rows
    assert ("FILLER", "G.FILLER", 4) in rows
    assert not any(name.startswith("ANONYMOUS-") for name, _, _ in rows)


def test_lineage_treats_unnamed_entry_as_filler() -> None:
    report = FieldFlowAnalyzer().analyze(parse_cobol(PROGRAM).ast).to_dict()
    names = [item["name"] for item in report["items"]]
    assert names == ["G", "FILLER", "Z", "FILLER"]


def test_host_variable_resolver_skips_unnamed_filler() -> None:
    resolver = HostVariableResolver()
    resolver.resolve(parse_cobol(PROGRAM).ast)
    assert not any(name.startswith("ANONYMOUS-") for name in resolver._symbol_table)
    assert "Z" in resolver._symbol_table
