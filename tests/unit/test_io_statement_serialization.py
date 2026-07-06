"""Tests for IO statement model to_dict() serialization.

Targets uncovered lines in models/statements/io.py (79.15%):
  - IOReadStatement setter methods and to_dict()
  - IOWriteStatement set_advancing, set_at_eop, set_lock, set_retry, to_dict()
  - IOOpenStatement set_reel_unit_control
  - IOCloseStatement add_file with options (reel, unit, no_rewind, with_lock)
  - IOAcceptStatement set_environment_name, set_position, to_dict()
  - IORewriteStatement setters and to_dict()
  - IODeleteStatement setters and to_dict()
  - IOStartStatement to_dict()
  - IOUnlockStatement set_record_scope, to_dict()
"""

from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.statements.base import CobolStatement
from cobolparser.models.statements.io import (
    IOAcceptStatement,
    IOCloseStatement,
    IODeleteStatement,
    IOOpenStatement,
    IOReadStatement,
    IORewriteStatement,
    IOStartStatement,
    IOUnlockStatement,
    IOWriteStatement,
)

LOC = SourceLocation(1, 1)


def _stmt() -> CobolStatement:
    """A minimal real statement node for clause-list setters."""
    return CobolStatement("DISPLAY", LOC)


class TestIOReadStatementSerialization:
    """Cover IOReadStatement setters and to_dict()."""

    def test_set_file_name(self):
        stmt = IOReadStatement(LOC)
        stmt.set_file_name("CUST-FILE")
        assert stmt.file_name == "CUST-FILE"
        assert "CUST-FILE" in stmt.operands

    def test_set_file_name_no_duplicate(self):
        stmt = IOReadStatement(LOC)
        stmt.set_file_name("CUST-FILE")
        stmt.set_file_name("CUST-FILE")
        assert stmt.operands.count("CUST-FILE") == 1

    def test_set_record_name(self):
        stmt = IOReadStatement(LOC)
        stmt.set_record_name("CUST-REC")
        assert stmt.record_name == "CUST-REC"
        assert "CUST-REC" in stmt.operands

    def test_set_into(self):
        stmt = IOReadStatement(LOC)
        stmt.set_into("WS-BUFFER")
        assert stmt.into_target == "WS-BUFFER"
        assert "WS-BUFFER" in stmt.operands

    def test_set_access_mode(self):
        stmt = IOReadStatement(LOC)
        stmt.set_access_mode("next")
        assert stmt.access_mode == "NEXT"

    def test_set_lock_mode(self):
        stmt = IOReadStatement(LOC)
        stmt.set_lock_mode(with_lock=True, with_nowait=True)
        assert stmt.with_lock is True
        assert stmt.with_nowait is True
        assert stmt.metadata["uses_lock"] is True
        assert stmt.lock_scope == "record"

    def test_set_retry(self):
        stmt = IOReadStatement(LOC)
        stmt.set_retry(3)
        assert stmt.retry_count == 3

    def test_set_at_end_clause(self):
        stmt = IOReadStatement(LOC)
        stmt.set_at_end_clause([])
        assert stmt.metadata["has_at_end"] is False
        inner = _stmt()
        stmt.set_at_end_clause([inner])
        assert stmt.metadata["has_at_end"] is True
        assert inner.parent is stmt

    def test_set_not_at_end_clause(self):
        stmt = IOReadStatement(LOC)
        inner = _stmt()
        stmt.set_not_at_end_clause([inner])
        assert stmt.not_at_end_clause == [inner]
        assert inner.parent is stmt

    def test_set_invalid_key_clause(self):
        stmt = IOReadStatement(LOC)
        inner = _stmt()
        stmt.set_invalid_key_clause([inner])
        assert stmt.metadata["has_invalid_key"] is True
        assert inner.parent is stmt

    def test_set_not_invalid_key_clause(self):
        stmt = IOReadStatement(LOC)
        inner = _stmt()
        stmt.set_not_invalid_key_clause([inner])
        assert stmt.not_invalid_key_clause == [inner]
        assert inner.parent is stmt

    def test_to_dict_complete(self):
        stmt = IOReadStatement(LOC)
        stmt.set_file_name("CUST-FILE")
        stmt.set_record_name("CUST-REC")
        stmt.set_into("WS-BUFFER")
        stmt.set_key("CUST-KEY")
        stmt.set_access_mode("NEXT")
        stmt.set_lock_mode(with_lock=True)
        stmt.set_retry(5)
        d = stmt.to_dict()
        assert d["file_name"] == "CUST-FILE"
        assert d["record_name"] == "CUST-REC"
        assert d["into_target"] == "WS-BUFFER"
        assert d["key_name"] == "CUST-KEY"
        assert d["access_mode"] == "NEXT"
        assert d["with_lock"] is True
        assert d["retry_count"] == 5


class TestIOWriteStatementSerialization:
    """Cover IOWriteStatement setters and to_dict()."""

    def test_set_advancing_before_lines(self):
        stmt = IOWriteStatement(LOC)
        stmt.set_advancing("BEFORE", lines=2)
        assert stmt.advancing_clause is not None
        assert stmt.advancing_clause["type"] == "BEFORE"
        assert stmt.advancing_clause["value"] == 2
        assert stmt.advancing_clause["unit"] == "LINES"
        assert stmt.metadata["uses_advancing"] is True

    def test_set_advancing_after_page(self):
        stmt = IOWriteStatement(LOC)
        stmt.set_advancing("AFTER", page=True)
        assert stmt.advancing_clause["type"] == "AFTER"
        assert stmt.advancing_clause["value"] == "PAGE"
        assert stmt.advancing_clause["unit"] == "CHANNEL"

    def test_set_advancing_before_no_lines_no_page(self):
        stmt = IOWriteStatement(LOC)
        stmt.set_advancing("BEFORE")
        assert stmt.advancing_clause["value"] is None
        assert stmt.advancing_clause["unit"] is None

    def test_set_at_eop_clause(self):
        stmt = IOWriteStatement(LOC)
        inner = _stmt()
        stmt.set_at_eop_clause([inner])
        assert stmt.at_eop_clause == [inner]
        assert inner.parent is stmt

    def test_set_invalid_key_clause(self):
        stmt = IOWriteStatement(LOC)
        inner = _stmt()
        stmt.set_invalid_key_clause([inner])
        assert stmt.metadata["has_invalid_key"] is True
        assert inner.parent is stmt

    def test_set_not_invalid_key_clause(self):
        stmt = IOWriteStatement(LOC)
        inner = _stmt()
        stmt.set_not_invalid_key_clause([inner])
        assert stmt.not_invalid_key_clause == [inner]
        assert inner.parent is stmt

    def test_set_retry(self):
        stmt = IOWriteStatement(LOC)
        stmt.set_retry(10)
        assert stmt.retry_count == 10

    def test_set_lock(self):
        stmt = IOWriteStatement(LOC)
        stmt.set_lock(True)
        assert stmt.with_lock is True
        assert stmt.metadata["uses_lock"] is True
        assert stmt.lock_scope == "record"

    def test_set_delete(self):
        stmt = IOWriteStatement(LOC)
        stmt.set_delete(True)
        assert stmt.delete_record is True

    def test_set_from(self):
        stmt = IOWriteStatement(LOC)
        stmt.set_from("WS-BUFFER")
        assert stmt.from_clause == "WS-BUFFER"
        assert "WS-BUFFER" in stmt.operands

    def test_set_record_name(self):
        stmt = IOWriteStatement(LOC)
        stmt.set_record_name("OUTPUT-REC")
        assert stmt.record_name == "OUTPUT-REC"
        assert "OUTPUT-REC" in stmt.operands

    def test_to_dict_complete(self):
        stmt = IOWriteStatement(LOC)
        stmt.set_record_name("OUTPUT-REC")
        stmt.set_from("WS-DATA")
        stmt.set_advancing("AFTER", lines=3)
        stmt.set_lock(True)
        stmt.set_retry(2)
        d = stmt.to_dict()
        assert d["record_name"] == "OUTPUT-REC"
        assert d["from_clause"] == "WS-DATA"
        assert d["advancing_clause"]["type"] == "AFTER"
        assert d["with_lock"] is True
        assert d["retry_count"] == 2


class TestIOOpenStatementSerialization:
    """Cover IOOpenStatement setters and to_dict()."""

    def test_set_reel_unit_control(self):
        stmt = IOOpenStatement(LOC)
        stmt.set_reel_unit_control("reel")
        assert stmt.reel_unit_control == "REEL"
        assert stmt.metadata["has_reel_unit"] is True

    def test_set_reposition(self):
        stmt = IOOpenStatement(LOC)
        stmt.set_reposition(True)
        assert stmt.with_reposition is True

    def test_to_dict(self):
        stmt = IOOpenStatement(LOC)
        stmt.set_open_mode("I-O")
        stmt.add_file("CUST-FILE")
        stmt.set_reel_unit_control("unit")
        d = stmt.to_dict()
        assert d["open_mode"] == "I-O"
        assert "CUST-FILE" in d["file_names"]
        assert d["reel_unit_control"] == "UNIT"


class TestIOCloseStatementSerialization:
    """Cover IOCloseStatement add_file with options."""

    def test_add_file_with_lock(self):
        stmt = IOCloseStatement(LOC)
        stmt.add_file("FILE-A", with_lock=True)
        assert "FILE-A" in stmt.file_names
        assert stmt.close_options["FILE-A"]["with_lock"] is True
        assert stmt.metadata["has_lock"] is True

    def test_add_file_with_reel(self):
        stmt = IOCloseStatement(LOC)
        stmt.add_file("TAPE-FILE", reel=True)
        assert stmt.close_options["TAPE-FILE"]["reel"] is True
        assert stmt.metadata["has_reel_unit"] is True

    def test_add_file_with_unit(self):
        stmt = IOCloseStatement(LOC)
        stmt.add_file("TAPE-FILE", unit=True)
        assert stmt.close_options["TAPE-FILE"]["unit"] is True
        assert stmt.metadata["has_reel_unit"] is True

    def test_add_file_with_no_rewind(self):
        stmt = IOCloseStatement(LOC)
        stmt.add_file("FILE-B", no_rewind=True)
        assert stmt.close_options["FILE-B"]["no_rewind"] is True

    def test_add_file_no_duplicate(self):
        stmt = IOCloseStatement(LOC)
        stmt.add_file("FILE-A")
        stmt.add_file("FILE-A")
        assert stmt.file_names.count("FILE-A") == 1

    def test_to_dict(self):
        stmt = IOCloseStatement(LOC)
        stmt.add_file("FILE-A", with_lock=True)
        stmt.add_file("FILE-B", reel=True)
        d = stmt.to_dict()
        assert "FILE-A" in d["file_names"]
        assert "FILE-B" in d["file_names"]
        assert d["close_options"]["FILE-A"]["with_lock"] is True
        assert d["close_options"]["FILE-B"]["reel"] is True


class TestIOAcceptStatementSerialization:
    """Cover IOAcceptStatement setters and to_dict()."""

    def test_set_target(self):
        stmt = IOAcceptStatement(LOC)
        stmt.set_target("WS-INPUT")
        assert stmt.target == "WS-INPUT"
        assert "WS-INPUT" in stmt.operands

    def test_set_from(self):
        stmt = IOAcceptStatement(LOC)
        stmt.set_from("console")
        assert stmt.from_source == "CONSOLE"

    def test_set_environment_name(self):
        stmt = IOAcceptStatement(LOC)
        stmt.set_environment_name("ENV-PATH")
        assert stmt.environment_name == "ENV-PATH"
        assert stmt.metadata["has_environment_name"] is True

    def test_set_position(self):
        stmt = IOAcceptStatement(LOC)
        stmt.set_position(line=5, column=10)
        assert stmt.at_line == 5
        assert stmt.at_column == 10
        assert stmt.metadata["has_position"] is True

    def test_set_position_none(self):
        stmt = IOAcceptStatement(LOC)
        stmt.set_position()
        assert stmt.metadata["has_position"] is False

    def test_set_cursor(self):
        stmt = IOAcceptStatement(LOC)
        stmt.set_cursor(True)
        assert stmt.with_cursor is True

    def test_set_color(self):
        stmt = IOAcceptStatement(LOC)
        stmt.set_color("RED")
        assert stmt.color_attribute == "RED"

    def test_set_beep(self):
        stmt = IOAcceptStatement(LOC)
        stmt.set_beep(True)
        assert stmt.with_beep is True

    def test_set_no_echo(self):
        stmt = IOAcceptStatement(LOC)
        stmt.set_no_echo(True)
        assert stmt.with_no_echo is True

    def test_to_dict_complete(self):
        stmt = IOAcceptStatement(LOC)
        stmt.set_target("WS-INPUT")
        stmt.set_from("ENVIRONMENT")
        stmt.set_environment_name("PATH")
        stmt.set_position(line=3, column=20)
        stmt.set_cursor(True)
        stmt.set_color("BLUE")
        stmt.set_beep(True)
        stmt.set_no_echo(True)
        d = stmt.to_dict()
        assert d["target"] == "WS-INPUT"
        assert d["from_source"] == "ENVIRONMENT"
        assert d["environment_name"] == "PATH"
        assert d["at_line"] == 3
        assert d["at_column"] == 20
        assert d["with_cursor"] is True
        assert d["color_attribute"] == "BLUE"
        assert d["with_beep"] is True
        assert d["with_no_echo"] is True


class TestIORewriteStatementSerialization:
    """Cover IORewriteStatement setters and to_dict()."""

    def test_set_file_name(self):
        stmt = IORewriteStatement(LOC)
        stmt.set_file_name("CUST-FILE")
        assert stmt.file_name == "CUST-FILE"

    def test_set_record_name(self):
        stmt = IORewriteStatement(LOC)
        stmt.set_record_name("CUST-REC")
        assert stmt.record_name == "CUST-REC"
        assert "CUST-REC" in stmt.operands

    def test_set_invalid_key_clause(self):
        stmt = IORewriteStatement(LOC)
        inner = _stmt()
        stmt.set_invalid_key_clause([inner])
        assert stmt.metadata["has_invalid_key"] is True
        assert inner.parent is stmt

    def test_set_not_invalid_key_clause(self):
        stmt = IORewriteStatement(LOC)
        inner = _stmt()
        stmt.set_not_invalid_key_clause([inner])
        assert stmt.not_invalid_key_clause == [inner]
        assert inner.parent is stmt

    def test_set_lock(self):
        stmt = IORewriteStatement(LOC)
        stmt.set_lock(True)
        assert stmt.with_lock is True
        assert stmt.metadata["uses_lock"] is True

    def test_to_dict(self):
        stmt = IORewriteStatement(LOC)
        stmt.set_file_name("CUST-FILE")
        stmt.set_record_name("CUST-REC")
        stmt.set_lock(True)
        d = stmt.to_dict()
        assert d["file_name"] == "CUST-FILE"
        assert d["record_name"] == "CUST-REC"
        assert d["with_lock"] is True
        assert d["invalid_key_clause"] == []
        assert d["not_invalid_key_clause"] == []


class TestIODeleteStatementSerialization:
    """Cover IODeleteStatement setters and to_dict()."""

    def test_set_file_name(self):
        stmt = IODeleteStatement(LOC)
        stmt.set_file_name("CUST-FILE")
        assert stmt.file_name == "CUST-FILE"

    def test_set_invalid_key_clause(self):
        stmt = IODeleteStatement(LOC)
        inner = _stmt()
        stmt.set_invalid_key_clause([inner])
        assert stmt.metadata["has_invalid_key"] is True
        assert inner.parent is stmt

    def test_set_not_invalid_key_clause(self):
        stmt = IODeleteStatement(LOC)
        inner = _stmt()
        stmt.set_not_invalid_key_clause([inner])
        assert stmt.not_invalid_key_clause == [inner]
        assert inner.parent is stmt

    def test_set_lock(self):
        stmt = IODeleteStatement(LOC)
        stmt.set_lock(True)
        assert stmt.with_lock is True
        assert stmt.metadata["uses_lock"] is True

    def test_to_dict(self):
        stmt = IODeleteStatement(LOC)
        stmt.set_file_name("CUST-FILE")
        stmt.set_lock(True)
        d = stmt.to_dict()
        assert d["file_name"] == "CUST-FILE"
        assert d["with_lock"] is True


class TestIOStartStatementSerialization:
    """Cover IOStartStatement to_dict()."""

    def test_set_key_condition(self):
        stmt = IOStartStatement(LOC)
        stmt.set_key_condition("greater than")
        assert stmt.key_condition == "GREATER THAN"

    def test_set_invalid_key_clause(self):
        stmt = IOStartStatement(LOC)
        inner = _stmt()
        stmt.set_invalid_key_clause([inner])
        assert stmt.metadata["has_invalid_key"] is True
        assert inner.parent is stmt

    def test_set_not_invalid_key_clause(self):
        stmt = IOStartStatement(LOC)
        inner = _stmt()
        stmt.set_not_invalid_key_clause([inner])
        assert stmt.not_invalid_key_clause == [inner]
        assert inner.parent is stmt

    def test_to_dict(self):
        stmt = IOStartStatement(LOC)
        stmt.set_file_name("IDX-FILE")
        stmt.set_key_condition("EQUAL")
        d = stmt.to_dict()
        assert d["file_name"] == "IDX-FILE"
        assert d["key_condition"] == "EQUAL"
        assert d["invalid_key_clause"] == []
        assert d["not_invalid_key_clause"] == []


class TestIOUnlockStatementSerialization:
    """Cover IOUnlockStatement setters and to_dict()."""

    def test_set_file_name(self):
        stmt = IOUnlockStatement(LOC)
        stmt.set_file_name("CUST-FILE")
        assert stmt.file_name == "CUST-FILE"

    def test_set_record_scope(self):
        stmt = IOUnlockStatement(LOC)
        stmt.set_record_scope("record")
        assert stmt.record_scope == "RECORD"
        assert stmt.metadata["has_record_scope"] is True

    def test_set_record_scope_file(self):
        stmt = IOUnlockStatement(LOC)
        stmt.set_record_scope("file")
        assert stmt.record_scope == "FILE"

    def test_to_dict(self):
        stmt = IOUnlockStatement(LOC)
        stmt.set_file_name("CUST-FILE")
        stmt.set_record_scope("RECORD")
        d = stmt.to_dict()
        assert d["file_name"] == "CUST-FILE"
        assert d["record_scope"] == "RECORD"
