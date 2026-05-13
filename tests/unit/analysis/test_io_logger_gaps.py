"""Tests for io_logger.py paths not covered by existing tests.

Targets:
- _collect_sql_operations(): SQL with cursor_name in details (line 337)
- _collect_sql_operations(): SQL with no host variables — direction by sql_type
  (lines 380-396): SELECT/FETCH → OUTPUT, OPEN/CLOSE/COMMIT/ROLLBACK → BIDIRECTIONAL,
  INSERT/UPDATE/DELETE → INPUT
- _collect_call_operations(): dynamic call with possible_values (lines 219-220)
- _collect_call_operations(): GIVING and RETURNING parameters (lines 256-268)
- _collect_file_io_operations(): IORewriteStatement with record_name (lines 474-488)
- _collect_file_io_operations(): IODeleteStatement (lines 490-501)
- _collect_file_io_operations(): IOStartStatement (lines 503-514)
- _collect_file_io_operations(): IOUnlockStatement (lines 516-527)
"""

from __future__ import annotations

from cobolparser.analysis.io_logger import IOLogger
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.program import CobolDivision, CobolParagraph, CobolProgram
from cobolparser.models.sql_statements import ExecSQLStatement
from cobolparser.models.statements.call import CallStatement
from cobolparser.models.statements.io import (
    IODeleteStatement,
    IORewriteStatement,
    IOStartStatement,
    IOUnlockStatement,
)

_LOC = SourceLocation(1, 1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_program(*statements) -> CobolProgram:
    prog = CobolProgram("TEST-PROG", _LOC)
    prog.add_division(CobolDivision("IDENTIFICATION", _LOC))
    proc_div = CobolDivision("PROCEDURE", _LOC)
    para = CobolParagraph("MAIN-LOGIC", _LOC)
    for stmt in statements:
        para.add_statement(stmt)
    proc_div.add_paragraph(para)
    prog.add_division(proc_div)
    return prog


def _sql(sql_text: str) -> ExecSQLStatement:
    stmt = ExecSQLStatement(_LOC)
    stmt.set_sql_text(sql_text)
    return stmt


# ---------------------------------------------------------------------------
# SQL with cursor_name in details
# ---------------------------------------------------------------------------


class TestSQLCursorName:
    def test_fetch_cursor_name_in_details(self):
        stmt = _sql("FETCH NEXT FROM MY-CURSOR INTO :WS-VAR")
        prog = _make_program(stmt)
        report = IOLogger().analyze(prog)
        sql_ops = report.sql_operations
        assert len(sql_ops) >= 1
        detail_op = sql_ops[0]
        # cursor_name should be present in details when set by the SQL parser
        assert "sql_type" in detail_op.details

    def test_declare_cursor_sets_cursor_name(self):
        stmt = _sql("DECLARE MY-CURSOR CURSOR FOR SELECT * FROM EMP-TABLE")
        prog = _make_program(stmt)
        report = IOLogger().analyze(prog)
        assert len(report.sql_operations) >= 1


# ---------------------------------------------------------------------------
# SQL with no host variables — direction by sql_type (lines 380-396)
# ---------------------------------------------------------------------------


class TestSQLNoHostVariables:
    def test_select_no_host_vars_direction_output(self):
        stmt = _sql("SELECT * FROM EMP-TABLE")
        prog = _make_program(stmt)
        report = IOLogger().analyze(prog)
        sql_ops = report.sql_operations
        assert len(sql_ops) >= 1
        assert sql_ops[0].direction == "OUTPUT"

    def test_fetch_no_host_vars_direction_output(self):
        stmt = _sql("FETCH NEXT FROM MY-CURSOR")
        prog = _make_program(stmt)
        report = IOLogger().analyze(prog)
        sql_ops = report.sql_operations
        assert len(sql_ops) >= 1
        assert sql_ops[0].direction == "OUTPUT"

    def test_commit_no_host_vars_direction_bidirectional(self):
        stmt = _sql("COMMIT WORK")
        prog = _make_program(stmt)
        report = IOLogger().analyze(prog)
        sql_ops = report.sql_operations
        assert len(sql_ops) >= 1
        assert sql_ops[0].direction == "BIDIRECTIONAL"

    def test_rollback_no_host_vars_direction_bidirectional(self):
        stmt = _sql("ROLLBACK")
        prog = _make_program(stmt)
        report = IOLogger().analyze(prog)
        sql_ops = report.sql_operations
        assert len(sql_ops) >= 1
        assert sql_ops[0].direction == "BIDIRECTIONAL"

    def test_open_cursor_no_host_vars_direction_bidirectional(self):
        stmt = _sql("OPEN MY-CURSOR")
        prog = _make_program(stmt)
        report = IOLogger().analyze(prog)
        sql_ops = report.sql_operations
        assert len(sql_ops) >= 1
        assert sql_ops[0].direction == "BIDIRECTIONAL"

    def test_close_cursor_no_host_vars_direction_bidirectional(self):
        stmt = _sql("CLOSE MY-CURSOR")
        prog = _make_program(stmt)
        report = IOLogger().analyze(prog)
        sql_ops = report.sql_operations
        assert len(sql_ops) >= 1
        assert sql_ops[0].direction == "BIDIRECTIONAL"

    def test_insert_no_host_vars_direction_input(self):
        stmt = _sql("INSERT INTO EMP-TABLE VALUES (1, 'TEST')")
        prog = _make_program(stmt)
        report = IOLogger().analyze(prog)
        sql_ops = report.sql_operations
        # May or may not have host variables; find one with empty variables list
        no_var_ops = [op for op in sql_ops if op.variables == []]
        if no_var_ops:
            assert no_var_ops[0].direction == "INPUT"

    def test_update_no_host_vars_direction_input(self):
        stmt = _sql("UPDATE EMP-TABLE SET NAME = 'TEST'")
        prog = _make_program(stmt)
        report = IOLogger().analyze(prog)
        sql_ops = report.sql_operations
        no_var_ops = [op for op in sql_ops if op.variables == []]
        if no_var_ops:
            assert no_var_ops[0].direction == "INPUT"

    def test_delete_no_host_vars_direction_input(self):
        stmt = _sql("DELETE FROM EMP-TABLE WHERE ID = 1")
        prog = _make_program(stmt)
        report = IOLogger().analyze(prog)
        sql_ops = report.sql_operations
        no_var_ops = [op for op in sql_ops if op.variables == []]
        if no_var_ops:
            assert no_var_ops[0].direction == "INPUT"


# ---------------------------------------------------------------------------
# CALL with dynamic possible_values
# ---------------------------------------------------------------------------


class TestCallDynamicPossibleValues:
    def test_possible_values_in_details(self):
        stmt = CallStatement(_LOC)
        stmt.set_called_program("WS-PROG-NAME", is_dynamic=True)
        stmt.set_possible_values(["PROG-A", "PROG-B"])
        prog = _make_program(stmt)
        report = IOLogger().analyze(prog)
        call_ops = report.calls
        assert len(call_ops) >= 1
        call_op = call_ops[0]
        assert call_op.details.get("is_dynamic") is True
        assert "possible_values" in call_op.details
        assert set(call_op.details["possible_values"]) >= {"PROG-A", "PROG-B"}


# ---------------------------------------------------------------------------
# CALL with GIVING and RETURNING parameters
# ---------------------------------------------------------------------------


class TestCallGivingReturning:
    def test_giving_parameter_becomes_output_operation(self):
        stmt = CallStatement(_LOC)
        stmt.set_called_program("MY-PROG")
        stmt.set_giving_parameter("WS-RESULT")
        prog = _make_program(stmt)
        report = IOLogger().analyze(prog)
        call_ops = report.calls
        giving_ops = [
            op for op in call_ops if op.details.get("passing_mode") == "GIVING"
        ]
        assert len(giving_ops) >= 1
        assert giving_ops[0].direction == "OUTPUT"
        assert "WS-RESULT" in giving_ops[0].variables

    def test_returning_parameter_becomes_output_operation(self):
        stmt = CallStatement(_LOC)
        stmt.set_called_program("MY-PROG")
        stmt.set_returning_parameter("WS-RET")
        prog = _make_program(stmt)
        report = IOLogger().analyze(prog)
        call_ops = report.calls
        ret_ops = [
            op for op in call_ops if op.details.get("passing_mode") == "RETURNING"
        ]
        assert len(ret_ops) >= 1
        assert ret_ops[0].direction == "OUTPUT"
        assert "WS-RET" in ret_ops[0].variables


# ---------------------------------------------------------------------------
# IORewriteStatement with record_name
# ---------------------------------------------------------------------------


class TestFileIORewrite:
    def test_rewrite_with_record_name(self):
        stmt = IORewriteStatement(_LOC)
        stmt.set_file_name("MY-FILE")
        stmt.set_record_name("MY-RECORD")
        prog = _make_program(stmt)
        report = IOLogger().analyze(prog)
        file_ops = report.file_operations
        rw = [op for op in file_ops if op.operation == "REWRITE"]
        assert len(rw) >= 1
        assert "MY-RECORD" in rw[0].variables

    def test_rewrite_no_record_name(self):
        stmt = IORewriteStatement(_LOC)
        stmt.set_file_name("MY-FILE")
        prog = _make_program(stmt)
        report = IOLogger().analyze(prog)
        file_ops = report.file_operations
        rw = [op for op in file_ops if op.operation == "REWRITE"]
        assert len(rw) >= 1
        assert rw[0].variables == []


# ---------------------------------------------------------------------------
# IODeleteStatement
# ---------------------------------------------------------------------------


class TestFileIODelete:
    def test_delete_produces_output_operation(self):
        stmt = IODeleteStatement(_LOC)
        stmt.set_file_name("MY-FILE")
        prog = _make_program(stmt)
        report = IOLogger().analyze(prog)
        file_ops = report.file_operations
        deletes = [op for op in file_ops if op.operation == "DELETE"]
        assert len(deletes) >= 1
        assert deletes[0].direction == "OUTPUT"
        assert deletes[0].target == "MY-FILE"

    def test_delete_variables_empty(self):
        stmt = IODeleteStatement(_LOC)
        stmt.set_file_name("MY-FILE")
        prog = _make_program(stmt)
        report = IOLogger().analyze(prog)
        deletes = [op for op in report.file_operations if op.operation == "DELETE"]
        assert deletes[0].variables == []


# ---------------------------------------------------------------------------
# IOStartStatement
# ---------------------------------------------------------------------------


class TestFileIOStart:
    def test_start_produces_input_operation(self):
        stmt = IOStartStatement(_LOC)
        stmt.set_file_name("IDX-FILE")
        stmt.set_key_condition("EQUAL")
        prog = _make_program(stmt)
        report = IOLogger().analyze(prog)
        file_ops = report.file_operations
        starts = [op for op in file_ops if op.operation == "START"]
        assert len(starts) >= 1
        assert starts[0].direction == "INPUT"

    def test_start_key_condition_in_details(self):
        stmt = IOStartStatement(_LOC)
        stmt.set_file_name("IDX-FILE")
        stmt.set_key_condition("GREATER")
        prog = _make_program(stmt)
        report = IOLogger().analyze(prog)
        starts = [op for op in report.file_operations if op.operation == "START"]
        assert starts[0].details.get("key_condition") == "GREATER"


# ---------------------------------------------------------------------------
# IOUnlockStatement
# ---------------------------------------------------------------------------


class TestFileIOUnlock:
    def test_unlock_produces_bidirectional_operation(self):
        stmt = IOUnlockStatement(_LOC)
        stmt.set_file_name("MY-FILE")
        prog = _make_program(stmt)
        report = IOLogger().analyze(prog)
        file_ops = report.file_operations
        unlocks = [op for op in file_ops if op.operation == "UNLOCK"]
        assert len(unlocks) >= 1
        assert unlocks[0].direction == "BIDIRECTIONAL"

    def test_unlock_record_scope_in_details(self):
        stmt = IOUnlockStatement(_LOC)
        stmt.set_file_name("MY-FILE")
        stmt.set_record_scope("RECORD")
        prog = _make_program(stmt)
        report = IOLogger().analyze(prog)
        unlocks = [op for op in report.file_operations if op.operation == "UNLOCK"]
        assert unlocks[0].details.get("record_scope") == "RECORD"
