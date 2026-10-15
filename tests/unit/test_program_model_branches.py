"""Tests targeting uncovered branches in models/program.py.

Covers branch coverage gaps (45 missing branches) in:
- find_data_items: name_pattern filter, level filter, combined (lines 280-287)
- find_procedures: proc_type PARAGRAPH/SECTION, name_pattern (lines 303-317)
- get_all_statements: nested statement attributes traversal (lines 366-394)
- to_dict: SerializationConfig options (lines 651-668)
- to_json: config_or_indent overloads (lines 670-679)
- from_json: metadata reconstruction (lines 706-718)
- validate: missing divisions, division order (lines 550-600)
- _calculate_statistics: node type checks (lines 619-636)
- CobolSection.get_paragraph_by_name (lines 45-53)
- CobolDivision sections/paragraphs management
- has_sql, has_cics, has_ims: False paths (lines 423-445)
- find_statements_using_variable (lines 407-421)
"""

import json

import pytest

from cobolparser import parse_cobol
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.program import (
    CobolDivision,
    CobolParagraph,
    CobolProgram,
    CobolSection,
    LossyDeserializationWarning,
)
from cobolparser.plugins.core import SerializationConfig


def _parse(code):
    """Parse a full COBOL program."""
    return parse_cobol(code)


def _make_minimal_program():
    """Create a minimal program with all divisions."""
    src = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. TEST-PROG.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-A PIC X(10).\n"
        "       01 WS-B PIC 9(4) VALUE 0.\n"
        "       01 WS-C PIC 9(4) VALUE 100.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-LOGIC.\n"
        "           MOVE WS-A TO WS-B.\n"
        "           DISPLAY WS-C.\n"
        "           STOP RUN.\n"
    )
    return parse_cobol(src)


class TestFindDataItems:
    """Tests for find_data_items branch coverage (lines 270-291)."""

    def test_find_data_items_no_filters(self):
        """find_data_items with no filters returns all items."""
        result = _make_minimal_program()
        items = result.ast.find_data_items()
        assert len(items) >= 3

    def test_find_data_items_by_name_pattern(self):
        """find_data_items with name_pattern filter."""
        result = _make_minimal_program()
        items = result.ast.find_data_items(name_pattern="WS-A")
        assert any(item.name == "WS-A" for item in items)

    def test_find_data_items_by_name_pattern_wildcard(self):
        """find_data_items with wildcard name pattern."""
        result = _make_minimal_program()
        items = result.ast.find_data_items(name_pattern="WS-*")
        assert len(items) >= 3

    def test_find_data_items_by_name_pattern_no_match(self):
        """find_data_items with non-matching pattern returns empty."""
        result = _make_minimal_program()
        items = result.ast.find_data_items(name_pattern="NONEXISTENT")
        assert len(items) == 0

    def test_find_data_items_by_level(self):
        """find_data_items with level filter."""
        result = _make_minimal_program()
        items = result.ast.find_data_items(level=1)
        assert all(item.level == 1 for item in items)

    def test_find_data_items_by_level_no_match(self):
        """find_data_items with non-matching level."""
        result = _make_minimal_program()
        items = result.ast.find_data_items(level=88)
        assert len(items) == 0

    def test_find_data_items_combined_filters(self):
        """find_data_items with both name_pattern and level."""
        result = _make_minimal_program()
        items = result.ast.find_data_items(name_pattern="WS-*", level=1)
        assert len(items) >= 1
        assert all(item.level == 1 for item in items)


class TestFindProcedures:
    """Tests for find_procedures branch coverage (lines 293-319)."""

    def test_find_procedures_no_filters(self):
        """find_procedures with no filters returns all procedures."""
        result = _make_minimal_program()
        procs = result.ast.find_procedures()
        assert len(procs) >= 1

    def test_find_procedures_paragraph_type(self):
        """find_procedures with proc_type='PARAGRAPH'."""
        result = _make_minimal_program()
        procs = result.ast.find_procedures(proc_type="PARAGRAPH")
        assert all(isinstance(p, CobolParagraph) for p in procs)

    def test_find_procedures_section_type(self):
        """find_procedures with proc_type='SECTION'."""
        result = _make_minimal_program()
        procs = result.ast.find_procedures(proc_type="SECTION")
        assert all(isinstance(p, CobolSection) for p in procs)

    def test_find_procedures_by_name_pattern(self):
        """find_procedures with name_pattern."""
        result = _make_minimal_program()
        procs = result.ast.find_procedures(name_pattern="MAIN-*")
        assert len(procs) >= 1

    def test_find_procedures_by_name_no_match(self):
        """find_procedures with non-matching name returns empty."""
        result = _make_minimal_program()
        procs = result.ast.find_procedures(name_pattern="NONEXISTENT")
        assert len(procs) == 0

    def test_find_procedures_combined(self):
        """find_procedures with proc_type and name_pattern."""
        result = _make_minimal_program()
        procs = result.ast.find_procedures(proc_type="PARAGRAPH", name_pattern="MAIN-*")
        assert len(procs) >= 1


class TestGetAllStatements:
    """Tests for get_all_statements traversal (lines 321-396)."""

    def test_get_all_statements_basic(self):
        """get_all_statements returns all statements."""
        result = _make_minimal_program()
        stmts = result.ast.get_all_statements()
        types = [s.statement_type for s in stmts]
        assert "MOVE" in types
        assert "DISPLAY" in types

    def test_get_all_statements_with_nested_if(self):
        """get_all_statements traverses nested IF/ELSE branches."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-IF.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-X PIC 9(4) VALUE 5.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-LOGIC.\n"
            "           IF WS-X > 3\n"
            "               DISPLAY 'BIG'\n"
            "           ELSE\n"
            "               DISPLAY 'SMALL'\n"
            "           END-IF.\n"
            "           STOP RUN.\n"
        )
        result = parse_cobol(src)
        stmts = result.ast.get_all_statements()
        types = [s.statement_type for s in stmts]
        assert "IF" in types
        assert types.count("DISPLAY") >= 2

    def test_find_statements_by_type(self):
        """find_statements filters by type."""
        result = _make_minimal_program()
        move_stmts = result.ast.find_statements(stmt_type="MOVE")
        assert all(s.statement_type == "MOVE" for s in move_stmts)

    def test_find_statements_all(self):
        """find_statements with no type returns all."""
        result = _make_minimal_program()
        all_stmts = result.ast.find_statements()
        assert len(all_stmts) == len(result.ast.get_all_statements())


class TestFindStatementsUsingVariable:
    """Tests for find_statements_using_variable (lines 407-421)."""

    def test_find_statements_using_existing_variable(self):
        """Find statements that use WS-A."""
        result = _make_minimal_program()
        stmts = result.ast.find_statements_using_variable("WS-A")
        assert len(stmts) >= 1

    def test_find_statements_using_nonexistent_variable(self):
        """No statements use NONEXISTENT variable."""
        result = _make_minimal_program()
        stmts = result.ast.find_statements_using_variable("NONEXISTENT")
        assert len(stmts) == 0


class TestHasSqlCicsIms:
    """Tests for has_sql, has_cics, has_ims returning False (lines 423-445)."""

    def test_has_sql_false(self):
        result = _make_minimal_program()
        assert result.ast.has_sql() is False

    def test_has_cics_false(self):
        result = _make_minimal_program()
        assert result.ast.has_cics() is False

    def test_has_ims_false(self):
        result = _make_minimal_program()
        assert result.ast.has_ims() is False

    def test_uses_ims_interface_false(self):
        result = _make_minimal_program()
        assert result.ast.uses_ims_interface() is False

    def test_get_sql_statements_empty(self):
        result = _make_minimal_program()
        assert result.ast.get_sql_statements() == []

    def test_get_cics_statements_empty(self):
        result = _make_minimal_program()
        assert result.ast.get_cics_statements() == []

    def test_get_ims_statements_empty(self):
        result = _make_minimal_program()
        assert result.ast.get_ims_statements() == []

    def test_get_ims_interface_calls_empty(self):
        result = _make_minimal_program()
        assert result.ast.get_ims_interface_calls() == []


class TestValidate:
    """Tests for validate method branch coverage (lines 550-600)."""

    def test_validate_complete_program(self):
        """Program with all divisions validates without errors."""
        result = _make_minimal_program()
        validation = result.ast.validate()
        assert len(validation.errors) == 0

    def test_validate_missing_identification(self):
        """Program without IDENTIFICATION reports error."""
        program = CobolProgram("", SourceLocation(1, 1))
        validation = program.validate()
        assert any("IDENTIFICATION" in e for e in validation.errors)

    def test_validate_missing_program_id(self):
        """Program with IDENTIFICATION but no PROGRAM-ID reports error."""
        program = CobolProgram("", SourceLocation(1, 1))
        id_div = CobolDivision("IDENTIFICATION", SourceLocation(1, 1))
        program.add_division(id_div)
        validation = program.validate()
        assert any("PROGRAM-ID" in e for e in validation.errors)

    def test_validate_empty_procedure(self):
        """Empty PROCEDURE DIVISION warns."""
        program = CobolProgram("TEST", SourceLocation(1, 1))
        id_div = CobolDivision("IDENTIFICATION", SourceLocation(1, 1))
        proc_div = CobolDivision("PROCEDURE", SourceLocation(2, 1))
        program.add_division(id_div)
        program.add_division(proc_div)
        validation = program.validate()
        assert any("empty" in w.lower() for w in validation.warnings)

    def test_validate_empty_data_division(self):
        """Empty DATA DIVISION warns about no sections."""
        program = CobolProgram("TEST", SourceLocation(1, 1))
        id_div = CobolDivision("IDENTIFICATION", SourceLocation(1, 1))
        data_div = CobolDivision("DATA", SourceLocation(2, 1))
        program.add_division(id_div)
        program.add_division(data_div)
        validation = program.validate()
        assert any("no sections" in w.lower() for w in validation.warnings)


class TestToDictToJson:
    """Tests for to_dict/to_json with SerializationConfig (lines 638-679)."""

    def test_to_dict_default_config(self):
        """to_dict with default config."""
        result = _make_minimal_program()
        d = result.ast.to_dict()
        assert "program_name" in d
        assert "divisions" in d

    def test_to_dict_with_source_locations(self):
        """to_dict with include_source_locations=True."""
        result = _make_minimal_program()
        config = SerializationConfig(include_source_locations=True)
        d = result.ast.to_dict(config)
        assert "location" in d

    def test_to_dict_with_metadata(self):
        """to_dict with include_metadata=True."""
        result = _make_minimal_program()
        config = SerializationConfig(include_metadata=True)
        d = result.ast.to_dict(config)
        assert "metadata" in d
        assert "statistics" in d["metadata"]

    def test_to_dict_with_all_options(self):
        """to_dict with both source locations and metadata."""
        result = _make_minimal_program()
        config = SerializationConfig(
            include_source_locations=True, include_metadata=True
        )
        d = result.ast.to_dict(config)
        assert "location" in d
        assert "metadata" in d
        assert d["metadata"].get("source_locations") is True

    def test_to_json_with_int_indent(self):
        """to_json with integer indent."""
        result = _make_minimal_program()
        j = result.ast.to_json(4)
        data = json.loads(j)
        assert "program_name" in data

    def test_to_json_with_config(self):
        """to_json with SerializationConfig."""
        result = _make_minimal_program()
        config = SerializationConfig(include_metadata=True)
        j = result.ast.to_json(config)
        data = json.loads(j)
        assert "metadata" in data

    def test_to_json_default(self):
        """to_json with no arguments."""
        result = _make_minimal_program()
        j = result.ast.to_json()
        data = json.loads(j)
        assert "program_name" in data


class TestFromJson:
    """Tests for from_json reconstruction (lines 681-718)."""

    def test_from_json_roundtrip(self):
        """Round-trip: to_json -> from_json preserves structure."""
        result = _make_minimal_program()
        config = SerializationConfig(include_source_locations=True)
        j = result.ast.to_json(config)
        with pytest.warns(LossyDeserializationWarning, match="dropped 3"):
            reconstructed = CobolProgram.from_json(j)
        assert reconstructed.program_name == result.ast.program_name

    def test_from_json_with_metadata(self):
        """from_json reconstructs metadata (lines 706-718)."""
        result = _make_minimal_program()
        result.ast.set_metadata("custom_key", "custom_value")
        config = SerializationConfig(
            include_source_locations=True, include_metadata=True
        )
        j = result.ast.to_json(config)
        with pytest.warns(LossyDeserializationWarning):
            reconstructed = CobolProgram.from_json(j)
        assert reconstructed._metadata.get("custom_key") == "custom_value"

    def test_from_json_minimal(self):
        """from_json with minimal JSON (no metadata, no location)."""
        j = json.dumps(
            {
                "node_type": "Program",
                "program_name": "MINIMAL",
                "divisions": {},
            }
        )
        program = CobolProgram.from_json(j)
        assert program.program_name == "MINIMAL"


class TestGetStatistics:
    """Tests for get_statistics / _calculate_statistics (lines 602-636)."""

    def test_get_statistics(self):
        """get_statistics returns calculated stats."""
        result = _make_minimal_program()
        stats = result.ast.get_statistics()
        assert stats["division_count"] >= 2
        assert stats["statement_count"] >= 2
        assert stats["data_item_count"] >= 3

    def test_get_statistics_cached(self):
        """get_statistics returns same dict on second call."""
        result = _make_minimal_program()
        stats1 = result.ast.get_statistics()
        stats2 = result.ast.get_statistics()
        assert stats1 is stats2


class TestCobolSectionEdgeCases:
    """Tests for CobolSection methods."""

    def test_get_paragraph_by_name_found(self):
        """get_paragraph_by_name returns matching paragraph."""
        section = CobolSection("TEST-SECTION", SourceLocation(1, 1))
        para = CobolParagraph("TARGET-PARA", SourceLocation(2, 1))
        section.add_paragraph(para)
        assert section.get_paragraph_by_name("TARGET-PARA") is para

    def test_get_paragraph_by_name_not_found(self):
        """get_paragraph_by_name returns None when not found."""
        section = CobolSection("TEST-SECTION", SourceLocation(1, 1))
        para = CobolParagraph("OTHER-PARA", SourceLocation(2, 1))
        section.add_paragraph(para)
        assert section.get_paragraph_by_name("MISSING") is None

    def test_section_to_dict(self):
        """CobolSection.to_dict returns expected structure."""
        section = CobolSection("MY-SECTION", SourceLocation(1, 1))
        d = section.to_dict()
        assert d["section_name"] == "MY-SECTION"
        assert d["node_type"] == "Section"


class TestGetProcedures:
    """Tests for get_procedures (lines 494-512)."""

    def test_get_procedures_with_sections_and_paragraphs(self):
        """Program with sections containing paragraphs."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-PROCS.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-SECTION SECTION.\n"
            "       PARA-1.\n"
            "           DISPLAY 'HELLO'.\n"
            "       PARA-2.\n"
            "           STOP RUN.\n"
        )
        result = parse_cobol(src)
        procs = result.ast.get_procedures()
        assert len(procs) >= 2


class TestFromJsonSelectEntries:
    """from_json rebuilds FILE-CONTROL SELECT entries (issue #346)."""

    _SRC = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. SELPROG.\n"
        "       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n"
        "       FILE-CONTROL.\n"
        "           SELECT IN-FILE ASSIGN TO INDD\n"
        "               ORGANIZATION IS INDEXED\n"
        "               ACCESS MODE IS DYNAMIC\n"
        "               RECORD KEY IS IN-KEY\n"
        "               ALTERNATE RECORD KEY IS IN-ALT WITH DUPLICATES\n"
        "               FILE STATUS IS WS-IN-STAT.\n"
        "           SELECT OUT-FILE ASSIGN TO OUTDD\n"
        "               ORGANIZATION IS RELATIVE\n"
        "               RELATIVE KEY IS WS-REL.\n"
        "       DATA DIVISION.\n"
        "       FILE SECTION.\n"
        "       FD IN-FILE.\n"
        "       01 IN-REC.\n"
        "          05 IN-KEY PIC X(5).\n"
        "          05 IN-ALT PIC X(5).\n"
        "       FD OUT-FILE.\n"
        "       01 OUT-REC PIC X(10).\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-IN-STAT PIC XX.\n"
        "       01 WS-REL PIC 9(4) COMP.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        "           CONTINUE.\n"
    )

    def _round_trip(self):
        ast = parse_cobol(self._SRC).ast
        with pytest.warns(LossyDeserializationWarning) as record:
            restored = CobolProgram.from_json(ast.to_json())
        return ast, restored, [str(w.message) for w in record]

    def test_select_entries_survive_round_trip(self):
        ast, restored, _ = self._round_trip()
        env = "ENVIRONMENT"
        assert restored.to_dict()["divisions"][env] == ast.to_dict()["divisions"][env]

    def test_warning_counts_only_procedure_statements(self):
        _, _, messages = self._round_trip()
        assert len(messages) == 1
        assert "dropped 1 PROCEDURE DIVISION statement(s) from 1 paragraph(s)" in (
            messages[0]
        )

    def test_file_facts_match_after_round_trip(self):
        from cobolparser.generators import ProgramLayoutIndex

        ast, restored, _ = self._round_trip()
        before = ProgramLayoutIndex.build(ast)
        after = ProgramLayoutIndex.build(restored)
        for name in ("IN-FILE", "OUT-FILE"):
            b, a = before.file_facts(name), after.file_facts(name)
            assert a is not None and b is not None
            assert (a.organization, a.access_mode, a.record_key) == (
                b.organization,
                b.access_mode,
                b.record_key,
            )
            assert a.alternate_keys == b.alternate_keys
            assert a.relative_key == b.relative_key
            assert a.file_status_field == b.file_status_field
        assert after.file_facts("IN-FILE").organization == "INDEXED"
        assert after.file_facts("OUT-FILE").relative_key == "WS-REL"

    def test_select_only_program_emits_no_warning(self):
        src = self._SRC.replace("       MAIN-PARA.\n           CONTINUE.\n", "")
        ast = parse_cobol(src).ast
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("error", LossyDeserializationWarning)
            restored = CobolProgram.from_json(ast.to_json())
        assert restored.to_dict()["divisions"]["ENVIRONMENT"] == (
            ast.to_dict()["divisions"]["ENVIRONMENT"]
        )
