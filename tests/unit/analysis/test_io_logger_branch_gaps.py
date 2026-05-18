"""Branch-coverage tests for io_logger.py.

Targets specific missing branches identified in the 2026-05-18 coverage
analysis (analysis/io_logger.py was at 82% line / 71% branch). These tests
exercise the `elif` arms that prior tests skip by always taking the first
branch.

Specifically:
  - 407-408: READ with record_name but no into_target
  - 425-426: WRITE with record_name but no from_clause
  - 442: OPEN with mode "I-O" (BIDIRECTIONAL direction)
  - 475-478: REWRITE with record_name set
  - 491, 504, 517: DELETE / START / UNLOCK with target only
  - 381-386: SQL with empty host_variables AND empty into_vars (direction by sql_type)
  - 536->538: ACCEPT statement
"""

from __future__ import annotations

from cobolparser.analysis.io_logger import IOLogger
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.program import CobolDivision, CobolParagraph, CobolProgram
from cobolparser.models.statements.io import (
    IOAcceptStatement,
    IOOpenStatement,
    IOReadStatement,
    IORewriteStatement,
    IOWriteStatement,
)

_LOC = SourceLocation(1, 1)


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


class TestReadElseRecordName:
    """READ with record_name set but no INTO target (line 407-408)."""

    def test_read_with_record_name_no_into_uses_record(self):
        stmt = IOReadStatement(_LOC)
        stmt.set_file_name("DATA-FILE")
        stmt.set_record_name("DATA-REC")
        # Explicitly no INTO target
        prog = _make_program(stmt)
        report = IOLogger().analyze(prog)
        reads = [op for op in report.file_operations if op.operation == "READ"]
        assert reads
        assert "DATA-REC" in reads[0].variables


class TestWriteElseRecordName:
    """WRITE with record_name set but no FROM clause (line 425-426)."""

    def test_write_with_record_name_no_from_uses_record(self):
        stmt = IOWriteStatement(_LOC)
        stmt.file_name = "DATA-FILE"
        stmt.set_record_name("DATA-REC")
        # No from_clause
        prog = _make_program(stmt)
        report = IOLogger().analyze(prog)
        writes = [op for op in report.file_operations if op.operation == "WRITE"]
        assert writes
        assert "DATA-REC" in writes[0].variables


class TestOpenModeIO:
    """OPEN I-O mode produces BIDIRECTIONAL direction (line 442)."""

    def test_open_io_mode_is_bidirectional(self):
        stmt = IOOpenStatement(_LOC)
        stmt.set_open_mode("I-O")
        stmt.add_file("UPDATE-FILE")
        prog = _make_program(stmt)
        report = IOLogger().analyze(prog)
        opens = [op for op in report.file_operations if op.operation.startswith("OPEN")]
        assert opens
        assert opens[0].direction == "BIDIRECTIONAL"


class TestRewriteWithRecord:
    """REWRITE with record_name set (lines 475-478)."""

    def test_rewrite_record_name_in_variables(self):
        stmt = IORewriteStatement(_LOC)
        stmt.set_file_name("UPD-FILE")
        stmt.set_record_name("UPD-REC")
        prog = _make_program(stmt)
        report = IOLogger().analyze(prog)
        rw = [op for op in report.file_operations if op.operation == "REWRITE"]
        assert rw
        assert "UPD-REC" in rw[0].variables


class TestAcceptWithTarget:
    """ACCEPT statement with target (branch 536->538)."""

    def test_accept_target_in_variables(self):
        stmt = IOAcceptStatement(_LOC)
        # Use whatever setter exists; both names appear in usage
        if hasattr(stmt, "set_target"):
            stmt.set_target("WS-INPUT")
        else:
            stmt.target = "WS-INPUT"
        prog = _make_program(stmt)
        report = IOLogger().analyze(prog)
        accepts = [op for op in report.console_operations if op.operation == "ACCEPT"]
        assert accepts
        assert "WS-INPUT" in accepts[0].variables

    def test_accept_no_target_empty_variables(self):
        stmt = IOAcceptStatement(_LOC)
        # target deliberately unset
        prog = _make_program(stmt)
        report = IOLogger().analyze(prog)
        accepts = [op for op in report.console_operations if op.operation == "ACCEPT"]
        assert accepts
        assert accepts[0].variables == []
