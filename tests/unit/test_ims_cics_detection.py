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

from cobolparser.dialects.ibm_enterprise import IBMEnterpriseCobol
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.program import CobolDivision, CobolParagraph, CobolProgram
from cobolparser.models.statements import CobolStatement


class TestProgramSQLDetection:
    """Test SQL detection in CobolProgram."""

    def test_has_sql_false(self):
        """Test has_sql returns False when no SQL statements exist."""
        location = SourceLocation(1, 1)
        program = CobolProgram("TEST-PROG", location)

        # Create PROCEDURE division without SQL statement
        proc_div = CobolDivision("PROCEDURE", location)
        program.add_division(proc_div)

        assert program.has_sql() is False


class TestProgramCICSDetection:
    """Test CICS detection in CobolProgram."""

    def test_has_cics_false(self):
        """Test has_cics returns False when no CICS statements exist."""
        location = SourceLocation(1, 1)
        program = CobolProgram("TEST-PROG", location)

        # Create PROCEDURE division without CICS statement
        proc_div = CobolDivision("PROCEDURE", location)
        program.add_division(proc_div)

        assert program.has_cics() is False


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


class TestIBMEnterpriseIMSSupport:
    """Test IMS support in IBMEnterpriseCobol dialect."""

    def test_ims_commands_defined(self):
        """Test that IMS commands are defined in dialect."""
        dialect = IBMEnterpriseCobol

        # Test some key IMS commands
        assert "GU" in dialect.IMS_COMMANDS
        assert "GN" in dialect.IMS_COMMANDS
        assert "GNP" in dialect.IMS_COMMANDS
        assert "ISRT" in dialect.IMS_COMMANDS
        assert "REPL" in dialect.IMS_COMMANDS
        assert "DLET" in dialect.IMS_COMMANDS

        assert len(dialect.IMS_COMMANDS) >= 12


class TestDLITCBLEntryPoint:
    """Tests for ENTRY 'DLITCBL' detection as an IMS transaction entry point."""

    _IMS_SOURCE = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. IMSBATCH.
PROCEDURE DIVISION.
    ENTRY 'DLITCBL' USING IO-PCB
                          ALT-PCB
                          DB-PCB.
    STOP RUN.
"""

    def _parse(self, source: str):
        from cobolparser import CobolParser

        return CobolParser(free_form=True).parse(source)

    def test_is_ims_dlitcbl_program_true(self):
        result = self._parse(self._IMS_SOURCE)
        assert result.ast is not None
        assert result.ast.is_ims_dlitcbl_program() is True

    def test_is_ims_dlitcbl_program_false(self):
        source = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. NOTIMS.
PROCEDURE DIVISION.
    ENTRY 'OTHERNAME' USING PARAM1.
    STOP RUN.
"""
        result = self._parse(source)
        assert result.ast is not None
        assert result.ast.is_ims_dlitcbl_program() is False

    def test_has_ims_includes_dlitcbl(self):
        result = self._parse(self._IMS_SOURCE)
        assert result.ast is not None
        assert result.ast.has_ims() is True

    def test_get_entry_statements(self):
        from cobolparser.models.statements import EntryStatement

        result = self._parse(self._IMS_SOURCE)
        assert result.ast is not None
        entries = result.ast.get_entry_statements()
        assert len(entries) == 1
        stmt = entries[0]
        assert isinstance(stmt, EntryStatement)
        assert stmt.entry_name == "DLITCBL"
        assert stmt.using_parameters == ["IO-PCB", "ALT-PCB", "DB-PCB"]

    def test_ims_segment_analyzer_entry_points(self):
        from cobolparser.analysis.ims_segment_analyzer import (
            IMSEntryPoint,
            IMSSegmentAnalyzer,
        )

        result = self._parse(self._IMS_SOURCE)
        assert result.ast is not None
        points = IMSSegmentAnalyzer().get_entry_points(result.ast)
        assert len(points) == 1
        ep = points[0]
        assert isinstance(ep, IMSEntryPoint)
        assert ep.entry_name == "DLITCBL"
        assert ep.pcb_names == ["IO-PCB", "ALT-PCB", "DB-PCB"]

    def test_dlitcbl_case_insensitive(self):
        source = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. IMSLOWER.
PROCEDURE DIVISION.
    ENTRY 'dlitcbl' USING IO-PCB DB-PCB.
    STOP RUN.
"""
        result = self._parse(source)
        assert result.ast is not None
        assert result.ast.is_ims_dlitcbl_program() is True
        assert result.ast.has_ims() is True

    def test_ims_entry_point_exported_from_analysis(self):
        from cobolparser.analysis import IMSEntryPoint

        assert IMSEntryPoint is not None
