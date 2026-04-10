"""Unit tests for CoverageAnalyzer.

Tests the coverage analyzer that walks a parsed COBOL AST and
produces a CoverageMap with paragraph info, branch points,
variable reads/writes, and data item info.
"""

from cobolparser.analysis.coverage_analyzer import (
    BranchType,
    CoverageAnalyzer,
    CoverageMap,
    DataItemInfo,
    ParagraphCoverage,
)
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.data_items import CobolDataItem, PictureClause
from cobolparser.models.program import (
    CobolDivision,
    CobolParagraph,
    CobolProgram,
    CobolSection,
)
from cobolparser.models.statements.arithmetic import AddStatement, ComputeStatement
from cobolparser.models.statements.call import CallStatement
from cobolparser.models.statements.control import (
    EvaluateStatement,
    IfStatement,
    PerformStatement,
    SearchStatement,
    StopStatement,
    WhenClause,
)
from cobolparser.models.statements.data import (
    DisplayStatement,
    MoveStatement,
    StringStatement,
    UnstringStatement,
)
from cobolparser.models.statements.io import (
    IODeleteStatement,
    IOReadStatement,
    IOWriteStatement,
)
from cobolparser.models.statements.misc import GobackStatement

LOC = SourceLocation(1, 1)


def _make_program(name: str = "TESTPROG") -> CobolProgram:
    """Build a minimal CobolProgram with IDENTIFICATION division."""
    prog = CobolProgram(name, LOC)
    id_div = CobolDivision("IDENTIFICATION", LOC)
    id_div.program_id = name
    prog.add_division(id_div)
    return prog


def _add_procedure(prog: CobolProgram) -> CobolDivision:
    """Add and return a PROCEDURE division."""
    proc = CobolDivision("PROCEDURE", LOC)
    prog.add_division(proc)
    return proc


def _add_data_division_with_items(
    prog: CobolProgram, items: list[CobolDataItem]
) -> None:
    """Add a DATA division with WORKING-STORAGE items."""
    data_div = CobolDivision("DATA", LOC)
    ws_section = CobolSection("WORKING-STORAGE", LOC)
    for item in items:
        ws_section.add_data_item(item)
    data_div.add_section(ws_section)
    prog.add_division(data_div)


def _make_data_item(
    name: str, level: int = 1, pic_pattern: str | None = None
) -> CobolDataItem:
    """Build a CobolDataItem with optional PIC clause."""
    item = CobolDataItem(name, level, LOC)
    if pic_pattern is not None:
        item.picture_clause = PictureClause(pic_pattern, LOC)
    return item


class TestCoverageAnalyzerEmpty:
    """Tests for programs with no PROCEDURE division or empty paragraphs."""

    def test_empty_program_no_procedure_division(self):
        prog = _make_program()
        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        assert cmap.program_name == "TESTPROG"
        assert cmap.has_procedure_division is False
        assert cmap.total_paragraphs == 0
        assert cmap.total_branch_points == 0
        assert cmap.paragraphs == []

    def test_empty_procedure_division(self):
        prog = _make_program()
        _add_procedure(prog)
        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        assert cmap.has_procedure_division is True
        assert cmap.total_paragraphs == 0

    def test_empty_paragraph(self):
        prog = _make_program()
        proc = _add_procedure(prog)
        para = CobolParagraph("EMPTY-PARA", LOC)
        proc.add_paragraph(para)
        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        assert len(cmap.paragraphs) == 1
        assert cmap.paragraphs[0].paragraph_name == "EMPTY-PARA"
        assert cmap.paragraphs[0].is_empty is True
        assert cmap.paragraphs[0].statement_count == 0

    def test_program_name_fallback_no_id_div(self):
        prog = CobolProgram("FALLBACK", LOC)
        # No IDENTIFICATION division -> falls back to program.program_name
        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        assert cmap.program_name == "FALLBACK"

    def test_program_name_from_id_division(self):
        prog = _make_program("MYPROG")
        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        assert cmap.program_name == "MYPROG"


class TestCoverageAnalyzerIF:
    """Tests for IF statement branch detection."""

    def test_if_produces_true_and_false_branches(self):
        prog = _make_program()
        proc = _add_procedure(prog)
        para = CobolParagraph("CHECK-PARA", LOC)

        if_stmt = IfStatement(LOC)
        then_display = DisplayStatement(LOC)
        then_display.add_display_item("TRUE-PATH")
        if_stmt.add_then_statement(then_display)
        para.add_statement(if_stmt)
        proc.add_paragraph(para)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)

        bp_types = [bp.branch_type for bp in cmap.paragraphs[0].branch_points]
        assert BranchType.IF_TRUE in bp_types
        assert BranchType.IF_FALSE in bp_types
        assert len(bp_types) == 2

    def test_if_with_else_still_two_branches(self):
        prog = _make_program()
        proc = _add_procedure(prog)
        para = CobolParagraph("IF-ELSE-PARA", LOC)

        if_stmt = IfStatement(LOC)
        if_stmt.add_then_statement(DisplayStatement(LOC))
        if_stmt.add_else_statement(DisplayStatement(LOC))
        para.add_statement(if_stmt)
        proc.add_paragraph(para)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        bp_types = [bp.branch_type for bp in cmap.paragraphs[0].branch_points]
        assert bp_types.count(BranchType.IF_TRUE) == 1
        assert bp_types.count(BranchType.IF_FALSE) == 1

    def test_nested_if_produces_four_branches(self):
        prog = _make_program()
        proc = _add_procedure(prog)
        para = CobolParagraph("NESTED-IF", LOC)

        outer_if = IfStatement(LOC)
        inner_if = IfStatement(LOC)
        inner_if.add_then_statement(DisplayStatement(LOC))
        outer_if.add_then_statement(inner_if)
        para.add_statement(outer_if)
        proc.add_paragraph(para)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        bps = cmap.paragraphs[0].branch_points
        # outer IF_TRUE + IF_FALSE, inner IF_TRUE + IF_FALSE
        assert len(bps) == 4


class TestCoverageAnalyzerEvaluate:
    """Tests for EVALUATE statement branch detection."""

    def test_evaluate_when_clauses(self):
        prog = _make_program()
        proc = _add_procedure(prog)
        para = CobolParagraph("EVAL-PARA", LOC)

        eval_stmt = EvaluateStatement(LOC)
        wc1 = WhenClause([{"type": "Literal", "value": "1"}], LOC)
        wc1.add_statement(DisplayStatement(LOC))
        eval_stmt.add_when_clause(wc1)

        wc2 = WhenClause([{"type": "Literal", "value": "2"}], LOC)
        wc2.add_statement(DisplayStatement(LOC))
        eval_stmt.add_when_clause(wc2)

        para.add_statement(eval_stmt)
        proc.add_paragraph(para)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        bp_types = [bp.branch_type for bp in cmap.paragraphs[0].branch_points]
        assert bp_types.count(BranchType.EVALUATE_WHEN) == 2
        assert BranchType.EVALUATE_DEFAULT not in bp_types

    def test_evaluate_with_default_when(self):
        prog = _make_program()
        proc = _add_procedure(prog)
        para = CobolParagraph("EVAL-DEFAULT", LOC)

        eval_stmt = EvaluateStatement(LOC)
        wc = WhenClause([{"type": "Literal", "value": "1"}], LOC)
        eval_stmt.add_when_clause(wc)

        default_wc = WhenClause([{"type": "Any"}], LOC)
        default_wc.add_statement(DisplayStatement(LOC))
        eval_stmt.set_default_when(default_wc)

        para.add_statement(eval_stmt)
        proc.add_paragraph(para)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        bp_types = [bp.branch_type for bp in cmap.paragraphs[0].branch_points]
        assert BranchType.EVALUATE_WHEN in bp_types
        assert BranchType.EVALUATE_DEFAULT in bp_types


class TestCoverageAnalyzerSearch:
    """Tests for SEARCH statement branch detection."""

    def test_search_when_and_at_end(self):
        prog = _make_program()
        proc = _add_procedure(prog)
        para = CobolParagraph("SEARCH-PARA", LOC)

        search = SearchStatement(LOC)
        search.when_clauses = [
            {"condition": "WS-X = 1", "statements": []},
            {"condition": "WS-X = 2", "statements": []},
        ]
        search.at_end_clause = [DisplayStatement(LOC)]
        para.add_statement(search)
        proc.add_paragraph(para)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        bp_types = [bp.branch_type for bp in cmap.paragraphs[0].branch_points]
        assert bp_types.count(BranchType.SEARCH_WHEN) == 2
        assert BranchType.SEARCH_AT_END in bp_types

    def test_search_without_at_end(self):
        prog = _make_program()
        proc = _add_procedure(prog)
        para = CobolParagraph("SEARCH-NO-END", LOC)

        search = SearchStatement(LOC)
        search.when_clauses = [{"condition": "WS-X = 1", "statements": []}]
        search.at_end_clause = None
        para.add_statement(search)
        proc.add_paragraph(para)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        bp_types = [bp.branch_type for bp in cmap.paragraphs[0].branch_points]
        assert BranchType.SEARCH_WHEN in bp_types
        assert BranchType.SEARCH_AT_END not in bp_types


class TestCoverageAnalyzerIO:
    """Tests for IO statement branch detection."""

    def test_read_at_end_and_invalid_key(self):
        prog = _make_program()
        proc = _add_procedure(prog)
        para = CobolParagraph("READ-PARA", LOC)

        read_stmt = IOReadStatement(LOC)
        read_stmt.at_end_clause = [DisplayStatement(LOC)]
        read_stmt.not_at_end_clause = [DisplayStatement(LOC)]
        read_stmt.invalid_key_clause = [DisplayStatement(LOC)]
        read_stmt.not_invalid_key_clause = [DisplayStatement(LOC)]
        para.add_statement(read_stmt)
        proc.add_paragraph(para)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        bp_types = {bp.branch_type for bp in cmap.paragraphs[0].branch_points}
        assert BranchType.IO_AT_END in bp_types
        assert BranchType.IO_NOT_AT_END in bp_types
        assert BranchType.IO_INVALID_KEY in bp_types
        assert BranchType.IO_NOT_INVALID_KEY in bp_types

    def test_write_at_eop_and_invalid_key(self):
        prog = _make_program()
        proc = _add_procedure(prog)
        para = CobolParagraph("WRITE-PARA", LOC)

        write_stmt = IOWriteStatement(LOC)
        write_stmt.at_eop_clause = [DisplayStatement(LOC)]
        write_stmt.invalid_key_clause = [DisplayStatement(LOC)]
        write_stmt.not_invalid_key_clause = [DisplayStatement(LOC)]
        para.add_statement(write_stmt)
        proc.add_paragraph(para)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        bp_types = {bp.branch_type for bp in cmap.paragraphs[0].branch_points}
        assert BranchType.IO_AT_EOP in bp_types
        assert BranchType.IO_INVALID_KEY in bp_types
        assert BranchType.IO_NOT_INVALID_KEY in bp_types

    def test_delete_invalid_key(self):
        prog = _make_program()
        proc = _add_procedure(prog)
        para = CobolParagraph("DELETE-PARA", LOC)

        delete_stmt = IODeleteStatement(LOC)
        delete_stmt.invalid_key_clause = [DisplayStatement(LOC)]
        para.add_statement(delete_stmt)
        proc.add_paragraph(para)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        bp_types = [bp.branch_type for bp in cmap.paragraphs[0].branch_points]
        assert BranchType.IO_INVALID_KEY in bp_types

    def test_read_no_clauses_no_branches(self):
        prog = _make_program()
        proc = _add_procedure(prog)
        para = CobolParagraph("READ-SIMPLE", LOC)

        read_stmt = IOReadStatement(LOC)
        para.add_statement(read_stmt)
        proc.add_paragraph(para)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        assert len(cmap.paragraphs[0].branch_points) == 0


class TestCoverageAnalyzerArithmetic:
    """Tests for arithmetic SIZE ERROR branch detection."""

    def test_add_with_size_error(self):
        prog = _make_program()
        proc = _add_procedure(prog)
        para = CobolParagraph("ADD-PARA", LOC)

        add_stmt = AddStatement(LOC)
        add_stmt.on_size_error = [DisplayStatement(LOC)]
        add_stmt.not_on_size_error = [DisplayStatement(LOC)]
        para.add_statement(add_stmt)
        proc.add_paragraph(para)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        bp_types = {bp.branch_type for bp in cmap.paragraphs[0].branch_points}
        assert BranchType.ARITH_SIZE_ERROR in bp_types
        assert BranchType.ARITH_NOT_SIZE_ERROR in bp_types

    def test_compute_with_size_error(self):
        prog = _make_program()
        proc = _add_procedure(prog)
        para = CobolParagraph("COMPUTE-PARA", LOC)

        compute = ComputeStatement(LOC)
        compute.on_size_error = [DisplayStatement(LOC)]
        para.add_statement(compute)
        proc.add_paragraph(para)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        bp_types = [bp.branch_type for bp in cmap.paragraphs[0].branch_points]
        assert BranchType.ARITH_SIZE_ERROR in bp_types

    def test_arithmetic_no_size_error_no_branches(self):
        prog = _make_program()
        proc = _add_procedure(prog)
        para = CobolParagraph("SIMPLE-ADD", LOC)

        add_stmt = AddStatement(LOC)
        para.add_statement(add_stmt)
        proc.add_paragraph(para)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        assert len(cmap.paragraphs[0].branch_points) == 0


class TestCoverageAnalyzerCall:
    """Tests for CALL ON EXCEPTION branch detection."""

    def test_call_exception_branches(self):
        prog = _make_program()
        proc = _add_procedure(prog)
        para = CobolParagraph("CALL-PARA", LOC)

        call = CallStatement(LOC)
        call.on_exception = [DisplayStatement(LOC)]
        call.not_on_exception = [DisplayStatement(LOC)]
        para.add_statement(call)
        proc.add_paragraph(para)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        bp_types = {bp.branch_type for bp in cmap.paragraphs[0].branch_points}
        assert BranchType.CALL_ON_EXCEPTION in bp_types
        assert BranchType.CALL_NOT_ON_EXCEPTION in bp_types

    def test_call_no_exception_no_branches(self):
        prog = _make_program()
        proc = _add_procedure(prog)
        para = CobolParagraph("CALL-SIMPLE", LOC)

        call = CallStatement(LOC)
        para.add_statement(call)
        proc.add_paragraph(para)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        assert len(cmap.paragraphs[0].branch_points) == 0


class TestCoverageAnalyzerStringOverflow:
    """Tests for STRING/UNSTRING ON OVERFLOW."""

    def test_string_overflow_branches(self):
        prog = _make_program()
        proc = _add_procedure(prog)
        para = CobolParagraph("STRING-PARA", LOC)

        string_stmt = StringStatement(LOC)
        string_stmt.on_overflow = [DisplayStatement(LOC)]
        string_stmt.not_on_overflow = [DisplayStatement(LOC)]
        para.add_statement(string_stmt)
        proc.add_paragraph(para)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        bp_types = {bp.branch_type for bp in cmap.paragraphs[0].branch_points}
        assert BranchType.STRING_ON_OVERFLOW in bp_types
        assert BranchType.STRING_NOT_ON_OVERFLOW in bp_types

    def test_unstring_overflow_branches(self):
        prog = _make_program()
        proc = _add_procedure(prog)
        para = CobolParagraph("UNSTRING-PARA", LOC)

        unstring_stmt = UnstringStatement(LOC)
        unstring_stmt.on_overflow = [DisplayStatement(LOC)]
        para.add_statement(unstring_stmt)
        proc.add_paragraph(para)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        bp_types = [bp.branch_type for bp in cmap.paragraphs[0].branch_points]
        assert BranchType.STRING_ON_OVERFLOW in bp_types


class TestCoverageAnalyzerPerform:
    """Tests for PERFORM inline body branch detection."""

    def test_perform_inline_body(self):
        prog = _make_program()
        proc = _add_procedure(prog)
        para = CobolParagraph("PERFORM-PARA", LOC)

        perform = PerformStatement(LOC)
        perform.add_inline_statement(DisplayStatement(LOC))
        para.add_statement(perform)
        proc.add_paragraph(para)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        bp_types = [bp.branch_type for bp in cmap.paragraphs[0].branch_points]
        assert BranchType.PERFORM_BODY in bp_types

    def test_perform_target_tracked(self):
        prog = _make_program()
        proc = _add_procedure(prog)
        para = CobolParagraph("CALLER-PARA", LOC)

        perform = PerformStatement(LOC)
        perform.target_paragraph = "TARGET-PARA"
        para.add_statement(perform)
        proc.add_paragraph(para)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        assert "TARGET-PARA" in cmap.paragraphs[0].calls_paragraphs

    def test_perform_no_inline_no_branch(self):
        prog = _make_program()
        proc = _add_procedure(prog)
        para = CobolParagraph("PERFORM-SIMPLE", LOC)

        perform = PerformStatement(LOC)
        perform.target_paragraph = "OTHER"
        para.add_statement(perform)
        proc.add_paragraph(para)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        assert len(cmap.paragraphs[0].branch_points) == 0


class TestCoverageAnalyzerStopGoback:
    """Tests for STOP RUN and GOBACK detection."""

    def test_stop_run_detected(self):
        prog = _make_program()
        proc = _add_procedure(prog)
        para = CobolParagraph("STOP-PARA", LOC)
        para.add_statement(StopStatement(LOC))
        proc.add_paragraph(para)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        assert cmap.paragraphs[0].has_stop_run is True
        assert cmap.paragraphs[0].has_goback is False

    def test_goback_detected(self):
        prog = _make_program()
        proc = _add_procedure(prog)
        para = CobolParagraph("GOBACK-PARA", LOC)
        para.add_statement(GobackStatement(LOC))
        proc.add_paragraph(para)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        assert cmap.paragraphs[0].has_goback is True
        assert cmap.paragraphs[0].has_stop_run is False


class TestCoverageAnalyzerVariableTracking:
    """Tests for variable read/write tracking."""

    def test_move_source_read_target_written(self):
        prog = _make_program()
        proc = _add_procedure(prog)
        para = CobolParagraph("MOVE-PARA", LOC)

        move = MoveStatement(LOC)
        move.source = "WS-SOURCE"
        move.targets = ["WS-TARGET-1", "WS-TARGET-2"]
        para.add_statement(move)
        proc.add_paragraph(para)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        pc = cmap.paragraphs[0]
        assert "WS-SOURCE" in pc.reads_variables
        assert "WS-TARGET-1" in pc.writes_variables
        assert "WS-TARGET-2" in pc.writes_variables

    def test_display_items_read(self):
        prog = _make_program()
        proc = _add_procedure(prog)
        para = CobolParagraph("DISPLAY-PARA", LOC)

        display = DisplayStatement(LOC)
        display.display_items = ["WS-VAR-1", "WS-VAR-2"]
        para.add_statement(display)
        proc.add_paragraph(para)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        pc = cmap.paragraphs[0]
        assert "WS-VAR-1" in pc.reads_variables
        assert "WS-VAR-2" in pc.reads_variables

    def test_arithmetic_operands_read_target_written(self):
        prog = _make_program()
        proc = _add_procedure(prog)
        para = CobolParagraph("ADD-VARS", LOC)

        add_stmt = AddStatement(LOC)
        add_stmt.operands = ["WS-A", "WS-B"]
        add_stmt.target = "WS-RESULT"
        add_stmt.giving = "WS-GIVING"
        para.add_statement(add_stmt)
        proc.add_paragraph(para)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        pc = cmap.paragraphs[0]
        assert "WS-A" in pc.reads_variables
        assert "WS-B" in pc.reads_variables
        assert "WS-RESULT" in pc.writes_variables
        assert "WS-GIVING" in pc.writes_variables

    def test_call_parameters_read(self):
        prog = _make_program()
        proc = _add_procedure(prog)
        para = CobolParagraph("CALL-VARS", LOC)

        call = CallStatement(LOC)
        call.add_using_parameter("WS-PARAM1")
        call.add_using_parameter("WS-PARAM2")
        para.add_statement(call)
        proc.add_paragraph(para)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        pc = cmap.paragraphs[0]
        assert "WS-PARAM1" in pc.reads_variables
        assert "WS-PARAM2" in pc.reads_variables

    def test_read_into_target_written(self):
        prog = _make_program()
        proc = _add_procedure(prog)
        para = CobolParagraph("READ-INTO", LOC)

        read_stmt = IOReadStatement(LOC)
        read_stmt.into_target = "WS-RECORD"
        para.add_statement(read_stmt)
        proc.add_paragraph(para)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        assert "WS-RECORD" in cmap.paragraphs[0].writes_variables

    def test_perform_varying_variable_written(self):
        prog = _make_program()
        proc = _add_procedure(prog)
        para = CobolParagraph("VARY-PARA", LOC)

        perform = PerformStatement(LOC)
        perform.varying_clause = {"variable": "WS-IDX"}
        para.add_statement(perform)
        proc.add_paragraph(para)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        assert "WS-IDX" in cmap.paragraphs[0].writes_variables


class TestCoverageAnalyzerDataItems:
    """Tests for data item extraction from DATA division."""

    def test_extract_numeric_data_item(self):
        prog = _make_program()
        item = _make_data_item("WS-AMOUNT", 1, "9(5)V99")
        _add_data_division_with_items(prog, [item])
        _add_procedure(prog)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        assert len(cmap.data_items) == 1
        di = cmap.data_items[0]
        assert di.name == "WS-AMOUNT"
        assert di.is_numeric is True
        assert di.integer_digits == 5
        assert di.decimal_digits == 2

    def test_extract_alphanumeric_data_item(self):
        prog = _make_program()
        item = _make_data_item("WS-NAME", 1, "X(30)")
        _add_data_division_with_items(prog, [item])
        _add_procedure(prog)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        assert len(cmap.data_items) == 1
        di = cmap.data_items[0]
        assert di.name == "WS-NAME"
        assert di.is_numeric is False

    def test_filler_excluded(self):
        prog = _make_program()
        filler = CobolDataItem("FILLER", 1, LOC)
        filler.is_filler = True
        regular = _make_data_item("WS-FIELD", 1, "X(10)")
        _add_data_division_with_items(prog, [filler, regular])
        _add_procedure(prog)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        assert len(cmap.data_items) == 1
        assert cmap.data_items[0].name == "WS-FIELD"

    def test_no_data_division(self):
        prog = _make_program()
        _add_procedure(prog)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        assert cmap.data_items == []

    def test_signed_numeric_detected(self):
        prog = _make_program()
        item = _make_data_item("WS-SIGNED", 1, "S9(5)V99")
        _add_data_division_with_items(prog, [item])
        _add_procedure(prog)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        di = cmap.data_items[0]
        assert di.is_signed is True
        assert di.is_numeric is True

    def test_data_item_initial_value(self):
        prog = _make_program()
        item = _make_data_item("WS-COUNT", 1, "9(3)")
        item.value_clause = 0
        _add_data_division_with_items(prog, [item])
        _add_procedure(prog)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        assert cmap.data_items[0].initial_value == "0"


class TestCoverageAnalyzerSections:
    """Tests for paragraphs within sections."""

    def test_paragraphs_within_section(self):
        prog = _make_program()
        proc = _add_procedure(prog)

        section = CobolSection("MAIN-SECTION", LOC)
        para1 = CobolParagraph("PARA-1", LOC)
        para1.add_statement(DisplayStatement(LOC))
        para2 = CobolParagraph("PARA-2", LOC)
        para2.add_statement(DisplayStatement(LOC))
        section.add_paragraph(para1)
        section.add_paragraph(para2)
        proc.add_section(section)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        assert cmap.total_paragraphs == 2
        assert cmap.paragraphs[0].section_name == "MAIN-SECTION"
        assert cmap.paragraphs[1].section_name == "MAIN-SECTION"

    def test_mixed_standalone_and_section_paragraphs(self):
        prog = _make_program()
        proc = _add_procedure(prog)

        standalone = CobolParagraph("STANDALONE", LOC)
        standalone.add_statement(DisplayStatement(LOC))
        proc.add_paragraph(standalone)

        section = CobolSection("MY-SECTION", LOC)
        in_section = CobolParagraph("IN-SECTION", LOC)
        in_section.add_statement(DisplayStatement(LOC))
        section.add_paragraph(in_section)
        proc.add_section(section)

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(prog)
        assert cmap.total_paragraphs == 2
        names = [p.paragraph_name for p in cmap.paragraphs]
        assert "STANDALONE" in names
        assert "IN-SECTION" in names


class TestCoverageMapLookup:
    """Tests for CoverageMap helper methods."""

    def test_get_paragraph_found(self):
        cmap = CoverageMap(program_name="TEST")
        cmap.paragraphs = [
            ParagraphCoverage(paragraph_name="PARA-A"),
            ParagraphCoverage(paragraph_name="PARA-B"),
        ]
        result = cmap.get_paragraph("PARA-A")
        assert result is not None
        assert result.paragraph_name == "PARA-A"

    def test_get_paragraph_case_insensitive(self):
        cmap = CoverageMap(program_name="TEST")
        cmap.paragraphs = [ParagraphCoverage(paragraph_name="MY-PARA")]
        assert cmap.get_paragraph("my-para") is not None

    def test_get_paragraph_not_found(self):
        cmap = CoverageMap(program_name="TEST")
        cmap.paragraphs = [ParagraphCoverage(paragraph_name="PARA-A")]
        assert cmap.get_paragraph("NONEXISTENT") is None

    def test_get_data_item_found(self):
        cmap = CoverageMap(program_name="TEST")
        cmap.data_items = [DataItemInfo(name="WS-FIELD", level=1)]
        result = cmap.get_data_item("WS-FIELD")
        assert result is not None
        assert result.name == "WS-FIELD"

    def test_get_data_item_case_insensitive(self):
        cmap = CoverageMap(program_name="TEST")
        cmap.data_items = [DataItemInfo(name="WS-FIELD", level=1)]
        assert cmap.get_data_item("ws-field") is not None

    def test_get_data_item_not_found(self):
        cmap = CoverageMap(program_name="TEST")
        assert cmap.get_data_item("MISSING") is None
