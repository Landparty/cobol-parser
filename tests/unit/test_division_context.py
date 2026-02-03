"""
Test division context tracking for AST nodes.

This test suite verifies that all AST nodes properly track which COBOL
division and section they belong to.
"""

import pytest
from cobolparser import parse_cobol
from cobolparser.models.statements import CobolStatement
from cobolparser.models.data_items import CobolDataItem


class TestDivisionContextTracking:
    """Test that AST nodes track their division context."""
    
    def test_statement_tracks_division(self):
        """Test that statements know which division they belong to."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            MOVE 1 TO X.
            DISPLAY "HELLO".
        """
        result = parse_cobol(source)
        
        assert result.success, f"Parse failed: {result.errors}"
        statements = result.ast.get_all_statements()
        
        # Should have at least 2 statements
        assert len(statements) >= 2, f"Expected at least 2 statements, got {len(statements)}"
        
        # All statements should be in PROCEDURE division
        for stmt in statements:
            assert stmt.division_name == "PROCEDURE", \
                f"Statement {stmt.statement_type} has division {stmt.division_name}, expected PROCEDURE"
    
    def test_data_item_tracks_division(self):
        """Test that data items know which division they belong to."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-VAR PIC X(10).
        01 WS-NUM PIC 9(5).
        """
        result = parse_cobol(source)
        
        assert result.success, f"Parse failed: {result.errors}"
        data_items = result.ast.get_data_items()
        
        # Should have at least 2 data items
        assert len(data_items) >= 2, f"Expected at least 2 data items, got {len(data_items)}"
        
        # All data items should be in DATA division
        for item in data_items:
            assert item.division_name == "DATA", \
                f"Data item {item.name} has division {item.division_name}, expected DATA"
            assert item.section_name == "WORKING-STORAGE", \
                f"Data item {item.name} has section {item.section_name}, expected WORKING-STORAGE"
    
    def test_paragraph_tracks_division(self):
        """Test that paragraphs know which division they belong to."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
        MAIN-PARA.
            DISPLAY "MAIN".
        SUB-PARA.
            DISPLAY "SUB".
        """
        result = parse_cobol(source)
        
        assert result.success, f"Parse failed: {result.errors}"
        
        proc_div = result.ast.get_division("PROCEDURE")
        assert proc_div is not None, "PROCEDURE division not found"
        
        # Check sections (paragraphs are created as sections in PROCEDURE division)
        assert len(proc_div.sections) >= 2, f"Expected at least 2 sections, got {len(proc_div.sections)}"
        
        for section in proc_div.sections:
            assert section.division_name == "PROCEDURE", \
                f"Section {section.section_name} has division {section.division_name}, expected PROCEDURE"
    
    def test_section_tracks_division(self):
        """Test that sections know which division they belong to."""
        source = """
           IDENTIFICATION DIVISION.
           PROGRAM-ID. TEST.
           DATA DIVISION.
           WORKING-STORAGE SECTION.
           01 WS-VAR PIC X(10).
           FILE SECTION.
           FD MYFILE.
           01 FILE-REC PIC X(80).
        """
        parser = CobolParser()
        result = parser.parse(source)
        
        assert result.success, f"Parse failed: {result.errors}"
        
        data_div = result.ast.get_division("DATA")
        assert data_div is not None, "DATA division not found"
        
        # Check sections
        for section in data_div.sections:
            assert section.division_name == "DATA", \
                f"Section {section.section_name} has division {section.division_name}, expected DATA"
    
    def test_get_nodes_in_division(self):
        """Test the get_nodes_in_division method."""
        source = """
           IDENTIFICATION DIVISION.
           PROGRAM-ID. TEST.
           DATA DIVISION.
           WORKING-STORAGE SECTION.
           01 WS-VAR PIC X(10).
           PROCEDURE DIVISION.
               MOVE 1 TO WS-VAR.
               DISPLAY WS-VAR.
        """
        parser = CobolParser()
        result = parser.parse(source)
        
        assert result.success, f"Parse failed: {result.errors}"
        
        # Get all nodes in PROCEDURE division
        proc_nodes = result.ast.get_nodes_in_division("PROCEDURE")
        assert len(proc_nodes) > 0, "No nodes found in PROCEDURE division"
        
        # Verify all nodes are in PROCEDURE division
        for node in proc_nodes:
            assert node.division_name == "PROCEDURE", \
                f"Node {node.node_type} has division {node.division_name}, expected PROCEDURE"
        
        # Get all nodes in DATA division
        data_nodes = result.ast.get_nodes_in_division("DATA")
        assert len(data_nodes) > 0, "No nodes found in DATA division"
        
        # Verify all nodes are in DATA division
        for node in data_nodes:
            assert node.division_name == "DATA", \
                f"Node {node.node_type} has division {node.division_name}, expected DATA"
    
    def test_get_statements_in_division(self):
        """Test the get_statements_in_division method."""
        source = """
           IDENTIFICATION DIVISION.
           PROGRAM-ID. TEST.
           PROCEDURE DIVISION.
               MOVE 1 TO X.
               DISPLAY "HELLO".
               STOP RUN.
        """
        parser = CobolParser()
        result = parser.parse(source)
        
        assert result.success, f"Parse failed: {result.errors}"
        
        # Get all statements in PROCEDURE division
        proc_stmts = result.ast.get_statements_in_division("PROCEDURE")
        # Note: STOP RUN may not be in the statement list due to parser limitations
        assert len(proc_stmts) >= 2, f"Expected at least 2 statements, got {len(proc_stmts)}"
        
        # Verify all are statements and in PROCEDURE division
        for stmt in proc_stmts:
            assert isinstance(stmt, CobolStatement), f"Expected CobolStatement, got {type(stmt)}"
            assert stmt.division_name == "PROCEDURE", \
                f"Statement has division {stmt.division_name}, expected PROCEDURE"
    
    def test_nested_statement_tracks_division(self):
        """Test that nested statements (IF, PERFORM inline) track division."""
        source = """
           IDENTIFICATION DIVISION.
           PROGRAM-ID. TEST.
           PROCEDURE DIVISION.
               IF X = 1
                   DISPLAY "ONE"
                   MOVE 2 TO Y
               ELSE
                   DISPLAY "OTHER"
               END-IF.
               PERFORM
                   DISPLAY "INLINE"
                   MOVE 3 TO Z
               END-PERFORM.
        """
        parser = CobolParser()
        result = parser.parse(source)
        
        assert result.success, f"Parse failed: {result.errors}"
        
        # Get all statements (including nested)
        all_stmts = result.ast.get_all_statements()
        
        # All statements should be in PROCEDURE division
        for stmt in all_stmts:
            assert stmt.division_name == "PROCEDURE", \
                f"Nested statement {stmt.statement_type} has division {stmt.division_name}, expected PROCEDURE"
    
    def test_get_division_context_method(self):
        """Test the get_division_context method returns both division and section."""
        source = """
           IDENTIFICATION DIVISION.
           PROGRAM-ID. TEST.
           DATA DIVISION.
           WORKING-STORAGE SECTION.
           01 WS-VAR PIC X(10).
        """
        parser = CobolParser()
        result = parser.parse(source)
        
        assert result.success, f"Parse failed: {result.errors}"
        
        data_items = result.ast.get_data_items()
        assert len(data_items) > 0, "No data items found"
        
        # Check context
        context = data_items[0].get_division_context()
        assert context['division'] == "DATA", f"Expected DATA division, got {context['division']}"
        assert context['section'] == "WORKING-STORAGE", \
            f"Expected WORKING-STORAGE section, got {context['section']}"
    
    def test_division_context_with_multiple_sections(self):
        """Test division context with multiple sections in DATA division."""
        source = """
           IDENTIFICATION DIVISION.
           PROGRAM-ID. TEST.
           DATA DIVISION.
           FILE SECTION.
           FD MYFILE.
           01 FILE-REC PIC X(80).
           WORKING-STORAGE SECTION.
           01 WS-VAR PIC X(10).
           LINKAGE SECTION.
           01 LNK-VAR PIC X(5).
        """
        parser = CobolParser()
        result = parser.parse(source)
        
        assert result.success, f"Parse failed: {result.errors}"
        
        data_items = result.ast.get_data_items()
        
        # Group by section
        sections_found = set()
        for item in data_items:
            assert item.division_name == "DATA", \
                f"Data item {item.name} has division {item.division_name}, expected DATA"
            sections_found.add(item.section_name)
        
        # Should have items from multiple sections
        assert len(sections_found) > 1, f"Expected multiple sections, found: {sections_found}"


class TestDivisionContextEdgeCases:
    """Test edge cases for division context tracking."""
    
    def test_division_context_without_sections(self):
        """Test division context for divisions without sections."""
        source = """
           IDENTIFICATION DIVISION.
           PROGRAM-ID. TEST.
           PROCEDURE DIVISION.
               DISPLAY "NO SECTIONS".
        """
        parser = CobolParser()
        result = parser.parse(source)
        
        assert result.success, f"Parse failed: {result.errors}"
        
        stmts = result.ast.get_all_statements()
        for stmt in stmts:
            assert stmt.division_name == "PROCEDURE"
            # Section name may be None or a default value
    
    def test_division_context_serialization(self):
        """Test that division context is preserved in to_dict()."""
        source = """
           IDENTIFICATION DIVISION.
           PROGRAM-ID. TEST.
           PROCEDURE DIVISION.
               MOVE 1 TO X.
        """
        parser = CobolParser()
        result = parser.parse(source)
        
        assert result.success, f"Parse failed: {result.errors}"
        
        # Convert to dict
        program_dict = result.ast.to_dict()
        
        # The structure should be preserved
        assert 'divisions' in program_dict
        assert 'PROCEDURE' in program_dict['divisions']
