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

Edge cases (TestEdgeCasesUnit):
- Qualified SSA: segment name still comes from first 8 bytes of first child
- CHKP / REPL / DLET calls with zero SSAs
- No USING clause (bare CALL)
- Group SSA whose first child has no VALUE clause -> None
- Elementary SSA VALUE longer than 8 chars -> truncated to 8
- MOVE chain: A (VALUE) -> B -> SSA-VAR (2-hop propagation)
- Function code with two possible MOVE-assigned values -> "CODE1/CODE2"
- Hold-variant function codes: GHU, GHN, GHNP
- GNP function code
- Function codes defined as sub-items of a group (level-05)

Real-world sample tests (3 programs):
- ims_patient_records.cbl: healthcare hierarchy, GU/GN/ISRT/GHU/REPL/CHKP
- ims_banking_accounts.cbl: banking, two PCBs, GHU+REPL pattern
- ims_order_management.cbl: orders, GNP, DLET, dynamic SSA via MOVE
"""

from pathlib import Path

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


def _make_data_item(
    name: str, level: int = 5, value: str | None = None
) -> CobolDataItem:
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

    def test_primary_segment_is_last_ssa(self):
        # Issue #398: the last SSA is the target, the earlier ones are parents.
        call = self._make_call(["EMPLOYEE", "DEPT"])
        assert call.primary_segment == "DEPT"

    def test_primary_segment_unresolved_target_is_none(self):
        # An unresolved target is unknown; a resolved parent is not it.
        call = self._make_call(["EMPLOYEE", None])
        assert call.primary_segment is None

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
        # The last SSA names the target; HOSPITAL only qualifies the path.
        assert call.primary_segment == "PATIENT"

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


# ── Edge-case unit tests ──────────────────────────────────────────────────────


class TestEdgeCasesUnit:
    """Focused unit tests for tricky/boundary behaviors."""

    def _single_call_program(
        self,
        interface: str,
        params: list[str],
        data_items: list[CobolDataItem],
        move_stmts: list[tuple[str, str]] | None = None,
    ) -> CobolProgram:
        """Build a minimal program with one CALL and optional MOVEs."""
        loc = _make_loc()
        program = CobolProgram("TEST", loc)

        data_div = CobolDivision("DATA", loc)
        for item in data_items:
            data_div.add_child(item)
        program.add_division(data_div)

        proc_div = CobolDivision("PROCEDURE", loc)
        para = CobolParagraph("MAIN", loc)

        for src, tgt in move_stmts or []:
            mv = MoveStatement(loc)
            mv.set_source(src)
            mv.add_target(tgt)
            para.add_statement(mv)

        call = CallStatement(loc)
        call.set_called_program(f"'{interface}'")
        for p in params:
            call.add_using_parameter(p)
        para.add_statement(call)

        proc_div.add_paragraph(para)
        program.add_division(proc_div)
        return program

    # ── Qualified SSA ──────────────────────────────────────────────────────

    def test_qualified_ssa_segment_name_not_field_name(self):
        """
        A qualified SSA has: seg-name(8) + '(' + field-name(8) + op + key + ')'.
        The segment name is the FIRST child's VALUE ('EMPLOYEE'), not the
        field-name child ('EMP-ID  ').
        """
        root = _make_data_item("SSA-EMP-QUAL", level=1)
        root.add_child(_make_data_item("SSA-SEG", level=5, value="EMPLOYEE"))
        root.add_child(_make_data_item("SSA-OPEN", level=5, value="("))
        root.add_child(_make_data_item("SSA-FIELD", level=5, value="EMP-ID  "))
        root.add_child(_make_data_item("SSA-OPER", level=5, value="= "))
        root.add_child(_make_data_item("SSA-KEY", level=5))  # no VALUE
        root.add_child(_make_data_item("SSA-CLOSE", level=5, value=")"))

        program = self._single_call_program(
            "CBLTDLI", ["F", "P", "I", "SSA-EMP-QUAL"], [root]
        )
        results = IMSSegmentAnalyzer().analyze(program)
        assert results[0].primary_segment == "EMPLOYEE"

    # ── Zero-SSA calls (CHKP, REPL, DLET) ────────────────────────────────

    def test_chkp_zero_ssa(self):
        """CHKP call: func + PCB + io-area, no SSAs -> segment_names = []."""
        func = _make_data_item("DLI-CHKP", level=1, value="CHKP")
        program = self._single_call_program(
            "CBLTDLI", ["DLI-CHKP", "DB-PCB", "CHKP-AREA"], [func]
        )
        results = IMSSegmentAnalyzer().analyze(program)
        assert len(results) == 1
        assert results[0].function_code == "CHKP"
        assert results[0].ssa_names == []
        assert results[0].segment_names == []
        assert results[0].primary_segment is None

    def test_repl_zero_ssa(self):
        """REPL after GHU: only func + PCB + io-area, no SSAs."""
        func = _make_data_item("DLI-REPL", level=1, value="REPL")
        program = self._single_call_program(
            "CBLTDLI", ["DLI-REPL", "DB-PCB", "IO-AREA"], [func]
        )
        results = IMSSegmentAnalyzer().analyze(program)
        assert results[0].function_code == "REPL"
        assert results[0].segment_names == []

    def test_dlet_zero_ssa(self):
        """DLET after GHU: no SSAs, but function code resolves."""
        func = _make_data_item("DLI-DLET", level=1, value="DLET")
        program = self._single_call_program(
            "CBLTDLI", ["DLI-DLET", "DB-PCB", "IO-AREA"], [func]
        )
        results = IMSSegmentAnalyzer().analyze(program)
        assert results[0].function_code == "DLET"
        assert results[0].segment_names == []

    # ── Hold-variant function codes ───────────────────────────────────────

    def test_ghu_function_code(self):
        """GHU (Get Hold Unique) resolves correctly."""
        func = _make_data_item("DLI-GHU", level=1, value="GHU ")
        ssa = _make_data_item("SSA-ACCT", level=1)
        ssa.add_child(_make_data_item("N", level=5, value="ACCOUNT "))
        program = self._single_call_program(
            "CBLTDLI", ["DLI-GHU", "P", "I", "SSA-ACCT"], [func, ssa]
        )
        results = IMSSegmentAnalyzer().analyze(program)
        assert results[0].function_code == "GHU"
        assert results[0].primary_segment == "ACCOUNT"

    def test_ghn_function_code(self):
        """GHN (Get Hold Next) resolves correctly."""
        func = _make_data_item("DLI-GHN", level=1, value="GHN ")
        ssa = _make_data_item("SSA-X", level=1)
        ssa.add_child(_make_data_item("N", level=5, value="PATIENT "))
        program = self._single_call_program(
            "CBLTDLI", ["DLI-GHN", "P", "I", "SSA-X"], [func, ssa]
        )
        results = IMSSegmentAnalyzer().analyze(program)
        assert results[0].function_code == "GHN"

    def test_ghnp_function_code(self):
        """GHNP (Get Hold Next in Parent) resolves correctly."""
        func = _make_data_item("DLI-GHNP", level=1, value="GHNP")
        ssa = _make_data_item("SSA-X", level=1)
        ssa.add_child(_make_data_item("N", level=5, value="SHIPMENT"))
        program = self._single_call_program(
            "CBLTDLI", ["DLI-GHNP", "P", "I", "SSA-X"], [func, ssa]
        )
        results = IMSSegmentAnalyzer().analyze(program)
        assert results[0].function_code == "GHNP"

    def test_gnp_function_code(self):
        """GNP (Get Next in Parent) resolves correctly."""
        func = _make_data_item("DLI-GNP", level=1, value="GNP ")
        ssa = _make_data_item("SSA-X", level=1)
        ssa.add_child(_make_data_item("N", level=5, value="LINEITEM"))
        program = self._single_call_program(
            "CBLTDLI", ["DLI-GNP", "P", "I", "SSA-X"], [func, ssa]
        )
        results = IMSSegmentAnalyzer().analyze(program)
        assert results[0].function_code == "GNP"
        assert results[0].primary_segment == "LINEITEM"

    # ── Func code as level-05 sub-item of a group ─────────────────────────

    def test_func_code_as_group_sub_item(self):
        """
        Function code defined inside a group item (level 01 parent, level 05
        sub-item with VALUE) is still resolved via recursive data collection.
        """
        group = _make_data_item("DLI-CODES", level=1)
        group.add_child(_make_data_item("DLI-GU", level=5, value="GU  "))
        group.add_child(_make_data_item("DLI-ISRT", level=5, value="ISRT"))

        ssa = _make_data_item("SSA-X", level=1)
        ssa.add_child(_make_data_item("N", level=5, value="CUSTOMER"))

        program = self._single_call_program(
            "CBLTDLI", ["DLI-GU", "P", "I", "SSA-X"], [group, ssa]
        )
        results = IMSSegmentAnalyzer().analyze(program)
        assert results[0].function_code == "GU"
        assert results[0].primary_segment == "CUSTOMER"

    # ── Inline literal func code – CALL parser strips quotes ─────────────

    def test_func_code_inline_literal_quotes_stripped(self):
        """
        When COBOL source is ``CALL 'CBLTDLI' USING 'GU  ' ...`` the CALL
        parser delivers the parameter *without* surrounding quotes (the quotes
        are removed during parsing, before the analyzer sees it).  Case 2 of
        ``_resolve_func_code`` must therefore recognise ``"GU  "`` directly
        as a known IMS verb rather than treating it as an unresolved variable.
        """
        ssa = _make_data_item("SSA-X", level=1)
        ssa.add_child(_make_data_item("N", level=5, value="EMPLOYEE"))

        # Pass "GU  " (no quotes) as the func-code parameter to simulate the
        # CALL parser having already stripped the surrounding quote characters.
        program = self._single_call_program(
            "CBLTDLI", ["GU  ", "P", "I", "SSA-X"], [ssa]
        )
        results = IMSSegmentAnalyzer().analyze(program)
        assert results[0].function_code == "GU"
        assert results[0].primary_segment == "EMPLOYEE"

    def test_func_code_inline_literal_with_trailing_spaces(self):
        """All four-char IMS verb literals (e.g. ``'ISRT'``, ``'GNP '``) are
        correctly resolved after quote-stripping, regardless of trailing spaces.
        """
        ssa = _make_data_item("SSA-Y", level=1)
        ssa.add_child(_make_data_item("N", level=5, value="CUSTOMER"))

        for raw, expected in [("ISRT", "ISRT"), ("GNP ", "GNP"), ("DLET", "DLET")]:
            program = self._single_call_program(
                "CBLTDLI", [raw, "P", "I", "SSA-Y"], [ssa]
            )
            results = IMSSegmentAnalyzer().analyze(program)
            assert results[0].function_code == expected, f"failed for {raw!r}"

    # ── No USING parameters ───────────────────────────────────────────────

    def test_call_with_no_using_params(self):
        """
        A DLI CALL with no USING clause (degenerate but shouldn't crash).
        func_code_var, pcb_name, io_area_name and ssa_names are all None/empty.
        """
        program = self._single_call_program("CBLTDLI", [], [])
        results = IMSSegmentAnalyzer().analyze(program)
        assert len(results) == 1
        assert results[0].function_code is None
        assert results[0].pcb_name is None
        assert results[0].io_area_name is None
        assert results[0].ssa_names == []
        assert results[0].segment_names == []

    def test_call_with_only_func_param(self):
        """CALL with only the function-code param (no PCB, no IO, no SSA)."""
        func = _make_data_item("DLI-TERM", level=1, value="TERM")
        program = self._single_call_program("CBLTDLI", ["DLI-TERM"], [func])
        results = IMSSegmentAnalyzer().analyze(program)
        assert results[0].function_code == "TERM"
        assert results[0].pcb_name is None
        assert results[0].segment_names == []

    # ── Group SSA: first child has no VALUE ───────────────────────────────

    def test_group_ssa_first_child_no_value_returns_none(self):
        """
        If the first CobolDataItem child of the SSA group has no VALUE clause,
        the segment name cannot be determined statically -> None.
        """
        root = _make_data_item("SSA-NODYN", level=1)
        # First child intentionally has NO value_clause (runtime-set)
        child_novalue = _make_data_item("SSA-SEG", level=5)
        root.add_child(child_novalue)
        root.add_child(_make_data_item("FILLER", level=5, value=" "))

        program = self._single_call_program(
            "CBLTDLI", ["F", "P", "I", "SSA-NODYN"], [root]
        )
        results = IMSSegmentAnalyzer().analyze(program)
        assert results[0].primary_segment is None

    # ── Elementary SSA: VALUE longer than 8 chars ─────────────────────────

    def test_elementary_ssa_value_truncated_to_8(self):
        """
        An elementary SSA with VALUE longer than 8 chars: only the first 8
        bytes (i.e. the segment name field) are returned.
        'TOOLONGNAME' -> 'TOOLONGN'
        """
        item = _make_data_item("SSA-LONG", level=1, value="TOOLONGNAME")
        program = self._single_call_program(
            "CBLTDLI", ["F", "P", "I", "SSA-LONG"], [item]
        )
        results = IMSSegmentAnalyzer().analyze(program)
        assert results[0].primary_segment == "TOOLONGN"

    def test_elementary_ssa_value_shorter_than_8(self):
        """VALUE shorter than 8 chars (no trailing spaces): returned as-is."""
        item = _make_data_item("SSA-SHORT", level=1, value="DEPT")
        program = self._single_call_program(
            "CBLTDLI", ["F", "P", "I", "SSA-SHORT"], [item]
        )
        results = IMSSegmentAnalyzer().analyze(program)
        assert results[0].primary_segment == "DEPT"

    # ── MOVE chain (two hops) ─────────────────────────────────────────────

    def test_move_chain_two_hops(self):
        """
        A (VALUE 'ACCOUNT ') -> MOVE A TO B -> MOVE B TO SSA-DYN
        The analyzer resolves SSA-DYN = 'ACCOUNT' via the two-hop chain.
        """
        item_a = _make_data_item("VAR-A", level=1, value="ACCOUNT ")
        item_b = _make_data_item("VAR-B", level=1)
        ssa = _make_data_item("SSA-DYN", level=1)

        program = self._single_call_program(
            "CBLTDLI",
            ["F", "P", "I", "SSA-DYN"],
            [item_a, item_b, ssa],
            move_stmts=[("VAR-A", "VAR-B"), ("VAR-B", "SSA-DYN")],
        )
        results = IMSSegmentAnalyzer().analyze(program)
        assert results[0].primary_segment == "ACCOUNT"

    # ── Function code with two possible values ────────────────────────────

    def test_func_code_two_possible_values(self):
        """
        When two MOVE statements assign different values to the func-code
        variable, both are returned joined by '/' in sorted order.
        """
        func_item = _make_data_item("DLI-FUNC", level=1)  # no VALUE

        loc = _make_loc()
        program = CobolProgram("PROG", loc)

        data_div = CobolDivision("DATA", loc)
        data_div.add_child(func_item)
        program.add_division(data_div)

        proc_div = CobolDivision("PROCEDURE", loc)
        para = CobolParagraph("MAIN", loc)

        for lit in ("'GU  '", "'GN  '"):
            mv = MoveStatement(loc)
            mv.set_source(lit)
            mv.add_target("DLI-FUNC")
            para.add_statement(mv)

        call = CallStatement(loc)
        call.set_called_program("'CBLTDLI'")
        call.add_using_parameter("DLI-FUNC")
        para.add_statement(call)

        proc_div.add_paragraph(para)
        program.add_division(proc_div)

        results = IMSSegmentAnalyzer().analyze(program)
        # Both 'GN' and 'GU' are known codes; sorted -> 'GN/GU'
        assert results[0].function_code == "GN/GU"

    # ── Three-level hierarchy path call ──────────────────────────────────

    def test_three_ssa_path_call(self):
        """Path call through three hierarchy levels (root -> mid -> leaf)."""
        ssa_root = _make_data_item("SSA-A", level=1)
        ssa_root.add_child(_make_data_item("N1", level=5, value="DIVISION"))
        ssa_mid = _make_data_item("SSA-B", level=1)
        ssa_mid.add_child(_make_data_item("N2", level=5, value="DEPARTMT"))
        ssa_leaf = _make_data_item("SSA-C", level=1)
        ssa_leaf.add_child(_make_data_item("N3", level=5, value="EMPLOYEE"))

        program = self._single_call_program(
            "CBLTDLI",
            ["F", "P", "I", "SSA-A", "SSA-B", "SSA-C"],
            [ssa_root, ssa_mid, ssa_leaf],
        )
        results = IMSSegmentAnalyzer().analyze(program)
        assert results[0].segment_names == ["DIVISION", "DEPARTMT", "EMPLOYEE"]
        assert results[0].ssa_names == ["SSA-A", "SSA-B", "SSA-C"]

    # ── Analyzer reset between calls ──────────────────────────────────────

    def test_analyze_resets_state_between_runs(self):
        """Calling analyze() twice resets internal state (no data bleeding)."""
        prog1 = self._single_call_program(
            "CBLTDLI",
            ["F", "P", "I", "SSA-EMP"],
            [_make_data_item("SSA-EMP", level=1, value="EMPLOYEE")],
        )
        prog2 = self._single_call_program(
            "CBLTDLI",
            ["F", "P", "I", "SSA-ORD"],
            [_make_data_item("SSA-ORD", level=1, value="ORDER   ")],
        )
        analyzer = IMSSegmentAnalyzer()
        r1 = analyzer.analyze(prog1)
        r2 = analyzer.analyze(prog2)

        # Second run must not inherit EMPLOYEE from the first
        assert r1[0].primary_segment == "EMPLOYEE"
        assert r2[0].primary_segment == "ORDER"


# ── Real-world sample file tests ──────────────────────────────────────────────


@pytest.mark.integration
class TestRealWorldPatientRecords:
    """
    Tests against tests/samples/ims_patient_records.cbl.

    IMS hierarchy: HOSPITAL -> WARD -> PATIENT -> DIAGNOSI
    Interface: CBLTDLI
    Operations: GU, GN (×2), ISRT, GHU, REPL, CHKP
    """

    @pytest.fixture(scope="class")
    def results(self, samples_dir):
        src = (samples_dir / "ims_patient_records.cbl").read_text()
        ast = parse_cobol(src).ast
        assert ast is not None
        analyzer = IMSSegmentAnalyzer()
        calls = analyzer.analyze(ast)
        return analyzer, calls

    @pytest.fixture(scope="class")
    def samples_dir(self):
        from pathlib import Path

        return Path(__file__).parent.parent / "samples"

    def test_call_count(self, results):
        _, calls = results
        # GU, GN, GN (loop), ISRT, GHU, REPL, CHKP
        assert len(calls) == 7

    def test_all_calls_use_cbltdli(self, results):
        _, calls = results
        assert all(c.interface == "CBLTDLI" for c in calls)

    def test_gu_path_call_resolves_hospital_and_patient(self, results):
        _, calls = results
        gu = next(c for c in calls if c.function_code == "GU")
        assert "HOSPITAL" in gu.segment_names
        assert "PATIENT" in gu.segment_names
        assert gu.primary_segment == "PATIENT"

    def test_gn_path_call_resolves_ward_and_diagnosi(self, results):
        _, calls = results
        gn_calls = [c for c in calls if c.function_code == "GN"]
        assert len(gn_calls) == 2  # loop body executes call twice
        for gn in gn_calls:
            assert "WARD" in gn.segment_names
            assert "DIAGNOSI" in gn.segment_names

    def test_isrt_uses_path_ssas(self, results):
        _, calls = results
        isrt = next(c for c in calls if c.function_code == "ISRT")
        assert "HOSPITAL" in isrt.segment_names
        assert "PATIENT" in isrt.segment_names

    def test_ghu_path_call(self, results):
        _, calls = results
        ghu = next(c for c in calls if c.function_code == "GHU")
        assert ghu.segment_names == ["HOSPITAL", "PATIENT"]

    def test_repl_has_zero_ssas(self, results):
        """REPL replaces the currently-held segment - no SSA needed."""
        _, calls = results
        repl = next(c for c in calls if c.function_code == "REPL")
        assert repl.ssa_names == []
        assert repl.segment_names == []
        assert repl.primary_segment is None

    def test_chkp_has_zero_ssas(self, results):
        """Checkpoint call accesses no segment."""
        _, calls = results
        chkp = next(c for c in calls if c.function_code == "CHKP")
        assert chkp.ssa_names == []
        assert chkp.segment_names == []

    def test_all_segment_names(self, results):
        analyzer, calls = results
        assert analyzer.get_all_segment_names(calls) == [
            "DIAGNOSI",
            "HOSPITAL",
            "PATIENT",
            "WARD",
        ]

    def test_function_codes_present(self, results):
        _, calls = results
        found = {c.function_code for c in calls}
        assert {"GU", "GN", "ISRT", "GHU", "REPL", "CHKP"} <= found

    def test_pcb_name_populated(self, results):
        _, calls = results
        # All calls in this program use PATIENT-PCB
        assert all(c.pcb_name == "PATIENT-PCB" for c in calls)


@pytest.mark.integration
class TestRealWorldBankingAccounts:
    """
    Tests against tests/samples/ims_banking_accounts.cbl.

    IMS hierarchy: CUSTOMER -> ACCOUNT -> TRANSACT  (CUST-PCB / BANKDB)
                   AUDITENT                          (AUDIT-PCB / AUDITDB)
    Interface: CBLTDLI
    Operations: GHU, REPL (in an ELSE branch), ISRT (×2, two different PCBs), CHKP

    REPL sits right after an un-punctuated ``SUBTRACT ... FROM ACCT-BALANCE``
    (DEBIT-ACCOUNT paragraph, ELSE branch): before the SubtractStatementParser
    fix, its trailing ``skip_to_period()`` call blindly consumed every token
    up to the next period, silently swallowing the CALL, the nested IF, and
    both END-IF terminators. REPL is correctly present in the ELSE branch now
    that the parser stops at the next statement boundary instead.
    """

    @pytest.fixture(scope="class")
    def results(self, samples_dir):
        src = (samples_dir / "ims_banking_accounts.cbl").read_text()
        ast = parse_cobol(src).ast
        assert ast is not None
        analyzer = IMSSegmentAnalyzer()
        calls = analyzer.analyze(ast)
        return analyzer, calls

    @pytest.fixture(scope="class")
    def samples_dir(self):
        from pathlib import Path

        return Path(__file__).parent.parent / "samples"

    def test_call_count(self, results):
        _, calls = results
        # GHU, REPL, ISRT (CUST-PCB), ISRT (AUDIT-PCB), CHKP
        assert len(calls) == 5

    def test_repl_detected_in_else_branch(self, results):
        """REPL must not vanish when it follows an un-punctuated SUBTRACT."""
        _, calls = results
        repl_calls = [c for c in calls if c.function_code == "REPL"]
        assert repl_calls, "REPL call was silently dropped from the ELSE branch"
        assert repl_calls[0].pcb_name == "CUST-PCB"

    def test_ghu_resolves_customer_and_account(self, results):
        _, calls = results
        ghu = next(c for c in calls if c.function_code == "GHU")
        assert ghu.segment_names == ["CUSTOMER", "ACCOUNT"]

    def test_isrt_three_ssas_for_transact(self, results):
        """ISRT into CUST-PCB uses 3 SSAs: CUSTOMER + ACCOUNT + TRANSACT."""
        _, calls = results
        isrt_calls = [c for c in calls if c.function_code == "ISRT"]
        three_ssa = next(c for c in isrt_calls if len(c.ssa_names) == 3)
        assert three_ssa.segment_names == ["CUSTOMER", "ACCOUNT", "TRANSACT"]

    def test_isrt_one_ssa_for_audit_entry(self, results):
        """ISRT into AUDIT-PCB uses one SSA: AUDITENT."""
        _, calls = results
        isrt_calls = [c for c in calls if c.function_code == "ISRT"]
        one_ssa = next(c for c in isrt_calls if len(c.ssa_names) == 1)
        assert one_ssa.primary_segment == "AUDITENT"

    def test_chkp_zero_ssas(self, results):
        _, calls = results
        chkp = next(c for c in calls if c.function_code == "CHKP")
        assert chkp.segment_names == []

    def test_two_databases_both_represented(self, results):
        """Segments from both BANKDB and AUDITDB appear in the combined output."""
        analyzer, calls = results
        all_segs = analyzer.get_all_segment_names(calls)
        # Main database segments
        assert "CUSTOMER" in all_segs
        assert "ACCOUNT" in all_segs
        assert "TRANSACT" in all_segs
        # Audit database segment
        assert "AUDITENT" in all_segs

    def test_all_segment_names(self, results):
        analyzer, calls = results
        assert analyzer.get_all_segment_names(calls) == [
            "ACCOUNT",
            "AUDITENT",
            "CUSTOMER",
            "TRANSACT",
        ]


@pytest.mark.integration
class TestRealWorldOrderManagement:
    """
    Tests against tests/samples/ims_order_management.cbl.

    IMS hierarchy: ORDER -> LINEITEM -> SHIPMENT
    Interface: CBLTDLI
    Operations: GU, GN (×2 in loop), GNP (×2 in loop), GHU, DLET, ISRT (dynamic SSA)
    """

    @pytest.fixture(scope="class")
    def results(self, samples_dir):
        src = (samples_dir / "ims_order_management.cbl").read_text()
        ast = parse_cobol(src).ast
        assert ast is not None
        analyzer = IMSSegmentAnalyzer()
        calls = analyzer.analyze(ast)
        return analyzer, calls

    @pytest.fixture(scope="class")
    def samples_dir(self):
        from pathlib import Path

        return Path(__file__).parent.parent / "samples"

    def test_call_count(self, results):
        _, calls = results
        # GU, GN, GN, GNP, GNP, GHU, DLET, ISRT(dynamic)
        assert len(calls) == 8

    def test_gu_resolves_order(self, results):
        _, calls = results
        gu = next(c for c in calls if c.function_code == "GU")
        assert gu.primary_segment == "ORDER"
        assert len(gu.ssa_names) == 1

    def test_gn_resolves_lineitem(self, results):
        """Both GN calls (initial + loop) resolve to LINEITEM."""
        _, calls = results
        gn_calls = [c for c in calls if c.function_code == "GN"]
        assert len(gn_calls) == 2
        for gn in gn_calls:
            assert gn.primary_segment == "LINEITEM"

    def test_gnp_resolves_shipment(self, results):
        """GNP (get-next-in-parent) targets SHIPMENT under LINEITEM."""
        _, calls = results
        gnp_calls = [c for c in calls if c.function_code == "GNP"]
        assert len(gnp_calls) == 2
        for gnp in gnp_calls:
            assert gnp.primary_segment == "SHIPMENT"

    def test_ghu_resolves_lineitem(self, results):
        _, calls = results
        ghu = next(c for c in calls if c.function_code == "GHU")
        assert ghu.primary_segment == "LINEITEM"

    def test_dlet_zero_ssas(self, results):
        """DLET after GHU position hold: no SSA parameters."""
        _, calls = results
        dlet = next(c for c in calls if c.function_code == "DLET")
        assert dlet.ssa_names == []
        assert dlet.segment_names == []

    def test_dynamic_ssa_resolved_via_move(self, results):
        """
        SSA-DYNAMIC has no VALUE clause; its segment name is set via:
            MOVE WS-SEGMENT-NAME TO SSA-DYNAMIC
        where WS-SEGMENT-NAME has VALUE 'LINEITEM'.
        The analyzer resolves it to 'LINEITEM' through MOVE tracking.
        """
        _, calls = results
        # The ISRT call in INSERT-SHIPMENT-DYNAMIC uses SSA-DYNAMIC
        isrt = next(c for c in calls if c.function_code == "ISRT")
        assert "SSA-DYNAMIC" in isrt.ssa_names
        assert isrt.primary_segment == "LINEITEM"

    def test_all_segment_names(self, results):
        analyzer, calls = results
        assert analyzer.get_all_segment_names(calls) == [
            "LINEITEM",
            "ORDER",
            "SHIPMENT",
        ]

    def test_order_is_qualified_ssa(self, results):
        """
        SSA-ORDER is a qualified SSA (has '(' condition); the segment name
        must still be extracted correctly from the first child VALUE.
        """
        _, calls = results
        gu = next(c for c in calls if c.function_code == "GU")
        # Segment name = 'ORDER   '[:8].rstrip() = 'ORDER'
        assert gu.primary_segment == "ORDER"


class TestParmcountOperand:
    """``CALL 'CBLTDLI' USING parmcount, function, pcb, ...`` -- the optional
    leading count used to be read as the function code, shifting the PCB,
    I/O area and every SSA one position."""

    _SRC = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. T1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 PARM-CT PIC S9(9) COMP VALUE +4.
       01 GU-FUNC PIC X(4) VALUE 'GU  '.
       01 IO-AREA PIC X(100).
       01 SSA1 PIC X(9) VALUE 'CUSTOMER '.
       LINKAGE SECTION.
       01 DB-PCB PIC X(40).
       PROCEDURE DIVISION.
           CALL '{iface}' USING PARM-CT GU-FUNC DB-PCB IO-AREA SSA1.
           GOBACK.
"""

    @pytest.mark.parametrize("iface", ["CBLTDLI", "AIBTDLI"])
    def test_leading_count_is_skipped(self, iface):
        result = parse_cobol(self._SRC.format(iface=iface))
        (call,) = IMSSegmentAnalyzer().analyze(result.ast)
        assert call.function_code == "GU"
        assert call.function_code_var == "GU-FUNC"
        assert call.pcb_name == "DB-PCB"
        assert call.io_area_name == "IO-AREA"
        assert call.ssa_names == ["SSA1"]
        assert call.segment_names == ["CUSTOMER"]

    def test_ceetdli_takes_no_count(self):
        # CEETDLI has no parmcount operand: the positions are left alone.
        result = parse_cobol(self._SRC.format(iface="CEETDLI"))
        (call,) = IMSSegmentAnalyzer().analyze(result.ast)
        assert call.function_code_var == "PARM-CT"


# ── Issue #398: primary_segment is the target (last) segment ─────────────────

_COBOL_ISRT_PATH = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IMSISRT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  FUNC-ISRT           PIC X(4) VALUE 'ISRT'.
       01  DBPCB               PIC S9(9) COMP.
       01  ITEM-IO             PIC X(40).
       01  ORD-SSA             PIC X(9) VALUE 'ORDSEG   '.
       01  ITEM-SSA            PIC X(9) VALUE 'ITEMSEG  '.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           CALL 'CBLTDLI' USING FUNC-ISRT DBPCB ITEM-IO ORD-SSA ITEM-SSA.
           STOP RUN.
"""

_EXECDLI_SAMPLE = (
    Path(__file__).resolve().parents[1] / "samples" / "enterprise" / "EXECDLI.cbl"
)


class TestPrimarySegmentIsTarget:
    def test_call_isrt_under_parent_targets_child(self):
        results = IMSSegmentAnalyzer().analyze(_parse(_COBOL_ISRT_PATH))
        assert results[0].segment_names == ["ORDSEG", "ITEMSEG"]
        assert results[0].primary_segment == "ITEMSEG"

    def test_exec_dli_isrt_targets_last_segment_option(self):
        ast = _parse(_EXECDLI_SAMPLE.read_text())
        isrt = [
            c
            for c in IMSSegmentAnalyzer().analyze(ast)
            if c.function_code == "ISRT" and len(c.segment_names) == 2
        ]
        assert isrt, "EXECDLI.cbl's two-segment ISRT not found"
        assert isrt[0].segment_names == ["CUSTSEG", "NOTESEG"]
        assert isrt[0].primary_segment == "NOTESEG"
