"""
Contract tests for IfStatement AST node.

These tests verify the stability of the IfStatement API and ensure
IBM Enterprise COBOL compliance per project guidelines.

Contract tests validate:
1. IfStatement class exists and has required public API
2. Required attributes: condition, then_statements, else_statements
3. Required methods: set_condition, add_then_statement, add_else_statement, to_dict
4. JSON serialization includes all nested branches
5. Type stability: IfStatement objects are returned consistently
"""

import pytest
from cobolparser.models.statements import IfStatement, CobolExpression, DisplayStatement
from cobolparser.models.ast_base import SourceLocation


class TestIfStatementContract:
    """Contract tests for IfStatement class."""
    
    def test_if_statement_class_exists(self):
        """Test that IfStatement class is properly defined."""
        assert IfStatement is not None
        assert hasattr(IfStatement, '__init__')
    
    def test_if_statement_creation(self):
        """Test basic IfStatement creation."""
        location = SourceLocation(1, 1)
        if_stmt = IfStatement(location)
        
        assert if_stmt is not None
        assert if_stmt.statement_type == "IF"
        assert if_stmt.location == location
    
    def test_if_statement_required_attributes(self):
        """Test that IfStatement has all required attributes."""
        location = SourceLocation(1, 1)
        if_stmt = IfStatement(location)
        
        # Check required attributes exist
        assert hasattr(if_stmt, 'condition')
        assert hasattr(if_stmt, 'then_statements')
        assert hasattr(if_stmt, 'else_statements')
        
        # Check initial values
        assert if_stmt.condition is None
        assert isinstance(if_stmt.then_statements, list)
        assert isinstance(if_stmt.else_statements, list)
        assert len(if_stmt.then_statements) == 0
        assert len(if_stmt.else_statements) == 0
    
    def test_if_statement_required_methods(self):
        """Test that IfStatement has all required public methods."""
        location = SourceLocation(1, 1)
        if_stmt = IfStatement(location)
        
        # Check required methods exist
        assert hasattr(if_stmt, 'set_condition')
        assert callable(if_stmt.set_condition)
        
        assert hasattr(if_stmt, 'add_then_statement')
        assert callable(if_stmt.add_then_statement)
        
        assert hasattr(if_stmt, 'add_else_statement')
        assert callable(if_stmt.add_else_statement)
        
        assert hasattr(if_stmt, 'to_dict')
        assert callable(if_stmt.to_dict)
    
    def test_set_condition_method(self):
        """Test set_condition() method."""
        location = SourceLocation(1, 1)
        if_stmt = IfStatement(location)
        
        # Create condition
        condition = CobolExpression("COMPARISON", location)
        condition._metadata["value"] = "A > B"
        
        # Set condition
        if_stmt.set_condition(condition)
        
        # Verify
        assert if_stmt.condition is not None
        assert if_stmt.condition == condition
    
    def test_add_then_statement_method(self):
        """Test add_then_statement() method."""
        location = SourceLocation(1, 1)
        if_stmt = IfStatement(location)
        
        # Create and add then statement
        display_stmt = DisplayStatement(location)
        if_stmt.add_then_statement(display_stmt)
        
        # Verify
        assert len(if_stmt.then_statements) == 1
        assert if_stmt.then_statements[0] == display_stmt
    
    def test_add_else_statement_method(self):
        """Test add_else_statement() method."""
        location = SourceLocation(1, 1)
        if_stmt = IfStatement(location)
        
        # Create and add else statement
        display_stmt = DisplayStatement(location)
        if_stmt.add_else_statement(display_stmt)
        
        # Verify
        assert len(if_stmt.else_statements) == 1
        assert if_stmt.else_statements[0] == display_stmt
    
    def test_multiple_then_statements(self):
        """Test adding multiple THEN statements."""
        location = SourceLocation(1, 1)
        if_stmt = IfStatement(location)
        
        # Add multiple then statements
        stmt1 = DisplayStatement(location)
        stmt2 = DisplayStatement(location)
        stmt3 = DisplayStatement(location)
        
        if_stmt.add_then_statement(stmt1)
        if_stmt.add_then_statement(stmt2)
        if_stmt.add_then_statement(stmt3)
        
        # Verify
        assert len(if_stmt.then_statements) == 3
        assert if_stmt.then_statements[0] == stmt1
        assert if_stmt.then_statements[1] == stmt2
        assert if_stmt.then_statements[2] == stmt3
    
    def test_multiple_else_statements(self):
        """Test adding multiple ELSE statements."""
        location = SourceLocation(1, 1)
        if_stmt = IfStatement(location)
        
        # Add multiple else statements
        stmt1 = DisplayStatement(location)
        stmt2 = DisplayStatement(location)
        
        if_stmt.add_else_statement(stmt1)
        if_stmt.add_else_statement(stmt2)
        
        # Verify
        assert len(if_stmt.else_statements) == 2
        assert if_stmt.else_statements[0] == stmt1
        assert if_stmt.else_statements[1] == stmt2


class TestIfStatementJsonSerialization:
    """Test IfStatement JSON serialization per IBM Enterprise COBOL requirements."""
    
    def test_to_dict_returns_dictionary(self):
        """Test that to_dict() returns a dictionary."""
        location = SourceLocation(1, 1)
        if_stmt = IfStatement(location)
        
        result = if_stmt.to_dict()
        
        assert isinstance(result, dict)
    
    def test_to_dict_includes_statement_type(self):
        """Test that to_dict() includes statement type."""
        location = SourceLocation(1, 1)
        if_stmt = IfStatement(location)
        
        result = if_stmt.to_dict()
        
        assert 'node_type' in result or 'statement_type' in result
    
    def test_to_dict_includes_condition(self):
        """Test that to_dict() includes condition."""
        location = SourceLocation(1, 1)
        if_stmt = IfStatement(location)
        
        condition = CobolExpression("COMPARISON", location)
        condition._metadata["value"] = "A > B"
        if_stmt.set_condition(condition)
        
        result = if_stmt.to_dict()
        
        assert 'condition' in result
        assert result['condition'] is not None
    
    def test_to_dict_includes_then_statements(self):
        """Test that to_dict() includes then_statements."""
        location = SourceLocation(1, 1)
        if_stmt = IfStatement(location)
        
        stmt = DisplayStatement(location)
        if_stmt.add_then_statement(stmt)
        
        result = if_stmt.to_dict()
        
        assert 'then_statements' in result
        assert isinstance(result['then_statements'], list)
        assert len(result['then_statements']) == 1
    
    def test_to_dict_includes_else_statements(self):
        """Test that to_dict() includes else_statements."""
        location = SourceLocation(1, 1)
        if_stmt = IfStatement(location)
        
        stmt = DisplayStatement(location)
        if_stmt.add_else_statement(stmt)
        
        result = if_stmt.to_dict()
        
        assert 'else_statements' in result
        assert isinstance(result['else_statements'], list)
        assert len(result['else_statements']) == 1
    
    def test_to_dict_includes_location(self):
        """Test that to_dict() includes source location information."""
        location = SourceLocation(5, 10)
        if_stmt = IfStatement(location)
        
        result = if_stmt.to_dict()
        
        assert 'location' in result
        assert result['location'] is not None
    
    def test_to_dict_with_complex_structure(self):
        """Test to_dict() with condition and multiple statements."""
        location = SourceLocation(1, 1)
        if_stmt = IfStatement(location)
        
        # Set condition
        condition = CobolExpression("COMPARISON", location)
        condition._metadata["value"] = "X > 0"
        if_stmt.set_condition(condition)
        
        # Add then statements
        then_stmt1 = DisplayStatement(location)
        then_stmt2 = DisplayStatement(location)
        if_stmt.add_then_statement(then_stmt1)
        if_stmt.add_then_statement(then_stmt2)
        
        # Add else statements
        else_stmt = DisplayStatement(location)
        if_stmt.add_else_statement(else_stmt)
        
        # Serialize
        result = if_stmt.to_dict()
        
        # Verify structure
        assert 'condition' in result
        assert 'then_statements' in result
        assert 'else_statements' in result
        assert len(result['then_statements']) == 2
        assert len(result['else_statements']) == 1


class TestIfStatementNesting:
    """Test nested IfStatement structures."""
    
    def test_nested_if_in_then_branch(self):
        """Test nested IF statement in THEN branch."""
        location = SourceLocation(1, 1)
        
        # Create outer IF
        outer_if = IfStatement(location)
        outer_cond = CobolExpression("COMPARISON", location)
        outer_if.set_condition(outer_cond)
        
        # Create inner IF
        inner_if = IfStatement(location)
        inner_cond = CobolExpression("COMPARISON", location)
        inner_if.set_condition(inner_cond)
        
        # Nest inner IF in outer IF's THEN branch
        outer_if.add_then_statement(inner_if)
        
        # Verify nesting
        assert len(outer_if.then_statements) == 1
        assert outer_if.then_statements[0] == inner_if
        assert isinstance(outer_if.then_statements[0], IfStatement)
    
    def test_nested_if_in_else_branch(self):
        """Test nested IF statement in ELSE branch."""
        location = SourceLocation(1, 1)
        
        # Create outer IF
        outer_if = IfStatement(location)
        outer_cond = CobolExpression("COMPARISON", location)
        outer_if.set_condition(outer_cond)
        
        # Create inner IF
        inner_if = IfStatement(location)
        inner_cond = CobolExpression("COMPARISON", location)
        inner_if.set_condition(inner_cond)
        
        # Nest inner IF in outer IF's ELSE branch
        outer_if.add_else_statement(inner_if)
        
        # Verify nesting
        assert len(outer_if.else_statements) == 1
        assert outer_if.else_statements[0] == inner_if
        assert isinstance(outer_if.else_statements[0], IfStatement)
    
    def test_deeply_nested_if_statements(self):
        """Test deeply nested IF statements (3 levels)."""
        location = SourceLocation(1, 1)
        
        # Level 1
        level1 = IfStatement(location)
        level1.set_condition(CobolExpression("COMPARISON", location))
        
        # Level 2
        level2 = IfStatement(location)
        level2.set_condition(CobolExpression("COMPARISON", location))
        level1.add_then_statement(level2)
        
        # Level 3
        level3 = IfStatement(location)
        level3.set_condition(CobolExpression("COMPARISON", location))
        level2.add_then_statement(level3)
        
        # Verify nesting
        assert isinstance(level1.then_statements[0], IfStatement)
        assert isinstance(level1.then_statements[0].then_statements[0], IfStatement)
        
        # Serialize and verify
        result = level1.to_dict()
        assert 'then_statements' in result
        assert len(result['then_statements']) == 1


class TestIfStatementTypeStability:
    """Test type stability of IfStatement objects."""
    
    def test_if_statement_type_after_creation(self):
        """Test that IfStatement type is stable after creation."""
        location = SourceLocation(1, 1)
        if_stmt = IfStatement(location)
        
        assert type(if_stmt).__name__ == "IfStatement"
        assert isinstance(if_stmt, IfStatement)
    
    def test_if_statement_type_with_condition(self):
        """Test that type remains stable after setting condition."""
        location = SourceLocation(1, 1)
        if_stmt = IfStatement(location)
        
        condition = CobolExpression("COMPARISON", location)
        if_stmt.set_condition(condition)
        
        assert type(if_stmt).__name__ == "IfStatement"
        assert isinstance(if_stmt, IfStatement)
    
    def test_if_statement_type_with_statements(self):
        """Test that type remains stable after adding statements."""
        location = SourceLocation(1, 1)
        if_stmt = IfStatement(location)
        
        stmt = DisplayStatement(location)
        if_stmt.add_then_statement(stmt)
        if_stmt.add_else_statement(stmt)
        
        assert type(if_stmt).__name__ == "IfStatement"
        assert isinstance(if_stmt, IfStatement)
    
    def test_if_statement_inheritance(self):
        """Test that IfStatement properly inherits from CobolStatement."""
        from cobolparser.models.statements import CobolStatement
        
        location = SourceLocation(1, 1)
        if_stmt = IfStatement(location)
        
        assert isinstance(if_stmt, CobolStatement)
        assert hasattr(if_stmt, 'statement_type')
        assert hasattr(if_stmt, 'location')
        assert hasattr(if_stmt, 'to_dict')
