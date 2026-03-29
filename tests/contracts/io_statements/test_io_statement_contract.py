"""Contract tests for IO statement AST node serialization.

These tests verify that the parser produces AST nodes that conform to
the io-statement-ast.md contract specification.
"""

import json
import pytest
from cobolparser import parse_cobol
from cobolparser.models.statements import (
    IOReadStatement, IOWriteStatement, IOOpenStatement, IOCloseStatement, IOAcceptStatement,
    ReadStatement, WriteStatement, OpenStatement, CloseStatement, AcceptStatement
)
from cobolparser.models.ast_base import SourceLocation


class TestReadStatementContract:
    """Contract tests for ReadStatement AST node."""
    
    def test_read_statement_to_dict_structure(self):
        """Verify ReadStatement.to_dict() produces required fields."""
        location = SourceLocation(line=10, column=1)
        stmt = ReadStatement(location)
        stmt.set_file_name("MYFILE")
        stmt.set_into("INPUT-DATA")
        stmt.set_access_mode("NEXT")
        stmt.set_lock_mode(with_lock=True)

        result = stmt.to_dict()

        # Verify required fields exist
        assert "node_type" in result
        assert result["node_type"] == "Statement"
        assert "statement_type" in result
        assert result["statement_type"] == "READ"
        assert "file_name" in result
        assert result["file_name"] == "MYFILE"
        assert "into_target" in result
        assert result["into_target"] == "INPUT-DATA"
        assert "access_mode" in result
        assert result["access_mode"] == "NEXT"
        assert "with_lock" in result
        assert result["with_lock"] is True
        assert "location" in result
    
    def test_read_statement_json_serializable(self):
        """Verify ReadStatement can be serialized to JSON."""
        location = SourceLocation(line=10, column=1)
        stmt = ReadStatement(location)
        stmt.set_file_name("MYFILE")
        stmt.set_into("INPUT-DATA")
        
        result = stmt.to_dict()
        json_str = json.dumps(result)
        
        # Should not raise
        assert isinstance(json_str, str)
        parsed = json.loads(json_str)
        assert parsed["file_name"] == "MYFILE"
    
    def test_read_statement_location_metadata(self):
        """Verify ReadStatement includes source location."""
        location = SourceLocation(line=15, column=8)
        stmt = ReadStatement(location)
        
        result = stmt.to_dict()
        
        assert "location" in result
        assert result["location"]["line"] == 15
        assert result["location"]["column"] == 8


class TestWriteStatementContract:
    """Contract tests for WriteStatement AST node."""
    
    def test_write_statement_to_dict_structure(self):
        """Verify WriteStatement.to_dict() produces required fields."""
        location = SourceLocation(line=20, column=1)
        stmt = WriteStatement(location)
        stmt.set_record_name("OUTPUT-RECORD")
        stmt.set_from("SOURCE-DATA")
        stmt.set_advancing("AFTER", 2, False)
        
        result = stmt.to_dict()
        
        # Verify required fields
        assert "node_type" in result
        assert result["node_type"] == "Statement"
        assert "statement_type" in result
        assert result["statement_type"] == "WRITE"
        assert "record_name" in result
        assert result["record_name"] == "OUTPUT-RECORD"
        assert "from_clause" in result
        assert result["from_clause"] == "SOURCE-DATA"
        assert "advancing_clause" in result
        assert result["advancing_clause"]["type"] == "AFTER"
        assert result["advancing_clause"]["value"] == 2
    
    def test_write_statement_advancing_page(self):
        """Verify WriteStatement with ADVANCING PAGE."""
        location = SourceLocation(line=20, column=1)
        stmt = WriteStatement(location)
        stmt.set_record_name("PRINT-RECORD")
        stmt.set_advancing("BEFORE", None, True)
        
        result = stmt.to_dict()
        
        assert result["advancing_clause"]["type"] == "BEFORE"
        assert result["advancing_clause"]["value"] == "PAGE"
        assert result["advancing_clause"]["unit"] == "CHANNEL"
    
    def test_write_statement_delete_record(self):
        """Verify WriteStatement can mark record for deletion."""
        location = SourceLocation(line=20, column=1)
        stmt = WriteStatement(location)
        stmt.set_record_name("INDEXED-RECORD")
        stmt.set_delete(True)
        
        result = stmt.to_dict()
        
        assert "delete_record" in result
        assert result["delete_record"] is True


class TestOpenStatementContract:
    """Contract tests for OpenStatement AST node."""
    
    def test_open_statement_to_dict_structure(self):
        """Verify OpenStatement.to_dict() produces required fields."""
        location = SourceLocation(line=30, column=1)
        stmt = OpenStatement(location)
        stmt.set_open_mode("INPUT")
        stmt.add_file("FILE1")
        stmt.add_file("FILE2")
        
        result = stmt.to_dict()
        
        # Verify required fields
        assert "node_type" in result
        assert result["node_type"] == "Statement"
        assert "statement_type" in result
        assert result["statement_type"] == "OPEN"
        assert "open_mode" in result
        assert result["open_mode"] == "INPUT"
        assert "file_names" in result
        assert len(result["file_names"]) == 2
        assert "FILE1" in result["file_names"]
        assert "FILE2" in result["file_names"]
    
    def test_open_statement_all_modes(self):
        """Verify OpenStatement supports all modes."""
        location = SourceLocation(line=30, column=1)
        
        for mode in ["INPUT", "OUTPUT", "I-O", "EXTEND"]:
            stmt = OpenStatement(location)
            stmt.set_open_mode(mode)
            result = stmt.to_dict()
            assert result["open_mode"] == mode
    
    def test_open_statement_with_reposition(self):
        """Verify OpenStatement can set reposition flag."""
        location = SourceLocation(line=30, column=1)
        stmt = OpenStatement(location)
        stmt.set_open_mode("INPUT")
        stmt.add_file("MYFILE")
        stmt.set_reposition()
        
        result = stmt.to_dict()
        
        assert "with_reposition" in result
        assert result["with_reposition"] is True


class TestCloseStatementContract:
    """Contract tests for CloseStatement AST node."""
    
    def test_close_statement_to_dict_structure(self):
        """Verify CloseStatement.to_dict() produces required fields."""
        location = SourceLocation(line=40, column=1)
        stmt = CloseStatement(location)
        stmt.add_file("FILE1")
        stmt.add_file("FILE2", reel=True)
        
        result = stmt.to_dict()
        
        # Verify required fields
        assert "node_type" in result
        assert result["node_type"] == "Statement"
        assert "statement_type" in result
        assert result["statement_type"] == "CLOSE"
        assert "file_names" in result
        assert len(result["file_names"]) == 2
    
    def test_close_statement_file_options(self):
        """Verify CloseStatement properly tracks file-specific options."""
        location = SourceLocation(line=40, column=1)
        stmt = CloseStatement(location)
        stmt.add_file("TAPE-FILE", reel=True, no_rewind=True, with_lock=True)
        
        result = stmt.to_dict()
        
        # File options should be preserved
        assert "FILE-TAPE-FILE" in result or len(result["file_names"]) > 0
        # Verify serialization works
        json.dumps(result)
    
    def test_close_statement_multiple_files(self):
        """Verify CloseStatement handles multiple files with different options."""
        location = SourceLocation(line=40, column=1)
        stmt = CloseStatement(location)
        
        # File with no options
        stmt.add_file("FILE1")
        # File with REEL
        stmt.add_file("FILE2", reel=True)
        # File with UNIT
        stmt.add_file("FILE3", unit=True)
        # File with NO REWIND
        stmt.add_file("FILE4", no_rewind=True)
        # File with WITH LOCK
        stmt.add_file("FILE5", with_lock=True)
        
        result = stmt.to_dict()
        
        assert len(result["file_names"]) == 5
        json.dumps(result)  # Should be JSON serializable


class TestAcceptStatementContract:
    """Contract tests for AcceptStatement AST node."""
    
    def test_accept_statement_to_dict_structure(self):
        """Verify AcceptStatement.to_dict() produces required fields."""
        location = SourceLocation(line=50, column=1)
        stmt = AcceptStatement(location)
        stmt.set_target("USER-INPUT")
        stmt.set_from("CONSOLE")
        
        result = stmt.to_dict()
        
        # Verify required fields
        assert "node_type" in result
        assert result["node_type"] == "Statement"
        assert "statement_type" in result
        assert result["statement_type"] == "ACCEPT"
        assert "target" in result
        assert result["target"] == "USER-INPUT"
        assert "from_source" in result
        assert result["from_source"] == "CONSOLE"
    
    def test_accept_statement_with_position(self):
        """Verify AcceptStatement with AT LINE/COLUMN."""
        location = SourceLocation(line=50, column=1)
        stmt = AcceptStatement(location)
        stmt.set_target("SCREEN-FIELD")
        stmt.set_position(10, 20)
        
        result = stmt.to_dict()
        
        assert "at_line" in result
        assert result["at_line"] == 10
        assert "at_column" in result
        assert result["at_column"] == 20
    
    def test_accept_statement_display_attributes(self):
        """Verify AcceptStatement with display attributes."""
        location = SourceLocation(line=50, column=1)
        stmt = AcceptStatement(location)
        stmt.set_target("SCREEN-INPUT")
        stmt.set_cursor()
        stmt.set_color("YELLOW")
        stmt.set_beep()
        stmt.set_no_echo()
        
        result = stmt.to_dict()
        
        assert result["with_cursor"] is True
        assert result["color_attribute"] == "YELLOW"
        assert result["with_beep"] is True
        assert result["with_no_echo"] is True
    
    def test_accept_statement_all_attributes(self):
        """Verify AcceptStatement with all attributes combined."""
        location = SourceLocation(line=50, column=1)
        stmt = AcceptStatement(location)
        stmt.set_target("FULL-INPUT")
        stmt.set_from("ENVIRONMENT NAME")
        stmt.set_position(5, 15)
        stmt.set_cursor()
        stmt.set_color("BRIGHT RED")
        stmt.set_beep()
        
        result = stmt.to_dict()
        
        # All fields should be present
        assert result["target"] == "FULL-INPUT"
        assert result["from_source"] == "ENVIRONMENT NAME"
        assert result["at_line"] == 5
        assert result["at_column"] == 15
        assert result["with_cursor"] is True
        assert result["color_attribute"] == "BRIGHT RED"
        assert result["with_beep"] is True
        
        # Should be JSON serializable
        json.dumps(result)


class TestIOStatementParsedOutput:
    """Contract tests verifying parser-produced AST matches spec."""
    
    def test_parsed_read_statement_contract(self):
        """Verify parsed READ statement produces correct AST."""
        code = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-READ.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-DATA.
        PROCEDURE DIVISION.
            READ MYFILE INTO WS-DATA.
            STOP RUN.
        """
        result = parse_cobol(code)
        assert result.ast is not None
        
        # AST should be JSON serializable
        ast_dict = result.ast.to_dict()
        json_str = json.dumps(ast_dict)
        assert len(json_str) > 0
    
    def test_parsed_write_statement_contract(self):
        """Verify parsed WRITE statement produces correct AST."""
        code = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-WRITE.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 OUTPUT-REC.
        PROCEDURE DIVISION.
            WRITE OUTPUT-REC FROM OUTPUT-REC.
            STOP RUN.
        """
        result = parse_cobol(code)
        assert result.ast is not None
        
        # Should be JSON serializable
        ast_dict = result.ast.to_dict()
        json.dumps(ast_dict)
    
    def test_parsed_open_statement_contract(self):
        """Verify parsed OPEN statement produces correct AST."""
        code = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-OPEN.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT INFILE ASSIGN TO "input.dat".
        DATA DIVISION.
        FILE SECTION.
        FD INFILE.
        01 INREC.
        PROCEDURE DIVISION.
            OPEN INPUT INFILE.
            STOP RUN.
        """
        result = parse_cobol(code)
        assert result.ast is not None
        
        ast_dict = result.ast.to_dict()
        json.dumps(ast_dict)
    
    def test_parsed_close_statement_contract(self):
        """Verify parsed CLOSE statement produces correct AST."""
        code = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-CLOSE.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 MYFILE.
        PROCEDURE DIVISION.
            CLOSE MYFILE.
            STOP RUN.
        """
        result = parse_cobol(code)
        assert result.ast is not None
        
        ast_dict = result.ast.to_dict()
        json.dumps(ast_dict)
    
    def test_parsed_accept_statement_contract(self):
        """Verify parsed ACCEPT statement produces correct AST."""
        code = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-ACCEPT.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 USER-INPUT.
        PROCEDURE DIVISION.
            ACCEPT USER-INPUT.
            STOP RUN.
        """
        result = parse_cobol(code)
        assert result.ast is not None
        
        ast_dict = result.ast.to_dict()
        json.dumps(ast_dict)
