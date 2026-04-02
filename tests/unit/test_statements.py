"""
Comprehensive unit tests for cobolparser.models.statements.py module.

This test suite aims for 100% test coverage of all statement and expression
AST node classes, including all methods, properties, and edge cases.
"""

import pytest
from typing import List, Dict, Any

# Import the classes we're testing
from cobolparser.models.statements import (
    CobolStatement, MoveStatement, DisplayStatement, PerformStatement,
    ComputeStatement, CallStatement, SelectStatement, CobolExpression,
    ArithmeticExpression, ConditionalExpression, LogicalExpression,
    FunctionCall
)

# Import base classes for testing
from cobolparser.models.ast_base import SourceLocation, ASTNode


class TestCobolStatement:
    """Test the CobolStatement base class."""
    
    def test_cobol_statement_creation_basic(self):
        """Test basic CobolStatement creation."""
        location = SourceLocation(1, 1)
        stmt = CobolStatement("TEST", location)
        
        assert stmt.statement_type == "TEST"
        assert stmt.node_type == "Statement"
        assert stmt.location == location
        assert stmt.operands == []
        assert isinstance(stmt.operands, list)
    
    def test_add_operand_single(self):
        """Test adding a single operand."""
        location = SourceLocation(1, 1)
        stmt = CobolStatement("MOVE", location)
        
        stmt.add_operand("WS-VARIABLE")
        assert stmt.operands == ["WS-VARIABLE"]
    
    def test_add_operand_multiple(self):
        """Test adding multiple operands."""
        location = SourceLocation(1, 1)
        stmt = CobolStatement("DISPLAY", location)
        
        stmt.add_operand("WS-VAR1")
        stmt.add_operand("WS-VAR2")
        stmt.add_operand("WS-VAR3")
        
        assert stmt.operands == ["WS-VAR1", "WS-VAR2", "WS-VAR3"]
        assert len(stmt.operands) == 3
    
    def test_cobol_statement_to_dict(self):
        """Test CobolStatement to_dict method."""
        location = SourceLocation(5, 10)
        stmt = CobolStatement("COMPUTE", location)
        stmt.add_operand("RESULT")
        
        result = stmt.to_dict()
        
        assert result["node_type"] == "Statement"
        assert result["statement_type"] == "COMPUTE"
        assert result["operands"] == ["RESULT"]
        assert "location" in result
        assert "metadata" in result
        
        # Verify location structure
        assert result["location"]["line"] == 5
        assert result["location"]["column"] == 10
    
    def test_cobol_statement_inheritance(self):
        """Test CobolStatement inheritance from ASTNode."""
        location = SourceLocation(1, 1)
        stmt = CobolStatement("IF", location)
        
        # Should inherit ASTNode methods
        assert isinstance(stmt, ASTNode)
        assert hasattr(stmt, 'children')
        assert hasattr(stmt, 'add_child')
        assert hasattr(stmt, 'location')
        assert hasattr(stmt, '_metadata')


class TestMoveStatement:
    """Test the MoveStatement class."""
    
    def test_move_statement_creation(self):
        """Test MoveStatement creation."""
        location = SourceLocation(10, 5)
        move_stmt = MoveStatement(location)
        
        assert move_stmt.statement_type == "MOVE"
        assert move_stmt.source is None
        assert move_stmt.targets == []
        assert move_stmt.is_corresponding is False
        assert move_stmt.operands == []
    
    def test_set_source(self):
        """Test setting the source operand."""
        location = SourceLocation(1, 1)
        move_stmt = MoveStatement(location)
        
        move_stmt.set_source("WS-SOURCE-VAR")
        
        assert move_stmt.source == "WS-SOURCE-VAR"
        assert "WS-SOURCE-VAR" in move_stmt.operands
        assert move_stmt.operands[0] == "WS-SOURCE-VAR"
    
    def test_set_source_already_in_operands(self):
        """Test setting source when already in operands list."""
        location = SourceLocation(1, 1)
        move_stmt = MoveStatement(location)
        
        # Add to operands first
        move_stmt.add_operand("WS-SOURCE-VAR")
        
        # Then set as source
        move_stmt.set_source("WS-SOURCE-VAR")
        
        assert move_stmt.source == "WS-SOURCE-VAR"
        # Should not duplicate in operands
        assert move_stmt.operands.count("WS-SOURCE-VAR") == 1
    
    def test_add_target_single(self):
        """Test adding a single target."""
        location = SourceLocation(1, 1)
        move_stmt = MoveStatement(location)
        
        move_stmt.add_target("WS-TARGET-VAR")
        
        assert move_stmt.targets == ["WS-TARGET-VAR"]
        assert "WS-TARGET-VAR" in move_stmt.operands
    
    def test_add_target_multiple(self):
        """Test adding multiple targets."""
        location = SourceLocation(1, 1)
        move_stmt = MoveStatement(location)
        
        move_stmt.add_target("WS-TARGET1")
        move_stmt.add_target("WS-TARGET2")
        move_stmt.add_target("WS-TARGET3")
        
        assert move_stmt.targets == ["WS-TARGET1", "WS-TARGET2", "WS-TARGET3"]
        assert len(move_stmt.targets) == 3
        
        # All should be in operands
        assert "WS-TARGET1" in move_stmt.operands
        assert "WS-TARGET2" in move_stmt.operands  
        assert "WS-TARGET3" in move_stmt.operands
    
    def test_add_target_already_in_operands(self):
        """Test adding target when already in operands list."""
        location = SourceLocation(1, 1)
        move_stmt = MoveStatement(location)
        
        # Add to operands first
        move_stmt.add_operand("WS-TARGET-VAR")
        
        # Then add as target
        move_stmt.add_target("WS-TARGET-VAR")
        
        assert "WS-TARGET-VAR" in move_stmt.targets
        # Should not duplicate in operands
        assert move_stmt.operands.count("WS-TARGET-VAR") == 1
    
    def test_set_corresponding_default(self):
        """Test setting CORRESPONDING clause with default value."""
        location = SourceLocation(1, 1)
        move_stmt = MoveStatement(location)
        
        move_stmt.set_corresponding()
        
        assert move_stmt.is_corresponding is True
    
    def test_set_corresponding_explicit_true(self):
        """Test setting CORRESPONDING clause explicitly to True."""
        location = SourceLocation(1, 1)
        move_stmt = MoveStatement(location)
        
        move_stmt.set_corresponding(True)
        
        assert move_stmt.is_corresponding is True
    
    def test_set_corresponding_explicit_false(self):
        """Test setting CORRESPONDING clause explicitly to False."""
        location = SourceLocation(1, 1)
        move_stmt = MoveStatement(location)
        
        # Set to True first
        move_stmt.set_corresponding(True)
        assert move_stmt.is_corresponding is True
        
        # Then set to False
        move_stmt.set_corresponding(False)
        assert move_stmt.is_corresponding is False
    
    def test_move_statement_to_dict(self):
        """Test MoveStatement to_dict method."""
        location = SourceLocation(15, 20)
        move_stmt = MoveStatement(location)
        
        move_stmt.set_source("WS-INPUT")
        move_stmt.add_target("WS-OUTPUT1")
        move_stmt.add_target("WS-OUTPUT2")
        move_stmt.set_corresponding(True)
        
        result = move_stmt.to_dict()
        
        # Check base statement properties
        assert result["node_type"] == "Statement"
        assert result["statement_type"] == "MOVE"
        assert result["operands"] == ["WS-INPUT", "WS-OUTPUT1", "WS-OUTPUT2"]
        
        # Check MOVE-specific properties
        assert result["source"] == "WS-INPUT"
        assert result["targets"] == ["WS-OUTPUT1", "WS-OUTPUT2"]
        assert result["is_corresponding"] is True
        
        # Check location
        assert result["location"]["line"] == 15
        assert result["location"]["column"] == 20
    
    def test_move_statement_complete_workflow(self):
        """Test complete MoveStatement workflow."""
        location = SourceLocation(1, 1)
        move_stmt = MoveStatement(location)
        
        # Build a complete MOVE statement
        move_stmt.set_source("ZEROS")
        move_stmt.add_target("WS-COUNTER")
        move_stmt.add_target("WS-TOTAL")
        move_stmt.set_corresponding(False)
        
        # Verify complete state
        assert move_stmt.source == "ZEROS"
        assert move_stmt.targets == ["WS-COUNTER", "WS-TOTAL"]
        assert move_stmt.is_corresponding is False
        assert len(move_stmt.operands) == 3
        
        # Verify serialization includes everything
        result = move_stmt.to_dict()
        assert result["source"] == "ZEROS"
        assert len(result["targets"]) == 2
        assert result["is_corresponding"] is False


class TestDisplayStatement:
    """Test the DisplayStatement class."""
    
    def test_display_statement_creation(self):
        """Test DisplayStatement creation."""
        location = SourceLocation(20, 8)
        display_stmt = DisplayStatement(location)
        
        assert display_stmt.statement_type == "DISPLAY"
        assert display_stmt.display_items == []
        assert display_stmt.output_device is None
        assert display_stmt.operands == []
    
    def test_add_display_item_single(self):
        """Test adding a single display item."""
        location = SourceLocation(1, 1)
        display_stmt = DisplayStatement(location)
        
        display_stmt.add_display_item("WS-MESSAGE")
        
        assert display_stmt.display_items == ["WS-MESSAGE"]
        assert "WS-MESSAGE" in display_stmt.operands
    
    def test_add_display_item_multiple(self):
        """Test adding multiple display items."""
        location = SourceLocation(1, 1)
        display_stmt = DisplayStatement(location)
        
        display_stmt.add_display_item("WS-HEADER")
        display_stmt.add_display_item("WS-DATA")
        display_stmt.add_display_item("WS-FOOTER")
        
        expected_items = ["WS-HEADER", "WS-DATA", "WS-FOOTER"]
        assert display_stmt.display_items == expected_items
        assert len(display_stmt.display_items) == 3
        
        # All should be in operands
        for item in expected_items:
            assert item in display_stmt.operands
    
    def test_set_output_device(self):
        """Test setting the output device (UPON clause)."""
        location = SourceLocation(1, 1)
        display_stmt = DisplayStatement(location)
        
        display_stmt.set_output_device("CONSOLE")
        
        assert display_stmt.output_device == "CONSOLE"
    
    def test_set_output_device_update(self):
        """Test updating the output device."""
        location = SourceLocation(1, 1)
        display_stmt = DisplayStatement(location)
        
        # Set initial device
        display_stmt.set_output_device("PRINTER")
        assert display_stmt.output_device == "PRINTER"
        
        # Update to different device
        display_stmt.set_output_device("SYSOUT")
        assert display_stmt.output_device == "SYSOUT"
    
    def test_display_statement_to_dict(self):
        """Test DisplayStatement to_dict method."""
        location = SourceLocation(25, 12)
        display_stmt = DisplayStatement(location)
        
        display_stmt.add_display_item("'Hello World'")
        display_stmt.add_display_item("WS-NAME")
        display_stmt.set_output_device("CONSOLE")
        
        result = display_stmt.to_dict()
        
        # Check base statement properties
        assert result["node_type"] == "Statement"
        assert result["statement_type"] == "DISPLAY"
        assert result["operands"] == ["'Hello World'", "WS-NAME"]
        
        # Check DISPLAY-specific properties
        assert result["display_items"] == ["'Hello World'", "WS-NAME"]
        assert result["output_device"] == "CONSOLE"
        
        # Check location
        assert result["location"]["line"] == 25
        assert result["location"]["column"] == 12
    
    def test_display_statement_no_output_device(self):
        """Test DisplayStatement without output device."""
        location = SourceLocation(1, 1)
        display_stmt = DisplayStatement(location)
        
        display_stmt.add_display_item("WS-SIMPLE-MSG")
        
        result = display_stmt.to_dict()
        assert result["display_items"] == ["WS-SIMPLE-MSG"]
        assert result["output_device"] is None


class TestPerformStatement:
    """Test the PerformStatement class."""
    
    def test_perform_statement_creation(self):
        """Test PerformStatement creation."""
        location = SourceLocation(30, 4)
        perform_stmt = PerformStatement(location)
        
        assert perform_stmt.statement_type == "PERFORM"
        assert perform_stmt.target_paragraph is None
        assert perform_stmt.perform_type == "SIMPLE"
        assert perform_stmt.times_count is None
        assert perform_stmt.until_condition is None
        assert perform_stmt.varying_clause is None
    
    def test_set_target_paragraph(self):
        """Test setting the target paragraph."""
        location = SourceLocation(1, 1)
        perform_stmt = PerformStatement(location)
        
        perform_stmt.set_target_paragraph("CALC-TOTALS")
        
        assert perform_stmt.target_paragraph == "CALC-TOTALS"
        assert "CALC-TOTALS" in perform_stmt.operands
        assert perform_stmt.operands[0] == "CALC-TOTALS"
    
    def test_set_target_paragraph_already_in_operands(self):
        """Test setting target paragraph when already in operands."""
        location = SourceLocation(1, 1)
        perform_stmt = PerformStatement(location)
        
        # Add to operands first
        perform_stmt.add_operand("PROCESS-DATA")
        
        # Then set as target paragraph
        perform_stmt.set_target_paragraph("PROCESS-DATA")
        
        assert perform_stmt.target_paragraph == "PROCESS-DATA"
        # Should not duplicate in operands
        assert perform_stmt.operands.count("PROCESS-DATA") == 1
    
    def test_set_times_clause(self):
        """Test setting TIMES clause."""
        location = SourceLocation(1, 1)
        perform_stmt = PerformStatement(location)
        
        perform_stmt.set_times_clause(10)
        
        assert perform_stmt.perform_type == "TIMES"
        assert perform_stmt.times_count == 10
    
    def test_set_until_clause(self):
        """Test setting UNTIL clause."""
        location = SourceLocation(1, 1)
        perform_stmt = PerformStatement(location)
        
        # Create a mock condition expression
        condition_location = SourceLocation(1, 20)
        condition = ConditionalExpression("=", condition_location)
        condition.set_left_operand("WS-COUNTER")
        condition.set_right_operand("100")
        
        perform_stmt.set_until_clause(condition)
        
        assert perform_stmt.perform_type == "UNTIL"
        assert perform_stmt.until_condition == condition
        assert condition in perform_stmt.children
    
    def test_set_varying_clause(self):
        """Test setting VARYING clause."""
        location = SourceLocation(1, 1)
        perform_stmt = PerformStatement(location)
        
        # Create condition for VARYING
        condition_location = SourceLocation(1, 50)
        condition = ConditionalExpression(">", condition_location)
        condition.set_left_operand("I")
        condition.set_right_operand("10")
        
        perform_stmt.set_varying_clause("I", "1", "1", condition)
        
        assert perform_stmt.perform_type == "VARYING"
        assert perform_stmt.varying_clause is not None
        assert perform_stmt.varying_clause["variable"] == "I"
        assert perform_stmt.varying_clause["from_value"] == "1"
        assert perform_stmt.varying_clause["by_value"] == "1"
        assert perform_stmt.until_condition == condition
        assert condition in perform_stmt.children
    
    def test_perform_statement_to_dict_simple(self):
        """Test PerformStatement to_dict for simple PERFORM."""
        location = SourceLocation(35, 8)
        perform_stmt = PerformStatement(location)
        
        perform_stmt.set_target_paragraph("CALCULATE-INTEREST")
        
        result = perform_stmt.to_dict()
        
        # Check base statement properties
        assert result["node_type"] == "Statement"
        assert result["statement_type"] == "PERFORM"
        assert result["operands"] == ["CALCULATE-INTEREST"]
        
        # Check PERFORM-specific properties
        assert result["target_paragraph"] == "CALCULATE-INTEREST"
        assert result["perform_type"] == "SIMPLE"
        assert result["times_count"] is None
        assert result["until_condition"] is None
        assert result["varying_clause"] is None
    
    def test_perform_statement_to_dict_times(self):
        """Test PerformStatement to_dict for TIMES variant."""
        location = SourceLocation(1, 1)
        perform_stmt = PerformStatement(location)
        
        perform_stmt.set_target_paragraph("READ-RECORD")
        perform_stmt.set_times_clause(5)
        
        result = perform_stmt.to_dict()
        
        assert result["perform_type"] == "TIMES"
        assert result["times_count"] == 5
        assert result["target_paragraph"] == "READ-RECORD"
    
    def test_perform_statement_to_dict_until(self):
        """Test PerformStatement to_dict for UNTIL variant."""
        location = SourceLocation(1, 1)
        perform_stmt = PerformStatement(location)
        
        # Create condition
        condition = ConditionalExpression("=", SourceLocation(1, 30))
        condition.set_left_operand("WS-EOF")
        condition.set_right_operand("'Y'")
        
        perform_stmt.set_target_paragraph("PROCESS-RECORD")
        perform_stmt.set_until_clause(condition)
        
        result = perform_stmt.to_dict()
        
        assert result["perform_type"] == "UNTIL"
        assert result["until_condition"] is not None
        assert result["until_condition"]["operator"] == "="
        assert result["until_condition"]["left_operand"] == "WS-EOF"
        assert result["until_condition"]["right_operand"] == "'Y'"
    
    def test_perform_statement_to_dict_varying(self):
        """Test PerformStatement to_dict for VARYING variant."""
        location = SourceLocation(1, 1)
        perform_stmt = PerformStatement(location)
        
        # Create condition
        condition = ConditionalExpression(">", SourceLocation(1, 40))
        condition.set_left_operand("IDX")
        condition.set_right_operand("MAX-ITEMS")
        
        perform_stmt.set_target_paragraph("PROCESS-ARRAY")
        perform_stmt.set_varying_clause("IDX", "1", "1", condition)
        
        result = perform_stmt.to_dict()
        
        assert result["perform_type"] == "VARYING"
        assert result["varying_clause"]["variable"] == "IDX"
        assert result["varying_clause"]["from_value"] == "1"
        assert result["varying_clause"]["by_value"] == "1"
        assert result["until_condition"] is not None
    
    # ============================================================================
    # Phase 3.1: NEW TESTS - Model Extensions for test_timing and variable TIMES
    # ============================================================================
    
    def test_perform_statement_test_timing_default(self):
        """Test that test_timing defaults to 'BEFORE'."""
        location = SourceLocation(1, 1)
        perform_stmt = PerformStatement(location)
        
        # Default should be BEFORE
        assert perform_stmt.test_timing == "BEFORE"
    
    def test_perform_statement_test_timing_after(self):
        """Test setting test_timing to AFTER."""
        location = SourceLocation(1, 1)
        perform_stmt = PerformStatement(location)
        
        perform_stmt.set_test_timing("AFTER")
        
        assert perform_stmt.test_timing == "AFTER"
    
    def test_perform_statement_test_timing_before(self):
        """Test explicitly setting test_timing to BEFORE."""
        location = SourceLocation(1, 1)
        perform_stmt = PerformStatement(location)
        
        # Change from default
        perform_stmt.set_test_timing("AFTER")
        assert perform_stmt.test_timing == "AFTER"
        
        # Change back
        perform_stmt.set_test_timing("BEFORE")
        assert perform_stmt.test_timing == "BEFORE"
    
    def test_perform_statement_test_timing_case_insensitive(self):
        """Test that set_test_timing is case-insensitive."""
        location = SourceLocation(1, 1)
        perform_stmt = PerformStatement(location)
        
        # Set with lowercase
        perform_stmt.set_test_timing("before")
        assert perform_stmt.test_timing == "BEFORE"
        
        # Set with mixed case
        perform_stmt.set_test_timing("AfTeR")
        assert perform_stmt.test_timing == "AFTER"
    
    def test_perform_statement_test_timing_invalid_value(self):
        """Test that invalid test_timing values raise ValueError."""
        location = SourceLocation(1, 1)
        perform_stmt = PerformStatement(location)
        
        with pytest.raises(ValueError, match="Invalid test timing"):
            perform_stmt.set_test_timing("INVALID")
        
        with pytest.raises(ValueError, match="Invalid test timing"):
            perform_stmt.set_test_timing("MIDDLE")
    
    def test_perform_statement_test_timing_chaining(self):
        """Test that set_test_timing returns self for method chaining."""
        location = SourceLocation(1, 1)
        perform_stmt = PerformStatement(location)
        
        result = perform_stmt.set_test_timing("AFTER")
        
        assert result is perform_stmt
        assert perform_stmt.test_timing == "AFTER"
    
    def test_perform_statement_times_count_numeric(self):
        """Test times_count with numeric literal."""
        location = SourceLocation(1, 1)
        perform_stmt = PerformStatement(location)
        
        perform_stmt.set_times_clause(10)
        
        assert perform_stmt.times_count == 10
        assert isinstance(perform_stmt.times_count, int)
    
    def test_perform_statement_times_count_variable(self):
        """Test times_count with variable name."""
        location = SourceLocation(1, 1)
        perform_stmt = PerformStatement(location)
        
        perform_stmt.set_times_clause("WS-COUNT")
        
        assert perform_stmt.times_count == "WS-COUNT"
        assert isinstance(perform_stmt.times_count, str)
        assert perform_stmt.perform_type == "TIMES"
    
    def test_perform_statement_times_count_zero(self):
        """Test times_count with zero (valid edge case)."""
        location = SourceLocation(1, 1)
        perform_stmt = PerformStatement(location)
        
        perform_stmt.set_times_clause(0)
        
        assert perform_stmt.times_count == 0
        assert perform_stmt.perform_type == "TIMES"
    
    def test_perform_statement_times_count_large_number(self):
        """Test times_count with large number."""
        location = SourceLocation(1, 1)
        perform_stmt = PerformStatement(location)
        
        perform_stmt.set_times_clause(999999)
        
        assert perform_stmt.times_count == 999999
        assert perform_stmt.perform_type == "TIMES"
    
    def test_perform_statement_times_count_variable_names(self):
        """Test times_count with various valid variable names."""
        location = SourceLocation(1, 1)
        
        variable_names = ["COUNT", "COUNTER", "WS-COUNT", "WS-LOOP-COUNT", "I"]
        
        for var_name in variable_names:
            perform_stmt = PerformStatement(location)
            perform_stmt.set_times_clause(var_name)
            assert perform_stmt.times_count == var_name
    
    def test_perform_statement_to_dict_with_test_timing(self):
        """Test to_dict includes test_timing."""
        location = SourceLocation(1, 1)
        perform_stmt = PerformStatement(location)
        
        perform_stmt.set_test_timing("AFTER")
        
        result = perform_stmt.to_dict()
        
        assert "test_timing" in result
        assert result["test_timing"] == "AFTER"
    
    def test_perform_statement_to_dict_test_timing_default(self):
        """Test to_dict includes default test_timing."""
        location = SourceLocation(1, 1)
        perform_stmt = PerformStatement(location)
        
        result = perform_stmt.to_dict()
        
        assert "test_timing" in result
        assert result["test_timing"] == "BEFORE"
    
    def test_perform_statement_to_dict_times_numeric(self):
        """Test to_dict with numeric times_count."""
        location = SourceLocation(1, 1)
        perform_stmt = PerformStatement(location)
        
        perform_stmt.set_times_clause(5)
        
        result = perform_stmt.to_dict()
        
        assert result["times_count"] == 5
        assert isinstance(result["times_count"], int)
    
    def test_perform_statement_to_dict_times_variable(self):
        """Test to_dict with variable times_count."""
        location = SourceLocation(1, 1)
        perform_stmt = PerformStatement(location)
        
        perform_stmt.set_times_clause("WS-COUNT")
        
        result = perform_stmt.to_dict()
        
        assert result["times_count"] == "WS-COUNT"
        assert isinstance(result["times_count"], str)
    
    def test_perform_statement_complex_with_test_timing_and_until(self):
        """Test complex PERFORM with both test_timing and UNTIL."""
        location = SourceLocation(1, 1)
        perform_stmt = PerformStatement(location)
        
        # Create condition
        condition = ConditionalExpression("=", SourceLocation(1, 20))
        condition.set_left_operand("WS-EOF")
        condition.set_right_operand("'Y'")
        
        perform_stmt.set_target_paragraph("PROCESS")
        perform_stmt.set_test_timing("AFTER")
        perform_stmt.set_until_clause(condition)
        
        result = perform_stmt.to_dict()
        
        assert result["perform_type"] == "UNTIL"
        assert result["test_timing"] == "AFTER"
        assert result["until_condition"] is not None
    
    def test_perform_statement_complex_with_test_timing_and_times(self):
        """Test complex PERFORM with both test_timing and TIMES."""
        location = SourceLocation(1, 1)
        perform_stmt = PerformStatement(location)
        
        perform_stmt.set_target_paragraph("PROCESS")
        perform_stmt.set_test_timing("BEFORE")
        perform_stmt.set_times_clause("WS-COUNT")
        
        result = perform_stmt.to_dict()
        
        assert result["perform_type"] == "TIMES"
        assert result["test_timing"] == "BEFORE"
        assert result["times_count"] == "WS-COUNT"
    
    def test_perform_statement_complex_varying_with_test_timing(self):
        """Test complex PERFORM VARYING with test_timing."""
        location = SourceLocation(1, 1)
        perform_stmt = PerformStatement(location)
        
        condition = ConditionalExpression(">", SourceLocation(1, 40))
        condition.set_left_operand("IDX")
        condition.set_right_operand("100")
        
        perform_stmt.set_target_paragraph("PROCESS-ARRAY")
        perform_stmt.set_test_timing("AFTER")
        perform_stmt.set_varying_clause("IDX", "1", "1", condition)
        
        result = perform_stmt.to_dict()
        
        assert result["perform_type"] == "VARYING"
        assert result["test_timing"] == "AFTER"
        assert result["varying_clause"]["variable"] == "IDX"


class TestComputeStatement:
    """Test the ComputeStatement class."""
    
    def test_compute_statement_creation(self):
        """Test ComputeStatement creation."""
        location = SourceLocation(40, 12)
        compute_stmt = ComputeStatement(location)
        
        assert compute_stmt.statement_type == "COMPUTE"
        assert compute_stmt.targets == []
        assert compute_stmt.expression is None
        assert compute_stmt.operands == []
    
    def test_add_target_single(self):
        """Test adding a single target variable."""
        location = SourceLocation(1, 1)
        compute_stmt = ComputeStatement(location)
        
        compute_stmt.add_target("WS-RESULT")
        
        assert compute_stmt.targets == ["WS-RESULT"]
        assert "WS-RESULT" in compute_stmt.operands
    
    def test_add_target_multiple(self):
        """Test adding multiple target variables."""
        location = SourceLocation(1, 1)
        compute_stmt = ComputeStatement(location)
        
        compute_stmt.add_target("WS-TOTAL")
        compute_stmt.add_target("WS-AVERAGE")
        compute_stmt.add_target("WS-COUNT")
        
        expected_targets = ["WS-TOTAL", "WS-AVERAGE", "WS-COUNT"]
        assert compute_stmt.targets == expected_targets
        
        # All should be in operands
        for target in expected_targets:
            assert target in compute_stmt.operands
    
    def test_add_target_already_in_operands(self):
        """Test adding target when already in operands."""
        location = SourceLocation(1, 1)
        compute_stmt = ComputeStatement(location)
        
        # Add to operands first
        compute_stmt.add_operand("WS-CALC-RESULT")
        
        # Then add as target
        compute_stmt.add_target("WS-CALC-RESULT")
        
        assert "WS-CALC-RESULT" in compute_stmt.targets
        # Should not duplicate in operands
        assert compute_stmt.operands.count("WS-CALC-RESULT") == 1
    
    def test_set_expression(self):
        """Test setting the arithmetic expression."""
        location = SourceLocation(1, 1)
        compute_stmt = ComputeStatement(location)
        
        # Create an arithmetic expression
        expr_location = SourceLocation(1, 25)
        expression = ArithmeticExpression("+", expr_location)
        expression.set_left_operand("WS-VALUE1")
        expression.set_right_operand("WS-VALUE2")
        
        compute_stmt.set_expression(expression)
        
        assert compute_stmt.expression == expression
        assert expression in compute_stmt.children
    
    def test_compute_statement_to_dict(self):
        """Test ComputeStatement to_dict method."""
        location = SourceLocation(45, 16)
        compute_stmt = ComputeStatement(location)
        
        # Add targets
        compute_stmt.add_target("WS-RESULT1")
        compute_stmt.add_target("WS-RESULT2")
        
        # Create and add expression
        expression = ArithmeticExpression("*", SourceLocation(1, 30))
        expression.set_left_operand("WS-BASE")
        expression.set_right_operand("WS-RATE")
        compute_stmt.set_expression(expression)
        
        result = compute_stmt.to_dict()
        
        # Check base statement properties
        assert result["node_type"] == "Statement"
        assert result["statement_type"] == "COMPUTE"
        assert result["operands"] == ["WS-RESULT1", "WS-RESULT2"]
        
        # Check COMPUTE-specific properties
        assert result["targets"] == ["WS-RESULT1", "WS-RESULT2"]
        assert result["expression"] is not None
        assert result["expression"]["operator"] == "*"
        assert result["expression"]["left_operand"] == "WS-BASE"
        assert result["expression"]["right_operand"] == "WS-RATE"
    
    def test_compute_statement_no_expression(self):
        """Test ComputeStatement to_dict with no expression."""
        location = SourceLocation(1, 1)
        compute_stmt = ComputeStatement(location)
        
        compute_stmt.add_target("WS-TARGET")
        
        result = compute_stmt.to_dict()
        assert result["targets"] == ["WS-TARGET"]
        assert result["expression"] is None


class TestCallStatement:
    """Test the CallStatement class."""
    
    def test_call_statement_creation(self):
        """Test CallStatement creation."""
        location = SourceLocation(50, 20)
        call_stmt = CallStatement(location)
        
        assert call_stmt.statement_type == "CALL"
        assert call_stmt.called_program is None
        assert call_stmt.using_parameters == []
        assert call_stmt.giving_parameter is None
        assert call_stmt.on_overflow is None
        assert call_stmt.on_exception is None
        assert call_stmt.operands == []
    
    def test_set_called_program(self):
        """Test setting the called program name."""
        location = SourceLocation(1, 1)
        call_stmt = CallStatement(location)
        
        call_stmt.set_called_program("SUBPROGRAM1")
        
        assert call_stmt.called_program == "SUBPROGRAM1"
        assert "SUBPROGRAM1" in call_stmt.operands
        assert call_stmt.operands[0] == "SUBPROGRAM1"
    
    def test_set_called_program_already_in_operands(self):
        """Test setting called program when already in operands."""
        location = SourceLocation(1, 1)
        call_stmt = CallStatement(location)
        
        # Add to operands first
        call_stmt.add_operand("MATHLIB")
        
        # Then set as called program
        call_stmt.set_called_program("MATHLIB")
        
        assert call_stmt.called_program == "MATHLIB"
        # Should not duplicate in operands
        assert call_stmt.operands.count("MATHLIB") == 1
    
    def test_add_using_parameter_single(self):
        """Test adding a single USING parameter."""
        location = SourceLocation(1, 1)
        call_stmt = CallStatement(location)
        
        call_stmt.add_using_parameter("WS-INPUT-DATA")
        
        assert len(call_stmt.using_parameters) == 1
        assert call_stmt.using_parameters[0].name == "WS-INPUT-DATA"
        assert call_stmt.using_parameters[0].passing_mode == "REFERENCE"
        assert "WS-INPUT-DATA" in call_stmt.operands
    
    def test_add_using_parameter_multiple(self):
        """Test adding multiple USING parameters."""
        location = SourceLocation(1, 1)
        call_stmt = CallStatement(location)
        
        call_stmt.add_using_parameter("WS-PARAM1")
        call_stmt.add_using_parameter("WS-PARAM2")
        call_stmt.add_using_parameter("WS-PARAM3")
        
        expected_params = ["WS-PARAM1", "WS-PARAM2", "WS-PARAM3"]
        assert len(call_stmt.using_parameters) == 3
        for i, param_name in enumerate(expected_params):
            assert call_stmt.using_parameters[i].name == param_name
            assert call_stmt.using_parameters[i].passing_mode == "REFERENCE"
        
        # All should be in operands
        for param in expected_params:
            assert param in call_stmt.operands
    
    def test_add_using_parameter_already_in_operands(self):
        """Test adding USING parameter when already in operands."""
        location = SourceLocation(1, 1)
        call_stmt = CallStatement(location)
        
        # Add to operands first
        call_stmt.add_operand("WS-SHARED-PARAM")
        
        # Then add as using parameter
        call_stmt.add_using_parameter("WS-SHARED-PARAM")
        
        assert len(call_stmt.using_parameters) == 1
        assert call_stmt.using_parameters[0].name == "WS-SHARED-PARAM"
        # Should not duplicate in operands
        assert call_stmt.operands.count("WS-SHARED-PARAM") == 1
    
    def test_set_giving_parameter(self):
        """Test setting the GIVING parameter."""
        location = SourceLocation(1, 1)
        call_stmt = CallStatement(location)
        
        call_stmt.set_giving_parameter("WS-RETURN-CODE")
        
        assert call_stmt.giving_parameter == "WS-RETURN-CODE"
        assert "WS-RETURN-CODE" in call_stmt.operands
    
    def test_set_giving_parameter_already_in_operands(self):
        """Test setting GIVING parameter when already in operands."""
        location = SourceLocation(1, 1)
        call_stmt = CallStatement(location)
        
        # Add to operands first
        call_stmt.add_operand("WS-RESULT")
        
        # Then set as giving parameter
        call_stmt.set_giving_parameter("WS-RESULT")
        
        assert call_stmt.giving_parameter == "WS-RESULT"
        # Should not duplicate in operands
        assert call_stmt.operands.count("WS-RESULT") == 1
    
    def test_call_statement_to_dict(self):
        """Test CallStatement to_dict method."""
        location = SourceLocation(55, 24)
        call_stmt = CallStatement(location)
        
        call_stmt.set_called_program("CALCULATETAX")
        call_stmt.add_using_parameter("WS-SALARY")
        call_stmt.add_using_parameter("WS-DEDUCTIONS")
        call_stmt.set_giving_parameter("WS-TAX-AMOUNT")
        
        result = call_stmt.to_dict()
        
        # Check base statement properties
        assert result["node_type"] == "Statement"
        assert result["statement_type"] == "CALL"
        expected_operands = ["CALCULATETAX", "WS-SALARY", "WS-DEDUCTIONS", "WS-TAX-AMOUNT"]
        assert result["operands"] == expected_operands
        
        # Check CALL-specific properties
        assert result["called_program"] == "CALCULATETAX"
        assert len(result["using_parameters"]) == 2
        assert result["using_parameters"][0]["name"] == "WS-SALARY"
        assert result["using_parameters"][0]["mode"] == "REFERENCE"
        assert result["using_parameters"][1]["name"] == "WS-DEDUCTIONS"
        assert result["using_parameters"][1]["mode"] == "REFERENCE"
        assert result["giving_parameter"] == "WS-TAX-AMOUNT"
    
    def test_call_statement_minimal(self):
        """Test CallStatement with minimal configuration."""
        location = SourceLocation(1, 1)
        call_stmt = CallStatement(location)
        
        call_stmt.set_called_program("UTILITY")
        
        result = call_stmt.to_dict()
        assert result["called_program"] == "UTILITY"
        assert result["using_parameters"] == []
        assert result["giving_parameter"] is None
    
    def test_set_called_program_static(self):
        """Test setting a static called program (literal)."""
        location = SourceLocation(1, 1)
        call_stmt = CallStatement(location)
        
        call_stmt.set_called_program('"SUBPROG"', is_dynamic=False)
        
        assert call_stmt.called_program == '"SUBPROG"'
        assert call_stmt.is_dynamic == False
        assert call_stmt.possible_values == []
    
    def test_set_called_program_dynamic(self):
        """Test setting a dynamic called program (variable)."""
        location = SourceLocation(1, 1)
        call_stmt = CallStatement(location)
        
        call_stmt.set_called_program('WS-PROGRAM-NAME', is_dynamic=True)
        
        assert call_stmt.called_program == 'WS-PROGRAM-NAME'
        assert call_stmt.is_dynamic == True
        assert call_stmt.possible_values == []  # Empty until analyzed
    
    def test_add_possible_value(self):
        """Test adding a possible value to a dynamic CALL."""
        location = SourceLocation(1, 1)
        call_stmt = CallStatement(location)
        
        call_stmt.set_called_program('WS-PROG', is_dynamic=True)
        call_stmt.add_possible_value("PROG1")
        call_stmt.add_possible_value("PROG2")
        
        assert len(call_stmt.possible_values) == 2
        assert "PROG1" in call_stmt.possible_values
        assert "PROG2" in call_stmt.possible_values
    
    def test_add_possible_value_no_duplicates(self):
        """Test that adding duplicate values doesn't create duplicates."""
        location = SourceLocation(1, 1)
        call_stmt = CallStatement(location)
        
        call_stmt.set_called_program('WS-PROG', is_dynamic=True)
        call_stmt.add_possible_value("PROG1")
        call_stmt.add_possible_value("PROG1")  # Duplicate
        call_stmt.add_possible_value("PROG2")
        
        assert len(call_stmt.possible_values) == 2
        assert call_stmt.possible_values.count("PROG1") == 1
    
    def test_set_possible_values(self):
        """Test setting all possible values at once."""
        location = SourceLocation(1, 1)
        call_stmt = CallStatement(location)
        
        call_stmt.set_called_program('WS-PROG', is_dynamic=True)
        call_stmt.set_possible_values(["PROG-A", "PROG-B", "PROG-C"])
        
        assert len(call_stmt.possible_values) == 3
        assert "PROG-A" in call_stmt.possible_values
        assert "PROG-B" in call_stmt.possible_values
        assert "PROG-C" in call_stmt.possible_values
    
    def test_possible_values_returns_copy(self):
        """Test that possible_values property returns a copy."""
        location = SourceLocation(1, 1)
        call_stmt = CallStatement(location)
        
        call_stmt.set_called_program('WS-PROG', is_dynamic=True)
        call_stmt.add_possible_value("PROG1")
        
        # Get values and modify
        values = call_stmt.possible_values
        values.append("MODIFIED")
        
        # Verify original is not affected
        assert "MODIFIED" not in call_stmt.possible_values
        assert len(call_stmt.possible_values) == 1
    
    def test_to_dict_includes_dynamic_fields(self):
        """Test that to_dict includes is_dynamic and possible_values."""
        location = SourceLocation(1, 1)
        call_stmt = CallStatement(location)
        
        call_stmt.set_called_program('WS-PROG', is_dynamic=True)
        call_stmt.add_possible_value("PROG1")
        call_stmt.add_possible_value("PROG2")
        
        result = call_stmt.to_dict()
        
        assert "is_dynamic" in result
        assert "possible_values" in result
        assert result["is_dynamic"] == True
        assert len(result["possible_values"]) == 2
        assert "PROG1" in result["possible_values"]
        assert "PROG2" in result["possible_values"]
    
    def test_to_dict_static_call(self):
        """Test to_dict for static CALL statement."""
        location = SourceLocation(1, 1)
        call_stmt = CallStatement(location)
        
        call_stmt.set_called_program('"STATIC-PROG"', is_dynamic=False)
        
        result = call_stmt.to_dict()
        
        assert result["is_dynamic"] == False
        assert result["possible_values"] == []


class TestSelectStatement:
    """Test the SelectStatement class."""
    
    def test_select_statement_creation(self):
        """Test SelectStatement creation."""
        location = SourceLocation(60, 4)
        select_stmt = SelectStatement(location)
        
        assert select_stmt.statement_type == "SELECT"
        assert select_stmt.file_name is None
        assert select_stmt.assign_to is None
        assert select_stmt.organization is None
        assert select_stmt.access_mode is None
        assert select_stmt.file_status is None
        assert select_stmt.operands == []
    
    def test_set_file_name(self):
        """Test setting the file name."""
        location = SourceLocation(1, 1)
        select_stmt = SelectStatement(location)
        
        select_stmt.set_file_name("CUSTOMER-FILE")
        
        assert select_stmt.file_name == "CUSTOMER-FILE"
        assert "CUSTOMER-FILE" in select_stmt.operands
        assert select_stmt.operands[0] == "CUSTOMER-FILE"
    
    def test_set_file_name_already_in_operands(self):
        """Test setting file name when already in operands."""
        location = SourceLocation(1, 1)
        select_stmt = SelectStatement(location)
        
        # Add to operands first
        select_stmt.add_operand("INPUT-FILE")
        
        # Then set as file name
        select_stmt.set_file_name("INPUT-FILE")
        
        assert select_stmt.file_name == "INPUT-FILE"
        # Should not duplicate in operands
        assert select_stmt.operands.count("INPUT-FILE") == 1
    
    def test_set_assign_to(self):
        """Test setting the ASSIGN TO clause."""
        location = SourceLocation(1, 1)
        select_stmt = SelectStatement(location)
        
        select_stmt.set_assign_to("DISK")
        
        assert select_stmt.assign_to == "DISK"
        assert "DISK" in select_stmt.operands
    
    def test_set_assign_to_already_in_operands(self):
        """Test setting ASSIGN TO when already in operands."""
        location = SourceLocation(1, 1)
        select_stmt = SelectStatement(location)
        
        # Add to operands first
        select_stmt.add_operand("TAPE")
        
        # Then set as assign to
        select_stmt.set_assign_to("TAPE")
        
        assert select_stmt.assign_to == "TAPE"
        # Should not duplicate in operands
        assert select_stmt.operands.count("TAPE") == 1
    
    def test_set_organization(self):
        """Test setting the ORGANIZATION clause."""
        location = SourceLocation(1, 1)
        select_stmt = SelectStatement(location)
        
        select_stmt.set_organization("INDEXED")
        
        assert select_stmt.organization == "INDEXED"
    
    def test_set_access_mode(self):
        """Test setting the ACCESS MODE clause."""
        location = SourceLocation(1, 1)
        select_stmt = SelectStatement(location)
        
        select_stmt.set_access_mode("SEQUENTIAL")
        
        assert select_stmt.access_mode == "SEQUENTIAL"
    
    def test_set_file_status(self):
        """Test setting the FILE STATUS clause."""
        location = SourceLocation(1, 1)
        select_stmt = SelectStatement(location)
        
        select_stmt.set_file_status("WS-FILE-STATUS")
        
        assert select_stmt.file_status == "WS-FILE-STATUS"
    
    def test_select_statement_to_dict(self):
        """Test SelectStatement to_dict method."""
        location = SourceLocation(65, 8)
        select_stmt = SelectStatement(location)
        
        select_stmt.set_file_name("TRANSACTION-FILE")
        select_stmt.set_assign_to("VSAM-KSDS")
        select_stmt.set_organization("INDEXED")
        select_stmt.set_access_mode("DYNAMIC")
        select_stmt.set_file_status("WS-TRANS-STATUS")
        
        result = select_stmt.to_dict()
        
        # Check base statement properties
        assert result["node_type"] == "Statement"
        assert result["statement_type"] == "SELECT"
        assert result["operands"] == ["TRANSACTION-FILE", "VSAM-KSDS"]
        
        # Check SELECT-specific properties
        assert result["file_name"] == "TRANSACTION-FILE"
        assert result["assign_to"] == "VSAM-KSDS"
        assert result["organization"] == "INDEXED"
        assert result["access_mode"] == "DYNAMIC"
        assert result["file_status"] == "WS-TRANS-STATUS"
    
    def test_select_statement_minimal(self):
        """Test SelectStatement with minimal configuration."""
        location = SourceLocation(1, 1)
        select_stmt = SelectStatement(location)
        
        select_stmt.set_file_name("SIMPLE-FILE")
        
        result = select_stmt.to_dict()
        assert result["file_name"] == "SIMPLE-FILE"
        assert result["assign_to"] is None
        assert result["organization"] is None
        assert result["access_mode"] is None
        assert result["file_status"] is None


class TestCobolExpression:
    """Test the CobolExpression base class."""
    
    def test_cobol_expression_creation(self):
        """Test CobolExpression creation."""
        location = SourceLocation(70, 15)
        expr = CobolExpression("TEST", location)
        
        assert expr.expression_type == "TEST"
        assert expr.node_type == "Expression"
        assert expr.location == location
    
    def test_cobol_expression_to_dict(self):
        """Test CobolExpression to_dict method."""
        location = SourceLocation(75, 20)
        expr = CobolExpression("BOOLEAN", location)
        
        result = expr.to_dict()
        
        assert result["node_type"] == "Expression"
        assert result["expression_type"] == "BOOLEAN"
        assert "location" in result
        assert "metadata" in result
        
        # Verify location structure
        assert result["location"]["line"] == 75
        assert result["location"]["column"] == 20
    
    def test_cobol_expression_inheritance(self):
        """Test CobolExpression inheritance from ASTNode."""
        location = SourceLocation(1, 1)
        expr = CobolExpression("LOGICAL", location)
        
        # Should inherit ASTNode methods
        assert isinstance(expr, ASTNode)
        assert hasattr(expr, 'children')
        assert hasattr(expr, 'add_child')
        assert hasattr(expr, 'location')
        assert hasattr(expr, '_metadata')


class TestArithmeticExpression:
    """Test the ArithmeticExpression class."""
    
    def test_arithmetic_expression_creation(self):
        """Test ArithmeticExpression creation."""
        location = SourceLocation(80, 25)
        arith_expr = ArithmeticExpression("+", location)
        
        assert arith_expr.expression_type == "ARITHMETIC"
        assert arith_expr.operator == "+"
        assert arith_expr.left_operand is None
        assert arith_expr.right_operand is None
    
    def test_set_left_operand_string(self):
        """Test setting left operand as string."""
        location = SourceLocation(1, 1)
        arith_expr = ArithmeticExpression("-", location)
        
        arith_expr.set_left_operand("WS-VALUE1")
        
        assert arith_expr.left_operand == "WS-VALUE1"
        # String operands should not be added as children
        assert len(arith_expr.children) == 0
    
    def test_set_left_operand_expression(self):
        """Test setting left operand as expression."""
        location = SourceLocation(1, 1)
        arith_expr = ArithmeticExpression("*", location)
        
        # Create nested expression
        nested_expr = ArithmeticExpression("+", SourceLocation(1, 10))
        nested_expr.set_left_operand("A")
        nested_expr.set_right_operand("B")
        
        arith_expr.set_left_operand(nested_expr)
        
        assert arith_expr.left_operand == nested_expr
        assert nested_expr in arith_expr.children
    
    def test_set_right_operand_string(self):
        """Test setting right operand as string."""
        location = SourceLocation(1, 1)
        arith_expr = ArithmeticExpression("/", location)
        
        arith_expr.set_right_operand("WS-DIVISOR")
        
        assert arith_expr.right_operand == "WS-DIVISOR"
        # String operands should not be added as children
        assert len(arith_expr.children) == 0
    
    def test_set_right_operand_expression(self):
        """Test setting right operand as expression."""
        location = SourceLocation(1, 1)
        arith_expr = ArithmeticExpression("**", location)  # Exponentiation
        
        # Create nested expression
        nested_expr = ArithmeticExpression("-", SourceLocation(1, 15))
        nested_expr.set_left_operand("X")
        nested_expr.set_right_operand("Y")
        
        arith_expr.set_right_operand(nested_expr)
        
        assert arith_expr.right_operand == nested_expr
        assert nested_expr in arith_expr.children
    
    def test_arithmetic_expression_to_dict_strings(self):
        """Test ArithmeticExpression to_dict with string operands."""
        location = SourceLocation(85, 30)
        arith_expr = ArithmeticExpression("+", location)
        
        arith_expr.set_left_operand("WS-TOTAL")
        arith_expr.set_right_operand("WS-INCREMENT")
        
        result = arith_expr.to_dict()
        
        # Check base expression properties
        assert result["node_type"] == "Expression"
        assert result["expression_type"] == "ARITHMETIC"
        
        # Check arithmetic-specific properties
        assert result["operator"] == "+"
        assert result["left_operand"] == "WS-TOTAL"
        assert result["right_operand"] == "WS-INCREMENT"
    
    def test_arithmetic_expression_to_dict_nested(self):
        """Test ArithmeticExpression to_dict with nested expressions."""
        location = SourceLocation(1, 1)
        arith_expr = ArithmeticExpression("*", location)
        
        # Create left nested expression
        left_expr = ArithmeticExpression("+", SourceLocation(1, 5))
        left_expr.set_left_operand("A")
        left_expr.set_right_operand("B")
        
        # Create right nested expression
        right_expr = ArithmeticExpression("-", SourceLocation(1, 15))
        right_expr.set_left_operand("C")
        right_expr.set_right_operand("D")
        
        arith_expr.set_left_operand(left_expr)
        arith_expr.set_right_operand(right_expr)
        
        result = arith_expr.to_dict()
        
        assert result["operator"] == "*"
        
        # Check left nested expression
        assert isinstance(result["left_operand"], dict)
        assert result["left_operand"]["operator"] == "+"
        assert result["left_operand"]["left_operand"] == "A"
        assert result["left_operand"]["right_operand"] == "B"
        
        # Check right nested expression
        assert isinstance(result["right_operand"], dict)
        assert result["right_operand"]["operator"] == "-"
        assert result["right_operand"]["left_operand"] == "C"
        assert result["right_operand"]["right_operand"] == "D"
    
    def test_arithmetic_expression_operators(self):
        """Test ArithmeticExpression with different operators."""
        operators = ["+", "-", "*", "/", "**"]
        
        for op in operators:
            location = SourceLocation(1, 1)
            arith_expr = ArithmeticExpression(op, location)
            
            assert arith_expr.operator == op
            assert arith_expr.expression_type == "ARITHMETIC"


class TestConditionalExpression:
    """Test the ConditionalExpression class."""
    
    def test_conditional_expression_creation(self):
        """Test ConditionalExpression creation."""
        location = SourceLocation(90, 12)
        cond_expr = ConditionalExpression("=", location)
        
        assert cond_expr.expression_type == "COMPARISON"
        assert cond_expr.operator == "="
        assert cond_expr.left_operand is None
        assert cond_expr.right_operand is None
    
    def test_expression_type(self):
        """Test the expression_type attribute."""
        location = SourceLocation(1, 1)
        cond_expr = ConditionalExpression(">", location)

        assert cond_expr.expression_type == "COMPARISON"
    
    def test_set_left_operand_string(self):
        """Test setting left operand as string."""
        location = SourceLocation(1, 1)
        cond_expr = ConditionalExpression("NOT =", location)
        
        cond_expr.set_left_operand("WS-STATUS")
        
        assert cond_expr.left_operand == "WS-STATUS"
        assert len(cond_expr.children) == 0
    
    def test_set_left_operand_expression(self):
        """Test setting left operand as expression."""
        location = SourceLocation(1, 1)
        cond_expr = ConditionalExpression("<", location)
        
        # Create nested arithmetic expression
        nested_expr = ArithmeticExpression("+", SourceLocation(1, 5))
        nested_expr.set_left_operand("X")
        nested_expr.set_right_operand("Y")
        
        cond_expr.set_left_operand(nested_expr)
        
        assert cond_expr.left_operand == nested_expr
        assert nested_expr in cond_expr.children
    
    def test_set_right_operand_string(self):
        """Test setting right operand as string."""
        location = SourceLocation(1, 1)
        cond_expr = ConditionalExpression(">=", location)
        
        cond_expr.set_right_operand("100")
        
        assert cond_expr.right_operand == "100"
        assert len(cond_expr.children) == 0
    
    def test_set_right_operand_expression(self):
        """Test setting right operand as expression."""
        location = SourceLocation(1, 1)
        cond_expr = ConditionalExpression("<=", location)
        
        # Create nested arithmetic expression
        nested_expr = ArithmeticExpression("*", SourceLocation(1, 10))
        nested_expr.set_left_operand("RATE")
        nested_expr.set_right_operand("FACTOR")
        
        cond_expr.set_right_operand(nested_expr)
        
        assert cond_expr.right_operand == nested_expr
        assert nested_expr in cond_expr.children
    
    def test_conditional_expression_to_dict_strings(self):
        """Test ConditionalExpression to_dict with string operands."""
        location = SourceLocation(95, 18)
        cond_expr = ConditionalExpression("=", location)
        
        cond_expr.set_left_operand("WS-CODE")
        cond_expr.set_right_operand("'SUCCESS'")
        
        result = cond_expr.to_dict()
        
        # Check base expression properties
        assert result["node_type"] == "Expression"
        assert result["expression_type"] == "COMPARISON"
        
        # Check conditional-specific properties
        assert result["operator"] == "="
        assert result["left_operand"] == "WS-CODE"
        assert result["right_operand"] == "'SUCCESS'"
        assert result["condition_type"] == "COMPARISON"
    
    def test_conditional_expression_to_dict_nested(self):
        """Test ConditionalExpression to_dict with nested expressions."""
        location = SourceLocation(1, 1)
        cond_expr = ConditionalExpression(">", location)
        
        # Create left nested expression
        left_expr = ArithmeticExpression("+", SourceLocation(1, 5))
        left_expr.set_left_operand("TOTAL")
        left_expr.set_right_operand("TAX")
        
        cond_expr.set_left_operand(left_expr)
        cond_expr.set_right_operand("BUDGET")
        
        result = cond_expr.to_dict()
        
        assert result["operator"] == ">"
        assert result["condition_type"] == "COMPARISON"
        
        # Check left nested expression
        assert isinstance(result["left_operand"], dict)
        assert result["left_operand"]["operator"] == "+"
        assert result["left_operand"]["left_operand"] == "TOTAL"
        assert result["left_operand"]["right_operand"] == "TAX"
        
        # Check right operand
        assert result["right_operand"] == "BUDGET"
    
    def test_conditional_expression_operators(self):
        """Test ConditionalExpression with different operators."""
        operators = ["=", "NOT =", "<", ">", "<=", ">=", "IS EQUAL TO", "IS GREATER THAN"]
        
        for op in operators:
            location = SourceLocation(1, 1)
            cond_expr = ConditionalExpression(op, location)
            
            assert cond_expr.operator == op
            assert cond_expr.expression_type == "COMPARISON"


class TestLogicalExpression:
    """Test the LogicalExpression class."""
    
    def test_logical_expression_creation(self):
        """Test LogicalExpression creation."""
        location = SourceLocation(100, 8)
        logic_expr = LogicalExpression("AND", location)
        
        assert logic_expr.expression_type == "LOGICAL"
        assert logic_expr.operator == "AND"
        assert logic_expr.left_condition is None
        assert logic_expr.right_condition is None
    
    def test_set_left_condition(self):
        """Test setting the left condition."""
        location = SourceLocation(1, 1)
        logic_expr = LogicalExpression("OR", location)
        
        # Create a conditional expression
        left_cond = ConditionalExpression("=", SourceLocation(1, 5))
        left_cond.set_left_operand("A")
        left_cond.set_right_operand("1")
        
        logic_expr.set_left_condition(left_cond)
        
        assert logic_expr.left_condition == left_cond
        assert left_cond in logic_expr.children
    
    def test_set_right_condition(self):
        """Test setting the right condition."""
        location = SourceLocation(1, 1)
        logic_expr = LogicalExpression("AND", location)
        
        # Create a conditional expression
        right_cond = ConditionalExpression(">", SourceLocation(1, 15))
        right_cond.set_left_operand("B")
        right_cond.set_right_operand("0")
        
        logic_expr.set_right_condition(right_cond)
        
        assert logic_expr.right_condition == right_cond
        assert right_cond in logic_expr.children
    
    def test_logical_expression_to_dict(self):
        """Test LogicalExpression to_dict method."""
        location = SourceLocation(105, 22)
        logic_expr = LogicalExpression("AND", location)
        
        # Create left condition
        left_cond = ConditionalExpression("=", SourceLocation(1, 5))
        left_cond.set_left_operand("WS-FLAG1")
        left_cond.set_right_operand("'Y'")
        
        # Create right condition
        right_cond = ConditionalExpression(">", SourceLocation(1, 25))
        right_cond.set_left_operand("WS-COUNT")
        right_cond.set_right_operand("0")
        
        logic_expr.set_left_condition(left_cond)
        logic_expr.set_right_condition(right_cond)
        
        result = logic_expr.to_dict()
        
        # Check base expression properties
        assert result["node_type"] == "Expression"
        assert result["expression_type"] == "LOGICAL"
        
        # Check logical-specific properties
        assert result["operator"] == "AND"
        
        # Check left condition
        assert result["left_condition"] is not None
        assert result["left_condition"]["operator"] == "="
        assert result["left_condition"]["left_operand"] == "WS-FLAG1"
        assert result["left_condition"]["right_operand"] == "'Y'"
        
        # Check right condition
        assert result["right_condition"] is not None
        assert result["right_condition"]["operator"] == ">"
        assert result["right_condition"]["left_operand"] == "WS-COUNT"
        assert result["right_condition"]["right_operand"] == "0"
    
    def test_logical_expression_to_dict_null_conditions(self):
        """Test LogicalExpression to_dict with null conditions."""
        location = SourceLocation(1, 1)
        logic_expr = LogicalExpression("NOT", location)
        
        result = logic_expr.to_dict()
        
        assert result["operator"] == "NOT"
        assert result["left_condition"] is None
        assert result["right_condition"] is None
    
    def test_logical_expression_operators(self):
        """Test LogicalExpression with different operators."""
        operators = ["AND", "OR", "NOT"]
        
        for op in operators:
            location = SourceLocation(1, 1)
            logic_expr = LogicalExpression(op, location)
            
            assert logic_expr.operator == op
            assert logic_expr.expression_type == "LOGICAL"
    
    def test_nested_logical_expressions(self):
        """Test nested LogicalExpression structures."""
        location = SourceLocation(1, 1)
        
        # Create outer AND expression
        outer_expr = LogicalExpression("AND", location)
        
        # Create inner OR expression as left condition
        inner_or = LogicalExpression("OR", SourceLocation(1, 5))
        
        # Add conditions to inner OR
        cond1 = ConditionalExpression("=", SourceLocation(1, 10))
        cond1.set_left_operand("X")
        cond1.set_right_operand("1")
        
        cond2 = ConditionalExpression("=", SourceLocation(1, 20))
        cond2.set_left_operand("Y")
        cond2.set_right_operand("2")
        
        inner_or.set_left_condition(cond1)
        inner_or.set_right_condition(cond2)
        
        # Create simple condition as right condition
        cond3 = ConditionalExpression(">", SourceLocation(1, 30))
        cond3.set_left_operand("Z")
        cond3.set_right_operand("0")
        
        outer_expr.set_left_condition(inner_or)
        outer_expr.set_right_condition(cond3)
        
        # Test serialization
        result = outer_expr.to_dict()
        
        assert result["operator"] == "AND"
        
        # Check nested OR in left condition
        left_cond = result["left_condition"]
        assert left_cond["operator"] == "OR"
        assert left_cond["left_condition"]["left_operand"] == "X"
        assert left_cond["right_condition"]["left_operand"] == "Y"
        
        # Check simple condition in right
        right_cond = result["right_condition"]
        assert right_cond["operator"] == ">"
        assert right_cond["left_operand"] == "Z"


class TestFunctionCall:
    """Test the FunctionCall class."""
    
    def test_function_call_creation(self):
        """Test FunctionCall creation."""
        location = SourceLocation(110, 16)
        func_call = FunctionCall("LENGTH", location)
        
        assert func_call.expression_type == "FUNCTION"
        assert func_call.function_name == "LENGTH"
        assert func_call.function_type == "INTRINSIC"
        assert func_call.arguments == []
    
    def test_add_argument_string(self):
        """Test adding string argument."""
        location = SourceLocation(1, 1)
        func_call = FunctionCall("NUMVAL", location)
        
        func_call.add_argument("WS-NUMERIC-STRING")
        
        assert func_call.arguments == ["WS-NUMERIC-STRING"]
        assert len(func_call.children) == 0
    
    def test_add_argument_expression(self):
        """Test adding expression argument."""
        location = SourceLocation(1, 1)
        func_call = FunctionCall("MAX", location)
        
        # Create arithmetic expression as argument
        expr_arg = ArithmeticExpression("+", SourceLocation(1, 10))
        expr_arg.set_left_operand("A")
        expr_arg.set_right_operand("B")
        
        func_call.add_argument(expr_arg)
        
        assert func_call.arguments == [expr_arg]
        assert expr_arg in func_call.children
    
    def test_add_argument_multiple(self):
        """Test adding multiple arguments."""
        location = SourceLocation(1, 1)
        func_call = FunctionCall("SUBSTR", location)
        
        func_call.add_argument("WS-STRING")
        func_call.add_argument("START-POS")
        func_call.add_argument("LENGTH-VAL")
        
        expected_args = ["WS-STRING", "START-POS", "LENGTH-VAL"]
        assert func_call.arguments == expected_args
    
    def test_add_argument_mixed_types(self):
        """Test adding mixed string and expression arguments."""
        location = SourceLocation(1, 1)
        func_call = FunctionCall("COMPUTE-HASH", location)
        
        # Add string argument
        func_call.add_argument("WS-INPUT-DATA")
        
        # Add expression argument
        arith_expr = ArithmeticExpression("*", SourceLocation(1, 15))
        arith_expr.set_left_operand("SEED")
        arith_expr.set_right_operand("PRIME")
        func_call.add_argument(arith_expr)
        
        # Add another string argument
        func_call.add_argument("WS-SALT")
        
        assert len(func_call.arguments) == 3
        assert func_call.arguments[0] == "WS-INPUT-DATA"
        assert func_call.arguments[1] == arith_expr
        assert func_call.arguments[2] == "WS-SALT"
        
        # Only expression should be in children
        assert len(func_call.children) == 1
        assert arith_expr in func_call.children
    
    def test_set_function_type_intrinsic(self):
        """Test setting function type to INTRINSIC."""
        location = SourceLocation(1, 1)
        func_call = FunctionCall("DATE", location)
        
        func_call.set_function_type("INTRINSIC")
        
        assert func_call.function_type == "INTRINSIC"
    
    def test_set_function_type_user_defined(self):
        """Test setting function type to USER_DEFINED."""
        location = SourceLocation(1, 1)
        func_call = FunctionCall("MY-CUSTOM-FUNC", location)
        
        func_call.set_function_type("USER_DEFINED")
        
        assert func_call.function_type == "USER_DEFINED"
    
    def test_function_call_to_dict_simple(self):
        """Test FunctionCall to_dict with simple arguments."""
        location = SourceLocation(115, 28)
        func_call = FunctionCall("UPPER-CASE", location)
        
        func_call.add_argument("WS-INPUT-TEXT")
        func_call.set_function_type("INTRINSIC")
        
        result = func_call.to_dict()
        
        # Check base expression properties
        assert result["node_type"] == "Expression"
        assert result["expression_type"] == "FUNCTION"
        
        # Check function-specific properties
        assert result["function_name"] == "UPPER-CASE"
        assert result["function_type"] == "INTRINSIC"
        assert result["arguments"] == ["WS-INPUT-TEXT"]
    
    def test_function_call_to_dict_expression_arguments(self):
        """Test FunctionCall to_dict with expression arguments."""
        location = SourceLocation(1, 1)
        func_call = FunctionCall("CALC-DISTANCE", location)
        
        # Add arithmetic expression argument
        expr1 = ArithmeticExpression("-", SourceLocation(1, 10))
        expr1.set_left_operand("X2")
        expr1.set_right_operand("X1")
        
        # Add another arithmetic expression
        expr2 = ArithmeticExpression("-", SourceLocation(1, 20))
        expr2.set_left_operand("Y2")
        expr2.set_right_operand("Y1")
        
        func_call.add_argument(expr1)
        func_call.add_argument(expr2)
        func_call.set_function_type("USER_DEFINED")
        
        result = func_call.to_dict()
        
        assert result["function_name"] == "CALC-DISTANCE"
        assert result["function_type"] == "USER_DEFINED"
        assert len(result["arguments"]) == 2
        
        # Check first expression argument
        arg1 = result["arguments"][0]
        assert isinstance(arg1, dict)
        assert arg1["operator"] == "-"
        assert arg1["left_operand"] == "X2"
        assert arg1["right_operand"] == "X1"
        
        # Check second expression argument
        arg2 = result["arguments"][1]
        assert isinstance(arg2, dict)
        assert arg2["operator"] == "-"
        assert arg2["left_operand"] == "Y2"
        assert arg2["right_operand"] == "Y1"
    
    def test_function_call_to_dict_mixed_arguments(self):
        """Test FunctionCall to_dict with mixed argument types."""
        location = SourceLocation(1, 1)
        func_call = FunctionCall("FORMAT-TEXT", location)
        
        # Add string argument
        func_call.add_argument("WS-TEMPLATE")
        
        # Add expression argument
        concat_expr = ArithmeticExpression("+", SourceLocation(1, 15))
        concat_expr.set_left_operand("FIRST-NAME")
        concat_expr.set_right_operand("LAST-NAME")
        func_call.add_argument(concat_expr)
        
        # Add another string argument
        func_call.add_argument("WS-SEPARATOR")
        
        result = func_call.to_dict()
        
        assert len(result["arguments"]) == 3
        assert result["arguments"][0] == "WS-TEMPLATE"
        assert isinstance(result["arguments"][1], dict)
        assert result["arguments"][2] == "WS-SEPARATOR"
    
    def test_function_call_no_arguments(self):
        """Test FunctionCall with no arguments."""
        location = SourceLocation(1, 1)
        func_call = FunctionCall("CURRENT-DATE", location)
        
        result = func_call.to_dict()
        
        assert result["function_name"] == "CURRENT-DATE"
        assert result["arguments"] == []
    
    def test_nested_function_calls(self):
        """Test nested FunctionCall as arguments."""
        location = SourceLocation(1, 1)
        outer_func = FunctionCall("LENGTH", location)
        
        # Create inner function call
        inner_func = FunctionCall("TRIM", SourceLocation(1, 10))
        inner_func.add_argument("WS-INPUT-STRING")
        inner_func.set_function_type("INTRINSIC")
        
        # Use inner function as argument to outer function
        outer_func.add_argument(inner_func)
        
        result = outer_func.to_dict()
        
        assert result["function_name"] == "LENGTH"
        assert len(result["arguments"]) == 1
        
        inner_result = result["arguments"][0]
        assert inner_result["function_name"] == "TRIM"
        assert inner_result["arguments"] == ["WS-INPUT-STRING"]


class TestEdgeCasesAndErrorConditions:
    """Test edge cases and error conditions for comprehensive coverage."""
    
    def test_empty_operands_handling(self):
        """Test statements with empty operand lists."""
        location = SourceLocation(1, 1)
        
        # Test each statement type with no operands
        statements = [
            CobolStatement("EMPTY", location),
            MoveStatement(location),
            DisplayStatement(location),
            PerformStatement(location),
            ComputeStatement(location),
            CallStatement(location),
            SelectStatement(location)
        ]
        
        for stmt in statements:
            assert stmt.operands == []
            result = stmt.to_dict()
            assert "operands" in result
            assert result["operands"] == []
    
    def test_none_values_in_expressions(self):
        """Test expressions with None values."""
        location = SourceLocation(1, 1)
        
        # Test ArithmeticExpression with None operands
        arith = ArithmeticExpression("+", location)
        result = arith.to_dict()
        assert result["left_operand"] is None
        assert result["right_operand"] is None
        
        # Test ConditionalExpression with None operands
        cond = ConditionalExpression("=", location)
        result = cond.to_dict()
        assert result["left_operand"] is None
        assert result["right_operand"] is None
        
        # Test LogicalExpression with None conditions
        logic = LogicalExpression("AND", location)
        result = logic.to_dict()
        assert result["left_condition"] is None
        assert result["right_condition"] is None
    
    def test_complex_nested_structures(self):
        """Test complex nested expression structures."""
        location = SourceLocation(1, 1)
        
        # Create deeply nested structure: ((A + B) * (C - D)) > ((E / F) + G)
        
        # Left side: (A + B) * (C - D)
        add_expr = ArithmeticExpression("+", location)
        add_expr.set_left_operand("A")
        add_expr.set_right_operand("B")
        
        sub_expr = ArithmeticExpression("-", location)
        sub_expr.set_left_operand("C")
        sub_expr.set_right_operand("D")
        
        mul_expr = ArithmeticExpression("*", location)
        mul_expr.set_left_operand(add_expr)
        mul_expr.set_right_operand(sub_expr)
        
        # Right side: (E / F) + G
        div_expr = ArithmeticExpression("/", location)
        div_expr.set_left_operand("E")
        div_expr.set_right_operand("F")
        
        add_expr2 = ArithmeticExpression("+", location)
        add_expr2.set_left_operand(div_expr)
        add_expr2.set_right_operand("G")
        
        # Overall comparison
        comp_expr = ConditionalExpression(">", location)
        comp_expr.set_left_operand(mul_expr)
        comp_expr.set_right_operand(add_expr2)
        
        # Test serialization works for deeply nested structure
        result = comp_expr.to_dict()
        
        # Verify structure is preserved
        assert result["operator"] == ">"
        assert isinstance(result["left_operand"], dict)
        assert isinstance(result["right_operand"], dict)
        
        # Verify nested expressions are properly serialized
        left_side = result["left_operand"]
        assert left_side["operator"] == "*"
        assert isinstance(left_side["left_operand"], dict)
        assert isinstance(left_side["right_operand"], dict)
    
    def test_duplicate_operand_edge_cases(self):
        """Test edge cases with duplicate operands."""
        location = SourceLocation(1, 1)
        
        # Test MoveStatement adding same variable as source and target
        move_stmt = MoveStatement(location)
        move_stmt.set_source("WS-VAR")
        move_stmt.add_target("WS-VAR")  # Same as source
        
        # Should appear only once in operands
        assert move_stmt.operands.count("WS-VAR") == 1
        
        # Test CallStatement with same parameter in using and giving
        call_stmt = CallStatement(location)
        call_stmt.set_called_program("PROG")
        call_stmt.add_using_parameter("WS-PARAM")
        call_stmt.set_giving_parameter("WS-PARAM")  # Same as using
        
        # Should appear only once in operands (besides program name)
        assert call_stmt.operands.count("WS-PARAM") == 1
    
    def test_metadata_inheritance(self):
        """Test that all statement and expression classes properly inherit metadata."""
        location = SourceLocation(1, 1)
        
        all_classes = [
            CobolStatement("TEST", location),
            MoveStatement(location),
            DisplayStatement(location),
            PerformStatement(location),
            ComputeStatement(location),
            CallStatement(location),
            SelectStatement(location),
            CobolExpression("TEST", location),
            ArithmeticExpression("+", location),
            ConditionalExpression("=", location),
            LogicalExpression("AND", location),
            FunctionCall("TEST", location)
        ]
        
        for instance in all_classes:
            # All should inherit from ASTNode
            assert isinstance(instance, ASTNode)
            
            # All should have metadata
            assert hasattr(instance, '_metadata')
            
            # All should have to_dict method
            assert hasattr(instance, 'to_dict')
            
            # to_dict should include metadata
            result = instance.to_dict()
            assert 'metadata' in result


# Module-level tests
def test_statements_module_exports():
    """Test that the statements module exports all expected symbols."""
    import cobolparser.models.statements as stmt_module
    
    # Test module has __all__
    assert hasattr(stmt_module, '__all__')
    
    # Test all expected classes are accessible
    expected_classes = [
        'CobolStatement', 'MoveStatement', 'DisplayStatement',
        'PerformStatement', 'ComputeStatement', 'CallStatement',
        'SelectStatement', 'CobolExpression', 'ArithmeticExpression',
        'ConditionalExpression', 'LogicalExpression', 'FunctionCall',
    ]
    
    for class_name in expected_classes:
        assert hasattr(stmt_module, class_name)


def test_integration_with_ast_base():
    """Test integration with AST base classes."""
    from cobolparser.models.ast_base import SourceLocation
    
    location = SourceLocation(1, 1)
    
    # Test that we can create instances with SourceLocation
    stmt = CobolStatement("TEST", location)
    assert stmt.location == location
    
    expr = CobolExpression("TEST", location)
    assert expr.location == location


def test_comprehensive_workflow_integration():
    """Test comprehensive workflow with multiple statement types."""
    location = SourceLocation(1, 1)
    
    # Create a PERFORM statement that uses an expression
    perform_stmt = PerformStatement(location)
    perform_stmt.set_target_paragraph("PROCESS-RECORDS")
    
    # Create an UNTIL condition with nested expressions
    # UNTIL (RECORD-COUNT >= MAX-RECORDS) OR (EOF-FLAG = 'Y')
    
    # Left condition: RECORD-COUNT >= MAX-RECORDS
    left_cond = ConditionalExpression(">=", SourceLocation(1, 20))
    left_cond.set_left_operand("RECORD-COUNT")
    left_cond.set_right_operand("MAX-RECORDS")
    
    # Right condition: EOF-FLAG = 'Y'
    right_cond = ConditionalExpression("=", SourceLocation(1, 50))
    right_cond.set_left_operand("EOF-FLAG")
    right_cond.set_right_operand("'Y'")
    
    # Combine with OR
    or_expr = LogicalExpression("OR", SourceLocation(1, 40))
    or_expr.set_left_condition(left_cond)
    or_expr.set_right_condition(right_cond)
    
    perform_stmt.set_until_clause(or_expr)
    
    # Test complete serialization
    result = perform_stmt.to_dict()
    
    # Verify structure
    assert result["statement_type"] == "PERFORM"
    assert result["perform_type"] == "UNTIL"
    assert result["target_paragraph"] == "PROCESS-RECORDS"
    
    # Verify nested condition structure
    until_cond = result["until_condition"]
    assert until_cond["operator"] == "OR"
    
    left_serialized = until_cond["left_condition"]
    assert left_serialized["operator"] == ">="
    assert left_serialized["left_operand"] == "RECORD-COUNT"
    assert left_serialized["right_operand"] == "MAX-RECORDS"
    
    right_serialized = until_cond["right_condition"]
    assert right_serialized["operator"] == "="
    assert right_serialized["left_operand"] == "EOF-FLAG"
    assert right_serialized["right_operand"] == "'Y'"