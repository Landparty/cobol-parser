"""End-to-end tests for copybook -> CSV synthetic data generation.

Exercises the generator against the real copybook corpora in the repository
(the shared samples and the NIST ``.CPY`` library) rather than hand-written
fragments, so parser changes that alter data-item shapes surface here.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from cobolparser.generators import (
    CopybookDataGenerator,
    CopybookLayoutError,
    DataGeneratorOptions,
)

REPO_ROOT = Path(__file__).parents[2]
COPYBOOKS = REPO_ROOT / "tests" / "samples" / "copybooks"
NIST_COPYBOOKS = sorted((REPO_ROOT / "examples" / "cobol").glob("*.CPY"))

# Copybooks that hold procedure text or SELECT clauses rather than a record
# layout; they have no fields to generate and must say so cleanly.
_LAYOUT_BEARING = sorted(COPYBOOKS.glob("*.cpy"))


pytestmark = pytest.mark.integration


def _generate(path: Path, **options):
    opts = DataGeneratorOptions(
        rows=options.pop("rows", 5), seed=options.pop("seed", 1), **options
    )
    return CopybookDataGenerator(opts).generate_from_file(path)


class TestSampleCopybooks:
    def test_customer_copybook_round_trips_through_csv(self):
        dataset = _generate(COPYBOOKS / "CUSTOMER.cpy", rows=10, seed=101)
        parsed = list(csv.reader(io.StringIO(dataset.to_csv())))
        assert parsed[0] == dataset.header
        assert len(parsed) == 11
        assert all(len(row) == len(dataset.header) for row in parsed[1:])

    def test_employee_copybook_produces_expected_columns(self):
        dataset = _generate(COPYBOOKS / "EMPLOYEE.cpy", rows=3, seed=103)
        assert dataset.header == [
            "EMPLOYEE-ID",
            "EMPLOYEE-NAME",
            "EMPLOYEE-SALARY",
            "EMPLOYEE-DEPARTMENT",
        ]

    @pytest.mark.parametrize("copybook", _LAYOUT_BEARING, ids=lambda p: p.stem)
    def test_sample_copybooks_generate_or_report_cleanly(self, copybook):
        """No sample copybook may crash the generator.

        A copybook with no record layout (procedure text, an empty file) must
        raise CopybookLayoutError -- the documented outcome -- rather than an
        arbitrary exception from deep inside the parser.
        """
        try:
            dataset = _generate(copybook, rows=3, seed=107)
        except CopybookLayoutError:
            return
        assert len(dataset.rows) == 3
        assert dataset.header


class TestNistCopybookCorpus:
    @pytest.mark.parametrize("copybook", NIST_COPYBOOKS, ids=lambda p: p.stem)
    def test_nist_copybooks_never_crash_the_generator(self, copybook):
        try:
            dataset = _generate(copybook, rows=2, seed=109)
        except CopybookLayoutError:
            return
        assert len(dataset.rows) == 2
        assert len(dataset.header) == len(dataset.fields)
        assert all(len(row) == len(dataset.header) for row in dataset.rows)

    def test_corpus_yields_a_meaningful_number_of_layouts(self):
        """Guard against a regression that silently stops finding layouts."""
        generated = 0
        for copybook in NIST_COPYBOOKS:
            try:
                _generate(copybook, rows=1, seed=113)
            except CopybookLayoutError:
                continue
            generated += 1
        # Most NIST "copybooks" are PROCEDURE DIVISION fragments; before
        # unnamed entries were treated as FILLER (#404) a dozen of them
        # "yielded" a layout of bogus ANONYMOUS-<level>-<line> columns.
        assert generated >= 10

    def test_orphan_subordinate_items_get_a_synthesised_record(self):
        # K101A.CPY holds bare level-02 items, meant to be COPY'd inside an
        # existing 01. The generator supplies the record root.
        dataset = _generate(REPO_ROOT / "examples" / "cobol" / "K101A.CPY", rows=2)
        assert dataset.record_name == "K101A-RECORD"
        assert dataset.header == ["TST-FLD-1"]


class TestGeneratedDataIsAssignable:
    """A generated row must be storable in the record it was generated from."""

    def test_every_cell_fits_its_field(self):
        dataset = _generate(COPYBOOKS / "TXNDATA.cpy", rows=100, seed=127)
        for index, spec in enumerate(dataset.fields):
            for row in dataset.rows:
                cell = row[index]
                if spec.category.value.startswith("numeric"):
                    text = cell.lstrip("-")
                    integer_part, _, decimal_part = text.partition(".")
                    assert len(integer_part) <= max(1, spec.integer_digits)
                    assert len(decimal_part) <= spec.decimal_digits
                    if not spec.is_signed:
                        assert not cell.startswith("-")
                else:
                    assert len(cell) <= spec.size

    def test_csv_is_parseable_by_a_standard_reader(self, tmp_path):
        dataset = _generate(COPYBOOKS / "TXNDATA.cpy", rows=25, seed=131)
        target = tmp_path / "txn.csv"
        dataset.write_csv(target)
        with target.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 25
        assert set(rows[0]) == set(dataset.header)
