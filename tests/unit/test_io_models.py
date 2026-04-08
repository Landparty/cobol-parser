"""Unit tests for IO statement models.

Tests verify that IOReadStatement, IOWriteStatement, IOOpenStatement, IOCloseStatement,
and IOAcceptStatement models work correctly.
"""

from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.statements import (
    IOAcceptStatement,
    IOCloseStatement,
    IOOpenStatement,
    IOReadStatement,
    IOWriteStatement,
)


class TestReadStatement:
    """Test the ReadStatement model."""

    def test_read_statement_creation(self):
        """ReadStatement should be creatable with a location."""
        loc = SourceLocation(line=10, column=5)
        read_stmt = IOReadStatement(loc)
        assert read_stmt.statement_type == "READ"
        assert read_stmt.file_name is None

    def test_read_statement_set_file_name(self):
        """ReadStatement should allow setting the file name."""
        loc = SourceLocation(line=10, column=5)
        read_stmt = IOReadStatement(loc)
        read_stmt.set_file_name("INPUT-FILE")
        assert read_stmt.file_name == "INPUT-FILE"
        assert "INPUT-FILE" in read_stmt.operands

    def test_read_statement_set_into(self):
        """ReadStatement should allow setting the INTO target."""
        loc = SourceLocation(line=10, column=5)
        read_stmt = IOReadStatement(loc)
        read_stmt.set_into("RECORD-AREA")
        assert read_stmt.into_target == "RECORD-AREA"
        assert "RECORD-AREA" in read_stmt.operands

    def test_read_statement_set_access_mode(self):
        """ReadStatement should allow setting the record format."""
        loc = SourceLocation(line=10, column=5)
        read_stmt = IOReadStatement(loc)
        read_stmt.set_access_mode("next")
        assert read_stmt.access_mode == "NEXT"

    def test_read_statement_to_dict(self):
        """ReadStatement should serialize to dict."""
        loc = SourceLocation(line=10, column=5)
        read_stmt = IOReadStatement(loc)
        read_stmt.set_file_name("INPUT-FILE")
        read_stmt.set_into("RECORD-AREA")

        result = read_stmt.to_dict()
        assert result["statement_type"] == "READ"
        assert result["file_name"] == "INPUT-FILE"
        assert result["into_target"] == "RECORD-AREA"


class TestWriteStatement:
    """Test the WriteStatement model."""

    def test_write_statement_creation(self):
        """WriteStatement should be creatable with a location."""
        loc = SourceLocation(line=20, column=5)
        write_stmt = IOWriteStatement(loc)
        assert write_stmt.statement_type == "WRITE"
        assert write_stmt.record_name is None

    def test_write_statement_set_record_name(self):
        """WriteStatement should allow setting the record name."""
        loc = SourceLocation(line=20, column=5)
        write_stmt = IOWriteStatement(loc)
        write_stmt.set_record_name("OUTPUT-RECORD")
        assert write_stmt.record_name == "OUTPUT-RECORD"
        assert "OUTPUT-RECORD" in write_stmt.operands

    def test_write_statement_set_from(self):
        """WriteStatement should allow setting the FROM source."""
        loc = SourceLocation(line=20, column=5)
        write_stmt = IOWriteStatement(loc)
        write_stmt.set_from("SOURCE-DATA")
        assert write_stmt.from_clause == "SOURCE-DATA"
        assert "SOURCE-DATA" in write_stmt.operands

    def test_write_statement_set_advancing(self):
        """WriteStatement should allow setting ADVANCING clause."""
        loc = SourceLocation(line=20, column=5)
        write_stmt = IOWriteStatement(loc)
        write_stmt.set_advancing("AFTER", lines=2)
        assert write_stmt.advancing_clause["type"] == "AFTER"
        assert write_stmt.advancing_clause["value"] == 2

    def test_write_statement_to_dict(self):
        """WriteStatement should serialize to dict."""
        loc = SourceLocation(line=20, column=5)
        write_stmt = IOWriteStatement(loc)
        write_stmt.set_record_name("OUTPUT-RECORD")
        write_stmt.set_from("SOURCE-DATA")
        write_stmt.set_advancing("BEFORE", lines=1)

        result = write_stmt.to_dict()
        assert result["statement_type"] == "WRITE"
        assert result["record_name"] == "OUTPUT-RECORD"
        assert result["from_clause"] == "SOURCE-DATA"
        assert result["advancing_clause"]["type"] == "BEFORE"
        assert result["advancing_clause"]["value"] == 1


class TestOpenStatement:
    """Test the OpenStatement model."""

    def test_open_statement_creation(self):
        """OpenStatement should be creatable with a location."""
        loc = SourceLocation(line=30, column=5)
        open_stmt = IOOpenStatement(loc)
        assert open_stmt.statement_type == "OPEN"
        assert open_stmt.open_mode is None

    def test_open_statement_set_mode(self):
        """OpenStatement should allow setting the OPEN mode."""
        loc = SourceLocation(line=30, column=5)
        open_stmt = IOOpenStatement(loc)
        open_stmt.set_open_mode("INPUT")
        assert open_stmt.open_mode == "INPUT"

    def test_open_statement_add_file(self):
        """OpenStatement should allow adding files."""
        loc = SourceLocation(line=30, column=5)
        open_stmt = IOOpenStatement(loc)
        open_stmt.add_file("FILE-1")
        open_stmt.add_file("FILE-2")
        assert open_stmt.file_names == ["FILE-1", "FILE-2"]
        assert "FILE-1" in open_stmt.operands
        assert "FILE-2" in open_stmt.operands

    def test_open_statement_to_dict(self):
        """OpenStatement should serialize to dict."""
        loc = SourceLocation(line=30, column=5)
        open_stmt = IOOpenStatement(loc)
        open_stmt.set_open_mode("INPUT")
        open_stmt.add_file("FILE-1")
        open_stmt.add_file("FILE-2")

        result = open_stmt.to_dict()
        assert result["statement_type"] == "OPEN"
        assert result["open_mode"] == "INPUT"
        assert result["file_names"] == ["FILE-1", "FILE-2"]


class TestCloseStatement:
    """Test the CloseStatement model."""

    def test_close_statement_creation(self):
        """CloseStatement should be creatable with a location."""
        loc = SourceLocation(line=40, column=5)
        close_stmt = IOCloseStatement(loc)
        assert close_stmt.statement_type == "CLOSE"
        assert len(close_stmt.file_names) == 0

    def test_close_statement_add_file(self):
        """CloseStatement should allow adding files."""
        loc = SourceLocation(line=40, column=5)
        close_stmt = IOCloseStatement(loc)
        close_stmt.add_file("FILE-1", no_rewind=True)
        close_stmt.add_file("FILE-2", with_lock=True)
        assert close_stmt.file_names == ["FILE-1", "FILE-2"]
        assert close_stmt.close_options["FILE-1"]["no_rewind"] is True
        assert close_stmt.close_options["FILE-2"]["with_lock"] is True

    def test_close_statement_to_dict(self):
        """CloseStatement should serialize to dict."""
        loc = SourceLocation(line=40, column=5)
        close_stmt = IOCloseStatement(loc)
        close_stmt.add_file("FILE-1", no_rewind=True)

        result = close_stmt.to_dict()
        assert result["statement_type"] == "CLOSE"
        assert "FILE-1" in result["file_names"]
        assert result["close_options"]["FILE-1"]["no_rewind"] is True


class TestAcceptStatement:
    """Test the AcceptStatement model."""

    def test_accept_statement_creation(self):
        """AcceptStatement should be creatable with a location."""
        loc = SourceLocation(line=50, column=5)
        accept_stmt = IOAcceptStatement(loc)
        assert accept_stmt.statement_type == "ACCEPT"
        assert accept_stmt.target is None

    def test_accept_statement_set_target(self):
        """AcceptStatement should allow setting the target."""
        loc = SourceLocation(line=50, column=5)
        accept_stmt = IOAcceptStatement(loc)
        accept_stmt.set_target("USER-INPUT")
        assert accept_stmt.target == "USER-INPUT"
        assert "USER-INPUT" in accept_stmt.operands

    def test_accept_statement_set_from(self):
        """AcceptStatement should allow setting the FROM source."""
        loc = SourceLocation(line=50, column=5)
        accept_stmt = IOAcceptStatement(loc)
        accept_stmt.set_from("CONSOLE")
        assert accept_stmt.from_source == "CONSOLE"

    def test_accept_statement_set_position(self):
        """AcceptStatement should allow setting position."""
        loc = SourceLocation(line=50, column=5)
        accept_stmt = IOAcceptStatement(loc)
        accept_stmt.set_position(line=10, column=20)
        assert accept_stmt.at_line == 10
        assert accept_stmt.at_column == 20

    def test_accept_statement_to_dict(self):
        """AcceptStatement should serialize to dict."""
        loc = SourceLocation(line=50, column=5)
        accept_stmt = IOAcceptStatement(loc)
        accept_stmt.set_target("USER-INPUT")
        accept_stmt.set_from("CONSOLE")
        accept_stmt.set_position(line=5, column=10)
        accept_stmt.set_no_echo(True)

        result = accept_stmt.to_dict()
        assert result["statement_type"] == "ACCEPT"
        assert result["target"] == "USER-INPUT"
        assert result["from_source"] == "CONSOLE"
        assert result["at_line"] == 5
        assert result["at_column"] == 10
        assert result["with_no_echo"] is True


class TestIOStatementIntegration:
    """Test IO statements working together."""

    def test_io_statement_creation_flow(self):
        """Test creating multiple IO statements in sequence."""
        base_loc = SourceLocation(line=10, column=5)

        # Create OPEN statement
        open_stmt = IOOpenStatement(base_loc)
        open_stmt.set_open_mode("INPUT")
        open_stmt.add_file("INPUT-FILE")
        assert open_stmt.open_mode == "INPUT"

        # Create READ statement
        read_stmt = IOReadStatement(base_loc)
        read_stmt.set_file_name("INPUT-FILE")
        read_stmt.set_into("RECORD-BUFFER")
        assert read_stmt.file_name == "INPUT-FILE"

        # Create CLOSE statement
        close_stmt = IOCloseStatement(base_loc)
        close_stmt.add_file("INPUT-FILE")
        assert "INPUT-FILE" in close_stmt.file_names

    def test_io_statements_to_dict_structure(self):
        """Test that all IO statements produce valid dict structures."""
        loc = SourceLocation(line=10, column=5)

        statements = [
            IOOpenStatement(loc),
            IOReadStatement(loc),
            IOWriteStatement(loc),
            IOCloseStatement(loc),
            IOAcceptStatement(loc),
        ]

        for stmt in statements:
            result = stmt.to_dict()
            assert isinstance(result, dict)
            assert "node_type" in result
            assert "location" in result
            assert "metadata" in result
            assert result["location"] is not None
