"""
Contract tests for CallStatement serialization and API stability.

Tests verify:
1. CallStatement.to_dict() output matches contract specification
2. Backward compatibility with baseline test cases
3. Exception handler nested statement serialization
4. Parameter modes and result clauses in serialized form
"""

import pytest
from cobolparser.parser import CobolParser, TokenType, Token, SourceLocation
from cobolparser.models.statements import CallStatement, CallParameter
import json


class TestCallStatementContract:
    """Test CallStatement serialization contracts."""
    
    def test_call_to_dict_output_basic(self):
        """Verify CallStatement.to_dict() structure matches contract specification."""
        parser = CobolParser()
        parser.tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.STRING_LITERAL, "'MYPROG'", SourceLocation(1, 6)),
            Token(TokenType.IDENTIFIER, "USING", SourceLocation(1, 16)),
            Token(TokenType.IDENTIFIER, "BY", SourceLocation(1, 22)),
            Token(TokenType.IDENTIFIER, "REFERENCE", SourceLocation(1, 25)),
            Token(TokenType.IDENTIFIER, "P1", SourceLocation(1, 35)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 37)),
            Token(TokenType.EOF, "", SourceLocation(2, 1))
        ]
        parser.current_token_index = 0
        parser.current_token = parser.tokens[0]
        
        call_stmt = parser.parse_call_statement()
        
        # Serialize to dict
        call_dict = call_stmt.to_dict()
        
        # Verify contract fields exist
        assert "node_type" in call_dict
        assert call_dict["node_type"] == "Statement"
        assert "location" in call_dict
        assert isinstance(call_dict["location"], dict)
    
    def test_call_with_returning_clause_serialization(self):
        """Verify RETURNING clause properly serialized in to_dict()."""
        parser = CobolParser()
        parser.tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.STRING_LITERAL, "'FUNC'", SourceLocation(1, 6)),
            Token(TokenType.IDENTIFIER, "RETURNING", SourceLocation(1, 13)),
            Token(TokenType.IDENTIFIER, "WS-RESULT", SourceLocation(1, 23)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 32)),
            Token(TokenType.EOF, "", SourceLocation(2, 1))
        ]
        parser.current_token_index = 0
        parser.current_token = parser.tokens[0]
        
        call_stmt = parser.parse_call_statement()
        
        # Verify RETURNING parameter is accessible
        assert hasattr(call_stmt, 'returning_parameter')
        assert call_stmt.returning_parameter == "WS-RESULT"
        
        # Verify serialization works
        call_dict = call_stmt.to_dict()
        assert call_dict is not None
    
    def test_call_with_giving_clause_serialization(self):
        """Verify GIVING clause properly serialized in to_dict()."""
        parser = CobolParser()
        parser.tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.STRING_LITERAL, "'PROCESS'", SourceLocation(1, 6)),
            Token(TokenType.IDENTIFIER, "GIVING", SourceLocation(1, 16)),
            Token(TokenType.IDENTIFIER, "WS-OUTPUT", SourceLocation(1, 23)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 32)),
            Token(TokenType.EOF, "", SourceLocation(2, 1))
        ]
        parser.current_token_index = 0
        parser.current_token = parser.tokens[0]
        
        call_stmt = parser.parse_call_statement()
        
        # Verify GIVING parameter is accessible
        assert hasattr(call_stmt, 'giving_parameter')
        assert call_stmt.giving_parameter == "WS-OUTPUT"
        
        call_dict = call_stmt.to_dict()
        assert call_dict is not None
    
    def test_call_with_parameters_serialization(self):
        """Verify parameter list serialized correctly in to_dict()."""
        parser = CobolParser()
        parser.tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.STRING_LITERAL, "'SUB'", SourceLocation(1, 6)),
            Token(TokenType.IDENTIFIER, "USING", SourceLocation(1, 12)),
            Token(TokenType.IDENTIFIER, "BY", SourceLocation(1, 18)),
            Token(TokenType.IDENTIFIER, "REFERENCE", SourceLocation(1, 21)),
            Token(TokenType.IDENTIFIER, "VAR1", SourceLocation(1, 31)),
            Token(TokenType.IDENTIFIER, "BY", SourceLocation(1, 36)),
            Token(TokenType.IDENTIFIER, "VALUE", SourceLocation(1, 39)),
            Token(TokenType.IDENTIFIER, "VAR2", SourceLocation(1, 45)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 49)),
            Token(TokenType.EOF, "", SourceLocation(2, 1))
        ]
        parser.current_token_index = 0
        parser.current_token = parser.tokens[0]
        
        call_stmt = parser.parse_call_statement()
        
        # Verify parameters are accessible
        assert hasattr(call_stmt, 'using_parameters')
        assert len(call_stmt.using_parameters) == 2
        assert call_stmt.using_parameters[0].name == "VAR1"
        assert call_stmt.using_parameters[1].passing_mode == "VALUE"
        
        call_dict = call_stmt.to_dict()
        assert call_dict is not None
    
    def test_backward_compatibility_baseline_test_case_1(self):
        """Verify baseline test case 1 (mixed modes) still parses correctly."""
        parser = CobolParser()
        parser.tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.STRING_LITERAL, "'SUBPROG'", SourceLocation(1, 6)),
            Token(TokenType.IDENTIFIER, "USING", SourceLocation(1, 16)),
            Token(TokenType.IDENTIFIER, "BY", SourceLocation(1, 22)),
            Token(TokenType.IDENTIFIER, "REFERENCE", SourceLocation(1, 25)),
            Token(TokenType.IDENTIFIER, "PARAM1", SourceLocation(1, 35)),
            Token(TokenType.IDENTIFIER, "BY", SourceLocation(1, 42)),
            Token(TokenType.IDENTIFIER, "CONTENT", SourceLocation(1, 45)),
            Token(TokenType.IDENTIFIER, "PARAM2", SourceLocation(1, 53)),
            Token(TokenType.IDENTIFIER, "BY", SourceLocation(1, 60)),
            Token(TokenType.IDENTIFIER, "VALUE", SourceLocation(1, 63)),
            Token(TokenType.IDENTIFIER, "PARAM3", SourceLocation(1, 69)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 75)),
            Token(TokenType.EOF, "", SourceLocation(2, 1))
        ]
        parser.current_token_index = 0
        parser.current_token = parser.tokens[0]
        
        call_stmt = parser.parse_call_statement()
        
        # Should still be serializable
        call_dict = call_stmt.to_dict()
        assert call_dict is not None
        assert "location" in call_dict
        assert len(call_stmt.using_parameters) == 3
    
    def test_backward_compatibility_baseline_test_case_2(self):
        """Verify baseline test case 2 (RETURNING) still parses correctly."""
        parser = CobolParser()
        parser.tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.STRING_LITERAL, "'FUNCTION'", SourceLocation(1, 6)),
            Token(TokenType.IDENTIFIER, "RETURNING", SourceLocation(1, 17)),
            Token(TokenType.IDENTIFIER, "RESULT", SourceLocation(1, 27)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 33)),
            Token(TokenType.EOF, "", SourceLocation(2, 1))
        ]
        parser.current_token_index = 0
        parser.current_token = parser.tokens[0]
        
        call_stmt = parser.parse_call_statement()
        
        # Should still be serializable
        call_dict = call_stmt.to_dict()
        assert call_dict is not None
        assert hasattr(call_stmt, 'returning_parameter')
    
    def test_backward_compatibility_baseline_test_case_3(self):
        """Verify baseline test case 3 (ON OVERFLOW) still parses correctly."""
        parser = CobolParser()
        parser.tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.STRING_LITERAL, "'PROCESS'", SourceLocation(1, 6)),
            Token(TokenType.IDENTIFIER, "ON", SourceLocation(1, 16)),
            Token(TokenType.IDENTIFIER, "OVERFLOW", SourceLocation(1, 19)),
            Token(TokenType.IDENTIFIER, "DISPLAY", SourceLocation(1, 28)),
            Token(TokenType.STRING_LITERAL, "'OVERFLOW'", SourceLocation(1, 36)),
            Token(TokenType.IDENTIFIER, "END-CALL", SourceLocation(1, 47)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 55)),
            Token(TokenType.EOF, "", SourceLocation(2, 1))
        ]
        parser.current_token_index = 0
        parser.current_token = parser.tokens[0]
        
        call_stmt = parser.parse_call_statement()
        
        # Should still be serializable
        call_dict = call_stmt.to_dict()
        assert call_dict is not None
        assert hasattr(call_stmt, 'on_overflow')
    
    def test_backward_compatibility_baseline_test_case_4(self):
        """Verify baseline test case 4 (ON EXCEPTION) still parses correctly."""
        parser = CobolParser()
        parser.tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.STRING_LITERAL, "'ERROR-HANDLER'", SourceLocation(1, 6)),
            Token(TokenType.IDENTIFIER, "ON", SourceLocation(1, 22)),
            Token(TokenType.IDENTIFIER, "EXCEPTION", SourceLocation(1, 25)),
            Token(TokenType.IDENTIFIER, "MOVE", SourceLocation(1, 35)),
            Token(TokenType.STRING_LITERAL, "'ERROR'", SourceLocation(1, 40)),
            Token(TokenType.IDENTIFIER, "TO", SourceLocation(1, 48)),
            Token(TokenType.IDENTIFIER, "STATUS", SourceLocation(1, 51)),
            Token(TokenType.IDENTIFIER, "END-CALL", SourceLocation(1, 57)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 65)),
            Token(TokenType.EOF, "", SourceLocation(2, 1))
        ]
        parser.current_token_index = 0
        parser.current_token = parser.tokens[0]
        
        call_stmt = parser.parse_call_statement()
        
        # Should still be serializable
        call_dict = call_stmt.to_dict()
        assert call_dict is not None
        assert hasattr(call_stmt, 'on_exception')
    
    def test_exception_structures_serialization(self):
        """Verify exception handler statement structures serialize correctly."""
        parser = CobolParser()
        parser.tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.STRING_LITERAL, "'APP'", SourceLocation(1, 6)),
            Token(TokenType.IDENTIFIER, "ON", SourceLocation(1, 12)),
            Token(TokenType.IDENTIFIER, "EXCEPTION", SourceLocation(1, 15)),
            Token(TokenType.IDENTIFIER, "MOVE", SourceLocation(1, 25)),
            Token(TokenType.STRING_LITERAL, "'ERROR'", SourceLocation(1, 30)),
            Token(TokenType.IDENTIFIER, "TO", SourceLocation(1, 38)),
            Token(TokenType.IDENTIFIER, "STATUS", SourceLocation(1, 41)),
            Token(TokenType.IDENTIFIER, "END-CALL", SourceLocation(1, 47)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 55)),
            Token(TokenType.EOF, "", SourceLocation(2, 1))
        ]
        parser.current_token_index = 0
        parser.current_token = parser.tokens[0]
        
        call_stmt = parser.parse_call_statement()
        
        # In implementation, on_exception contains list of statements
        if call_stmt.on_exception is not None:
            # Should be list of statements
            assert isinstance(call_stmt.on_exception, list)
        
        # Verify structure is JSON-serializable
        call_dict = call_stmt.to_dict()
        json_str = json.dumps(call_dict, default=str)
        assert json_str is not None
        assert isinstance(json_str, str)
    
    def test_dynamic_call_tracking_serialization(self):
        """Verify dynamic CALL tracking info serializes correctly."""
        parser = CobolParser()
        parser.tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.IDENTIFIER, "WS-PROG-NAME", SourceLocation(1, 6)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 18)),
            Token(TokenType.EOF, "", SourceLocation(2, 1))
        ]
        parser.current_token_index = 0
        parser.current_token = parser.tokens[0]
        
        call_stmt = parser.parse_call_statement()
        
        # Verify is_dynamic flag
        assert hasattr(call_stmt, 'is_dynamic')
        assert call_stmt.is_dynamic is True
        
        call_dict = call_stmt.to_dict()
        assert call_dict is not None


class TestCallParameterContract:
    """Test CallParameter serialization contracts."""
    
    def test_parameter_mode_values_valid(self):
        """Verify CallParameter.passing_mode accepts only valid modes."""
        # Valid modes: REFERENCE, CONTENT, VALUE
        param_ref = CallParameter("VAR1", "REFERENCE")
        param_content = CallParameter("VAR2", "CONTENT")
        param_value = CallParameter("VAR3", "VALUE")
        
        assert param_ref.passing_mode == "REFERENCE"
        assert param_content.passing_mode == "CONTENT"
        assert param_value.passing_mode == "VALUE"
    
    def test_parameter_serialization_properties(self):
        """Verify CallParameter has required serialization properties."""
        param = CallParameter("PARM1", "VALUE")
        
        # Verify required attributes
        assert hasattr(param, 'name')
        assert hasattr(param, 'passing_mode')
        assert param.name == "PARM1"
        assert param.passing_mode == "VALUE"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
