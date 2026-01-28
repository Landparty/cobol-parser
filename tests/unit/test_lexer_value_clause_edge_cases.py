"""
Unit tests for COBOL lexer VALUE clause edge cases.

Tests focus on fixing issues where the lexer incorrectly enters multi-line string mode:
1. VALUE IS SPACE/SPACES/ZERO (figurative constants) should NOT trigger string mode
2. Multi-line VALUE strings interrupted by comment lines should clear string state
3. Comment lines with quotes after VALUE clause should not be treated as string continuation

Related to IC222A.CBL parsing failures.
"""

import pytest
from cobolparser.lexer import CobolLexer, TokenType
from cobolparser.models.ast_base import SourceLocation


class TestValueClauseWithFigurativeConstants:
    """Test VALUE clause with figurative constants (SPACE, SPACES, ZERO, etc.)."""

    def test_value_is_space_not_multiline_string(self):
        """VALUE IS SPACE should not trigger multi-line string mode."""
        cobol_source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       03 COR-ANSI-REFERENCE    PIC X(48) VALUE SPACE.
       01 TEST-VAR              PIC X(10) VALUE 'HELLO'.
       PROCEDURE DIVISION.
       STOP RUN.
"""
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()
        
        # Should successfully tokenize without errors
        assert tokens is not None
        assert len(tokens) > 0
        
        # Find VALUE tokens
        value_tokens = [t for t in tokens if t.type == TokenType.VALUE]
        assert len(value_tokens) == 2, "Should find 2 VALUE clauses"
        
        # Should have SPACE as an identifier/keyword, not start of string
        space_tokens = [t for t in tokens if t.value == "SPACE"]
        assert len(space_tokens) >= 1, "Should find SPACE as a token"

    def test_value_is_spaces_not_multiline_string(self):
        """VALUE IS SPACES should not trigger multi-line string mode."""
        cobol_source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 ANSI-REFERENCE        PIC X(48)    VALUE SPACES.
       PROCEDURE DIVISION.
       STOP RUN.
"""
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()
        
        assert tokens is not None
        spaces_tokens = [t for t in tokens if t.value == "SPACES"]
        assert len(spaces_tokens) >= 1, "Should find SPACES as a token"

    def test_value_is_zero_not_multiline_string(self):
        """VALUE IS ZERO should not trigger multi-line string mode."""
        cobol_source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 COUNTER               PIC 9(5) VALUE ZERO.
       01 FLAGS                 PIC X(10) VALUE ZEROS.
       PROCEDURE DIVISION.
       STOP RUN.
"""
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()
        
        assert tokens is not None
        zero_tokens = [t for t in tokens if t.value in ("ZERO", "ZEROS")]
        assert len(zero_tokens) >= 2, "Should find ZERO/ZEROS tokens"

    def test_value_followed_by_quote_elsewhere_in_line(self):
        """VALUE with quote elsewhere in line should not trigger string mode."""
        cobol_source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 TEST-VAR              PIC X(10) VALUE SPACE.      *> "COMMENT
       PROCEDURE DIVISION.
       STOP RUN.
"""
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()
        
        # Should tokenize successfully without treating comment quote as string start
        assert tokens is not None
        value_tokens = [t for t in tokens if t.type == TokenType.VALUE]
        assert len(value_tokens) == 1


class TestValueClauseWithCommentInterruption:
    """Test multi-line VALUE strings interrupted by comment lines."""

    def test_multiline_string_interrupted_by_comment_line(self):
        """Multi-line VALUE string interrupted by comment should clear state."""
        cobol_source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       02 FILLER  PIC IS X(99)    VALUE IS " FEATURE           
      *    "SS  PARAGRAPH-NAME
      *    "       REMARKS".
       01 NEXT-VAR PIC X(10) VALUE SPACE.
       PROCEDURE DIVISION.
       STOP RUN.
"""
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()
        
        # Should successfully tokenize
        assert tokens is not None
        
        # Comment lines should be tokenized as COMMENT, not as string continuation
        comment_tokens = [t for t in tokens if t.type == TokenType.COMMENT]
        assert len(comment_tokens) >= 2, "Should find comment lines"
        
        # Should still process NEXT-VAR correctly after comments
        next_var_tokens = [t for t in tokens if t.value == "NEXT-VAR"]
        assert len(next_var_tokens) >= 1, "Should find NEXT-VAR after comments"

    def test_comment_with_quote_after_value_clause(self):
        """Comment line with quote after VALUE clause should not extend string."""
        cobol_source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 TEST-RESULTS.
           02 FILLER            PIC X      VALUE SPACE.
           02 FEATURE           PIC X(20)  VALUE SPACE.
      *    THIS IS A COMMENT WITH "QUOTES" IN IT
           02 FILLER            PIC X      VALUE SPACE.
       PROCEDURE DIVISION.
       STOP RUN.
"""
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()
        
        assert tokens is not None
        
        # Comment should be separate token
        comment_tokens = [t for t in tokens if t.type == TokenType.COMMENT]
        assert len(comment_tokens) >= 1
        
        # Should have 3 VALUE clauses (not merged with comment)
        value_tokens = [t for t in tokens if t.type == TokenType.VALUE]
        assert len(value_tokens) == 3

    def test_multiline_string_without_comment_interruption_works(self):
        """Valid multi-line string continuation without comments should still work."""
        cobol_source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 LONG-MSG PIC X(200) VALUE "This is a long message that
      -"continues on the next line with proper continuation.".
       PROCEDURE DIVISION.
       STOP RUN.
"""
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()
        
        assert tokens is not None
        
        # Should have a string literal token
        string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_tokens) >= 1, "Should find the continued string"


class TestValueClauseComplexScenarios:
    """Test complex scenarios from IC222A.CBL."""

    def test_ic222a_pattern_value_space_with_comment_number(self):
        """Test the specific pattern from IC222A.CBL line 15400."""
        cobol_source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. IC222A.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       03 COR-ANSI-REFERENCE             PIC X(48) VALUE SPACE.     IC2224.2
       PROCEDURE DIVISION.
       STOP RUN.
"""
        lexer = CobolLexer(cobol_source)
        tokens = lexer.tokenize()
        
        # The ".2" at end of comment should not be treated as continuation
        assert tokens is not None
        value_tokens = [t for t in tokens if t.type == TokenType.VALUE]
        assert len(value_tokens) == 1

    def test_ic222a_pattern_multiline_feature_with_comment_quotes(self):
        """Test the specific pattern from IC222A.CBL lines 15600-15800."""
        cobol_source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. IC222A.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       02 FILLER  PIC IS X(99)    VALUE IS " FEATURE              PAIC2224.2
      *    "SS  PARAGRAPH-NAME                                          IC2224.2
      *    "       REMARKS".                                            IC2224.2
       02 FILLER                     PIC X(20)    VALUE SPACE.      IC2224.2
       PROCEDURE DIVISION.
       STOP RUN.
"""
        lexer = CobolLexer(cobol_source)
        
        # This should not raise an exception
        try:
            tokens = lexer.tokenize()
            assert tokens is not None
            
            # Should have comment tokens, not string continuation
            comment_tokens = [t for t in tokens if t.type == TokenType.COMMENT]
            assert len(comment_tokens) >= 2, "Should have at least 2 comment lines"
            
            # Should still parse the second FILLER with VALUE SPACE
            value_tokens = [t for t in tokens if t.type == TokenType.VALUE]
            assert len(value_tokens) == 2, "Should have 2 VALUE clauses"
        except Exception as e:
            pytest.fail(f"Should not raise exception: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
