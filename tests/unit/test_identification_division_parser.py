"""Tests for IdentificationDivisionParser.

Comprehensive test suite validating the parsing of COBOL Identification Division,
including program metadata extraction, optional clauses, and error handling.
"""

import pytest

from cobolparser.core.exceptions import ParseError
from cobolparser.core.token_stream import TokenStream
from cobolparser.lexer import Token, TokenType
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.program import CobolDivision
from cobolparser.parsers.divisions.identification import IdentificationDivisionParser


class TestIdentificationDivisionParserBasics:
    """Test basic parsing functionality of IdentificationDivisionParser."""

    def create_token_stream(self, tokens_list):
        """Helper to create a TokenStream from token list."""
        return TokenStream(tokens_list)

    def test_parser_initialization(self):
        """Test that parser initializes with correct division name."""
        parser = IdentificationDivisionParser()
        assert parser.division_name == "IDENTIFICATION"
        assert "ID" in parser.division_keywords

    def test_can_parse_identification_keyword(self):
        """Test can_parse() correctly identifies IDENTIFICATION keyword."""
        parser = IdentificationDivisionParser()
        tokens = [
            Token(
                TokenType.IDENTIFICATION_DIVISION,
                "IDENTIFICATION",
                SourceLocation(1, 1),
            )
        ]
        stream = self.create_token_stream(tokens)
        assert parser.can_parse(stream)

    def test_can_parse_id_alias(self):
        """Test can_parse() recognizes ID as short form."""
        parser = IdentificationDivisionParser()
        tokens = [Token(TokenType.IDENTIFICATION_DIVISION, "ID", SourceLocation(1, 1))]
        stream = self.create_token_stream(tokens)
        assert parser.can_parse(stream)

    def test_can_parse_empty_stream(self):
        """Test can_parse() handles empty token stream."""
        parser = IdentificationDivisionParser()
        stream = self.create_token_stream([])
        assert not parser.can_parse(stream)

    def test_can_parse_wrong_keyword(self):
        """Test can_parse() rejects non-IDENTIFICATION keywords."""
        parser = IdentificationDivisionParser()
        tokens = [Token(TokenType.DATA_DIVISION, "DATA", SourceLocation(1, 1))]
        stream = self.create_token_stream(tokens)
        assert not parser.can_parse(stream)


class TestIdentificationDivisionParsing:
    """Test Identification Division content parsing."""

    def create_token_stream(self, tokens_list):
        """Helper to create a TokenStream from token list."""
        return TokenStream(tokens_list)

    def test_parse_minimal_identification_division(self):
        """Test parsing minimal valid Identification Division (PROGRAM-ID only)."""
        parser = IdentificationDivisionParser()
        tokens = [
            Token(
                TokenType.IDENTIFICATION_DIVISION,
                "IDENTIFICATION",
                SourceLocation(1, 1),
            ),
            Token(TokenType.IDENTIFIER, "DIVISION", SourceLocation(1, 20)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 27)),
            Token(TokenType.PROGRAM_ID, "PROGRAM-ID", SourceLocation(2, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 11)),
            Token(TokenType.IDENTIFIER, "MYPROG", SourceLocation(2, 13)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 19)),
        ]
        stream = self.create_token_stream(tokens)

        result = parser.parse(stream)

        assert isinstance(result, CobolDivision)
        assert result.node_type == "Division"
        assert result._metadata.get("program_id") == "MYPROG"

    def test_parse_with_author_clause(self):
        """Test parsing Identification Division with AUTHOR clause."""
        parser = IdentificationDivisionParser()
        tokens = [
            Token(
                TokenType.IDENTIFICATION_DIVISION,
                "IDENTIFICATION",
                SourceLocation(1, 1),
            ),
            Token(TokenType.IDENTIFIER, "DIVISION", SourceLocation(1, 20)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 27)),
            Token(TokenType.PROGRAM_ID, "PROGRAM-ID", SourceLocation(2, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 11)),
            Token(TokenType.IDENTIFIER, "PAYROLL", SourceLocation(2, 13)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 20)),
            Token(TokenType.AUTHOR, "AUTHOR", SourceLocation(3, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(3, 7)),
            Token(TokenType.IDENTIFIER, "John", SourceLocation(3, 9)),
            Token(TokenType.IDENTIFIER, "Smith", SourceLocation(3, 14)),
            Token(TokenType.PERIOD, ".", SourceLocation(3, 19)),
        ]
        stream = self.create_token_stream(tokens)

        result = parser.parse(stream)

        assert isinstance(result, CobolDivision)
        assert result._metadata.get("program_id") == "PAYROLL"
        assert result._metadata.get("author") == "John Smith"

    def test_parse_with_multiple_clauses(self):
        """Test parsing with multiple optional clauses."""
        parser = IdentificationDivisionParser()
        tokens = [
            Token(
                TokenType.IDENTIFICATION_DIVISION,
                "IDENTIFICATION",
                SourceLocation(1, 1),
            ),
            Token(TokenType.IDENTIFIER, "DIVISION", SourceLocation(1, 20)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 27)),
            Token(TokenType.PROGRAM_ID, "PROGRAM-ID", SourceLocation(2, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 11)),
            Token(TokenType.IDENTIFIER, "TESTPROG", SourceLocation(2, 13)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 21)),
            Token(TokenType.AUTHOR, "AUTHOR", SourceLocation(3, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(3, 7)),
            Token(TokenType.IDENTIFIER, "Alice", SourceLocation(3, 9)),
            Token(TokenType.PERIOD, ".", SourceLocation(3, 14)),
            Token(TokenType.IDENTIFIER, "INSTALLATION", SourceLocation(4, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(4, 13)),
            Token(TokenType.STRING_LITERAL, "Test Lab", SourceLocation(4, 15)),
            Token(TokenType.PERIOD, ".", SourceLocation(4, 23)),
            Token(TokenType.DATE_WRITTEN, "DATE-WRITTEN", SourceLocation(5, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(5, 13)),
            Token(TokenType.STRING_LITERAL, "2024-01-15", SourceLocation(5, 15)),
            Token(TokenType.PERIOD, ".", SourceLocation(5, 25)),
        ]
        stream = self.create_token_stream(tokens)

        result = parser.parse(stream)

        assert isinstance(result, CobolDivision)
        assert result._metadata.get("program_id") == "TESTPROG"
        assert result._metadata.get("author") == "Alice"
        assert result._metadata.get("installation") == "Test Lab"
        assert result._metadata.get("date_written") == "2024-01-15"

    def test_parse_with_remarks(self):
        """Test parsing REMARKS clause with multi-word content."""
        parser = IdentificationDivisionParser()
        tokens = [
            Token(
                TokenType.IDENTIFICATION_DIVISION,
                "IDENTIFICATION",
                SourceLocation(1, 1),
            ),
            Token(TokenType.IDENTIFIER, "DIVISION", SourceLocation(1, 20)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 27)),
            Token(TokenType.PROGRAM_ID, "PROGRAM-ID", SourceLocation(2, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 11)),
            Token(TokenType.IDENTIFIER, "UTIL", SourceLocation(2, 13)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 17)),
            Token(TokenType.IDENTIFIER, "REMARKS", SourceLocation(3, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(3, 8)),
            Token(TokenType.IDENTIFIER, "This", SourceLocation(3, 10)),
            Token(TokenType.IDENTIFIER, "is", SourceLocation(3, 15)),
            Token(TokenType.IDENTIFIER, "a", SourceLocation(3, 18)),
            Token(TokenType.IDENTIFIER, "utility", SourceLocation(3, 20)),
            Token(TokenType.IDENTIFIER, "program", SourceLocation(3, 28)),
            Token(TokenType.PERIOD, ".", SourceLocation(3, 35)),
        ]
        stream = self.create_token_stream(tokens)

        result = parser.parse(stream)

        assert result._metadata.get("program_id") == "UTIL"
        assert result._metadata.get("remarks") == "This is a utility program"

    def test_parse_stops_at_next_division(self):
        """Test parser stops parsing at next division keyword."""
        parser = IdentificationDivisionParser()
        tokens = [
            Token(
                TokenType.IDENTIFICATION_DIVISION,
                "IDENTIFICATION",
                SourceLocation(1, 1),
            ),
            Token(TokenType.IDENTIFIER, "DIVISION", SourceLocation(1, 20)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 27)),
            Token(TokenType.PROGRAM_ID, "PROGRAM-ID", SourceLocation(2, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 11)),
            Token(TokenType.IDENTIFIER, "STOPTEST", SourceLocation(2, 13)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 21)),
            Token(TokenType.AUTHOR, "AUTHOR", SourceLocation(3, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(3, 7)),
            Token(TokenType.IDENTIFIER, "Bob", SourceLocation(3, 9)),
            Token(TokenType.PERIOD, ".", SourceLocation(3, 12)),
            Token(TokenType.DATA_DIVISION, "DATA", SourceLocation(4, 1)),  # Stop here
        ]
        stream = self.create_token_stream(tokens)

        result = parser.parse(stream)

        assert result._metadata.get("program_id") == "STOPTEST"
        assert result._metadata.get("author") == "Bob"
        # DATA_DIVISION token should remain in stream
        assert not stream.is_empty()
        assert stream.peek(0).value == "DATA"


class TestIdentificationDivisionErrorHandling:
    """Test error handling in IdentificationDivisionParser."""

    def create_token_stream(self, tokens_list):
        """Helper to create a TokenStream from token list."""
        return TokenStream(tokens_list)

    def test_error_missing_program_id(self):
        """Test error when PROGRAM-ID is missing."""
        parser = IdentificationDivisionParser()
        tokens = [
            Token(
                TokenType.IDENTIFICATION_DIVISION,
                "IDENTIFICATION",
                SourceLocation(1, 1),
            ),
            Token(TokenType.IDENTIFIER, "DIVISION", SourceLocation(1, 20)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 27)),
            Token(
                TokenType.AUTHOR, "AUTHOR", SourceLocation(2, 1)
            ),  # Missing PROGRAM-ID
            Token(TokenType.PERIOD, ".", SourceLocation(2, 7)),
        ]
        stream = self.create_token_stream(tokens)

        with pytest.raises(ParseError) as exc_info:
            parser.parse(stream)
        assert "is mandatory in IDENTIFICATION DIVISION" in str(exc_info.value)

    def test_missing_period_after_program_id_keyword_is_tolerated(self):
        """``PROGRAM-ID BADPROG.`` -- the period after the keyword is
        optional in IBM Enterprise COBOL (2026-09-15), so this parses and
        names the program rather than raising "Expected '.'"."""
        parser = IdentificationDivisionParser()
        tokens = [
            Token(
                TokenType.IDENTIFICATION_DIVISION,
                "IDENTIFICATION",
                SourceLocation(1, 1),
            ),
            Token(TokenType.IDENTIFIER, "DIVISION", SourceLocation(1, 20)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 27)),
            Token(TokenType.PROGRAM_ID, "PROGRAM-ID", SourceLocation(2, 1)),
            Token(
                TokenType.IDENTIFIER, "BADPROG", SourceLocation(2, 12)
            ),  # Missing period
        ]
        stream = self.create_token_stream(tokens)

        node = parser.parse(stream)
        assert node.metadata["program_id"] == "BADPROG"

    def test_missing_period_after_program_name_is_tolerated(self):
        """IBM Enterprise COBOL tolerates a missing period after the
        PROGRAM-ID program name (2026-08-20 real-corpus fix) -- this no
        longer raises. Isolated to just PROGRAM-ID with no trailing clause,
        unlike the old version of this test, so it actually exercises the
        PROGRAM-ID-name period check rather than a coincidentally similar
        exception from a following clause's own period check.
        """
        parser = IdentificationDivisionParser()
        tokens = [
            Token(
                TokenType.IDENTIFICATION_DIVISION,
                "IDENTIFICATION",
                SourceLocation(1, 1),
            ),
            Token(TokenType.IDENTIFIER, "DIVISION", SourceLocation(1, 20)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 27)),
            Token(TokenType.PROGRAM_ID, "PROGRAM-ID", SourceLocation(2, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 11)),
            Token(TokenType.IDENTIFIER, "NOMINALNAME", SourceLocation(2, 13)),
            # Missing period, then EOF.
        ]
        stream = self.create_token_stream(tokens)

        division_node = parser.parse(stream)
        assert division_node.metadata["program_id"] == "NOMINALNAME"

    def test_missing_period_after_program_name_with_trailing_clause(self):
        """Same tolerance, but with a following AUTHOR clause (itself
        correctly period-terminated) reached afterward -- confirms parsing
        continues past the missing period instead of stopping there.
        """
        parser = IdentificationDivisionParser()
        tokens = [
            Token(
                TokenType.IDENTIFICATION_DIVISION,
                "IDENTIFICATION",
                SourceLocation(1, 1),
            ),
            Token(TokenType.IDENTIFIER, "DIVISION", SourceLocation(1, 20)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 27)),
            Token(TokenType.PROGRAM_ID, "PROGRAM-ID", SourceLocation(2, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 11)),
            Token(TokenType.IDENTIFIER, "NOMINALNAME", SourceLocation(2, 13)),
            # Missing period here.
            Token(TokenType.AUTHOR, "AUTHOR", SourceLocation(3, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(3, 7)),
            Token(TokenType.IDENTIFIER, "SOMEONE", SourceLocation(3, 9)),
            Token(TokenType.PERIOD, ".", SourceLocation(3, 16)),
        ]
        stream = self.create_token_stream(tokens)

        division_node = parser.parse(stream)
        assert division_node.metadata["program_id"] == "NOMINALNAME"
        assert division_node.metadata["author"] == "SOMEONE"

    def test_error_empty_stream_for_program_name(self):
        """Test error when stream ends unexpectedly during PROGRAM-ID parsing."""
        parser = IdentificationDivisionParser()
        tokens = [
            Token(
                TokenType.IDENTIFICATION_DIVISION,
                "IDENTIFICATION",
                SourceLocation(1, 1),
            ),
            Token(TokenType.IDENTIFIER, "DIVISION", SourceLocation(1, 20)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 27)),
            Token(TokenType.PROGRAM_ID, "PROGRAM-ID", SourceLocation(2, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 11)),
            # EOF - missing program name
        ]
        stream = self.create_token_stream(tokens)

        with pytest.raises(ParseError) as exc_info:
            parser.parse(stream)
        assert "Expected program name" in str(exc_info.value)

    def test_error_missing_division_keyword_period(self):
        """Test error when period after DIVISION keyword is missing."""
        parser = IdentificationDivisionParser()
        tokens = [
            Token(
                TokenType.IDENTIFICATION_DIVISION,
                "IDENTIFICATION",
                SourceLocation(1, 1),
            ),
            Token(TokenType.IDENTIFIER, "DIVISION", SourceLocation(1, 20)),
            Token(
                TokenType.PROGRAM_ID, "PROGRAM-ID", SourceLocation(1, 28)
            ),  # Missing period
        ]
        stream = self.create_token_stream(tokens)

        with pytest.raises(ParseError) as exc_info:
            parser.parse(stream)
        assert "Expected '.'" in str(exc_info.value)


class TestIdentificationDivisionAST:
    """Test AST node creation and representation."""

    def create_token_stream(self, tokens_list):
        """Helper to create a TokenStream from token list."""
        return TokenStream(tokens_list)

    def test_ast_node_type(self):
        """Test that parsed result is CobolDivision AST node."""
        parser = IdentificationDivisionParser()
        tokens = [
            Token(
                TokenType.IDENTIFICATION_DIVISION,
                "IDENTIFICATION",
                SourceLocation(1, 1),
            ),
            Token(TokenType.IDENTIFIER, "DIVISION", SourceLocation(1, 20)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 27)),
            Token(TokenType.PROGRAM_ID, "PROGRAM-ID", SourceLocation(2, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 11)),
            Token(TokenType.IDENTIFIER, "MYAPP", SourceLocation(2, 13)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 18)),
        ]
        stream = self.create_token_stream(tokens)

        result = parser.parse(stream)

        assert isinstance(result, CobolDivision)
        assert result.node_type == "Division"
        assert result.location.line == 1

    def test_ast_node_metadata_serialization(self):
        """Test that AST node metadata can be serialized to dict."""
        parser = IdentificationDivisionParser()
        tokens = [
            Token(
                TokenType.IDENTIFICATION_DIVISION,
                "IDENTIFICATION",
                SourceLocation(1, 1),
            ),
            Token(TokenType.IDENTIFIER, "DIVISION", SourceLocation(1, 20)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 27)),
            Token(TokenType.PROGRAM_ID, "PROGRAM-ID", SourceLocation(2, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 11)),
            Token(TokenType.IDENTIFIER, "SERIALIZE", SourceLocation(2, 13)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 21)),
            Token(TokenType.AUTHOR, "AUTHOR", SourceLocation(3, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(3, 7)),
            Token(TokenType.IDENTIFIER, "Test", SourceLocation(3, 9)),
            Token(TokenType.IDENTIFIER, "Author", SourceLocation(3, 14)),
            Token(TokenType.PERIOD, ".", SourceLocation(3, 20)),
        ]
        stream = self.create_token_stream(tokens)

        result = parser.parse(stream)
        result_dict = result.to_dict()

        assert result_dict["node_type"] == "Division"
        assert result_dict["division_name"] == "IDENTIFICATION"
        assert result_dict["metadata"]["program_id"] == "SERIALIZE"
        assert result_dict["metadata"]["author"] == "Test Author"

    def test_ast_node_has_location(self):
        """Test that AST node includes source location."""
        parser = IdentificationDivisionParser()
        tokens = [
            Token(
                TokenType.IDENTIFICATION_DIVISION,
                "IDENTIFICATION",
                SourceLocation(5, 10),
            ),
            Token(TokenType.IDENTIFIER, "DIVISION", SourceLocation(5, 20)),
            Token(TokenType.PERIOD, ".", SourceLocation(5, 27)),
            Token(TokenType.PROGRAM_ID, "PROGRAM-ID", SourceLocation(6, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(6, 11)),
            Token(TokenType.IDENTIFIER, "LOCLOC", SourceLocation(6, 13)),
            Token(TokenType.PERIOD, ".", SourceLocation(6, 19)),
        ]
        stream = self.create_token_stream(tokens)

        result = parser.parse(stream)
        location = result.location

        assert location.line == 5
        assert location.column == 10


class TestIdentificationDivisionEdgeCases:
    """Test edge cases and special scenarios."""

    def create_token_stream(self, tokens_list):
        """Helper to create a TokenStream from token list."""
        return TokenStream(tokens_list)

    def test_case_insensitive_keywords(self):
        """Test that keywords are case-insensitive."""
        parser = IdentificationDivisionParser()
        tokens = [
            Token(
                TokenType.IDENTIFICATION_DIVISION,
                "identification",
                SourceLocation(1, 1),
            ),  # lowercase
            Token(TokenType.IDENTIFIER, "division", SourceLocation(1, 20)),  # lowercase
            Token(TokenType.PERIOD, ".", SourceLocation(1, 27)),
            Token(
                TokenType.PROGRAM_ID, "program-id", SourceLocation(2, 1)
            ),  # lowercase
            Token(TokenType.PERIOD, ".", SourceLocation(2, 11)),
            Token(TokenType.IDENTIFIER, "CASETEST", SourceLocation(2, 13)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 21)),
        ]
        stream = self.create_token_stream(tokens)

        result = parser.parse(stream)

        assert result._metadata.get("program_id") == "CASETEST"

    def test_parse_with_date_compiled(self):
        """Test parsing DATE-COMPILED clause (optional, may be omitted)."""
        parser = IdentificationDivisionParser()
        tokens = [
            Token(
                TokenType.IDENTIFICATION_DIVISION,
                "IDENTIFICATION",
                SourceLocation(1, 1),
            ),
            Token(TokenType.IDENTIFIER, "DIVISION", SourceLocation(1, 20)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 27)),
            Token(TokenType.PROGRAM_ID, "PROGRAM-ID", SourceLocation(2, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 11)),
            Token(TokenType.IDENTIFIER, "COMPDATE", SourceLocation(2, 13)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 21)),
            Token(TokenType.IDENTIFIER, "DATE-COMPILED", SourceLocation(3, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(3, 14)),
            Token(TokenType.STRING_LITERAL, "2024-01-20", SourceLocation(3, 16)),
            Token(TokenType.PERIOD, ".", SourceLocation(3, 26)),
        ]
        stream = self.create_token_stream(tokens)

        result = parser.parse(stream)

        assert result._metadata.get("program_id") == "COMPDATE"
        assert result._metadata.get("date_compiled") == "2024-01-20"

    def test_parse_with_security_clause(self):
        """Test parsing SECURITY clause."""
        parser = IdentificationDivisionParser()
        tokens = [
            Token(
                TokenType.IDENTIFICATION_DIVISION,
                "IDENTIFICATION",
                SourceLocation(1, 1),
            ),
            Token(TokenType.IDENTIFIER, "DIVISION", SourceLocation(1, 20)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 27)),
            Token(TokenType.PROGRAM_ID, "PROGRAM-ID", SourceLocation(2, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 11)),
            Token(TokenType.IDENTIFIER, "SECRET", SourceLocation(2, 13)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 19)),
            Token(TokenType.IDENTIFIER, "SECURITY", SourceLocation(3, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(3, 9)),
            Token(TokenType.STRING_LITERAL, "CONFIDENTIAL", SourceLocation(3, 11)),
            Token(TokenType.PERIOD, ".", SourceLocation(3, 23)),
        ]
        stream = self.create_token_stream(tokens)

        result = parser.parse(stream)

        assert result._metadata.get("program_id") == "SECRET"
        assert result._metadata.get("security") == "CONFIDENTIAL"

    def test_empty_clause_values(self):
        """Test handling of empty clause values."""
        parser = IdentificationDivisionParser()
        tokens = [
            Token(
                TokenType.IDENTIFICATION_DIVISION,
                "IDENTIFICATION",
                SourceLocation(1, 1),
            ),
            Token(TokenType.IDENTIFIER, "DIVISION", SourceLocation(1, 20)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 27)),
            Token(TokenType.PROGRAM_ID, "PROGRAM-ID", SourceLocation(2, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 11)),
            Token(TokenType.IDENTIFIER, "EMPTYVAL", SourceLocation(2, 13)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 21)),
            Token(TokenType.AUTHOR, "AUTHOR", SourceLocation(3, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(3, 7)),
            Token(
                TokenType.PERIOD, ".", SourceLocation(3, 9)
            ),  # Empty value (back-to-back periods)
        ]
        stream = self.create_token_stream(tokens)

        result = parser.parse(stream)

        assert result._metadata.get("program_id") == "EMPTYVAL"
        assert result._metadata.get("author") == ""

    def test_all_clauses_present(self):
        """Test parsing with all optional clauses."""
        parser = IdentificationDivisionParser()
        tokens = [
            Token(
                TokenType.IDENTIFICATION_DIVISION,
                "IDENTIFICATION",
                SourceLocation(1, 1),
            ),
            Token(TokenType.IDENTIFIER, "DIVISION", SourceLocation(1, 20)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 27)),
            Token(TokenType.PROGRAM_ID, "PROGRAM-ID", SourceLocation(2, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 11)),
            Token(TokenType.IDENTIFIER, "FULLPROG", SourceLocation(2, 13)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 21)),
            Token(TokenType.AUTHOR, "AUTHOR", SourceLocation(3, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(3, 7)),
            Token(TokenType.IDENTIFIER, "Jane", SourceLocation(3, 9)),
            Token(TokenType.PERIOD, ".", SourceLocation(3, 13)),
            Token(TokenType.IDENTIFIER, "INSTALLATION", SourceLocation(4, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(4, 13)),
            Token(TokenType.STRING_LITERAL, "NY Office", SourceLocation(4, 15)),
            Token(TokenType.PERIOD, ".", SourceLocation(4, 24)),
            Token(TokenType.DATE_WRITTEN, "DATE-WRITTEN", SourceLocation(5, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(5, 13)),
            Token(TokenType.STRING_LITERAL, "2024-01-01", SourceLocation(5, 15)),
            Token(TokenType.PERIOD, ".", SourceLocation(5, 25)),
            Token(TokenType.IDENTIFIER, "DATE-COMPILED", SourceLocation(6, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(6, 14)),
            Token(TokenType.STRING_LITERAL, "2024-01-22", SourceLocation(6, 16)),
            Token(TokenType.PERIOD, ".", SourceLocation(6, 26)),
            Token(TokenType.IDENTIFIER, "REMARKS", SourceLocation(7, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(7, 8)),
            Token(TokenType.IDENTIFIER, "Full", SourceLocation(7, 10)),
            Token(TokenType.IDENTIFIER, "test", SourceLocation(7, 15)),
            Token(TokenType.PERIOD, ".", SourceLocation(7, 19)),
            Token(TokenType.IDENTIFIER, "SECURITY", SourceLocation(8, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(8, 9)),
            Token(TokenType.STRING_LITERAL, "UNCLASSIFIED", SourceLocation(8, 11)),
            Token(TokenType.PERIOD, ".", SourceLocation(8, 23)),
        ]
        stream = self.create_token_stream(tokens)

        result = parser.parse(stream)

        assert result._metadata.get("program_id") == "FULLPROG"
        assert result._metadata.get("author") == "Jane"
        assert result._metadata.get("installation") == "NY Office"
        assert result._metadata.get("date_written") == "2024-01-01"
        assert result._metadata.get("date_compiled") == "2024-01-22"
        assert result._metadata.get("remarks") == "Full test"
        assert result._metadata.get("security") == "UNCLASSIFIED"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
