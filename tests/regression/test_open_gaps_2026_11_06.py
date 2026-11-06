"""Gaps the cobol-test run on PAYMAIN + PAYCALC found (2026-11-06):
program-flow's fall-through out of a paragraph that is only PERFORMed, a
CALL fixture's empty ``direction``, and record images silently short of
their FILLER bytes."""

import warnings

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.program_flow import ProgramFlowAnalyzer
from cobolparser.generators import ProgramFixtureGenerator
from cobolparser.generators.data import (
    CopybookDataGenerator,
    DataGeneratorOptions,
    IncompleteRecordImageWarning,
)


def _fall_through(source: str) -> set[tuple[str, str]]:
    flow = ProgramFlowAnalyzer().analyze(parse_cobol(source).ast)
    return {
        (e.source, e.target) for e in flow.edges if e.edge_type.value == "FALL_THROUGH"
    }


PAYMAIN = """
IDENTIFICATION DIVISION.
PROGRAM-ID. PAYMAIN.
DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-EOF PIC X VALUE 'N'.
    88 END-OF-FILE VALUE 'Y'.
01  PAY-AREA PIC X(10).
PROCEDURE DIVISION.
0000-MAIN.
    PERFORM 1000-READ-EMP
    PERFORM 2000-PAY-EMP UNTIL END-OF-FILE
    GOBACK.
1000-READ-EMP.
    SET END-OF-FILE TO TRUE.
2000-PAY-EMP.
    CALL 'PAYCALC' USING PAY-AREA
    PERFORM 1000-READ-EMP.
"""


class TestPerformOnlyParagraphDoesNotFallThrough:
    def test_paymain_has_no_fall_through_and_no_cycle(self):
        flow = ProgramFlowAnalyzer().analyze(parse_cobol(PAYMAIN).ast)
        assert _fall_through(PAYMAIN) == set()
        assert flow.cycles == []
        assert flow.unreachable_nodes == []

    def test_thru_range_interior_still_falls_through(self):
        source = """
IDENTIFICATION DIVISION.
PROGRAM-ID. THRU1.
PROCEDURE DIVISION.
0000-MAIN.
    PERFORM 1000-A THRU 1000-A-EXIT
    STOP RUN.
1000-A.
    DISPLAY 'A'.
1000-B.
    DISPLAY 'B'.
1000-A-EXIT.
    EXIT.
2000-NEXT.
    DISPLAY 'N'.
"""
        edges = _fall_through(source)
        assert ("1000-A", "1000-B") in edges
        assert ("1000-B", "1000-A-EXIT") in edges
        # The range ends at 1000-A-EXIT: control returns from there.
        assert ("1000-A-EXIT", "2000-NEXT") not in edges

    def test_main_line_falling_into_a_performed_paragraph_keeps_it(self):
        source = """
IDENTIFICATION DIVISION.
PROGRAM-ID. FALLS.
PROCEDURE DIVISION.
0000-MAIN.
    PERFORM 2000-B.
1000-A.
    DISPLAY 'A'.
2000-B.
    DISPLAY 'B'.
3000-C.
    STOP RUN.
"""
        edges = _fall_through(source)
        assert ("0000-MAIN", "1000-A") in edges
        assert ("1000-A", "2000-B") in edges
        assert ("2000-B", "3000-C") in edges

    def test_goto_target_keeps_its_fall_through(self):
        source = """
IDENTIFICATION DIVISION.
PROGRAM-ID. GOTO1.
PROCEDURE DIVISION.
0000-MAIN.
    PERFORM 1000-A
    GO TO 1000-A.
1000-A.
    DISPLAY 'A'.
2000-B.
    STOP RUN.
"""
        assert ("1000-A", "2000-B") in _fall_through(source)

    def test_performed_section_paragraphs_fall_through_inside_it(self):
        source = """
IDENTIFICATION DIVISION.
PROGRAM-ID. SECT1.
PROCEDURE DIVISION.
MAIN-SECTION SECTION.
0000-MAIN.
    PERFORM WORK-SECTION
    STOP RUN.
WORK-SECTION SECTION.
W-1.
    DISPLAY '1'.
W-2.
    DISPLAY '2'.
LAST-SECTION SECTION.
L-1.
    DISPLAY 'L'.
"""
        edges = _fall_through(source)
        assert ("W-1", "W-2") in edges
        assert ("W-2", "LAST-SECTION") not in edges


class TestCallFixtureDirection:
    def test_call_fixture_carries_its_arguments_direction(self, tmp_path):
        source = """
IDENTIFICATION DIVISION.
PROGRAM-ID. CALLER.
DATA DIVISION.
WORKING-STORAGE SECTION.
01  PAY-AREA.
    05 PA-HOURS PIC 9(3).
    05 PA-RC    PIC 9(2).
PROCEDURE DIVISION.
0000-MAIN.
    CALL 'PAYCALC' USING PAY-AREA
    IF PA-RC = 0
        DISPLAY 'OK'
    END-IF
    GOBACK.
"""
        path = tmp_path / "CALLER.cbl"
        path.write_text(source, encoding="utf-8")
        bundle = ProgramFixtureGenerator().generate_with_scenarios_from_file(
            str(path), mode="happy", seed=1
        )
        fixtures = [
            f
            for scenario in bundle.to_dict()["scenarios"]
            for f in scenario.get("fixtures", [])
            if f["category"] == "CALL"
        ]
        assert fixtures
        # The schema's values only; it used to be "".
        assert {f["direction"] for f in fixtures} <= {
            "IN",
            "OUT",
            "BIDIRECTIONAL",
            "STATUS_ONLY",
        }


ORDREC = """
       01 ORDREC.
          05 ORD-ID   PIC 9(5).
          05 FILLER   PIC X(9).
          05 ORD-AMT  PIC 9(5)V99.
"""


class TestRecordImageMissingFiller:
    def _dataset(self, options: DataGeneratorOptions):
        return CopybookDataGenerator(options).generate_from_source(ORDREC)

    def test_csv_shaped_options_warn_on_record_output(self):
        dataset = self._dataset(DataGeneratorOptions(rows=2, seed=1))
        assert dataset.record_image_gap == (12, 21)
        with pytest.warns(IncompleteRecordImageWarning, match="12 of the record's 21"):
            dataset.to_records()
        with pytest.warns(IncompleteRecordImageWarning):
            dataset.to_hex_dump()
        with pytest.warns(IncompleteRecordImageWarning):
            dataset.record_length()

    def test_csv_output_does_not_warn(self):
        dataset = self._dataset(DataGeneratorOptions(rows=2, seed=1))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            dataset.to_csv()

    def test_write_records_warns_once(self, tmp_path):
        dataset = self._dataset(DataGeneratorOptions(rows=2, seed=1))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            dataset.write_records(tmp_path / "out.bin")
        assert [w.category for w in caught] == [IncompleteRecordImageWarning]

    def test_record_image_options_are_silent(self):
        dataset = self._dataset(DataGeneratorOptions(rows=2, seed=1).for_record_image())
        assert dataset.record_image_gap is None
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert len(dataset.to_records()) == 2 * 21


def test_call_direction_from_arguments():
    from types import SimpleNamespace as A

    from cobolparser.generators.program_fixtures import _call_direction

    assert _call_direction([A(name="X", direction="IN")]) == "IN"
    # The fixture exists only when it supplies a value (e.g. RETURN-CODE).
    assert _call_direction([A(name="X", direction="OUT")]) == "BIDIRECTIONAL"
    assert (
        _call_direction([A(name="X", direction="IN"), A(name="Y", direction="OUT")])
        == "BIDIRECTIONAL"
    )
    # Only RETURN-CODE left: the mock supplies it, so IN, not STATUS_ONLY.
    assert _call_direction([A(name="'LIT'", direction="IN")]) == "IN"
    assert _call_direction([]) == "IN"
