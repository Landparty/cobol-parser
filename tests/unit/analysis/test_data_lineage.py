"""Unit tests for data lineage / taint tracking analysis."""


from cobolparser.analysis.data_lineage import (
    DataLineageAnalyzer,
    LineageEdge,
    SinkKind,
    SourceKind,
    TaintSource,
)
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.data_items import CobolDataItem
from cobolparser.models.program import (
    CobolDivision,
    CobolParagraph,
    CobolProgram,
    CobolSection,
)
from cobolparser.models.statements.arithmetic import (
    AddStatement,
    ComputeStatement,
    DivideStatement,
    MultiplyStatement,
    SubtractStatement,
)
from cobolparser.models.statements.call import CallStatement
from cobolparser.models.statements.control import (
    EvaluateStatement,
    IfStatement,
    PerformStatement,
    WhenClause,
)
from cobolparser.models.statements.data import (
    DisplayStatement,
    MoveStatement,
    StringStatement,
    UnstringStatement,
)
from cobolparser.models.statements.io import (
    IOAcceptStatement,
    IOOpenStatement,
    IOReadStatement,
    IOWriteStatement,
)
from cobolparser.models.statements.misc import ContinueStatement

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

LOC = SourceLocation(1, 8)


def _make_program(
    paragraphs: list[tuple[str, list]],
    linkage_items: list[CobolDataItem] | None = None,
) -> CobolProgram:
    """Build a minimal CobolProgram with optional LINKAGE SECTION."""
    loc = SourceLocation(1, 1)
    prog = CobolProgram("TESTPROG", loc)

    id_div = CobolDivision("IDENTIFICATION", loc)
    prog.add_division(id_div)

    if linkage_items:
        data_div = CobolDivision("DATA", loc)
        linkage_sec = CobolSection("LINKAGE", loc)
        for item in linkage_items:
            linkage_sec.add_data_item(item)
            linkage_sec.add_child(item)
        data_div.add_section(linkage_sec)
        prog.add_division(data_div)

    proc_div = CobolDivision("PROCEDURE", loc)
    line = 10
    for pname, stmts in paragraphs:
        para = CobolParagraph(pname, SourceLocation(line, 8))
        for s in stmts:
            para.add_statement(s)
        proc_div.add_paragraph(para)
        line += 2
    prog.add_division(proc_div)

    return prog


def _move(src: str, *targets: str) -> MoveStatement:
    stmt = MoveStatement(LOC)
    stmt.set_source(src)
    for t in targets:
        stmt.add_target(t)
    return stmt


def _open_input(file_name: str) -> IOOpenStatement:
    stmt = IOOpenStatement(LOC)
    stmt.set_open_mode("INPUT")
    stmt.add_file(file_name)
    return stmt


def _read(file_name: str, record: str, into: str | None = None) -> IOReadStatement:
    stmt = IOReadStatement(LOC)
    stmt.set_file_name(file_name)
    stmt.set_record_name(record)
    if into:
        stmt.set_into(into)
    return stmt


def _write(record: str, from_var: str | None = None) -> IOWriteStatement:
    stmt = IOWriteStatement(LOC)
    stmt.set_record_name(record)
    if from_var:
        stmt.from_clause = from_var
    return stmt


def _add(operands: list[str], giving: str | None = None) -> AddStatement:
    stmt = AddStatement(LOC)
    for op in operands:
        stmt.add_operand(op)
    if giving:
        stmt.set_giving(giving)
    else:
        stmt.set_target(operands[-1])
    return stmt


def _compute(targets: list[str], expression: str) -> ComputeStatement:
    stmt = ComputeStatement(LOC)
    for t in targets:
        stmt.add_target(t)
    stmt.set_expression(expression)
    return stmt


def _string_stmt(operands: list[str], into: str) -> StringStatement:
    stmt = StringStatement(LOC)
    for op in operands:
        stmt.add_operand(op)
    stmt.set_into_target(into)
    return stmt


def _unstring_stmt(src: str, targets: list[str]) -> UnstringStatement:
    stmt = UnstringStatement(LOC)
    stmt.set_source(src)
    for t in targets:
        stmt.add_into_target(t, None, None)
    return stmt


def _call_by_ref(program: str, params: list[str]) -> CallStatement:
    stmt = CallStatement(LOC)
    stmt.set_called_program(program, is_dynamic=False)
    for p in params:
        stmt.add_using_parameter(p, "REFERENCE")
    return stmt


def _linkage_item(name: str, level: int = 1) -> CobolDataItem:
    item = CobolDataItem(name, level, LOC)
    return item


def _accept_from(target: str, from_src: str | None = None) -> IOAcceptStatement:
    stmt = IOAcceptStatement(LOC)
    stmt.set_target(target)
    if from_src:
        stmt.set_from(from_src)
    return stmt


# ---------------------------------------------------------------------------
# Tests: source identification
# ---------------------------------------------------------------------------


class TestLinkageSourceIdentification:
    def test_linkage_items_are_sources(self):
        item = _linkage_item("WS-INPUT")
        prog = _make_program([("MAIN", [ContinueStatement(LOC)])], linkage_items=[item])
        report = DataLineageAnalyzer().analyze(prog)

        names = {s.variable_name for s in report.sources}
        assert "WS-INPUT" in names

    def test_linkage_source_kind_is_linkage(self):
        item = _linkage_item("WS-PARAM")
        prog = _make_program([("MAIN", [ContinueStatement(LOC)])], linkage_items=[item])
        report = DataLineageAnalyzer().analyze(prog)

        kinds = {s.kind for s in report.sources}
        assert SourceKind.LINKAGE in kinds

    def test_dfhcommarea_gets_cics_commarea_kind(self):
        item = _linkage_item("DFHCOMMAREA")
        prog = _make_program([("MAIN", [ContinueStatement(LOC)])], linkage_items=[item])
        report = DataLineageAnalyzer().analyze(prog)

        cics_sources = [s for s in report.sources if s.kind == SourceKind.CICS_COMMAREA]
        assert len(cics_sources) == 1
        assert cics_sources[0].variable_name == "DFHCOMMAREA"

    def test_multiple_linkage_items_all_registered(self):
        items = [_linkage_item("WS-A"), _linkage_item("WS-B"), _linkage_item("WS-C")]
        prog = _make_program([("MAIN", [ContinueStatement(LOC)])], linkage_items=items)
        report = DataLineageAnalyzer().analyze(prog)

        names = {s.variable_name for s in report.sources}
        assert {"WS-A", "WS-B", "WS-C"}.issubset(names)


class TestFileSourceIdentification:
    def test_file_open_input_creates_source(self):
        open_stmt = _open_input("INFILE")
        prog = _make_program([("MAIN", [open_stmt])])
        report = DataLineageAnalyzer().analyze(prog)

        names = {s.variable_name for s in report.sources}
        assert "INFILE" in names

    def test_file_source_kind_is_file(self):
        open_stmt = _open_input("CUSTOMER-FILE")
        prog = _make_program([("MAIN", [open_stmt])])
        report = DataLineageAnalyzer().analyze(prog)

        kinds = {s.kind for s in report.sources}
        assert SourceKind.FILE in kinds

    def test_read_seeds_record_taint(self):
        open_stmt = _open_input("INFILE")
        read_stmt = _read("INFILE", "WS-RECORD")
        prog = _make_program([("MAIN", [open_stmt, read_stmt])])
        report = DataLineageAnalyzer().analyze(prog)

        assert "WS-RECORD" in report.variable_taints
        assert any("FILE:INFILE" in t for t in report.variable_taints["WS-RECORD"])

    def test_read_into_seeds_target_taint(self):
        open_stmt = _open_input("INFILE")
        read_stmt = _read("INFILE", "WS-RECORD", into="WS-WORK")
        prog = _make_program([("MAIN", [open_stmt, read_stmt])])
        report = DataLineageAnalyzer().analyze(prog)

        assert "WS-WORK" in report.variable_taints


class TestAcceptSourceIdentification:
    def test_accept_without_from_creates_source(self):
        stmt = _accept_from("WS-INPUT")
        prog = _make_program([("MAIN", [stmt])])
        report = DataLineageAnalyzer().analyze(prog)

        names = {s.variable_name for s in report.sources}
        assert "WS-INPUT" in names

    def test_accept_from_date_is_not_a_source(self):
        stmt = _accept_from("WS-TODAY", "DATE")
        prog = _make_program([("MAIN", [stmt])])
        report = DataLineageAnalyzer().analyze(prog)

        names = {s.variable_name for s in report.sources}
        assert "WS-TODAY" not in names

    def test_accept_from_time_is_not_a_source(self):
        stmt = _accept_from("WS-NOW", "TIME")
        prog = _make_program([("MAIN", [stmt])])
        report = DataLineageAnalyzer().analyze(prog)

        names = {s.variable_name for s in report.sources}
        assert "WS-NOW" not in names


# ---------------------------------------------------------------------------
# Tests: taint propagation
# ---------------------------------------------------------------------------


class TestMovePropagation:
    def test_move_propagates_linkage_taint(self):
        item = _linkage_item("WS-SRC")
        move = _move("WS-SRC", "WS-DEST")
        prog = _make_program([("MAIN", [move])], linkage_items=[item])
        report = DataLineageAnalyzer().analyze(prog)

        assert "WS-DEST" in report.variable_taints
        assert "LINKAGE:WS-SRC" in report.variable_taints["WS-DEST"]

    def test_move_to_multiple_targets_propagates_all(self):
        item = _linkage_item("WS-SRC")
        move = _move("WS-SRC", "WS-A", "WS-B", "WS-C")
        prog = _make_program([("MAIN", [move])], linkage_items=[item])
        report = DataLineageAnalyzer().analyze(prog)

        for target in ("WS-A", "WS-B", "WS-C"):
            assert "LINKAGE:WS-SRC" in report.variable_taints.get(target, [])

    def test_move_chained_propagation(self):
        item = _linkage_item("WS-SRC")
        move1 = _move("WS-SRC", "WS-TEMP")
        move2 = _move("WS-TEMP", "WS-FINAL")
        prog = _make_program([("MAIN", [move1, move2])], linkage_items=[item])
        report = DataLineageAnalyzer().analyze(prog)

        assert "WS-FINAL" in report.variable_taints
        assert "LINKAGE:WS-SRC" in report.variable_taints["WS-FINAL"]

    def test_move_untainted_src_produces_no_edge(self):
        move = _move("WS-INTERNAL", "WS-DEST")
        prog = _make_program([("MAIN", [move])])
        report = DataLineageAnalyzer().analyze(prog)

        # No taint on WS-DEST because WS-INTERNAL is not a source
        assert "WS-DEST" not in report.variable_taints

    def test_move_records_edge(self):
        item = _linkage_item("WS-SRC")
        move = _move("WS-SRC", "WS-DEST")
        prog = _make_program([("MAIN", [move])], linkage_items=[item])
        report = DataLineageAnalyzer().analyze(prog)

        move_edges = [e for e in report.edges if e.operation == "MOVE"]
        assert len(move_edges) >= 1
        dest_edges = [e for e in move_edges if e.target_variable == "WS-DEST"]
        assert dest_edges
        assert "LINKAGE:WS-SRC" in dest_edges[0].source_ids


class TestArithmeticPropagation:
    def test_add_propagates_operand_taints_to_giving(self):
        item = _linkage_item("WS-A")
        add = _add(["WS-A", "WS-B"], giving="WS-RESULT")
        prog = _make_program([("MAIN", [add])], linkage_items=[item])
        report = DataLineageAnalyzer().analyze(prog)

        assert "LINKAGE:WS-A" in report.variable_taints.get("WS-RESULT", [])

    def test_compute_propagates_expression_variable_taints(self):
        item = _linkage_item("WS-X")
        compute = _compute(["WS-OUTPUT"], "WS-X + 100")
        prog = _make_program([("MAIN", [compute])], linkage_items=[item])
        report = DataLineageAnalyzer().analyze(prog)

        assert "LINKAGE:WS-X" in report.variable_taints.get("WS-OUTPUT", [])


class TestStringUnstringPropagation:
    def test_string_merges_operand_taints_into_target(self):
        item_a = _linkage_item("WS-FIRST")
        item_b = _linkage_item("WS-LAST")
        string_stmt = _string_stmt(["WS-FIRST", "WS-LAST"], "WS-FULL-NAME")
        prog = _make_program(
            [("MAIN", [string_stmt])], linkage_items=[item_a, item_b]
        )
        report = DataLineageAnalyzer().analyze(prog)

        taints = report.variable_taints.get("WS-FULL-NAME", [])
        assert "LINKAGE:WS-FIRST" in taints
        assert "LINKAGE:WS-LAST" in taints

    def test_unstring_propagates_source_taint_to_each_into_target(self):
        item = _linkage_item("WS-SRC")
        unstring = _unstring_stmt("WS-SRC", ["WS-PART1", "WS-PART2"])
        prog = _make_program([("MAIN", [unstring])], linkage_items=[item])
        report = DataLineageAnalyzer().analyze(prog)

        for target in ("WS-PART1", "WS-PART2"):
            taints = report.variable_taints.get(target, [])
            assert "LINKAGE:WS-SRC" in taints


class TestCallByReference:
    def test_call_by_ref_creates_call_output_sink(self):
        call = _call_by_ref("SUBROUTINE", ["WS-PARAM"])
        prog = _make_program([("MAIN", [call])])
        report = DataLineageAnalyzer().analyze(prog)

        sink_ids = {s.sink_id for s in report.sinks}
        assert "CALL_OUTPUT:WS-PARAM" in sink_ids

    def test_call_by_ref_adds_external_taint_to_variable(self):
        call = _call_by_ref("SUBROUTINE", ["WS-RESULT"])
        prog = _make_program([("MAIN", [call])])
        report = DataLineageAnalyzer().analyze(prog)

        taints = report.variable_taints.get("WS-RESULT", [])
        assert any("CALL_REF:SUBROUTINE:WS-RESULT" in t for t in taints)

    def test_call_by_value_does_not_create_sink(self):
        stmt = CallStatement(LOC)
        stmt.set_called_program("SUBROUTINE", is_dynamic=False)
        stmt.add_using_parameter("WS-PARAM", "VALUE")
        prog = _make_program([("MAIN", [stmt])])
        report = DataLineageAnalyzer().analyze(prog)

        sink_ids = {s.sink_id for s in report.sinks}
        assert "CALL_OUTPUT:WS-PARAM" not in sink_ids


# ---------------------------------------------------------------------------
# Tests: sink identification
# ---------------------------------------------------------------------------


class TestSinkIdentification:
    def test_write_from_tainted_var_creates_file_write_sink(self):
        item = _linkage_item("WS-DATA")
        move = _move("WS-DATA", "WS-OUT-REC")
        write = _write("WS-OUT-REC", from_var="WS-OUT-REC")
        prog = _make_program([("MAIN", [move, write])], linkage_items=[item])
        report = DataLineageAnalyzer().analyze(prog)

        sink_ids = {s.sink_id for s in report.sinks}
        assert "FILE_WRITE:WS-OUT-REC" in sink_ids

    def test_write_creates_sink_taints_entry(self):
        item = _linkage_item("WS-DATA")
        move = _move("WS-DATA", "WS-OUT-REC")
        write = _write("WS-OUT-REC", from_var="WS-OUT-REC")
        prog = _make_program([("MAIN", [move, write])], linkage_items=[item])
        report = DataLineageAnalyzer().analyze(prog)

        sink_taints = report.sink_taints.get("FILE_WRITE:WS-OUT-REC", [])
        assert "LINKAGE:WS-DATA" in sink_taints

    def test_display_of_tainted_var_creates_display_sink(self):
        item = _linkage_item("WS-MSG")
        disp_stmt = DisplayStatement(LOC)
        disp_stmt.add_display_item("WS-MSG")
        prog = _make_program([("MAIN", [disp_stmt])], linkage_items=[item])
        report = DataLineageAnalyzer().analyze(prog)

        sink_ids = {s.sink_id for s in report.sinks}
        assert "DISPLAY:WS-MSG" in sink_ids

    def test_display_of_untainted_var_creates_no_display_sink(self):
        disp_stmt = DisplayStatement(LOC)
        disp_stmt.add_display_item("WS-INTERNAL")
        prog = _make_program([("MAIN", [disp_stmt])])
        report = DataLineageAnalyzer().analyze(prog)

        sink_ids = {s.sink_id for s in report.sinks}
        assert "DISPLAY:WS-INTERNAL" not in sink_ids


# ---------------------------------------------------------------------------
# Tests: nested statement handling
# ---------------------------------------------------------------------------


class TestNestedStatements:
    def test_move_inside_if_branch_propagates_taint(self):
        item = _linkage_item("WS-SRC")
        move = _move("WS-SRC", "WS-DEST")
        if_stmt = IfStatement(LOC)
        from cobolparser.models.statements.base import CobolExpression

        if_stmt.set_condition(CobolExpression("COMPARISON", LOC))
        if_stmt.add_then_statement(move)
        prog = _make_program([("MAIN", [if_stmt])], linkage_items=[item])
        report = DataLineageAnalyzer().analyze(prog)

        assert "LINKAGE:WS-SRC" in report.variable_taints.get("WS-DEST", [])

    def test_move_inside_evaluate_when_propagates_taint(self):
        item = _linkage_item("WS-SRC")
        move = _move("WS-SRC", "WS-DEST")
        wc = WhenClause([{"type": "Literal", "value": "1"}], LOC)
        wc.add_statement(move)
        eval_stmt = EvaluateStatement(LOC)
        eval_stmt.add_subject("WS-SRC")
        eval_stmt.add_when_clause(wc)
        prog = _make_program([("MAIN", [eval_stmt])], linkage_items=[item])
        report = DataLineageAnalyzer().analyze(prog)

        assert "LINKAGE:WS-SRC" in report.variable_taints.get("WS-DEST", [])

    def test_move_inside_inline_perform_propagates_taint(self):
        item = _linkage_item("WS-SRC")
        move = _move("WS-SRC", "WS-DEST")
        perform = PerformStatement(LOC)
        perform.add_inline_statement(move)
        prog = _make_program([("MAIN", [perform])], linkage_items=[item])
        report = DataLineageAnalyzer().analyze(prog)

        assert "LINKAGE:WS-SRC" in report.variable_taints.get("WS-DEST", [])


# ---------------------------------------------------------------------------
# Tests: serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_to_dict_contains_expected_keys(self):
        item = _linkage_item("WS-IN")
        move = _move("WS-IN", "WS-OUT")
        prog = _make_program([("MAIN", [move])], linkage_items=[item])
        report = DataLineageAnalyzer().analyze(prog)

        d = report.to_dict()
        assert "program_name" in d
        assert "sources" in d
        assert "sinks" in d
        assert "edges" in d
        assert "variable_taints" in d
        assert "sink_taints" in d
        assert "summary" in d

    def test_to_json_is_valid_json(self):
        import json

        item = _linkage_item("WS-IN")
        move = _move("WS-IN", "WS-OUT")
        prog = _make_program([("MAIN", [move])], linkage_items=[item])
        report = DataLineageAnalyzer().analyze(prog)

        raw = report.to_json()
        parsed = json.loads(raw)
        assert parsed["program_name"] == "TESTPROG"

    def test_taint_source_to_dict(self):
        src = TaintSource("LINKAGE:FOO", SourceKind.LINKAGE, "FOO")
        d = src.to_dict()
        assert d["source_id"] == "LINKAGE:FOO"
        assert d["kind"] == "LINKAGE"

    def test_lineage_edge_to_dict(self):
        edge = LineageEdge(["LINKAGE:FOO"], "BAR", "MOVE")
        d = edge.to_dict()
        assert d["target_variable"] == "BAR"
        assert d["operation"] == "MOVE"

    def test_empty_program_produces_empty_report(self):
        prog = _make_program([("MAIN", [ContinueStatement(LOC)])])
        report = DataLineageAnalyzer().analyze(prog)

        assert report.sources == []
        assert report.sinks == []
        assert report.edges == []
        assert report.variable_taints == {}


# ---------------------------------------------------------------------------
# Tests: MOVE CORRESPONDING
# ---------------------------------------------------------------------------


class TestMoveCorresponding:
    def test_move_corresponding_produces_corresponding_edge(self):
        item = _linkage_item("WS-SRC")
        move = _move("WS-SRC", "WS-DEST")
        move.set_corresponding(True)
        prog = _make_program([("MAIN", [move])], linkage_items=[item])
        report = DataLineageAnalyzer().analyze(prog)

        corr_edges = [e for e in report.edges if e.operation == "MOVE_CORRESPONDING"]
        assert len(corr_edges) >= 1
        assert corr_edges[0].target_variable == "WS-DEST"

    def test_regular_move_produces_move_edge_not_corresponding(self):
        item = _linkage_item("WS-SRC")
        move = _move("WS-SRC", "WS-DEST")
        # is_corresponding is False by default
        prog = _make_program([("MAIN", [move])], linkage_items=[item])
        report = DataLineageAnalyzer().analyze(prog)

        move_edges = [e for e in report.edges if e.operation == "MOVE"]
        corr_edges = [e for e in report.edges if e.operation == "MOVE_CORRESPONDING"]
        assert len(move_edges) >= 1
        assert len(corr_edges) == 0


# ---------------------------------------------------------------------------
# Tests: SUBTRACT / MULTIPLY / DIVIDE propagation
# ---------------------------------------------------------------------------


class TestSubtractMultiplyDivide:
    def test_subtract_propagates_taint_to_giving(self):
        item = _linkage_item("WS-A")
        stmt = SubtractStatement(LOC)
        stmt.add_operand("WS-A")
        stmt.set_giving("WS-RESULT")
        prog = _make_program([("MAIN", [stmt])], linkage_items=[item])
        report = DataLineageAnalyzer().analyze(prog)

        assert "LINKAGE:WS-A" in report.variable_taints.get("WS-RESULT", [])

    def test_multiply_propagates_taint_to_giving(self):
        item = _linkage_item("WS-A")
        stmt = MultiplyStatement(LOC)
        stmt.add_operand("WS-A")
        stmt.set_giving("WS-RESULT")
        prog = _make_program([("MAIN", [stmt])], linkage_items=[item])
        report = DataLineageAnalyzer().analyze(prog)

        assert "LINKAGE:WS-A" in report.variable_taints.get("WS-RESULT", [])

    def test_divide_propagates_taint_to_giving(self):
        item = _linkage_item("WS-A")
        stmt = DivideStatement(LOC)
        stmt.add_operand("WS-A")
        stmt.set_giving("WS-RESULT")
        prog = _make_program([("MAIN", [stmt])], linkage_items=[item])
        report = DataLineageAnalyzer().analyze(prog)

        assert "LINKAGE:WS-A" in report.variable_taints.get("WS-RESULT", [])

    def test_arithmetic_uses_statement_type_as_operation(self):
        item = _linkage_item("WS-A")
        stmt = SubtractStatement(LOC)
        stmt.add_operand("WS-A")
        stmt.set_giving("WS-RESULT")
        prog = _make_program([("MAIN", [stmt])], linkage_items=[item])
        report = DataLineageAnalyzer().analyze(prog)

        ops = {e.operation for e in report.edges}
        assert "SUBTRACT" in ops


# ---------------------------------------------------------------------------
# Tests: file open modes
# ---------------------------------------------------------------------------


class TestFileOpenModes:
    def test_file_open_output_does_not_create_source(self):
        stmt = IOOpenStatement(LOC)
        stmt.set_open_mode("OUTPUT")
        stmt.add_file("OUTFILE")
        prog = _make_program([("MAIN", [stmt])])
        report = DataLineageAnalyzer().analyze(prog)

        names = {s.variable_name for s in report.sources}
        assert "OUTFILE" not in names

    def test_file_open_io_creates_source(self):
        stmt = IOOpenStatement(LOC)
        stmt.set_open_mode("I-O")
        stmt.add_file("IOFILE")
        prog = _make_program([("MAIN", [stmt])])
        report = DataLineageAnalyzer().analyze(prog)

        names = {s.variable_name for s in report.sources}
        assert "IOFILE" in names

    def test_file_open_extend_does_not_create_source(self):
        stmt = IOOpenStatement(LOC)
        stmt.set_open_mode("EXTEND")
        stmt.add_file("EXTFILE")
        prog = _make_program([("MAIN", [stmt])])
        report = DataLineageAnalyzer().analyze(prog)

        names = {s.variable_name for s in report.sources}
        assert "EXTFILE" not in names


# ---------------------------------------------------------------------------
# Tests: FILLER exclusion
# ---------------------------------------------------------------------------


class TestFillerExclusion:
    def test_filler_item_not_registered_as_source(self):
        filler = _linkage_item("FILLER")  # is_filler is auto-set when name == "FILLER"
        prog = _make_program(
            [("MAIN", [ContinueStatement(LOC)])], linkage_items=[filler]
        )
        report = DataLineageAnalyzer().analyze(prog)

        names = {s.variable_name for s in report.sources}
        assert "FILLER" not in names

    def test_non_filler_item_next_to_filler_still_registered(self):
        filler = _linkage_item("FILLER")
        real_item = _linkage_item("WS-REAL")
        prog = _make_program(
            [("MAIN", [ContinueStatement(LOC)])], linkage_items=[filler, real_item]
        )
        report = DataLineageAnalyzer().analyze(prog)

        names = {s.variable_name for s in report.sources}
        assert "WS-REAL" in names


# ---------------------------------------------------------------------------
# Tests: missing divisions (graceful handling)
# ---------------------------------------------------------------------------


class TestNoProcedureDivision:
    def test_no_procedure_division_returns_empty_report(self):
        loc = SourceLocation(1, 1)
        prog = CobolProgram("NOPROC", loc)
        prog.add_division(CobolDivision("IDENTIFICATION", loc))
        # No PROCEDURE division added
        report = DataLineageAnalyzer().analyze(prog)

        assert report.sources == []
        assert report.sinks == []
        assert report.edges == []
        assert report.variable_taints == {}
        assert report.program_name == "NOPROC"


class TestNoDataDivision:
    def test_no_data_division_analyzes_without_error(self):
        prog = _make_program([("MAIN", [ContinueStatement(LOC)])])
        # _make_program without linkage_items creates no DATA division
        report = DataLineageAnalyzer().analyze(prog)

        # No linkage sources can exist
        linkage_sources = [s for s in report.sources if s.kind == SourceKind.LINKAGE]
        assert linkage_sources == []


# ---------------------------------------------------------------------------
# Tests: multiple CALL BY REFERENCE params
# ---------------------------------------------------------------------------


class TestMultipleCallByRefParams:
    def test_multiple_by_ref_params_all_create_sinks(self):
        call = _call_by_ref("SUBROUTINE", ["WS-PARAM1", "WS-PARAM2", "WS-PARAM3"])
        prog = _make_program([("MAIN", [call])])
        report = DataLineageAnalyzer().analyze(prog)

        sink_ids = {s.sink_id for s in report.sinks}
        assert "CALL_OUTPUT:WS-PARAM1" in sink_ids
        assert "CALL_OUTPUT:WS-PARAM2" in sink_ids
        assert "CALL_OUTPUT:WS-PARAM3" in sink_ids

    def test_multiple_by_ref_params_all_get_external_taints(self):
        call = _call_by_ref("SUBROUTINE", ["WS-P1", "WS-P2"])
        prog = _make_program([("MAIN", [call])])
        report = DataLineageAnalyzer().analyze(prog)

        assert any("CALL_REF:SUBROUTINE:WS-P1" in t for t in report.variable_taints.get("WS-P1", []))
        assert any("CALL_REF:SUBROUTINE:WS-P2" in t for t in report.variable_taints.get("WS-P2", []))


# ---------------------------------------------------------------------------
# Tests: dynamic CALL with quoted program name
# ---------------------------------------------------------------------------


class TestDynamicCall:
    def test_dynamic_call_strips_quotes_from_program_name(self):
        stmt = CallStatement(LOC)
        stmt.set_called_program("'SUBROUTINE'", is_dynamic=True)
        stmt.add_using_parameter("WS-PARAM", "REFERENCE")
        prog = _make_program([("MAIN", [stmt])])
        report = DataLineageAnalyzer().analyze(prog)

        taints = report.variable_taints.get("WS-PARAM", [])
        # After quote stripping, program name becomes "SUBROUTINE"
        assert any("SUBROUTINE" in t for t in taints)
        # Should not contain raw quotes in the source ID
        assert not any("'SUBROUTINE'" in t for t in taints)

    def test_dynamic_call_double_quoted_program_name_stripped(self):
        stmt = CallStatement(LOC)
        stmt.set_called_program('"EXT-PROG"', is_dynamic=True)
        stmt.add_using_parameter("WS-OUT", "REFERENCE")
        prog = _make_program([("MAIN", [stmt])])
        report = DataLineageAnalyzer().analyze(prog)

        taints = report.variable_taints.get("WS-OUT", [])
        assert any("EXT-PROG" in t for t in taints)


# ---------------------------------------------------------------------------
# Tests: taint union and long chain propagation
# ---------------------------------------------------------------------------


class TestTaintUnion:
    def test_two_sources_union_into_same_variable(self):
        item_a = _linkage_item("WS-A")
        item_b = _linkage_item("WS-B")
        move_a = _move("WS-A", "WS-RESULT")
        move_b = _move("WS-B", "WS-RESULT")
        prog = _make_program(
            [("MAIN", [move_a, move_b])], linkage_items=[item_a, item_b]
        )
        report = DataLineageAnalyzer().analyze(prog)

        taints = report.variable_taints.get("WS-RESULT", [])
        assert "LINKAGE:WS-A" in taints
        assert "LINKAGE:WS-B" in taints

    def test_add_unions_taint_from_both_operands(self):
        item_a = _linkage_item("WS-A")
        item_b = _linkage_item("WS-B")
        add = _add(["WS-A", "WS-B"], giving="WS-RESULT")
        prog = _make_program([("MAIN", [add])], linkage_items=[item_a, item_b])
        report = DataLineageAnalyzer().analyze(prog)

        taints = report.variable_taints.get("WS-RESULT", [])
        assert "LINKAGE:WS-A" in taints
        assert "LINKAGE:WS-B" in taints


class TestLongChainPropagation:
    def test_four_hop_chain_preserves_original_source(self):
        item = _linkage_item("WS-SRC")
        move1 = _move("WS-SRC", "WS-B")
        move2 = _move("WS-B", "WS-C")
        move3 = _move("WS-C", "WS-D")
        prog = _make_program([("MAIN", [move1, move2, move3])], linkage_items=[item])
        report = DataLineageAnalyzer().analyze(prog)

        assert "LINKAGE:WS-SRC" in report.variable_taints.get("WS-D", [])

    def test_intermediate_variables_also_tainted(self):
        item = _linkage_item("WS-SRC")
        move1 = _move("WS-SRC", "WS-MID")
        move2 = _move("WS-MID", "WS-END")
        prog = _make_program([("MAIN", [move1, move2])], linkage_items=[item])
        report = DataLineageAnalyzer().analyze(prog)

        assert "LINKAGE:WS-SRC" in report.variable_taints.get("WS-MID", [])
        assert "LINKAGE:WS-SRC" in report.variable_taints.get("WS-END", [])


# ---------------------------------------------------------------------------
# Tests: DISPLAY with mixed tainted/untainted items
# ---------------------------------------------------------------------------


class TestMixedDisplaySinks:
    def test_display_with_mix_creates_only_tainted_sinks(self):
        item = _linkage_item("WS-TAINTED")
        disp = DisplayStatement(LOC)
        disp.add_display_item("WS-TAINTED")
        disp.add_display_item("WS-UNTAINTED")
        prog = _make_program([("MAIN", [disp])], linkage_items=[item])
        report = DataLineageAnalyzer().analyze(prog)

        sink_ids = {s.sink_id for s in report.sinks}
        assert "DISPLAY:WS-TAINTED" in sink_ids
        assert "DISPLAY:WS-UNTAINTED" not in sink_ids


# ---------------------------------------------------------------------------
# Tests: IOWriteStatement with only record_name (no from_clause)
# ---------------------------------------------------------------------------


class TestWriteRecordNameOnly:
    def test_write_without_from_clause_uses_record_name_for_sink(self):
        item = _linkage_item("WS-DATA")
        move = _move("WS-DATA", "WS-OUT-REC")
        write = _write("WS-OUT-REC")  # no from_var → from_clause is None
        prog = _make_program([("MAIN", [move, write])], linkage_items=[item])
        report = DataLineageAnalyzer().analyze(prog)

        sink_ids = {s.sink_id for s in report.sinks}
        assert "FILE_WRITE:WS-OUT-REC" in sink_ids


# ---------------------------------------------------------------------------
# Tests: _extract_variable_names internals
# ---------------------------------------------------------------------------


class TestExtractVariableNames:
    def test_empty_string_returns_empty_list(self):
        from cobolparser.analysis.data_lineage import _extract_variable_names

        assert _extract_variable_names("") == []

    def test_numeric_literals_excluded(self):
        from cobolparser.analysis.data_lineage import _extract_variable_names

        # Pure numeric tokens should be filtered
        result = _extract_variable_names("100 + 200")
        assert "100" not in result
        assert "200" not in result

    def test_reserved_words_excluded(self):
        from cobolparser.analysis.data_lineage import _extract_variable_names

        result = _extract_variable_names("ZERO TO FUNCTION LENGTH NOT")
        for word in ("ZERO", "TO", "FUNCTION", "LENGTH", "NOT"):
            assert word not in result

    def test_cobol_identifiers_extracted(self):
        from cobolparser.analysis.data_lineage import _extract_variable_names

        result = _extract_variable_names("WS-PRICE * WS-QTY")
        assert "WS-PRICE" in result
        assert "WS-QTY" in result

    def test_mixed_expression_only_returns_identifiers(self):
        from cobolparser.analysis.data_lineage import _extract_variable_names

        result = _extract_variable_names("WS-X + 5 * WS-Y - ZERO")
        assert "WS-X" in result
        assert "WS-Y" in result
        assert "5" not in result
        assert "ZERO" not in result


# ---------------------------------------------------------------------------
# Tests: sink paragraph tracking
# ---------------------------------------------------------------------------


class TestSinkParagraphTracking:
    def test_file_write_sink_records_paragraph_name(self):
        item = _linkage_item("WS-DATA")
        write = _write("WS-DATA", from_var="WS-DATA")
        prog = _make_program([("OUTPUT-PARA", [write])], linkage_items=[item])
        report = DataLineageAnalyzer().analyze(prog)

        file_write_sinks = [s for s in report.sinks if s.kind == SinkKind.FILE_WRITE]
        assert file_write_sinks
        assert file_write_sinks[0].paragraph == "OUTPUT-PARA"

    def test_display_sink_records_paragraph_name(self):
        item = _linkage_item("WS-MSG")
        disp = DisplayStatement(LOC)
        disp.add_display_item("WS-MSG")
        prog = _make_program([("DISPLAY-PARA", [disp])], linkage_items=[item])
        report = DataLineageAnalyzer().analyze(prog)

        display_sinks = [s for s in report.sinks if s.kind == SinkKind.DISPLAY]
        assert display_sinks
        assert display_sinks[0].paragraph == "DISPLAY-PARA"

    def test_call_output_sink_records_paragraph_name(self):
        call = _call_by_ref("SUB", ["WS-PARAM"])
        prog = _make_program([("CALL-PARA", [call])])
        report = DataLineageAnalyzer().analyze(prog)

        call_sinks = [s for s in report.sinks if s.kind == SinkKind.CALL_OUTPUT]
        assert call_sinks
        assert call_sinks[0].paragraph == "CALL-PARA"


# ---------------------------------------------------------------------------
# Tests: state reset between calls to analyze()
# ---------------------------------------------------------------------------


class TestStateReset:
    def test_analyze_twice_on_same_program_returns_same_result(self):
        item = _linkage_item("WS-IN")
        move = _move("WS-IN", "WS-OUT")
        prog = _make_program([("MAIN", [move])], linkage_items=[item])

        analyzer = DataLineageAnalyzer()
        report1 = analyzer.analyze(prog)
        report2 = analyzer.analyze(prog)

        assert len(report1.sources) == len(report2.sources)
        assert len(report1.edges) == len(report2.edges)
        assert report1.variable_taints == report2.variable_taints

    def test_second_program_does_not_retain_first_programs_state(self):
        item = _linkage_item("WS-IN")
        move = _move("WS-IN", "WS-OUT")
        prog1 = _make_program([("MAIN", [move])], linkage_items=[item])
        prog2 = _make_program([("MAIN", [ContinueStatement(LOC)])])

        analyzer = DataLineageAnalyzer()
        analyzer.analyze(prog1)
        report2 = analyzer.analyze(prog2)

        # prog2 has no linkage items → WS-OUT should not appear
        assert "WS-OUT" not in report2.variable_taints


# ---------------------------------------------------------------------------
# Tests: to_dict / serialization details
# ---------------------------------------------------------------------------


class TestToDictDetails:
    def test_taint_source_with_location_includes_location(self):
        loc = SourceLocation(42, 8)
        src = TaintSource("LINKAGE:FOO", SourceKind.LINKAGE, "FOO", location=loc)
        d = src.to_dict()
        assert "location" in d
        assert d["location"]["line"] == 42

    def test_taint_source_without_location_excludes_location_key(self):
        src = TaintSource("LINKAGE:FOO", SourceKind.LINKAGE, "FOO")
        d = src.to_dict()
        assert "location" not in d

    def test_lineage_edge_with_paragraph_includes_paragraph_key(self):
        edge = LineageEdge(["LINKAGE:FOO"], "BAR", "MOVE", paragraph="MAIN-PARA")
        d = edge.to_dict()
        assert "paragraph" in d
        assert d["paragraph"] == "MAIN-PARA"

    def test_lineage_edge_without_paragraph_excludes_paragraph_key(self):
        edge = LineageEdge(["LINKAGE:FOO"], "BAR", "MOVE")
        d = edge.to_dict()
        assert "paragraph" not in d

    def test_lineage_edge_with_location_includes_location_key(self):
        loc = SourceLocation(10, 8)
        edge = LineageEdge(["LINKAGE:FOO"], "BAR", "MOVE", location=loc)
        d = edge.to_dict()
        assert "location" in d

    def test_sink_field_with_paragraph_includes_paragraph_key(self):
        from cobolparser.analysis.data_lineage import SinkField

        sf = SinkField("FILE_WRITE:FOO", SinkKind.FILE_WRITE, "FOO", paragraph="WRITE-PARA")
        d = sf.to_dict()
        assert "paragraph" in d
        assert d["paragraph"] == "WRITE-PARA"

    def test_to_json_custom_indent_produces_valid_json(self):
        import json

        item = _linkage_item("WS-IN")
        prog = _make_program([("MAIN", [ContinueStatement(LOC)])], linkage_items=[item])
        report = DataLineageAnalyzer().analyze(prog)

        raw = report.to_json(indent=4)
        parsed = json.loads(raw)
        assert parsed["program_name"] == "TESTPROG"
