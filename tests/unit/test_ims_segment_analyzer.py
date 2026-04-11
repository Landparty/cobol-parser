"""
Unit and integration tests for IMSSegmentAnalyzer.

Coverage:
- IMSDLICall dataclass (fields, primary_segment property)
- IMSSegmentAnalyzer.analyze() with:
    * group-item SSAs (most common real-world pattern)
    * elementary-item SSAs (simple unqualified)
    * MOVE-tracked SSA segment names (dynamic assignment)
    * multiple SSAs per DLI call
    * multiple DLI calls in one program
    * function-code resolution (VALUE clause, MOVE assignment)
    * all three IMS interfaces: CBLTDLI, AIBTDLI, CEETDLI
    * program with no IMS calls
    * unresolvable SSA (no definition found)
- IMSSegmentAnalyzer.get_all_segment_names()
- _strip_quotes helper
- __init__.py lazy-import paths (IMSSegmentAnalyzer, IMSDLICall)
"""

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.ims_segment_analyzer import (
    IMSDLICall,
    IMSSegmentAnalyzer,
    _strip_quotes,
)
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.data_items import CobolDataItem
from cobolparser.models.program import CobolDivision, CobolParagraph, CobolProgram
from cobolparser.models.statements import CallStatement, MoveStatement

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_loc(line: int = 1, col: int = 1) -> SourceLocation:
    return SourceLocation(line, col)


def _make_data_item(name: str, level: int = 5, value: str | None = None) -> CobolDataItem:
    item = CobolDataItem(name, level, _make_loc())
    if value is not None:
        item.set_value_clause(value)
    return item


def _parse(source: str):
    """Parse a fixed-format COBOL source string and assert success."""
    result = parse_cobol(source)
    assert result.ast is not None, f"Parse failed: {result.errors}"
    return result.ast


# ── Inline COBOL programs ─────────────────────────────────────────────────────

# Single GU call with a group-item SSA
_COBOL_SINGLE_GU = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IMSTEST1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  DLI-GU              PIC X(4) VALUE 'GU  '.
       01  DB-PCB              PIC S9(9) COMP.
       01  EMP-IO-AREA         PIC X(40).
       01  SSA-EMPLOYEE.
           05  SSA-SEG-NAME    PIC X(8) VALUE 'EMPLOYEE'.
           05  FILLER          PIC X(1) VALUE ' '.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           CALL 'CBLTDLI' USING DLI-GU
                                DB-PCB
                                EMP-IO-AREA
                                SSA-EMPLOYEE.
           STOP RUN.
"""

# Two DLI calls: GU with group SSA, ISRT with elementary SSA
_COBOL_TWO_CALLS = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IMSTEST2.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  DLI-GU              PIC X(4) VALUE 'GU  '.
       01  DLI-ISRT            PIC X(4) VALUE 'ISRT'.
       01  DB-PCB              PIC S9(9) COMP.
       01  IO-AREA             PIC X(40).
       01  SSA-DEPT.
           05  SSA-SEG-NAME    PIC X(8) VALUE 'DEPT    '.
           05  FILLER          PIC X(1) VALUE ' '.
       01  SSA-PROJ            PIC X(9) VALUE 'PROJECT  '.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           CALL 'CBLTDLI' USING DLI-GU
                                DB-PCB
                                IO-AREA
                                SSA-DEPT.
           CALL 'CBLTDLI' USING DLI-ISRT
                                DB-PCB
                                IO-AREA
                                SSA-PROJ.
           STOP RUN.
"""

# Multiple SSAs in one call (path call: root + child)
_COBOL_MULTI_SSA = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IMSTEST3.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  DLI-GU              PIC X(4) VALUE 'GU  '.
       01  DB-PCB              PIC S9(9) COMP.
       01  IO-AREA             PIC X(40).
       01  SSA-ROOT.
           05  SSA-SEG-NAME    PIC X(8) VALUE 'HOSPITAL'.
           05  FILLER          PIC X(1) VALUE ' '.
       01  SSA-CHILD.
           05  SSA-SEG-NAME    PIC X(8) VALUE 'PATIENT '.
           05  FILLER          PIC X(1) VALUE ' '.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           CALL 'CBLTDLI' USING DLI-GU
                                DB-PCB
                                IO-AREA
                                SSA-ROOT
                                SSA-CHILD.
           STOP RUN.
"""

# AIBTDLI interface
_COBOL_AIBTDLI = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IMSTEST4.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  DLI-GN              PIC X(4) VALUE 'GN  '.
       01  DB-PCB              PIC S9(9) COMP.
       01  IO-AREA             PIC X(40).
       01  SSA-ORDER.
           05  SSA-SEG-NAME    PIC X(8) VALUE 'ORDER   '.
           05  FILLER          PIC X(1) VALUE ' '.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           CALL 'AIBTDLI' USING DLI-GN
                                DB-PCB
                                IO-AREA
                                SSA-ORDER.
           STOP RUN.
"""

# CEETDLI interface
_COBOL_CEETDLI = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IMSTEST5.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  DLI-DLET            PIC X(4) VALUE 'DLET'.
       01  DB-PCB              PIC S9(9) COMP.
       01  IO-AREA             PIC X(40).
       01  SSA-ITEM.
           05  SSA-SEG-NAME    PIC X(8) VALUE 'LINEITEM'.
           05  FILLER          PIC X(1) VALUE ' '.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           CALL 'CEETDLI' USING DLI-DLET
                                DB-PCB
                                IO-AREA
                                SSA-ITEM.
           STOP RUN.
"""

# MOVE-based SSA assignment (dynamic segment name)
_COBOL_MOVE_SSA = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IMSTEST6.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  DLI-GU              PIC X(4) VALUE 'GU  '.
       01  DB-PCB              PIC S9(9) COMP.
       01  IO-AREA             PIC X(40).
       01  SSA-DYN             PIC X(9).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           MOVE 'ACCOUNT  '    TO SSA-DYN.
           CALL 'CBLTDLI' USING DLI-GU
                                DB-PCB
                                IO-AREA
                                SSA-DYN.
           STOP RUN.
"""

# No DLI calls at all
_COBOL_NO_IMS = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOIMS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-MSG              PIC X(20) VALUE 'HELLO'.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY WS-MSG.
           STOP RUN.
"""


# ── Tests: _strip_quotes ──────────────────────────────────────────────────────


class TestStripQuotes:
    def test_single_quoted(self):
        assert _strip_quotes("'CBLTDLI'") == "CBLTDLI"

    def test_double_quoted(self):
        assert _strip_quotes('"CBLTDLI"') == "CBLTDLI"

    def test_unquoted(self):
        assert _strip_quotes("CBLTDLI") == "CBLTDLI"

    def test_empty(self):
        assert _strip_quotes("") == ""

    def test_whitespace_around_quotes(self):
        assert _strip_quotes("  'GU  '  ") == "GU  "

    def test_single_char_not_stripped(self):
        # A single character string with quotes is stripped correctly
        assert _strip_quotes("'X'") == "X"

    def test_mismatched_quotes_not_stripped(self):
        assert _strip_quotes("'MIXED\"") == "'MIXED\""


# ── Tests: IMSDLICall dataclass ───────────────────────────────────────────────


class TestIMSDLICall:
    def _make_call(self, segment_names: list[str | None]) -> IMSDLICall:
        return IMSDLICall(
            location=_make_loc(),
            interface="CBLTDLI",
            function_code="GU",
            function_code_var="DLI-GU",
            pcb_name="DB-PCB",
            io_area_name="IO-AREA",
            ssa_names=["SSA-VAR"],
            segment_names=segment_names,
        )

    def test_primary_segment_first_resolved(self):
        call = self._make_call(["EMPLOYEE", "DEPT"])
        assert call.primary_segment == "EMPLOYEE"

    def test_primary_segment_skips_none(self):
        call = self._make_call([None, "DEPT"])
        assert call.primary_segment == "DEPT"

    def test_primary_segment_all_none(self):
        call = self._make_call([None, None])
        assert call.primary_segment is None

    def test_primary_segment_empty_list(self):
        call = self._make_call([])
        assert call.primary_segment is None

    def test_default_factory_fields(self):
        call = IMSDLICall(
            location=_make_loc(),
            interface="CBLTDLI",
            function_code=None,
            function_code_var=None,
            pcb_name=None,
            io_area_name=None,
        )
        assert call.ssa_names == []
        assert call.segment_names == []


# ── Tests: IMSSegmentAnalyzer unit (AST built manually) ──────────────────────


class TestIMSSegmentAnalyzerUnit:
    """Build minimal AST objects directly to isolate the analyzer logic."""

    def _make_program_with_call(
        self,
        interface: str,
        params: list[str],
        data_items: list[CobolDataItem],
    ) -> CobolProgram:
        loc = _make_loc()
        program = CobolProgram("TEST-PROG", loc)

        # DATA DIVISION with supplied items
        data_div = CobolDivision("DATA", loc)
        for item in data_items:
            data_div.add_child(item)
        program.add_division(data_div)

        # PROCEDURE DIVISION with one CALL statement
        proc_div = CobolDivision("PROCEDURE", loc)
        para = CobolParagraph("MAIN", loc)
        call = CallStatement(loc)
        call.set_called_program(f"'{interface}'", is_dynamic=False)
        for p in params:
            call.add_using_parameter(p)
        para.add_statement(call)
        proc_div.add_paragraph(para)
        program.add_division(proc_div)

        return program

    # -- group-item SSA --

    def test_group_item_ssa(self):
        """Segment name extracted from first child VALUE of a group SSA item."""
        root = _make_data_item("SSA-EMPLOYEE", level=1)
        child = _make_data_item("SSA-SEG-NAME", level=5, value="EMPLOYEE")
        root.add_child(child)

        program = self._make_program_with_call(
            "CBLTDLI",
            ["DLI-GU", "DB-PCB", "IO-AREA", "SSA-EMPLOYEE"],
            [root],
        )
        analyzer = IMSSegmentAnalyzer()
        results = analyzer.analyze(program)

        assert len(results) == 1
        assert results[0].segment_names == ["EMPLOYEE"]
        assert results[0].primary_segment == "EMPLOYEE"

    def test_group_item_ssa_trailing_spaces_stripped(self):
        """Trailing spaces in segment name are stripped."""
        root = _make_data_item("SSA-DEPT", level=1)
        child = _make_data_item("SSA-SEG-NAME", level=5, value="DEPT    ")
        root.add_child(child)

        program = self._make_program_with_call(
            "CBLTDLI",
            ["DLI-GU", "DB-PCB", "IO-AREA", "SSA-DEPT"],
            [root],
        )
        results = IMSSegmentAnalyzer().analyze(program)
        assert results[0].primary_segment == "DEPT"

    # -- elementary-item SSA --

    def test_elementary_ssa(self):
        """Segment name extracted from VALUE clause of an elementary SSA item."""
        item = _make_data_item("SSA-PROJ", level=1, value="PROJECT  ")

        program = self._make_program_with_call(
            "CBLTDLI",
            ["DLI-GU", "DB-PCB", "IO-AREA", "SSA-PROJ"],
            [item],
        )
        results = IMSSegmentAnalyzer().analyze(program)
        assert results[0].primary_segment == "PROJECT"

    def test_elementary_ssa_exactly_8_chars(self):
        item = _make_data_item("SSA-HOSP", level=1, value="HOSPITAL ")
        program = self._make_program_with_call(
            "CBLTDLI",
            ["DLI-GU", "DB-PCB", "IO-AREA", "SSA-HOSP"],
            [item],
        )
        results = IMSSegmentAnalyzer().analyze(program)
        assert results[0].primary_segment == "HOSPITAL"

    # -- unresolvable SSA --

    def test_unknown_ssa_returns_none(self):
        """If the SSA variable has no data definition, segment_name is None."""
        program = self._make_program_with_call(
            "CBLTDLI",
            ["DLI-GU", "DB-PCB", "IO-AREA", "SSA-UNKNOWN"],
            [],
        )
        results = IMSSegmentAnalyzer().analyze(program)
        assert results[0].segment_names == [None]
        assert results[0].primary_segment is None

    # -- function-code resolution --

    def test_func_code_resolved_from_value_clause(self):
        func_item = _make_data_item("DLI-GU", level=1, value="GU  ")
        program = self._make_program_with_call(
            "CBLTDLI",
            ["DLI-GU", "DB-PCB", "IO-AREA"],
            [func_item],
        )
        results = IMSSegmentAnalyzer().analyze(program)
        assert results[0].function_code == "GU"
        assert results[0].function_code_var == "DLI-GU"

    def test_func_code_unresolvable_returns_none(self):
        program = self._make_program_with_call(
            "CBLTDLI",
            ["DLI-UNKNOWN", "DB-PCB", "IO-AREA"],
            [],
        )
        results = IMSSegmentAnalyzer().analyze(program)
        assert results[0].function_code is None

    # -- no IMS calls --

    def test_no_ims_calls_returns_empty(self):
        loc = _make_loc()
        program = CobolProgram("NO-IMS", loc)
        proc_div = CobolDivision("PROCEDURE", loc)
        program.add_division(proc_div)

        results = IMSSegmentAnalyzer().analyze(program)
        assert results == []

    # -- interface names --

    def test_interface_field_unquoted(self):
        """Interface name stored without quotes regardless of input."""
        item = _make_data_item("SSA-X", level=1, value="SEGNAME ")
        program = self._make_program_with_call(
            "CBLTDLI", ["F", "P", "I", "SSA-X"], [item]
        )
        results = IMSSegmentAnalyzer().analyze(program)
        assert results[0].interface == "CBLTDLI"

    # -- get_all_segment_names --

    def test_get_all_segment_names_deduplicates(self):
        """Same segment name referenced twice appears only once in the output."""
        root1 = _make_data_item("SSA-A", level=1)
        root1.add_child(_make_data_item("SEG-NAME", level=5, value="EMPLOYEE"))

        root2 = _make_data_item("SSA-B", level=1)
        root2.add_child(_make_data_item("SEG-NAME2", level=5, value="EMPLOYEE"))

        loc = _make_loc()
        program = CobolProgram("PROG", loc)
        data_div = CobolDivision("DATA", loc)
        data_div.add_child(root1)
        data_div.add_child(root2)
        program.add_division(data_div)

        proc_div = CobolDivision("PROCEDURE", loc)
        para = CobolParagraph("MAIN", loc)

        call1 = CallStatement(loc)
        call1.set_called_program("'CBLTDLI'")
        call1.add_using_parameter("F")
        call1.add_using_parameter("P")
        call1.add_using_parameter("I")
        call1.add_using_parameter("SSA-A")
        para.add_statement(call1)

        call2 = CallStatement(loc)
        call2.set_called_program("'CBLTDLI'")
        call2.add_using_parameter("F")
        call2.add_using_parameter("P")
        call2.add_using_parameter("I")
        call2.add_using_parameter("SSA-B")
        para.add_statement(call2)

        proc_div.add_paragraph(para)
        program.add_division(proc_div)

        analyzer = IMSSegmentAnalyzer()
        results = analyzer.analyze(program)
        all_segs = analyzer.get_all_segment_names(results)
        assert all_segs == ["EMPLOYEE"]

    def test_get_all_segment_names_sorted(self):
        root_a = _make_data_item("SSA-A", level=1)
        root_a.add_child(_make_data_item("N1", level=5, value="Zzebra  "))
        root_b = _make_data_item("SSA-B", level=1)
        root_b.add_child(_make_data_item("N2", level=5, value="AARDVARK"))

        loc = _make_loc()
        program = CobolProgram("PROG", loc)
        data_div = CobolDivision("DATA", loc)
        data_div.add_child(root_a)
        data_div.add_child(root_b)
        program.add_division(data_div)

        proc_div = CobolDivision("PROCEDURE", loc)
        para = CobolParagraph("MAIN", loc)

        for ssa in ("SSA-A", "SSA-B"):
            call = CallStatement(loc)
            call.set_called_program("'CBLTDLI'")
            for p in ("F", "P", "I", ssa):
                call.add_using_parameter(p)
            para.add_statement(call)

        proc_div.add_paragraph(para)
        program.add_division(proc_div)

        analyzer = IMSSegmentAnalyzer()
        results = analyzer.analyze(program)
        assert analyzer.get_all_segment_names(results) == ["AARDVARK", "Zzebra"]

    # -- multiple SSAs in one call --

    def test_multiple_ssas_per_call(self):
        root = _make_data_item("SSA-ROOT", level=1)
        root.add_child(_make_data_item("N1", level=5, value="HOSPITAL"))
        child = _make_data_item("SSA-CHILD", level=1)
        child.add_child(_make_data_item("N2", level=5, value="PATIENT "))

        program = self._make_program_with_call(
            "CBLTDLI",
            ["DLI-GU", "DB-PCB", "IO-AREA", "SSA-ROOT", "SSA-CHILD"],
            [root, child],
        )
        results = IMSSegmentAnalyzer().analyze(program)
        assert results[0].ssa_names == ["SSA-ROOT", "SSA-CHILD"]
        assert results[0].segment_names == ["HOSPITAL", "PATIENT"]


# ── Tests: MOVE-tracking ──────────────────────────────────────────────────────


class TestMoveTracking:
    """Test SSA segment name resolution via MOVE statement tracking."""

    def test_move_literal_to_ssa_var(self):
        """MOVE 'ACCOUNT  ' TO SSA-DYN -> segment name resolved to ACCOUNT."""
        loc = _make_loc()
        program = CobolProgram("PROG", loc)

        data_div = CobolDivision("DATA", loc)
        ssa_item = _make_data_item("SSA-DYN", level=1)  # no VALUE clause
        data_div.add_child(ssa_item)
        program.add_division(data_div)

        proc_div = CobolDivision("PROCEDURE", loc)
        para = CobolParagraph("MAIN", loc)

        # MOVE 'ACCOUNT  ' TO SSA-DYN
        move = MoveStatement(loc)
        move.set_source("'ACCOUNT  '")
        move.add_target("SSA-DYN")
        para.add_statement(move)

        call = CallStatement(loc)
        call.set_called_program("'CBLTDLI'")
        for p in ("DLI-GU", "DB-PCB", "IO-AREA", "SSA-DYN"):
            call.add_using_parameter(p)
        para.add_statement(call)

        proc_div.add_paragraph(para)
        program.add_division(proc_div)

        analyzer = IMSSegmentAnalyzer()
        results = analyzer.analyze(program)
        assert results[0].primary_segment == "ACCOUNT"

    def test_move_variable_propagation(self):
        """MOVE SRC TO SSA-DYN where SRC has a VALUE clause."""
        loc = _make_loc()
        program = CobolProgram("PROG", loc)

        src_item = _make_data_item("SRC-SEG", level=1, value="LINEITEM")
        ssa_item = _make_data_item("SSA-DYN", level=1)

        data_div = CobolDivision("DATA", loc)
        data_div.add_child(src_item)
        data_div.add_child(ssa_item)
        program.add_division(data_div)

        proc_div = CobolDivision("PROCEDURE", loc)
        para = CobolParagraph("MAIN", loc)

        move = MoveStatement(loc)
        move.set_source("SRC-SEG")
        move.add_target("SSA-DYN")
        para.add_statement(move)

        call = CallStatement(loc)
        call.set_called_program("'CBLTDLI'")
        for p in ("F", "P", "I", "SSA-DYN"):
            call.add_using_parameter(p)
        para.add_statement(call)

        proc_div.add_paragraph(para)
        program.add_division(proc_div)

        analyzer = IMSSegmentAnalyzer()
        results = analyzer.analyze(program)
        assert results[0].primary_segment == "LINEITEM"


# ── Tests: lazy import via __init__.py ───────────────────────────────────────


class TestLazyImport:
    def test_import_ims_segment_analyzer(self):
        from cobolparser.analysis import IMSSegmentAnalyzer as Cls

        assert Cls is IMSSegmentAnalyzer

    def test_import_ims_dli_call(self):
        from cobolparser.analysis import IMSDLICall as Cls

        assert Cls is IMSDLICall

    def test_unknown_attr_raises(self):
        import cobolparser.analysis as mod

        with pytest.raises(AttributeError):
            _ = mod.DoesNotExist  # type: ignore[attr-defined]


# ── Integration tests: parse real COBOL source ────────────────────────────────


@pytest.mark.integration
class TestIMSSegmentAnalyzerIntegration:
    """End-to-end tests that parse COBOL text through the full parser pipeline."""

    def test_single_gu_call_group_ssa(self):
        ast = _parse(_COBOL_SINGLE_GU)
        analyzer = IMSSegmentAnalyzer()
        results = analyzer.analyze(ast)

        assert len(results) == 1
        call = results[0]
        assert call.interface == "CBLTDLI"
        assert call.function_code == "GU"
        assert call.pcb_name == "DB-PCB"
        assert call.io_area_name == "EMP-IO-AREA"
        assert call.ssa_names == ["SSA-EMPLOYEE"]
        assert call.segment_names == ["EMPLOYEE"]
        assert call.primary_segment == "EMPLOYEE"

    def test_two_calls_mixed_ssa_types(self):
        ast = _parse(_COBOL_TWO_CALLS)
        analyzer = IMSSegmentAnalyzer()
        results = analyzer.analyze(ast)

        assert len(results) == 2

        gu_call = results[0]
        assert gu_call.function_code == "GU"
        assert gu_call.primary_segment == "DEPT"

        isrt_call = results[1]
        assert isrt_call.function_code == "ISRT"
        assert isrt_call.primary_segment == "PROJECT"

    def test_multiple_ssas_path_call(self):
        ast = _parse(_COBOL_MULTI_SSA)
        results = IMSSegmentAnalyzer().analyze(ast)

        assert len(results) == 1
        call = results[0]
        assert call.segment_names == ["HOSPITAL", "PATIENT"]
        assert call.primary_segment == "HOSPITAL"

    def test_aibtdli_interface(self):
        ast = _parse(_COBOL_AIBTDLI)
        results = IMSSegmentAnalyzer().analyze(ast)

        assert len(results) == 1
        assert results[0].interface == "AIBTDLI"
        assert results[0].function_code == "GN"
        assert results[0].primary_segment == "ORDER"

    def test_ceetdli_interface(self):
        ast = _parse(_COBOL_CEETDLI)
        results = IMSSegmentAnalyzer().analyze(ast)

        assert len(results) == 1
        assert results[0].interface == "CEETDLI"
        assert results[0].function_code == "DLET"
        assert results[0].primary_segment == "LINEITEM"

    def test_move_assigned_ssa(self):
        ast = _parse(_COBOL_MOVE_SSA)
        results = IMSSegmentAnalyzer().analyze(ast)

        assert len(results) == 1
        assert results[0].primary_segment == "ACCOUNT"

    def test_no_ims_calls(self):
        ast = _parse(_COBOL_NO_IMS)
        results = IMSSegmentAnalyzer().analyze(ast)
        assert results == []

    def test_get_all_segment_names(self):
        ast = _parse(_COBOL_TWO_CALLS)
        analyzer = IMSSegmentAnalyzer()
        results = analyzer.analyze(ast)
        all_segs = analyzer.get_all_segment_names(results)
        assert all_segs == ["DEPT", "PROJECT"]

    def test_location_populated(self):
        """Each IMSDLICall has a valid SourceLocation."""
        ast = _parse(_COBOL_SINGLE_GU)
        results = IMSSegmentAnalyzer().analyze(ast)
        assert results[0].location.line > 0
