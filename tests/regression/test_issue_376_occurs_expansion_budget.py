"""Issue #376: OCCURS expansion had no bound across nested tables. The
per-table cap (10,000) still let ``OCCURS 1000`` inside ``OCCURS 1000``
materialize a million FieldSpecs, and a mistyped ``OCCURS 99999999`` around
``OCCURS 9999`` ran gen-fixtures, lineage and field-impact for minutes.
Expansion is now bounded across nested tables too, and every table a cap
cuts short is named (dataset caveats, ``ProgramLayoutIndex.unresolved``,
record-view caveats) instead of being cut silently.
"""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol
from cobolparser.generators import (
    CopybookDataGenerator,
    DataGeneratorOptions,
    ProgramFixtureGenerator,
    ProgramLayoutIndex,
)
from cobolparser.generators.data import layout
from cobolparser.generators.data.copybook import parse_copybook_records
from cobolparser.generators.data.layout import (
    _MAX_EXPANDED_OCCURRENCES,
    flatten_record,
    occurs_expansion_caveats,
)
from cobolparser.generators.data.views import build_record_views

MISTYPED = """\
       01  IN-REC.
           05  T OCCURS 99999999 TIMES.
               10  T1 PIC X(10) OCCURS 9999.
"""

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BIG.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO INDD.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
{record}
       PROCEDURE DIVISION.
           OPEN INPUT IN-FILE
           READ IN-FILE
           CLOSE IN-FILE
           GOBACK.
"""


def _record(source: str):
    (record,) = parse_copybook_records(source)
    return record


def test_nested_tables_are_bounded_across_dimensions() -> None:
    specs = flatten_record(_record(MISTYPED))
    assert len(specs) == _MAX_EXPANDED_OCCURRENCES
    assert max(s.subscripts[0] for s in specs) == 10_000
    assert max(s.subscripts[1] for s in specs) == 10


def test_every_cut_table_is_named() -> None:
    caveats = occurs_expansion_caveats(_record(MISTYPED))
    assert len(caveats) == 2
    assert caveats[0].startswith(
        "OCCURS table T expanded to 10000 of its 99999999 occurrences"
    )
    assert caveats[1].startswith("OCCURS table T1 expanded to 10 of its 9999")


def test_a_table_within_the_caps_is_whole_and_quiet() -> None:
    source = "01 R.\n  05 T OCCURS 12.\n    10 U PIC X OCCURS 31.\n"
    record = _record(source)
    assert len(flatten_record(record)) == 12 * 31
    assert occurs_expansion_caveats(record) == []


def test_a_requested_max_occurs_is_not_reported() -> None:
    opts = DataGeneratorOptions(max_occurs=2)
    assert occurs_expansion_caveats(_record(MISTYPED), opts) == []


@pytest.fixture
def small_caps(monkeypatch):
    """Shrink both caps so the caveat plumbing runs on a few hundred fields
    instead of 100,000 (the real caps are pinned by the tests above). Both
    constants are read at call time."""
    monkeypatch.setattr(layout, "_MAX_OCCURS_HARD_CAP", 50)
    monkeypatch.setattr(layout, "_MAX_EXPANDED_OCCURRENCES", 200)


def test_gen_data_and_views_carry_the_caveat(small_caps) -> None:
    dataset = CopybookDataGenerator(DataGeneratorOptions(rows=1)).generate_from_source(
        MISTYPED
    )
    assert any(c.startswith("OCCURS table T1 ") for c in dataset.caveats)
    views = build_record_views(_record(MISTYPED))
    assert any(c.startswith("OCCURS table T1 ") for c in views.caveats)


def test_gen_fixtures_reports_it_in_unresolved(tmp_path, small_caps) -> None:
    source = PROGRAM.format(record=MISTYPED.rstrip("\n"))
    ast = parse_cobol(source).ast
    assert ast is not None
    index = ProgramLayoutIndex.build(ast)
    assert any(u.startswith("OCCURS table T1 ") for u in index.unresolved)
    path = tmp_path / "BIG.cbl"
    path.write_text(source)
    bundle = ProgramFixtureGenerator(DataGeneratorOptions(rows=1)).generate_from_file(
        str(path), seed=1
    )
    assert any(u.startswith("OCCURS table T1 ") for u in bundle.unresolved)
