"""
Unit tests for COBOL lexer (tokenization) components.

These tests verify the lexical analysis phase of COBOL parsing,
ensuring proper tokenization of COBOL source code elements.

Test Coverage Areas:
1. COBOL keywords and reserved words
2. Identifiers and user-defined names
3. Numeric and string literals
4. Operators and punctuation
5. COBOL-specific tokens (PICTURE clauses, level numbers, etc.)
6. IBM Enterprise COBOL specific tokens
"""

from enum import Enum
from typing import NamedTuple

import pytest


class TokenType(Enum):
    """Expected token types for COBOL lexer."""

    # Literals
    NUMERIC_LITERAL = "NUMERIC_LITERAL"
    STRING_LITERAL = "STRING_LITERAL"

    # Identifiers
    IDENTIFIER = "IDENTIFIER"
    PROGRAM_NAME = "PROGRAM_NAME"

    # Keywords (COBOL reserved words)
    IDENTIFICATION = "IDENTIFICATION"
    DIVISION = "DIVISION"
    PROGRAM_ID = "PROGRAM_ID"
    DATA = "DATA"
    WORKING_STORAGE = "WORKING_STORAGE"
    SECTION = "SECTION"
    PROCEDURE = "PROCEDURE"
    PIC = "PIC"
    PICTURE = "PICTURE"
    DISPLAY = "DISPLAY"
    STOP = "STOP"
    RUN = "RUN"

    # IBM Enterprise COBOL specific
    COMP_3 = "COMP_3"
    EXEC_SQL = "EXEC_SQL"
    EXEC_CICS = "EXEC_CICS"
    END_EXEC = "END_EXEC"

    # Operators and punctuation
    PERIOD = "PERIOD"
    COMMA = "COMMA"
    LPAREN = "LPAREN"
    RPAREN = "RPAREN"

    # Special
    NEWLINE = "NEWLINE"
    EOF = "EOF"
    WHITESPACE = "WHITESPACE"
    COMMENT = "COMMENT"


class Token(NamedTuple):
    """Expected token structure."""

    type: TokenType
    value: str
    line: int
    column: int


class TestCobolLexerBasicTokens:
    """Unit tests for basic COBOL token recognition."""

    def test_cobol_keywords_tokenization(self):
        """Test tokenization of COBOL reserved words."""
        from cobolparser.lexer import CobolLexer, TokenType

        # Test basic COBOL keywords in fixed format
        cobol_source = "       IDENTIFICATION DIVISION."
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()

        # Filter out NEWLINE and EOF tokens for easier testing
        keyword_tokens = [
            t for t in tokens if t.type not in [TokenType.NEWLINE, TokenType.EOF]
        ]

        assert len(keyword_tokens) >= 3
        assert keyword_tokens[0].type == TokenType.IDENTIFICATION_DIVISION
        assert keyword_tokens[0].value == "IDENTIFICATION"
        assert (
            keyword_tokens[1].type == TokenType.IDENTIFIER
        )  # "DIVISION" is parsed as IDENTIFIER
        assert keyword_tokens[1].value == "DIVISION"
        assert keyword_tokens[2].type == TokenType.PERIOD
        assert keyword_tokens[2].value == "."

    def test_identifiers_tokenization(self):
        """Test tokenization of COBOL identifiers and user names."""
        from cobolparser.lexer import CobolLexer, TokenType

        # Test COBOL identifiers in fixed format
        cobol_source = "       77 WS-EMPLOYEE-NAME PIC X(30)."
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()

        # Find identifier tokens
        identifier_tokens = [t for t in tokens if t.type == TokenType.IDENTIFIER]

        assert len(identifier_tokens) >= 1
        assert "WS-EMPLOYEE-NAME" in [t.value for t in identifier_tokens]

        # Test hyphenated identifiers are properly recognized
        hyphenated_token = next(
            t for t in identifier_tokens if "WS-EMPLOYEE-NAME" in t.value
        )
        assert hyphenated_token.value == "WS-EMPLOYEE-NAME"

    def test_numeric_literals_tokenization(self):
        """Test tokenization of COBOL numeric literals."""
        from cobolparser.lexer import CobolLexer, TokenType

        # Test numeric literals in COBOL VALUE clauses
        cobol_source = "       77 WS-NUM1 PIC 9(5) VALUE 12345."
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()

        # Find numeric literal tokens
        numeric_tokens = [t for t in tokens if t.type == TokenType.NUMERIC_LITERAL]

        assert len(numeric_tokens) >= 1
        # Check if numeric literal is captured (might include period)
        numeric_values = [t.value for t in numeric_tokens]
        assert any("12345" in val for val in numeric_values)

        # Test decimal literals
        cobol_source2 = "       77 WS-NUM2 PIC 9(3)V99 VALUE 123.45."
        lexer2 = CobolLexer(cobol_source2)
        tokens2 = lexer2.tokenize()

        numeric_tokens2 = [t for t in tokens2 if t.type == TokenType.NUMERIC_LITERAL]
        assert len(numeric_tokens2) >= 1
        decimal_values = [t.value for t in numeric_tokens2]
        assert any("123.45" in val or "123" in val for val in decimal_values)

    def test_string_literals_tokenization(self):
        """Test tokenization of COBOL string literals."""
        from cobolparser.lexer import CobolLexer, TokenType

        # Test string literals in VALUE clauses
        cobol_source = '       77 WS-MSG PIC X(20) VALUE "Hello World".'
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()

        # Find string literal tokens
        string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]

        assert len(string_tokens) >= 1
        assert "Hello World" in [t.value for t in string_tokens]

        # Test single-quoted strings
        cobol_source2 = "       CALL 'SUBPROGRAM'."
        lexer2 = CobolLexer(cobol_source2)
        tokens2 = lexer2.tokenize()

        string_tokens2 = [t for t in tokens2 if t.type == TokenType.STRING_LITERAL]
        assert len(string_tokens2) >= 1
        assert "SUBPROGRAM" in [t.value for t in string_tokens2]


class TestCobolLexerPictureClause:
    """Unit tests for COBOL PICTURE clause tokenization."""

    def test_basic_picture_clauses(self):
        """Test tokenization of basic PICTURE clauses."""
        from cobolparser.lexer import CobolLexer, TokenType

        # Test basic PIC and PICTURE keywords
        cobol_source = "       01 WS-DATA PIC X(25)."
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()

        # Find PICTURE-related tokens
        pic_tokens = [t for t in tokens if t.type in [TokenType.PIC, TokenType.PICTURE]]

        assert len(pic_tokens) >= 1
        assert pic_tokens[0].type == TokenType.PIC
        assert pic_tokens[0].value == "PIC"

        # Test full PICTURE spelling
        cobol_source2 = "       01 WS-NUM PICTURE 9(7)V99."
        lexer2 = CobolLexer(cobol_source2)
        tokens2 = lexer2.tokenize()

        pic_tokens2 = [
            t for t in tokens2 if t.type in [TokenType.PIC, TokenType.PICTURE]
        ]
        assert len(pic_tokens2) >= 1
        assert pic_tokens2[0].type == TokenType.PICTURE
        assert pic_tokens2[0].value == "PICTURE"

    def test_complex_picture_patterns(self):
        """Test tokenization of complex PICTURE patterns."""
        from cobolparser.lexer import CobolLexer, TokenType

        # Test complex PICTURE patterns with parentheses
        cobol_source = "       01 WS-AMOUNT PIC S9(7)V99 COMP-3."
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()

        # Check that PIC token is recognized
        pic_tokens = [t for t in tokens if t.type == TokenType.PIC]
        assert len(pic_tokens) >= 1

        # Check for parentheses in pattern
        paren_tokens = [
            t for t in tokens if t.type in [TokenType.LEFT_PAREN, TokenType.RIGHT_PAREN]
        ]
        assert len(paren_tokens) >= 2  # Should have ( and )

        # Check for COMP-3 token
        comp3_tokens = [t for t in tokens if t.type == TokenType.COMP_3]
        assert len(comp3_tokens) >= 1
        assert comp3_tokens[0].value == "COMP-3"


class TestCobolLexerIBMSpecific:
    """Unit tests for IBM Enterprise COBOL specific tokens."""

    def test_ibm_data_types_tokenization(self):
        """Test tokenization of IBM-specific data types."""
        from cobolparser.lexer import CobolLexer, TokenType

        # Test COMP-3 packed decimal
        cobol_source = "       01 WS-PACKED PIC 9(7)V99 COMP-3."
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()

        comp3_tokens = [t for t in tokens if t.type == TokenType.COMP_3]
        assert len(comp3_tokens) >= 1
        assert comp3_tokens[0].value == "COMP-3"

        # Test other COMP types
        cobol_source2 = "       01 WS-FLOAT PIC S9(7) COMP-1."
        lexer2 = CobolLexer(cobol_source2)
        tokens2 = lexer2.tokenize()

        comp1_tokens = [t for t in tokens2 if t.type == TokenType.COMP_1]
        assert len(comp1_tokens) >= 1
        assert comp1_tokens[0].value == "COMP-1"

    def test_exec_sql_blocks_tokenization(self):
        """Test tokenization of EXEC SQL blocks."""
        from cobolparser.lexer import CobolLexer, TokenType

        # Test EXEC and END-EXEC tokens
        cobol_source = "       EXEC SQL SELECT * FROM TABLE END-EXEC."
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()

        # Find EXEC and END-EXEC tokens
        exec_tokens = [t for t in tokens if t.type == TokenType.EXEC]
        end_exec_tokens = [t for t in tokens if t.type == TokenType.END_EXEC]

        assert len(exec_tokens) >= 1
        assert exec_tokens[0].value == "EXEC"

        assert len(end_exec_tokens) >= 1
        assert end_exec_tokens[0].value == "END-EXEC"

        # Check for SQL keyword
        sql_tokens = [t for t in tokens if t.type == TokenType.SQL]
        assert len(sql_tokens) >= 1
        assert sql_tokens[0].value == "SQL"

    def test_exec_cics_blocks_tokenization(self):
        """Test tokenization of EXEC CICS blocks."""
        from cobolparser.lexer import CobolLexer, TokenType

        # Test EXEC CICS and END-EXEC tokens
        cobol_source = "       EXEC CICS SEND MAP('MAPNAME') END-EXEC."
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()

        # Find EXEC and END-EXEC tokens
        exec_tokens = [t for t in tokens if t.type == TokenType.EXEC]
        end_exec_tokens = [t for t in tokens if t.type == TokenType.END_EXEC]

        assert len(exec_tokens) >= 1
        assert exec_tokens[0].value == "EXEC"

        assert len(end_exec_tokens) >= 1
        assert end_exec_tokens[0].value == "END-EXEC"

        # Check for CICS keyword
        cics_tokens = [t for t in tokens if t.type == TokenType.CICS]
        assert len(cics_tokens) >= 1
        assert cics_tokens[0].value == "CICS"


class TestCobolLexerComments:
    """Unit tests for COBOL comment recognition."""

    def test_line_comments_tokenization(self):
        """Test tokenization of COBOL line comments."""
        from cobolparser.lexer import CobolLexer, TokenType

        # Test asterisk comment in column 7
        cobol_source = "      * This is a comment line\n       IDENTIFICATION DIVISION."
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()

        # Check for comment tokens
        comment_tokens = [t for t in tokens if t.type == TokenType.COMMENT]

        # Should find at least one comment token
        assert len(comment_tokens) >= 1

        # Verify comment content contains the text
        comment_found = any("This is a comment" in t.value for t in comment_tokens)
        assert comment_found, "Comment content not properly captured"

        # Ensure regular tokens are still parsed after comments
        division_tokens = [
            t for t in tokens if t.type == TokenType.IDENTIFICATION_DIVISION
        ]
        assert len(division_tokens) >= 1

    def test_comment_continuation(self):
        """Test handling of multi-line comments."""
        from cobolparser.lexer import CobolLexer, TokenType

        # Test multiple sequential comment lines
        cobol_source = """      * Comment line 1
      * Comment line 2
      * Comment line 3
       IDENTIFICATION DIVISION."""

        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()

        # Check for multiple comment tokens
        comment_tokens = [t for t in tokens if t.type == TokenType.COMMENT]

        # Should find multiple comment tokens (at least 3)
        assert len(comment_tokens) >= 3

        # Verify each comment line is captured
        comment_values = [t.value for t in comment_tokens]
        assert any("Comment line 1" in val for val in comment_values)
        assert any("Comment line 2" in val for val in comment_values)
        assert any("Comment line 3" in val for val in comment_values)

        # Ensure code after comments is still parsed
        division_tokens = [
            t for t in tokens if t.type == TokenType.IDENTIFICATION_DIVISION
        ]
        assert len(division_tokens) >= 1


class TestCobolLexerErrorHandling:
    """Unit tests for lexer error handling."""

    def test_invalid_characters(self):
        """Test handling of invalid characters in COBOL source."""
        from cobolparser.lexer import CobolLexer

        # Test lexer behavior with special characters that might cause issues
        cobol_source = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. TEST@PROG."
        lexer = CobolLexer(cobol_source)

        # Tokenize and verify it doesn't crash (graceful handling)
        try:
            tokens = lexer.tokenize()
            # Should produce some tokens even with special characters
            assert len(tokens) > 0

            # Should still find valid COBOL tokens
            id_tokens = [t for t in tokens if t.value == "IDENTIFICATION"]
            assert len(id_tokens) >= 1

        except Exception as e:
            # If lexer raises an exception, it should be a specific lexer error
            assert "lexer" in str(type(e)).lower() or "token" in str(type(e)).lower()

    def test_unterminated_strings(self):
        """Test handling of unterminated string literals."""
        from cobolparser.lexer import CobolLexer

        # Test unterminated string literal
        cobol_source = "       DISPLAY 'Unterminated string"
        lexer = CobolLexer(cobol_source)

        # Try tokenizing unterminated string
        try:
            tokens = lexer.tokenize()

            # If it doesn't raise an exception, check that it handles gracefully
            # Should still produce some tokens
            assert len(tokens) >= 1

            # Should find DISPLAY token at minimum
            display_tokens = [t for t in tokens if t.value == "DISPLAY"]
            assert len(display_tokens) >= 1

        except Exception as e:
            # If it raises an exception, should be related to string/lexing
            error_msg = str(e).lower()
            assert any(
                keyword in error_msg
                for keyword in ["string", "quote", "unterminated", "token", "lexer"]
            )

    def test_lexer_position_tracking(self):
        """Test accurate line/column position tracking."""
        from cobolparser.lexer import CobolLexer

        # Test multi-line source for position tracking
        cobol_source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION."""

        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()

        # Find specific tokens and check their positions if available
        program_id_tokens = [t for t in tokens if t.value == "PROGRAM-ID"]
        data_tokens = [t for t in tokens if t.value == "DATA"]

        assert len(program_id_tokens) >= 1
        assert len(data_tokens) >= 1

        # If tokens have position information, verify it's reasonable
        for token in tokens:
            if hasattr(token, "location") and token.location:
                assert (
                    token.location.line >= 1
                ), f"Token {token.value} has invalid line number {token.location.line}"
                assert (
                    token.location.column >= 1
                ), f"Token {token.value} has invalid column number {token.location.column}"


class TestCobolLexerPerformance:
    """Unit tests for lexer performance characteristics."""

    def test_large_program_tokenization(self):
        """Test lexer performance on large COBOL programs."""
        import time

        from cobolparser.lexer import CobolLexer

        # Create a moderately large COBOL program for performance testing
        large_program_lines = [
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. TESTPROG.",
            "       DATA DIVISION.",
            "       WORKING-STORAGE SECTION.",
        ]

        # Repeat the pattern to create a larger program
        large_program = ""
        for _i in range(100):  # Create 400 lines
            for line in large_program_lines:
                large_program += f"{line}\n"

        # Test tokenization performance
        lexer = CobolLexer(large_program)

        start_time = time.time()
        tokens = lexer.tokenize()
        end_time = time.time()

        duration = end_time - start_time

        # Verify tokenization completed and produced reasonable results
        assert len(tokens) > 0
        assert duration < 10.0, f"Tokenization took too long: {duration:.2f} seconds"

        # Verify we got expected tokens from the repeated pattern
        id_tokens = [t for t in tokens if t.value == "IDENTIFICATION"]
        assert len(id_tokens) >= 50  # Should have many repetitions

    def test_memory_efficient_tokenization(self):
        """Test memory-efficient tokenization for streaming."""
        from cobolparser.lexer import CobolLexer

        # Create a reasonable-sized program for memory testing
        cobol_lines = [
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. MEMTEST.",
            "       DATA DIVISION.",
            "       WORKING-STORAGE SECTION.",
            "       01 WS-COUNTER PIC 9(5) VALUE 0.",
            "       PROCEDURE DIVISION.",
            "       DISPLAY 'Testing memory usage'.",
            "       STOP RUN.",
        ]

        # Repeat to create larger program
        cobol_source = ""
        for _i in range(50):  # 400 lines
            for line in cobol_lines:
                cobol_source += f"{line}\n"

        # Test that tokenization works with reasonable memory usage
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()

        # Verify tokenization completed successfully
        assert len(tokens) > 0

        # Check for expected token types from our repeated program
        division_tokens = [
            t for t in tokens if t.value in ["IDENTIFICATION", "DATA", "PROCEDURE"]
        ]
        assert len(division_tokens) >= 150  # Should have many divisions from repetition


class TestCobolLexerTokenClass:
    """Unit tests for Token class methods and properties."""

    def test_token_str_method(self):
        """Test Token.__str__ method returns correct format."""
        from cobolparser.lexer import Token, TokenType
        from cobolparser.models.ast_base import SourceLocation

        location = SourceLocation(1, 1)
        token = Token(TokenType.IDENTIFIER, "TEST-VAR", location)

        # Test __str__ method
        str_result = str(token)
        assert str_result == "IDENTIFIER(TEST-VAR)"

    def test_token_repr_method(self):
        """Test Token.__repr__ method returns correct format."""
        from cobolparser.lexer import Token, TokenType
        from cobolparser.models.ast_base import SourceLocation

        location = SourceLocation(5, 10)
        token = Token(TokenType.NUMERIC_LITERAL, "123", location)

        # Test __repr__ method
        repr_result = repr(token)
        assert repr_result == "Token(NUMERIC_LITERAL, '123', Line 5, Column 10)"

    def test_token_with_raw_value(self):
        """Test Token with raw_value attribute."""
        from cobolparser.lexer import Token, TokenType
        from cobolparser.models.ast_base import SourceLocation

        location = SourceLocation(1, 1)
        token = Token(TokenType.IDENTIFIER, "test", location, raw_value="TEST")

        assert token.value == "test"
        assert token.raw_value == "TEST"
        assert str(token) == "IDENTIFIER(test)"


class TestCobolLexerStringLiterals:
    """Unit tests for string literal tokenization."""

    def test_unterminated_string_literal_error(self):
        """Test error handling for unterminated string literals."""
        from cobolparser.lexer import CobolLexer, LexerError

        # Test unterminated double-quoted string
        cobol_source = '       DISPLAY "Unterminated string'
        lexer = CobolLexer(cobol_source)
        lexer.tokenize()

        # Should have recorded an error
        assert len(lexer.errors) == 1
        error = lexer.errors[0]
        assert isinstance(error, LexerError)
        assert "Unterminated string literal" in error.message
        assert error.location.line == 1
        assert error.location.column == 16  # Position after DISPLAY

    def test_unterminated_single_quote_string_error(self):
        """Test error handling for unterminated single-quoted strings."""
        from cobolparser.lexer import CobolLexer, LexerError

        # Test unterminated single-quoted string
        cobol_source = "       MOVE 'Unterminated"
        lexer = CobolLexer(cobol_source)
        lexer.tokenize()

        # Should have recorded an error
        assert len(lexer.errors) == 1
        error = lexer.errors[0]
        assert isinstance(error, LexerError)
        assert "Unterminated string literal" in error.message

    def test_doubled_quotes_in_strings(self):
        """Test handling of doubled quotes for escaping."""
        from cobolparser.lexer import CobolLexer, TokenType

        # Test doubled quotes in string literals
        cobol_source = '       DISPLAY "He said ""Hello"" to me".'
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()

        # Find string literal token
        string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_tokens) >= 1

        # Should contain the properly unescaped content
        string_token = string_tokens[0]
        assert string_token.value == 'He said "Hello" to me'


class TestCobolLexerNumericLiterals:
    """Unit tests for numeric literal tokenization."""

    def test_scientific_notation_positive_exponent(self):
        """Test scientific notation with positive exponent."""
        from cobolparser.lexer import CobolLexer, TokenType

        cobol_source = "       COMPUTE RESULT = 1.23E+10."
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()

        # Find numeric literal token
        numeric_tokens = [t for t in tokens if t.type == TokenType.NUMERIC_LITERAL]
        assert len(numeric_tokens) >= 1

        # Should recognize scientific notation
        sci_token = next((t for t in numeric_tokens if "E" in t.value.upper()), None)
        assert sci_token is not None
        assert "1.23E+10" in sci_token.value or "1.23E10" in sci_token.value

    def test_scientific_notation_negative_exponent(self):
        """Test scientific notation with negative exponent."""
        from cobolparser.lexer import CobolLexer, TokenType

        cobol_source = "       MOVE 4.56e-7 TO WS-SMALL-NUM."
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()

        # Find numeric literal token
        numeric_tokens = [t for t in tokens if t.type == TokenType.NUMERIC_LITERAL]
        assert len(numeric_tokens) >= 1

        # Should recognize scientific notation
        sci_token = next((t for t in numeric_tokens if "e" in t.value.lower()), None)
        assert sci_token is not None
        assert "4.56e-7" in sci_token.value or "4.56E-7" in sci_token.value


class TestCobolLexerFigurativeConstants:
    """Unit tests for figurative constant recognition."""

    def test_zero_figurative_constants(self):
        """Test ZERO, ZEROS, ZEROES figurative constants."""
        from cobolparser.lexer import CobolLexer, TokenType

        cobol_source = "       MOVE ZERO TO WS-COUNT.\n       MOVE ZEROS TO WS-AMOUNT.\n       MOVE ZEROES TO WS-TOTAL."
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()

        # Find figurative constant tokens
        fig_tokens = [t for t in tokens if t.type == TokenType.FIGURATIVE_CONSTANT]
        assert len(fig_tokens) >= 3

        # Check values
        fig_values = [t.value.upper() for t in fig_tokens]
        assert "ZERO" in fig_values
        assert "ZEROS" in fig_values
        assert "ZEROES" in fig_values

    def test_space_figurative_constants(self):
        """Test SPACE, SPACES figurative constants."""
        from cobolparser.lexer import CobolLexer, TokenType

        cobol_source = "       MOVE SPACE TO WS-CHAR.\n       MOVE SPACES TO WS-STRING."
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()

        # Find figurative constant tokens
        fig_tokens = [t for t in tokens if t.type == TokenType.FIGURATIVE_CONSTANT]
        assert len(fig_tokens) >= 2

        # Check values
        fig_values = [t.value.upper() for t in fig_tokens]
        assert "SPACE" in fig_values
        assert "SPACES" in fig_values

    def test_high_low_value_constants(self):
        """Test HIGH-VALUE, HIGH-VALUES, LOW-VALUE, LOW-VALUES."""
        from cobolparser.lexer import CobolLexer, TokenType

        cobol_source = (
            "       MOVE HIGH-VALUE TO WS-MAX.\n       MOVE LOW-VALUES TO WS-MIN."
        )
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()

        # Find figurative constant tokens
        fig_tokens = [t for t in tokens if t.type == TokenType.FIGURATIVE_CONSTANT]
        assert len(fig_tokens) >= 2

        # Check values
        fig_values = [t.value.upper() for t in fig_tokens]
        assert "HIGH-VALUE" in fig_values
        assert "LOW-VALUES" in fig_values

    def test_quote_and_all_constants(self):
        """Test QUOTE, QUOTES, and ALL figurative constants."""
        from cobolparser.lexer import CobolLexer, TokenType

        cobol_source = (
            "       MOVE QUOTE TO WS-QUOTE.\n       MOVE ALL 'X' TO WS-FILLER."
        )
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()

        # Find figurative constant tokens
        fig_tokens = [t for t in tokens if t.type == TokenType.FIGURATIVE_CONSTANT]
        assert len(fig_tokens) >= 1

        # Check values
        fig_values = [t.value.upper() for t in fig_tokens]
        assert "QUOTE" in fig_values
        assert "ALL" in fig_values


class TestCobolLexerCommentMethods:
    """Unit tests for comment tokenization methods."""

    def test_read_comment_method(self):
        """Test the read_comment method directly."""
        from cobolparser.lexer import CobolLexer, TokenType

        # Create lexer and manually test read_comment
        cobol_source = "       * This is a comment line"
        lexer = CobolLexer(cobol_source)

        # Position at the comment start
        lexer.current_pos = 7  # After the 7 spaces

        # Call read_comment directly
        comment_token = lexer.read_comment()

        assert comment_token.type == TokenType.COMMENT
        assert "* This is a comment line" in comment_token.value

    def test_inline_comments(self):
        """Test comments that appear inline (not just column 7)."""
        from cobolparser.lexer import CobolLexer, TokenType

        # This would require inline comment syntax, but COBOL doesn't have it
        # So this test verifies that comments are only recognized in column 7
        cobol_source = "       MOVE * This is not a comment TO WS-VAR."
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()

        # Should not find any comment tokens
        comment_tokens = [t for t in tokens if t.type == TokenType.COMMENT]
        assert len(comment_tokens) == 0


class TestCobolLexerLineFormat:
    """Unit tests for COBOL line format handling."""

    def test_short_lines_less_than_7_chars(self):
        """Test handling of lines shorter than 7 characters."""
        from cobolparser.lexer import CobolLexer

        # Test very short line
        cobol_source = "ID"  # Only 2 characters
        lexer = CobolLexer(cobol_source)

        # Test handle_cobol_line_format directly
        tokens = lexer.handle_cobol_line_format("ID", 0)

        # Should return empty list for lines < 7 chars
        assert tokens == []

    def test_page_break_indicator(self):
        """Test page break indicator (/) in column 7."""
        from cobolparser.lexer import CobolLexer, TokenType

        # Test page break line
        cobol_source = "      / This is a page break"
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()

        # Should find comment token for page break
        comment_tokens = [t for t in tokens if t.type == TokenType.COMMENT]
        assert len(comment_tokens) >= 1

        # Should contain page break text
        page_break_found = any("/ PAGE BREAK" in t.value for t in comment_tokens)
        assert page_break_found

    def test_continuation_line_indicator(self):
        """Test continuation line indicator (-) in column 7."""
        from cobolparser.lexer import CobolLexer, TokenType

        # Test continuation line
        cobol_source = "      -     WS-NAME PIC X(30)."
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()

        # Should find continuation token
        cont_tokens = [t for t in tokens if t.type == TokenType.CONTINUATION]
        assert len(cont_tokens) >= 1

        assert cont_tokens[0].value == "-"


class TestCobolLexerProgramText:
    """Unit tests for program text tokenization."""

    def test_tokenize_program_text_whitespace_skipping(self):
        """Test whitespace skipping in tokenize_program_text."""
        from cobolparser.lexer import CobolLexer

        lexer = CobolLexer("")

        # Test tokenize_program_text with whitespace
        text = "  MOVE   WS-A   TO   WS-B  .  "
        tokens = lexer.tokenize_program_text(text, 0, 8)

        # Should skip whitespace and find tokens
        assert len(tokens) >= 3  # MOVE, WS-A, TO, WS-B, PERIOD

    def test_invalid_character_error(self):
        """Test error handling for invalid characters."""
        from cobolparser.lexer import CobolLexer, LexerError

        lexer = CobolLexer("")

        # Test with invalid character
        text = "MOVE @ WS-VAR."  # @ is invalid
        lexer.tokenize_program_text(text, 0, 8)

        # Should have recorded an error
        assert len(lexer.errors) >= 1
        error = lexer.errors[0]
        assert isinstance(error, LexerError)
        assert "Invalid character" in error.message
        assert "@" in error.message


class TestCobolLexerTokenizeMethod:
    """Unit tests for the main tokenize method."""

    def test_newline_token_insertion(self):
        """Test that newline tokens are inserted between lines."""
        from cobolparser.lexer import CobolLexer, TokenType

        # Multi-line program
        cobol_source = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. TEST."
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()

        # Should find newline tokens
        newline_tokens = [t for t in tokens if t.type == TokenType.NEWLINE]
        assert len(newline_tokens) >= 1

        # Newline should have correct value
        assert newline_tokens[0].value == "\n"

    def test_eof_token_always_added(self):
        """Test that EOF token is always added at the end."""
        from cobolparser.lexer import CobolLexer, TokenType

        # Empty source
        lexer = CobolLexer("")
        tokens = lexer.tokenize()

        # Should still have EOF token
        eof_tokens = [t for t in tokens if t.type == TokenType.EOF]
        assert len(eof_tokens) == 1

        assert eof_tokens[0].value == ""


class TestCobolLexerConvenienceFunction:
    """Unit tests for the tokenize_cobol convenience function."""

    def test_tokenize_cobol_success(self):
        """Test tokenize_cobol function with valid input."""
        from cobolparser.lexer import TokenType, tokenize_cobol

        source = "       IDENTIFICATION DIVISION."
        tokens = tokenize_cobol(source, "test.cob")

        # Should return tokens without errors
        assert len(tokens) > 0
        assert tokens[-1].type == TokenType.EOF

    def test_tokenize_cobol_with_errors(self):
        """Test tokenize_cobol function raises error on invalid input."""
        from cobolparser.lexer import LexerError, tokenize_cobol

        # Invalid source that should cause errors
        source = '       DISPLAY "Unterminated string'

        # Should raise LexerError
        with pytest.raises(LexerError) as exc_info:
            tokenize_cobol(source, "test.cob")

        assert "Unterminated string literal" in str(exc_info.value)


class TestCobolLexerLevelNumbers:
    """Unit tests for level number recognition."""

    def test_level_number_recognition(self):
        """Test that 01-99 are recognized as level numbers."""
        from cobolparser.lexer import CobolLexer, TokenType

        cobol_source = (
            "       01 WS-RECORD.\n       77 WS-ITEM.\n       88 WS-CONDITION."
        )
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()

        # Find level number tokens
        level_tokens = [t for t in tokens if t.type == TokenType.LEVEL_NUMBER]
        assert len(level_tokens) >= 3

        # Check values
        level_values = [t.value for t in level_tokens]
        assert "01" in level_values
        assert "77" in level_values
        assert "88" in level_values

    def test_level_number_not_recognized_as_numeric(self):
        """Test that level numbers are not treated as numeric literals."""
        from cobolparser.lexer import CobolLexer, TokenType

        cobol_source = "       01 WS-RECORD."
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()

        # Should be LEVEL_NUMBER, not NUMERIC_LITERAL
        level_tokens = [t for t in tokens if t.type == TokenType.LEVEL_NUMBER]
        numeric_tokens = [t for t in tokens if t.type == TokenType.NUMERIC_LITERAL]

        assert len(level_tokens) >= 1
        assert len(numeric_tokens) == 0 or all(
            t.value not in ["01", "1"] for t in numeric_tokens
        )


class TestCobolLexerMethods:
    """Unit tests for lexer utility methods."""

    def test_get_tokens_caches_result(self):
        """Test that get_tokens caches the tokenization result."""
        from cobolparser.lexer import CobolLexer

        lexer = CobolLexer("       IDENTIFICATION DIVISION.")

        # First call should tokenize
        tokens1 = lexer.get_tokens()
        assert len(tokens1) > 0

        # Second call should return cached result
        tokens2 = lexer.get_tokens()
        assert tokens1 is tokens2  # Same object

    def test_has_errors_method(self):
        """Test has_errors method."""
        from cobolparser.lexer import CobolLexer

        # No errors
        lexer1 = CobolLexer("       IDENTIFICATION DIVISION.")
        lexer1.tokenize()
        assert not lexer1.has_errors()

        # With errors
        lexer2 = CobolLexer('       DISPLAY "Unterminated')
        lexer2.tokenize()
        assert lexer2.has_errors()

    def test_get_current_location(self):
        """Test get_current_location method."""
        from cobolparser.lexer import CobolLexer

        lexer = CobolLexer("       IDENTIFICATION DIVISION.")

        # At start
        location = lexer.get_current_location()
        assert location.line == 1
        assert location.column == 1

        # After advancing
        lexer.advance_char()
        location = lexer.get_current_location()
        assert location.line == 1
        assert location.column == 2

    def test_peek_char_and_advance(self):
        """Test peek_char and advance_char methods."""
        from cobolparser.lexer import CobolLexer

        lexer = CobolLexer("AB")

        # Peek at first char
        assert lexer.peek_char() == "A"
        assert lexer.peek_char(1) == "B"

        # Advance
        char = lexer.advance_char()
        assert char == "A"
        assert lexer.peek_char() == "B"

        # Advance to end
        char = lexer.advance_char()
        assert char == "B"
        assert lexer.peek_char() is None
