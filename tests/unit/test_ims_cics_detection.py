"""Unit tests for IMS and CICS detection in COBOL programs.

This module provides comprehensive tests for detecting IMS (Information Management System)
and CICS (Customer Information Control System) statements in COBOL programs, similar to
existing SQL detection capabilities.

IMS is detected through CALL statements to IMS language interfaces:
- CBLTDLI (COBOL Language Interface)
- AIBTDLI (Application Interface Block Interface)
- CEETDLI (Language Environment-independent Interface)

CICS is detected through EXEC CICS statements.
"""

import pytest
from cobolparser.models.program import CobolProgram, CobolDivision, CobolParagraph
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.statements import CobolStatement
from cobolparser.dialects.ibm_enterprise import (
    ExecSQLStatement,
    ExecCICSStatement,
    ExecIMSStatement,
    IBMEnterpriseCobol
)


class TestExecIMSStatement:
    """Test ExecIMSStatement class."""
    
    def test_exec_ims_statement_creation(self):
        """Test basic creation of ExecIMSStatement."""
        location = SourceLocation(20, 8)
        stmt = ExecIMSStatement(location)
        
        assert stmt.node_type == "Statement"
        assert stmt.statement_type == "EXEC-IMS"
        assert stmt.location == location
        assert stmt.ims_command == ""
        assert stmt.ims_call_type == "UNKNOWN"
        assert stmt.ims_options == {}
    
    def test_set_ims_command(self):
        """Test setting IMS command."""
        location = SourceLocation(20, 8)
        stmt = ExecIMSStatement(location)
        
        stmt.set_command("gu")
        assert stmt.ims_command == "GU"
        assert stmt.ims_call_type == "GU"
        
        stmt.set_command("ISRT")
        assert stmt.ims_command == "ISRT"
        assert stmt.ims_call_type == "ISRT"
    
    def test_set_ims_command_unknown_type(self):
        """Test setting IMS command with unknown type."""
        location = SourceLocation(20, 8)
        stmt = ExecIMSStatement(location)
        
        stmt.set_command("UNKNOWN-CMD")
        assert stmt.ims_command == "UNKNOWN-CMD"
        assert stmt.ims_call_type == "UNKNOWN"
    
    def test_add_ims_option(self):
        """Test adding IMS options."""
        location = SourceLocation(20, 8)
        stmt = ExecIMSStatement(location)
        
        stmt.add_option("SEGMENT", "EMPLOYEE")
        stmt.add_option("SSA", "EMP-KEY")
        
        assert stmt.ims_options["SEGMENT"] == "EMPLOYEE"
        assert stmt.ims_options["SSA"] == "EMP-KEY"
        assert len(stmt.ims_options) == 2
    
    def test_exec_ims_to_dict(self):
        """Test converting ExecIMSStatement to dictionary."""
        location = SourceLocation(20, 8)
        stmt = ExecIMSStatement(location)
        stmt.set_command("GU")
        stmt.add_option("SEGMENT", "EMPLOYEE")
        stmt.add_option("SSA", "EMP-ID")
        
        result = stmt.to_dict()
        
        assert result["statement_type"] == "EXEC-IMS"
        assert result["ims_command"] == "GU"
        assert result["ims_call_type"] == "GU"
        assert result["ims_options"]["SEGMENT"] == "EMPLOYEE"
        assert result["ims_options"]["SSA"] == "EMP-ID"
        assert "location" in result


class TestProgramSQLDetection:
    """Test SQL detection in CobolProgram."""
    
    def test_has_sql_true(self):
        """Test has_sql returns True when SQL statements exist."""
        location = SourceLocation(1, 1)
        program = CobolProgram("TEST-PROG", location)
        
        # Create PROCEDURE division with SQL statement
        proc_div = CobolDivision("PROCEDURE", location)
        para = CobolParagraph("MAIN", location)
        
        sql_stmt = ExecSQLStatement(location)
        sql_stmt.set_sql_text("SELECT * FROM EMPLOYEE")
        para.add_statement(sql_stmt)
        proc_div.add_paragraph(para)
        program.add_division(proc_div)
        
        assert program.has_sql() is True
    
    def test_has_sql_false(self):
        """Test has_sql returns False when no SQL statements exist."""
        location = SourceLocation(1, 1)
        program = CobolProgram("TEST-PROG", location)
        
        # Create PROCEDURE division without SQL statement
        proc_div = CobolDivision("PROCEDURE", location)
        program.add_division(proc_div)
        
        assert program.has_sql() is False
    
    def test_get_sql_statements(self):
        """Test get_sql_statements returns all SQL statements."""
        location = SourceLocation(1, 1)
        program = CobolProgram("TEST-PROG", location)
        
        # Create PROCEDURE division with multiple SQL statements
        proc_div = CobolDivision("PROCEDURE", location)
        para = CobolParagraph("MAIN", location)
        
        sql_stmt1 = ExecSQLStatement(SourceLocation(10, 5))
        sql_stmt1.set_sql_text("SELECT * FROM EMPLOYEE")
        para.add_statement(sql_stmt1)
        
        sql_stmt2 = ExecSQLStatement(SourceLocation(15, 5))
        sql_stmt2.set_sql_text("INSERT INTO EMPLOYEE VALUES (1, 'John')")
        para.add_statement(sql_stmt2)
        
        proc_div.add_paragraph(para)
        program.add_division(proc_div)
        
        sql_stmts = program.get_sql_statements()
        assert len(sql_stmts) == 2
        assert sql_stmts[0].sql_type == "SELECT"
        assert sql_stmts[1].sql_type == "INSERT"


class TestProgramCICSDetection:
    """Test CICS detection in CobolProgram."""
    
    def test_has_cics_true(self):
        """Test has_cics returns True when CICS statements exist."""
        location = SourceLocation(1, 1)
        program = CobolProgram("TEST-PROG", location)
        
        # Create PROCEDURE division with CICS statement
        proc_div = CobolDivision("PROCEDURE", location)
        para = CobolParagraph("MAIN", location)
        
        cics_stmt = ExecCICSStatement(location)
        cics_stmt.set_command("RECEIVE")
        cics_stmt.add_option("INTO", "WS-COMMAREA")
        para.add_statement(cics_stmt)
        proc_div.add_paragraph(para)
        program.add_division(proc_div)
        
        assert program.has_cics() is True
    
    def test_has_cics_false(self):
        """Test has_cics returns False when no CICS statements exist."""
        location = SourceLocation(1, 1)
        program = CobolProgram("TEST-PROG", location)
        
        # Create PROCEDURE division without CICS statement
        proc_div = CobolDivision("PROCEDURE", location)
        program.add_division(proc_div)
        
        assert program.has_cics() is False
    
    def test_get_cics_statements(self):
        """Test get_cics_statements returns all CICS statements."""
        location = SourceLocation(1, 1)
        program = CobolProgram("TEST-PROG", location)
        
        # Create PROCEDURE division with multiple CICS statements
        proc_div = CobolDivision("PROCEDURE", location)
        para = CobolParagraph("MAIN", location)
        
        cics_stmt1 = ExecCICSStatement(SourceLocation(10, 5))
        cics_stmt1.set_command("RECEIVE")
        para.add_statement(cics_stmt1)
        
        cics_stmt2 = ExecCICSStatement(SourceLocation(15, 5))
        cics_stmt2.set_command("SEND")
        para.add_statement(cics_stmt2)
        
        proc_div.add_paragraph(para)
        program.add_division(proc_div)
        
        cics_stmts = program.get_cics_statements()
        assert len(cics_stmts) == 2
        assert cics_stmts[0].cics_command == "RECEIVE"
        assert cics_stmts[1].cics_command == "SEND"


class TestProgramIMSDetection:
    """Test IMS detection in CobolProgram through CALL statements."""
    
    def test_uses_ims_interface_true(self):
        """Test uses_ims_interface returns True when IMS interface CALL exists."""
        location = SourceLocation(1, 1)
        program = CobolProgram("TEST-PROG", location)
        
        # Create PROCEDURE division with IMS interface CALL
        proc_div = CobolDivision("PROCEDURE", location)
        para = CobolParagraph("MAIN", location)
        
        # Create a CALL statement to CBLTDLI
        call_stmt = CobolStatement("CALL", location)
        call_stmt.operands = ["'CBLTDLI'", "DLI-FUNCTION", "IO-PCB-MASK", "IO-AREA"]
        para.add_statement(call_stmt)
        proc_div.add_paragraph(para)
        program.add_division(proc_div)
        
        assert program.uses_ims_interface() is True
    
    def test_uses_ims_interface_false(self):
        """Test uses_ims_interface returns False when no IMS interface CALL exists."""
        location = SourceLocation(1, 1)
        program = CobolProgram("TEST-PROG", location)
        
        # Create PROCEDURE division without IMS interface CALL
        proc_div = CobolDivision("PROCEDURE", location)
        program.add_division(proc_div)
        
        assert program.uses_ims_interface() is False
    
    def test_get_ims_interface_calls(self):
        """Test get_ims_interface_calls returns all IMS interface CALL statements."""
        location = SourceLocation(1, 1)
        program = CobolProgram("TEST-PROG", location)
        
        # Create PROCEDURE division with multiple IMS interface CALLs
        proc_div = CobolDivision("PROCEDURE", location)
        para = CobolParagraph("MAIN", location)
        
        # CBLTDLI call
        call_stmt1 = CobolStatement("CALL", SourceLocation(10, 5))
        call_stmt1.operands = ["'CBLTDLI'", "DLI-FUNCTION", "IO-PCB-MASK"]
        para.add_statement(call_stmt1)
        
        # AIBTDLI call
        call_stmt2 = CobolStatement("CALL", SourceLocation(15, 5))
        call_stmt2.operands = ["'AIBTDLI'", "DLI-FUNCTION", "IO-PCB-MASK"]
        para.add_statement(call_stmt2)
        
        proc_div.add_paragraph(para)
        program.add_division(proc_div)
        
        ims_calls = program.get_ims_interface_calls()
        assert len(ims_calls) == 2
        assert ims_calls[0].statement_type == "CALL"
        assert ims_calls[1].statement_type == "CALL"


class TestProgramMixedDetection:
    """Test detection of mixed SQL, CICS, and IMS statements."""
    
    def test_program_with_all_three_types(self):
        """Test program containing SQL, CICS, and IMS interface calls."""
        location = SourceLocation(1, 1)
        program = CobolProgram("TEST-PROG", location)
        
        # Create PROCEDURE division with all three types
        proc_div = CobolDivision("PROCEDURE", location)
        para = CobolParagraph("MAIN", location)
        
        # Add SQL statement
        sql_stmt = ExecSQLStatement(SourceLocation(10, 5))
        sql_stmt.set_sql_text("SELECT * FROM EMPLOYEE")
        para.add_statement(sql_stmt)
        
        # Add CICS statement
        cics_stmt = ExecCICSStatement(SourceLocation(15, 5))
        cics_stmt.set_command("RECEIVE")
        para.add_statement(cics_stmt)
        
        # Add IMS interface CALL
        ims_call = CobolStatement("CALL", SourceLocation(20, 5))
        ims_call.operands = ["'CBLTDLI'", "DLI-FUNCTION", "IO-PCB-MASK"]
        para.add_statement(ims_call)
        
        proc_div.add_paragraph(para)
        program.add_division(proc_div)
        
        # Verify all three are detected
        assert program.has_sql() is True
        assert program.has_cics() is True
        assert program.uses_ims_interface() is True
        
        assert len(program.get_sql_statements()) == 1
        assert len(program.get_cics_statements()) == 1
        assert len(program.get_ims_interface_calls()) == 1
    
    def test_program_with_only_sql(self):
        """Test program containing only SQL statements."""
        location = SourceLocation(1, 1)
        program = CobolProgram("TEST-PROG", location)
        
        proc_div = CobolDivision("PROCEDURE", location)
        para = CobolParagraph("MAIN", location)
        
        sql_stmt = ExecSQLStatement(SourceLocation(10, 5))
        sql_stmt.set_sql_text("SELECT * FROM EMPLOYEE")
        para.add_statement(sql_stmt)
        
        proc_div.add_paragraph(para)
        program.add_division(proc_div)
        
        assert program.has_sql() is True
        assert program.has_cics() is False
        assert program.has_ims() is False


class TestIBMEnterpriseIMSSupport:
    """Test IMS support in IBMEnterpriseCobol dialect."""
    
    def test_ims_commands_defined(self):
        """Test that IMS commands are defined in dialect."""
        dialect = IBMEnterpriseCobol()
        
        # Test some key IMS commands
        assert "GU" in dialect.IMS_COMMANDS
        assert "GN" in dialect.IMS_COMMANDS
        assert "GNP" in dialect.IMS_COMMANDS
        assert "ISRT" in dialect.IMS_COMMANDS
        assert "REPL" in dialect.IMS_COMMANDS
        assert "DLET" in dialect.IMS_COMMANDS
        
        assert len(dialect.IMS_COMMANDS) >= 12
    
    def test_is_ims_command_true_cases(self):
        """Test is_ims_command for true cases."""
        dialect = IBMEnterpriseCobol()
        
        commands = ["GU", "GN", "GNP", "ISRT", "REPL", "DLET"]
        
        for cmd in commands:
            assert dialect.is_ims_command(cmd) is True
            assert dialect.is_ims_command(cmd.lower()) is True  # Case insensitive
    
    def test_is_ims_command_false_cases(self):
        """Test is_ims_command for false cases."""
        dialect = IBMEnterpriseCobol()
        
        non_commands = ["CUSTOM-COMMAND", "INVALID", "NOT-AN-IMS-CMD"]
        
        for cmd in non_commands:
            assert dialect.is_ims_command(cmd) is False
    
    def test_parse_exec_ims_basic(self):
        """Test parsing basic EXEC IMS statement."""
        dialect = IBMEnterpriseCobol()
        location = SourceLocation(25, 8)
        
        ims_text = "GU SEGMENT(EMPLOYEE) SSA(EMP-ID)"
        stmt = dialect.parse_exec_ims(ims_text, location)
        
        assert stmt.statement_type == "EXEC-IMS"
        assert stmt.location == location
        assert stmt.ims_command == "GU"
        assert stmt.ims_call_type == "GU"
        assert "SEGMENT" in stmt.ims_options
        assert "SSA" in stmt.ims_options
    
    def test_parse_exec_ims_no_options(self):
        """Test parsing EXEC IMS with command only."""
        dialect = IBMEnterpriseCobol()
        location = SourceLocation(25, 8)
        
        ims_text = "CHKP"
        stmt = dialect.parse_exec_ims(ims_text, location)
        
        assert stmt.ims_command == "CHKP"
        assert len(stmt.ims_options) == 0
    
    def test_exec_ims_in_supported_features(self):
        """Test that exec_ims is in supported features."""
        dialect = IBMEnterpriseCobol()
        
        assert "exec_ims" in dialect.supported_features
    
    def test_dialect_info_includes_ims_commands(self):
        """Test that dialect info includes IMS commands count."""
        dialect = IBMEnterpriseCobol()
        
        info = dialect.get_dialect_info()
        
        assert "ims_commands" in info
        assert info["ims_commands"] == len(dialect.IMS_COMMANDS)
        assert info["ims_commands"] >= 12


class TestDetectionIntegration:
    """Integration tests for detection capabilities."""
    
    def test_program_detection_workflow(self):
        """Test complete workflow of detecting middleware usage."""
        location = SourceLocation(1, 1)
        program = CobolProgram("INTEGRATED-PROG", location)
        
        # Create PROCEDURE division
        proc_div = CobolDivision("PROCEDURE", location)
        para = CobolParagraph("MAIN", location)
        
        # Add various statements
        sql_stmt = ExecSQLStatement(SourceLocation(10, 5))
        sql_stmt.set_sql_text("UPDATE EMPLOYEE SET SALARY = 50000")
        para.add_statement(sql_stmt)
        
        cics_stmt = ExecCICSStatement(SourceLocation(15, 5))
        cics_stmt.set_command("SEND")
        para.add_statement(cics_stmt)
        
        ims_call = CobolStatement("CALL", SourceLocation(20, 5))
        ims_call.operands = ["'CEETDLI'", "DLI-FUNCTION", "IO-PCB-MASK"]
        para.add_statement(ims_call)
        
        proc_div.add_paragraph(para)
        program.add_division(proc_div)
        
        # Verify detection
        assert program.has_sql() is True
        assert program.has_cics() is True
        assert program.uses_ims_interface() is True
        
        # Verify retrieval
        sql_stmts = program.get_sql_statements()
        cics_stmts = program.get_cics_statements()
        ims_calls = program.get_ims_interface_calls()
        
        assert len(sql_stmts) == 1
        assert len(cics_stmts) == 1
        assert len(ims_calls) == 1
        
        # Verify statement details
        assert sql_stmts[0].sql_type == "UPDATE"
        assert cics_stmts[0].cics_command == "SEND"
        assert ims_calls[0].statement_type == "CALL"
