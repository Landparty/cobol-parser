"""Unit tests for ProgramLayoutIndex (cobolparser.generators.data.program_layout).

Covers FD/record resolution, FileFacts merging (SELECT + FD/SD clauses),
name resolution (bare / qualified / level-88), section lookups, and the
fail-loud unresolved/ambiguities bookkeeping.
"""

from __future__ import annotations

import pytest

from cobolparser import ErrorRecoveryMode, parse_cobol
from cobolparser.generators import ProgramLayoutError, ProgramLayoutIndex

_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LAYOUTTEST.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT INV-FILE ASSIGN TO 'INV.DAT'
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC
               RECORD KEY IS INV-KEY
               FILE STATUS IS WS-FS.
           SELECT SORT-WORK ASSIGN TO 'SORTWORK'.
       DATA DIVISION.
       FILE SECTION.
       FD  INV-FILE
           RECORD CONTAINS 80 CHARACTERS.
       01  INV-REC.
           05  INV-KEY         PIC 9(5).
           05  INV-QTY         PIC 9(3).
           05  INV-STATUS      PIC 9.
               88  IN-STOCK    VALUE 1 THRU 4.
       SD  SORT-WORK.
       01  SORT-REC            PIC X(80).
       WORKING-STORAGE SECTION.
       01  WS-FS               PIC XX.
       01  WS-EOF              PIC X.
           88  END-OF-FILE     VALUE 'Y'.
       01  WS-QTY-HOLDER.
           05  QTY-GROUP.
               10  INV-QTY     PIC 9(3).
       LINKAGE SECTION.
       01  LK-PARAM            PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY 'HI'.
"""


def _build_index() -> ProgramLayoutIndex:
    result = parse_cobol(
        _PROGRAM, filename="layouttest.cbl", error_recovery=ErrorRecoveryMode.FAIL_FAST
    )
    assert result.ast is not None, result.errors
    assert result.errors == []
    return ProgramLayoutIndex.build(result.ast)


class TestRecordsForFile:
    def test_record_for_file_resolves_the_fd(self):
        index = _build_index()
        record = index.record_for_file("INV-FILE")
        assert record is not None
        assert record.name == "INV-REC"

    def test_records_for_file_returns_every_variant(self):
        index = _build_index()
        assert [r.name for r in index.records_for_file("INV-FILE")] == ["INV-REC"]

    def test_lookup_is_case_insensitive(self):
        index = _build_index()
        assert index.record_for_file("inv-file").name == "INV-REC"

    def test_unknown_file_returns_none_and_empty_list(self):
        index = _build_index()
        assert index.record_for_file("NOPE") is None
        assert index.records_for_file("NOPE") == []

    def test_sd_sort_file_is_indexed_too(self):
        index = _build_index()
        record = index.record_for_file("SORT-WORK")
        assert record is not None
        assert record.name == "SORT-REC"


class TestFileFacts:
    def test_merges_select_and_fd_clauses(self):
        index = _build_index()
        facts = index.file_facts("INV-FILE")
        assert facts is not None
        assert facts.organization == "INDEXED"
        assert facts.access_mode == "DYNAMIC"
        assert facts.record_key == "INV-KEY"
        assert facts.file_status_field == "WS-FS"
        assert facts.record_contains == 80
        assert facts.record_type == "FD"
        assert facts.record_names == ("INV-REC",)

    def test_sd_file_is_flagged_record_type_sd(self):
        index = _build_index()
        facts = index.file_facts("SORT-WORK")
        assert facts is not None
        assert facts.record_type == "SD"

    def test_unknown_file_returns_none(self):
        index = _build_index()
        assert index.file_facts("NOPE") is None


class TestResolve:
    def test_bare_unique_name_resolves(self):
        index = _build_index()
        resolved = index.resolve("INV-KEY")
        assert resolved is not None
        assert resolved.spec.name == "INV-KEY"
        assert resolved.section == "file"
        assert resolved.record.name == "INV-REC"

    def test_ambiguous_bare_name_returns_none_and_is_recorded(self):
        # INV-QTY exists at two paths: INV-REC.INV-QTY (file) and
        # WS-QTY-HOLDER.QTY-GROUP.INV-QTY (working-storage).
        index = _build_index()
        assert index.resolve("INV-QTY") is None
        assert "INV-QTY" in index.ambiguities
        assert set(index.ambiguities["INV-QTY"]) == {
            "INV-REC.INV-QTY",
            "WS-QTY-HOLDER.QTY-GROUP.INV-QTY",
        }

    def test_qualified_of_form_disambiguates(self):
        index = _build_index()
        resolved = index.resolve("INV-QTY OF INV-REC")
        assert resolved is not None
        assert resolved.section == "file"

        resolved2 = index.resolve("INV-QTY OF QTY-GROUP")
        assert resolved2 is not None
        assert resolved2.section == "working_storage"

    def test_dotted_qualifier_form_also_disambiguates(self):
        index = _build_index()
        resolved = index.resolve("INV-REC.INV-QTY")
        assert resolved is not None
        assert resolved.section == "file"

    def test_level_88_resolves_to_parent_field(self):
        index = _build_index()
        resolved = index.resolve("IN-STOCK")
        assert resolved is not None
        assert resolved.spec.name == "INV-STATUS"
        assert resolved.spec.condition_values == ["1", "2", "3", "4"]

        eof = index.resolve("END-OF-FILE")
        assert eof is not None
        assert eof.spec.name == "WS-EOF"

    def test_unknown_name_resolves_to_none(self):
        index = _build_index()
        assert index.resolve("TOTALLY-UNKNOWN-NAME") is None
        assert index.resolve("") is None
        assert index.resolve("   ") is None


class TestSectionOf:
    def test_section_of_each_kind(self):
        index = _build_index()
        assert index.section_of("WS-FS") == "working_storage"
        assert index.section_of("LK-PARAM") == "linkage"
        assert index.section_of("INV-KEY") == "file"

    def test_section_of_unknown_name_is_none(self):
        index = _build_index()
        assert index.section_of("NOPE") is None


class TestSectionRecords:
    def test_linkage_records(self):
        index = _build_index()
        assert [r.name for r in index.linkage_records()] == ["LK-PARAM"]

    def test_working_storage_records(self):
        index = _build_index()
        names = [r.name for r in index.working_storage_records()]
        assert names == ["WS-FS", "WS-EOF", "WS-QTY-HOLDER"]


class TestUnresolvedFileSectionRecord:
    def test_select_with_no_matching_fd_is_reported(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GAPTEST.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT GHOST-FILE ASSIGN TO 'GHOST.DAT'.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-DUMMY            PIC X.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY 'HI'.
"""
        result = parse_cobol(source, filename="gaptest.cbl")
        assert result.ast is not None
        index = ProgramLayoutIndex.build(result.ast)
        assert any("GHOST-FILE" in u for u in index.unresolved)


class TestMultiProgramCompilationUnit:
    """subprogram_demo.cbl bundles a caller and two callees (contained_programs)."""

    def test_contained_program_indexes_its_own_linkage(self):
        result = parse_cobol("tests/samples/subprogram_demo.cbl")
        assert result.ast is not None
        assert [p.program_name for p in result.ast.contained_programs] == [
            "CALCULATOR",
            "STRINGPROC",
        ]

        calculator_index = ProgramLayoutIndex.build(result.ast.contained_programs[0])
        assert [r.name for r in calculator_index.linkage_records()] == [
            "LK-NUM1",
            "LK-NUM2",
            "LK-OPERATION",
            "LK-RESULT",
            "LK-RETURN-CODE",
        ]
        assert calculator_index.unresolved == []

    def test_top_level_caller_has_no_linkage_of_its_own(self):
        result = parse_cobol("tests/samples/subprogram_demo.cbl")
        assert result.ast is not None
        caller_index = ProgramLayoutIndex.build(result.ast)
        assert caller_index.linkage_records() == []


class TestFromFile:
    def test_from_file_builds_over_a_sample(self):
        index = ProgramLayoutIndex.from_file("tests/samples/file_operations.cbl")
        assert index.record_for_file("SEQ-FILE") is not None
        assert index.file_facts("IDX-FILE").organization == "INDEXED"

    def test_from_file_raises_program_layout_error_when_ast_is_none(self):
        with pytest.raises(ProgramLayoutError):
            ProgramLayoutIndex.from_file("/this/path/does/not/exist.cbl")


class TestFdRecordTypeMetadata:
    """Pins the DATA DIVISION parser's new fd_record_type metadata tag.

    ProgramLayoutIndex.file_facts() depends on this to tell an SD (sort/merge
    work file) apart from a real FD -- without it, every FILE SECTION entry
    looked identical regardless of which keyword declared it.
    """

    def test_fd_tags_fd_and_sd_tags_sd(self):
        result = parse_cobol(_PROGRAM, filename="layouttest.cbl")
        assert result.ast is not None
        data_div = result.ast.get_division("DATA")
        file_section = data_div.get_section_by_name("FILE")
        by_name = {item.name: item for item in file_section.data_items}
        assert by_name["INV-REC"].get_metadata("fd_record_type") == "FD"
        assert by_name["SORT-REC"].get_metadata("fd_record_type") == "SD"
