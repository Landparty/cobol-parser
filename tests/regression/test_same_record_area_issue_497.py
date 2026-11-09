"""Issue #497: ``I-O-CONTROL. SAME RECORD AREA FOR f1 f2`` was kept as text
only, so constant folding and field lineage treated the records of the two
files as separate storage. The records of every file in the clause share one
area: a MOVE to an ``f1`` field changes what the matching ``f2`` field reads.
Plain ``SAME AREA`` shares only the I/O buffer and must not alias records.
"""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis._files import same_record_area_groups
from cobolparser.analysis.const_fold import ConstantFolder
from cobolparser.analysis.field_lineage import FieldFlowAnalyzer
from cobolparser.generators import ProgramFixtureGenerator
from cobolparser.layout.program import ProgramLayoutIndex


def _source(io_control: str, procedure: str) -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. SAME2.\n"
        "       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n"
        "       FILE-CONTROL.\n"
        "           SELECT IN-FILE ASSIGN TO INDD.\n"
        "           SELECT OUT-FILE ASSIGN TO OUTDD.\n"
        "           SELECT LOG-FILE ASSIGN TO LOGDD.\n"
        "       I-O-CONTROL.\n"
        f"           {io_control}.\n"
        "       DATA DIVISION.\n"
        "       FILE SECTION.\n"
        "       FD IN-FILE.\n"
        "       01 IN-REC.\n"
        "          05 IN-ID PIC X(5).\n"
        "          05 IN-AMT PIC 9(5).\n"
        "       FD OUT-FILE.\n"
        "       01 OUT-REC.\n"
        "          05 OUT-ID PIC X(5).\n"
        "          05 OUT-AMT PIC 9(5).\n"
        "       FD LOG-FILE.\n"
        "       01 LOG-REC.\n"
        "          05 LOG-ID PIC X(5).\n"
        "       PROCEDURE DIVISION.\n"
        + "".join(f"           {line}\n" for line in procedure.strip().splitlines())
        + "           STOP RUN.\n"
    )


_FOLD_BODY = """
OPEN OUTPUT OUT-FILE LOG-FILE
MOVE 'AAAAA' TO OUT-ID
MOVE 12345 TO OUT-AMT
MOVE 'CCCCC' TO LOG-ID
MOVE 'BBBBB' TO IN-ID
DISPLAY OUT-ID
DISPLAY LOG-ID
WRITE OUT-REC
WRITE LOG-REC
CLOSE OUT-FILE LOG-FILE
"""

_COPY_BODY = """
OPEN INPUT IN-FILE OUTPUT OUT-FILE
READ IN-FILE
WRITE OUT-REC
CLOSE IN-FILE OUT-FILE
"""


def _ast(io_control: str, procedure: str):
    result = parse_cobol(_source(io_control, procedure), filename="same2.cbl")
    assert result.ast is not None and result.errors == [], result.errors
    return result.ast


def _fold(io_control: str) -> dict[str, str]:
    ast = _ast(io_control, _FOLD_BODY)
    return ConstantFolder().fold(ast, ProgramLayoutIndex.build(ast)).known


def _port_flows(io_control: str) -> set[str]:
    report = FieldFlowAnalyzer().analyze(_ast(io_control, _COPY_BODY))
    return {f"{f.source.label()} => {f.target.label()}" for f in report.summary}


class TestIoControlMetadata:
    def test_same_record_area_entry_is_structured(self) -> None:
        ast = _ast("SAME RECORD AREA FOR IN-FILE, OUT-FILE", _COPY_BODY)
        sections = {s.section_name: s for s in ast.environment_division.sections}
        (entry,) = sections["INPUT-OUTPUT"].get_metadata("io_control")
        assert entry["text"] == "SAME RECORD AREA FOR IN-FILE OUT-FILE"
        assert entry["area"] == "RECORD"
        assert entry["files"] == ["IN-FILE", "OUT-FILE"]
        assert same_record_area_groups(ast) == [["IN-FILE", "OUT-FILE"]]

    @pytest.mark.parametrize(
        ("clause", "area"),
        [
            ("SAME AREA FOR IN-FILE OUT-FILE", ""),
            ("SAME SORT AREA FOR IN-FILE OUT-FILE", "SORT"),
            ("SAME SORT-MERGE AREA FOR IN-FILE OUT-FILE", "SORT-MERGE"),
        ],
    )
    def test_other_same_areas_share_no_records(self, clause: str, area: str) -> None:
        ast = _ast(clause, _COPY_BODY)
        sections = {s.section_name: s for s in ast.environment_division.sections}
        (entry,) = sections["INPUT-OUTPUT"].get_metadata("io_control")
        assert entry["area"] == area
        assert entry["files"] == ["IN-FILE", "OUT-FILE"]
        assert same_record_area_groups(ast) == []

    def test_groups_naming_a_common_file_merge(self) -> None:
        ast = _ast(
            "SAME RECORD AREA FOR IN-FILE OUT-FILE\n"
            "           SAME RECORD AREA FOR OUT-FILE LOG-FILE",
            _COPY_BODY,
        )
        assert same_record_area_groups(ast) == [["IN-FILE", "OUT-FILE", "LOG-FILE"]]


class TestConstantFolding:
    def test_move_to_one_file_poisons_the_other_files_record(self) -> None:
        known = _fold("SAME RECORD AREA FOR IN-FILE OUT-FILE")
        # OUT-ID holds 'BBBBB' at run time (IN-ID shares its bytes).
        assert "OUT-REC.OUT-ID" not in known
        # LOG-FILE is not in the clause: its record is its own storage.
        assert known["LOG-REC.LOG-ID"] == "CCCCC"

    def test_plain_same_area_does_not_alias_records(self) -> None:
        known = _fold("SAME AREA FOR IN-FILE OUT-FILE")
        assert known["OUT-REC.OUT-ID"] == "AAAAA"

    def test_gen_fixtures_asserts_no_wrong_field_equals(self, tmp_path) -> None:
        path = tmp_path / "same2.cbl"
        path.write_text(_source("SAME RECORD AREA FOR IN-FILE OUT-FILE", _FOLD_BODY))
        bundle = ProgramFixtureGenerator().generate_from_file(path, seed=1)
        refs = {
            e.ref
            for scenario in bundle.scenarios
            for e in scenario.expectations
            if e.kind == "field_equals"
        }
        assert "OUT-REC.OUT-ID" not in refs


class TestLineage:
    def test_copy_idiom_flows_input_to_output_through_the_shared_area(
        self,
    ) -> None:
        flows = _port_flows("SAME RECORD AREA FOR IN-FILE OUT-FILE")
        assert "file:INDD@0+5 => file:OUTDD@0+5" in flows
        assert "file:INDD@5+5 => file:OUTDD@5+5" in flows

    def test_plain_same_area_carries_no_flow(self) -> None:
        assert _port_flows("SAME AREA FOR IN-FILE OUT-FILE") == set()
