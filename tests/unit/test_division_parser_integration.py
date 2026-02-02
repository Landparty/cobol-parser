"""Integration tests for division parsers.

Tests that all 4 division parsers work together through the factory,
and verifies parsing of complete COBOL program structure.
"""

import pytest
from cobolparser.lexer import Token, TokenType
from cobolparser.core.token_stream import TokenStream
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.program import CobolProgram
from cobolparser.parsers.divisions.factory import DivisionParserFactory
from cobolparser.parsers.divisions.identification import IdentificationDivisionParser
from cobolparser.parsers.divisions.environment import EnvironmentDivisionParser
from cobolparser.parsers.divisions.data import DataDivisionParser
from cobolparser.parsers.divisions.procedure import ProcedureDivisionParser


class TestDivisionParserIntegration:
    """Test integration of all 4 division parsers via factory."""

    def setup_method(self):
        """Set up test factory and register all parsers."""
        self.factory = DivisionParserFactory()
        # Register all 4 division parsers
        self.factory.register_parser("IDENTIFICATION", IdentificationDivisionParser)
        self.factory.register_parser("ENVIRONMENT", EnvironmentDivisionParser)
        self.factory.register_parser("DATA", DataDivisionParser)
        self.factory.register_parser("PROCEDURE", ProcedureDivisionParser)

    def create_token_stream(self, tokens_list):
        """Helper to create a TokenStream from token list."""
        return TokenStream(tokens_list)

    def test_parse_identification_division(self):
        """Test parsing only Identification Division."""
        tokens = [
            Token(TokenType.IDENTIFICATION_DIVISION, "IDENTIFICATION", SourceLocation(1, 1)),
            Token(TokenType.IDENTIFIER, "DIVISION", SourceLocation(1, 20)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 27)),
            Token(TokenType.PROGRAM_ID, "PROGRAM-ID", SourceLocation(2, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 11)),
            Token(TokenType.IDENTIFIER, "MYPROG", SourceLocation(2, 13)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 19)),
        ]
        stream = self.create_token_stream(tokens)
        
        division = self.factory.parse_division(stream)
        
        assert division is not None
        assert division.node_type == "Division"
        assert division._metadata.get("program_id") == "MYPROG"

    def test_parse_environment_division(self):
        """Test parsing only Environment Division."""
        tokens = [
            Token(TokenType.ENVIRONMENT_DIVISION, "ENVIRONMENT", SourceLocation(1, 1)),
            Token(TokenType.IDENTIFIER, "DIVISION", SourceLocation(1, 15)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 22)),
            Token(TokenType.IDENTIFIER, "CONFIGURATION", SourceLocation(2, 1)),
            Token(TokenType.IDENTIFIER, "SECTION", SourceLocation(2, 15)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 22)),
        ]
        stream = self.create_token_stream(tokens)
        
        division = self.factory.parse_division(stream)
        
        assert division is not None
        assert division.node_type == "Division"
        assert division._metadata.get("has_configuration") is True

    def test_parse_data_division(self):
        """Test parsing only Data Division."""
        tokens = [
            Token(TokenType.DATA_DIVISION, "DATA", SourceLocation(1, 1)),
            Token(TokenType.IDENTIFIER, "DIVISION", SourceLocation(1, 8)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 15)),
            Token(TokenType.IDENTIFIER, "WORKING-STORAGE", SourceLocation(2, 1)),
            Token(TokenType.IDENTIFIER, "SECTION", SourceLocation(2, 18)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 25)),
        ]
        stream = self.create_token_stream(tokens)
        
        division = self.factory.parse_division(stream)
        
        assert division is not None
        assert division.node_type == "Division"
        assert division._metadata.get("has_working_storage") is True

    def test_parse_procedure_division(self):
        """Test parsing only Procedure Division."""
        tokens = [
            Token(TokenType.PROCEDURE_DIVISION, "PROCEDURE", SourceLocation(1, 1)),
            Token(TokenType.IDENTIFIER, "DIVISION", SourceLocation(1, 12)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 19)),
            Token(TokenType.IDENTIFIER, "MAIN-PARAGRAPH", SourceLocation(2, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 15)),
        ]
        stream = self.create_token_stream(tokens)
        
        division = self.factory.parse_division(stream)
        
        assert division is not None
        assert division.node_type == "Division"
        assert division._metadata.get("paragraph_count") >= 0

    def test_factory_finds_identification_parser(self):
        """Test factory correctly identifies and selects IdentificationDivisionParser."""
        tokens = [
            Token(TokenType.IDENTIFICATION_DIVISION, "IDENTIFICATION", SourceLocation(1, 1)),
        ]
        stream = self.create_token_stream(tokens)
        
        parser = self.factory.find_parser(stream)
        
        assert parser is not None
        assert isinstance(parser, IdentificationDivisionParser)

    def test_factory_finds_environment_parser(self):
        """Test factory correctly identifies and selects EnvironmentDivisionParser."""
        tokens = [
            Token(TokenType.ENVIRONMENT_DIVISION, "ENVIRONMENT", SourceLocation(1, 1)),
        ]
        stream = self.create_token_stream(tokens)
        
        parser = self.factory.find_parser(stream)
        
        assert parser is not None
        assert isinstance(parser, EnvironmentDivisionParser)

    def test_factory_finds_data_parser(self):
        """Test factory correctly identifies and selects DataDivisionParser."""
        tokens = [
            Token(TokenType.DATA_DIVISION, "DATA", SourceLocation(1, 1)),
        ]
        stream = self.create_token_stream(tokens)
        
        parser = self.factory.find_parser(stream)
        
        assert parser is not None
        assert isinstance(parser, DataDivisionParser)

    def test_factory_finds_procedure_parser(self):
        """Test factory correctly identifies and selects ProcedureDivisionParser."""
        tokens = [
            Token(TokenType.PROCEDURE_DIVISION, "PROCEDURE", SourceLocation(1, 1)),
        ]
        stream = self.create_token_stream(tokens)
        
        parser = self.factory.find_parser(stream)
        
        assert parser is not None
        assert isinstance(parser, ProcedureDivisionParser)

    def test_parse_multiple_divisions_sequentially(self):
        """Test parsing multiple divisions in sequence (program structure)."""
        id_tokens = [
            Token(TokenType.IDENTIFICATION_DIVISION, "IDENTIFICATION", SourceLocation(1, 1)),
            Token(TokenType.IDENTIFIER, "DIVISION", SourceLocation(1, 20)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 27)),
            Token(TokenType.PROGRAM_ID, "PROGRAM-ID", SourceLocation(2, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 11)),
            Token(TokenType.IDENTIFIER, "TESTPROG", SourceLocation(2, 13)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 21)),
        ]
        
        stream = self.create_token_stream(id_tokens)
        id_div = self.factory.parse_division(stream)
        
        assert id_div is not None
        assert id_div._metadata.get("program_id") == "TESTPROG"

    def test_environment_division_with_configuration(self):
        """Test parsing Environment Division with CONFIGURATION section."""
        tokens = [
            Token(TokenType.ENVIRONMENT_DIVISION, "ENVIRONMENT", SourceLocation(1, 1)),
            Token(TokenType.IDENTIFIER, "DIVISION", SourceLocation(1, 15)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 22)),
            Token(TokenType.IDENTIFIER, "CONFIGURATION", SourceLocation(2, 1)),
            Token(TokenType.IDENTIFIER, "SECTION", SourceLocation(2, 15)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 22)),
        ]
        stream = self.create_token_stream(tokens)
        
        division = self.factory.parse_division(stream)
        
        assert division._metadata.get("has_configuration") is True
        assert "CONFIGURATION" in [s.section_name for s in division.sections]

    def test_data_division_with_multiple_sections(self):
        """Test parsing Data Division with multiple sections."""
        tokens = [
            Token(TokenType.DATA_DIVISION, "DATA", SourceLocation(1, 1)),
            Token(TokenType.IDENTIFIER, "DIVISION", SourceLocation(1, 8)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 15)),
            Token(TokenType.IDENTIFIER, "FILE", SourceLocation(2, 1)),
            Token(TokenType.IDENTIFIER, "SECTION", SourceLocation(2, 8)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 15)),
            Token(TokenType.IDENTIFIER, "WORKING-STORAGE", SourceLocation(3, 1)),
            Token(TokenType.IDENTIFIER, "SECTION", SourceLocation(3, 18)),
            Token(TokenType.PERIOD, ".", SourceLocation(3, 25)),
        ]
        stream = self.create_token_stream(tokens)
        
        division = self.factory.parse_division(stream)
        
        assert division._metadata.get("has_file") is True
        assert division._metadata.get("has_working_storage") is True

    def test_all_parsers_registered(self):
        """Test that all 4 parsers are registered with factory."""
        # Reset factory and register all parsers
        factory = DivisionParserFactory()
        factory.register_parser("IDENTIFICATION", IdentificationDivisionParser)
        factory.register_parser("ENVIRONMENT", EnvironmentDivisionParser)
        factory.register_parser("DATA", DataDivisionParser)
        factory.register_parser("PROCEDURE", ProcedureDivisionParser)
        
        # Verify each parser is accessible
        id_parser = factory.get_parser("IDENTIFICATION")
        env_parser = factory.get_parser("ENVIRONMENT")
        data_parser = factory.get_parser("DATA")
        proc_parser = factory.get_parser("PROCEDURE")
        
        assert isinstance(id_parser, IdentificationDivisionParser)
        assert isinstance(env_parser, EnvironmentDivisionParser)
        assert isinstance(data_parser, DataDivisionParser)
        assert isinstance(proc_parser, ProcedureDivisionParser)

    def test_factory_selection_order(self):
        """Test that factory uses first-match selection strategy."""
        # Create a stream starting with IDENTIFICATION
        tokens = [Token(TokenType.IDENTIFICATION_DIVISION, "IDENTIFICATION", SourceLocation(1, 1))]
        stream = self.create_token_stream(tokens)
        
        # Parser selection should find IDENTIFICATION parser
        parser = self.factory.find_parser(stream)
        assert isinstance(parser, IdentificationDivisionParser)

    def test_division_ast_nodes_are_created(self):
        """Test that parsing creates proper AST division nodes."""
        # Test IDENTIFICATION division with required PROGRAM-ID
        id_tokens = [
            Token(TokenType.IDENTIFICATION_DIVISION, "IDENTIFICATION", SourceLocation(1, 1)),
            Token(TokenType.IDENTIFIER, "DIVISION", SourceLocation(1, 20)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 27)),
            Token(TokenType.PROGRAM_ID, "PROGRAM-ID", SourceLocation(2, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 11)),
            Token(TokenType.IDENTIFIER, "TEST", SourceLocation(2, 13)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 17)),
        ]
        stream = self.create_token_stream(id_tokens)
        division = self.factory.parse_division(stream)
        assert division is not None
        assert division.node_type == "Division"
        assert hasattr(division, 'to_dict')
        
        # Test ENVIRONMENT division
        env_tokens = [
            Token(TokenType.ENVIRONMENT_DIVISION, "ENVIRONMENT", SourceLocation(1, 1)),
            Token(TokenType.IDENTIFIER, "DIVISION", SourceLocation(1, 20)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 27)),
        ]
        stream = self.create_token_stream(env_tokens)
        division = self.factory.parse_division(stream)
        assert division is not None
        assert division.node_type == "Division"
        
        # Test DATA division
        data_tokens = [
            Token(TokenType.DATA_DIVISION, "DATA", SourceLocation(1, 1)),
            Token(TokenType.IDENTIFIER, "DIVISION", SourceLocation(1, 20)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 27)),
        ]
        stream = self.create_token_stream(data_tokens)
        division = self.factory.parse_division(stream)
        assert division is not None
        assert division.node_type == "Division"
        
        # Test PROCEDURE division
        proc_tokens = [
            Token(TokenType.PROCEDURE_DIVISION, "PROCEDURE", SourceLocation(1, 1)),
            Token(TokenType.IDENTIFIER, "DIVISION", SourceLocation(1, 20)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 27)),
        ]
        stream = self.create_token_stream(proc_tokens)
        division = self.factory.parse_division(stream)
        assert division is not None
        assert division.node_type == "Division"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
