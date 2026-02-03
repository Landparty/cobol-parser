"""Unit tests for ENTRY statement parsing."""

import pytest
from cobolparser.parser import CobolParser
from cobolparser.models.statements import EntryStatement


def find_entry_statement(proc_div):
    """Helper function to find ENTRY statement in new architecture."""
    # Check paragraphs directly in procedure division
    for para in proc_div.paragraphs:
        for stmt in para.statements:
            if isinstance(stmt, EntryStatement):
                return stmt
    
    # Also check sections (for completeness)
    for section in proc_div.sections:
        # Check statements in paragraph (new architecture)
        for para in section.paragraphs:
            for stmt in para.statements:
                if isinstance(stmt, EntryStatement):
                    return stmt
        # Check direct children (old architecture / already parsed)
        for child in section.children:
            if isinstance(child, EntryStatement):
                return child
    return None


class TestEntryStatement:
    """Test ENTRY statement parsing."""
    
    def test_basic_entry_statement(self):
        """Test basic ENTRY statement without parameters."""
        parser = CobolParser(free_form=True)
        source = """IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
PROCEDURE DIVISION.
    ENTRY 'MAINENTRY'.
    STOP RUN.
"""
        
        result = parser.parse(source)
        assert result.ast is not None
        
        # Find the ENTRY statement
        proc_div = result.ast.get_division("PROCEDURE")
        assert proc_div is not None
        
        entry_stmt = find_entry_statement(proc_div)
        
        assert entry_stmt is not None
        assert entry_stmt.entry_name == 'MAINENTRY'
        assert len(entry_stmt.using_parameters) == 0
    
    def test_entry_with_using_clause(self):
        """Test ENTRY statement with USING clause."""
        parser = CobolParser(free_form=True)
        source = """IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01  PARAM1 PIC X(10).
01  PARAM2 PIC X(10).
PROCEDURE DIVISION.
    ENTRY 'DLITCBL' USING PARAM1 PARAM2.
    STOP RUN.
"""
        
        result = parser.parse(source)
        assert result.ast is not None
        
        # Find the ENTRY statement
        proc_div = result.ast.get_division("PROCEDURE")
        assert proc_div is not None
        
        entry_stmt = find_entry_statement(proc_div)
        
        assert entry_stmt is not None
        assert entry_stmt.entry_name == 'DLITCBL'
        assert len(entry_stmt.using_parameters) == 2
        assert entry_stmt.using_parameters == ['PARAM1', 'PARAM2']
    
    def test_entry_with_multiple_parameters(self):
        """Test ENTRY statement with many parameters (IMS style)."""
        parser = CobolParser(free_form=True)
        source = """IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
PROCEDURE DIVISION.
    ENTRY 'DLITCBL' USING 
        LKPCB-IO
        LKPCB-ALT
        LKPCB-BPP100MA
        LKPCB-ENF100MA
        LKPCB-ENF200MA.
    STOP RUN.
"""
        
        result = parser.parse(source)
        assert result.ast is not None
        
        # Find the ENTRY statement
        proc_div = result.ast.get_division("PROCEDURE")
        assert proc_div is not None
        
        entry_stmt = find_entry_statement(proc_div)
        
        assert entry_stmt is not None
        assert entry_stmt.entry_name == 'DLITCBL'
        assert len(entry_stmt.using_parameters) == 5
        assert 'LKPCB-IO' in entry_stmt.using_parameters
        assert 'LKPCB-ALT' in entry_stmt.using_parameters
        assert 'LKPCB-ENF200MA' in entry_stmt.using_parameters
    
    def test_entry_to_dict(self):
        """Test ENTRY statement to_dict() method."""
        parser = CobolParser(free_form=True)
        source = """IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
PROCEDURE DIVISION.
    ENTRY 'TESTENTRY' USING PARAM1 PARAM2.
    STOP RUN.
"""
        
        result = parser.parse(source)
        assert result.ast is not None
        
        # Find the ENTRY statement
        proc_div = result.ast.get_division("PROCEDURE")
        entry_stmt = find_entry_statement(proc_div)
        
        assert entry_stmt is not None
        
        # Test to_dict()
        entry_dict = entry_stmt.to_dict()
        assert entry_dict['statement_type'] == 'ENTRY'
        assert entry_dict['entry_name'] == 'TESTENTRY'
        assert entry_dict['using_parameters'] == ['PARAM1', 'PARAM2']
        assert 'location' in entry_dict
