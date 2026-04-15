"""Unit tests for data lineage / taint tracking analysis."""


from cobolparser.analysis.data_lineage import (
    DataLineageAnalyzer,
    LineageEdge,
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
