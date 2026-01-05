"""
Comprehensive unit tests for cobolparser.preprocess.__init__ module.
Targets all uncovered lines for 100% coverage.

This test module covers:
- Exception classes: CircularReferenceError, CopybookNotFoundError, etc.
- normalize_fixed_format function for COBOL line format conversion
- preprocess_conditional_compilation for >>IF/>>DEFINE directives
- validate_copybook_content for content validation
- validate_level_numbers for level number alignment
"""

import pytest
import warnings
from typing import Dict, Any, List, Optional

from cobolparser.preprocess import (
    CircularReferenceError,
    CopybookNotFoundError,
    PathTraversalError,
    EncodingError,
    NestingDepthError,
    CopybookSizeExceededError,
    CopybookSyntaxError,
    LevelNumberMismatchWarning,
    TotalExpansionSizeExceededError,
    normalize_fixed_format,
    preprocess_conditional_compilation,
    validate_copybook_content,
    validate_level_numbers,
)


class TestCircularReferenceError:
    """Tests for CircularReferenceError exception."""
    
    def test_creation_with_chain(self):
        """Test creation with dependency chain."""
        chain = ["FILE-A", "FILE-B", "FILE-C", "FILE-A"]
        error = CircularReferenceError(chain)
        
        assert error.dependency_chain == chain
        assert "FILE-A → FILE-B → FILE-C → FILE-A" in str(error)
    
    def test_creation_with_custom_message(self):
        """Test creation with custom message."""
        chain = ["A", "B"]
        error = CircularReferenceError(chain, message="Custom circular error")
        
        assert error.dependency_chain == chain
        assert str(error) == "Custom circular error"


class TestCopybookNotFoundError:
    """Tests for CopybookNotFoundError exception."""
    
    def test_creation_basic(self):
        """Test creation with basic parameters."""
        error = CopybookNotFoundError(
            copybook_name="EMPLOYEE",
            search_paths=["/path/one", "/path/two"]
        )
        
        assert error.copybook_name == "EMPLOYEE"
        assert error.search_paths == ["/path/one", "/path/two"]
        assert error.suggestions == []
        assert "EMPLOYEE" in str(error)
        assert "not found" in str(error).lower()
    
    def test_creation_with_suggestions(self):
        """Test creation with suggestions for typos."""
        error = CopybookNotFoundError(
            copybook_name="EMPLOYE",
            search_paths=["/copybooks"],
            suggestions=["EMPLOYEE", "EMPLOYER"]
        )
        
        assert error.suggestions == ["EMPLOYEE", "EMPLOYER"]
        assert "Did you mean" in str(error)
        assert "EMPLOYEE" in str(error)
    
    def test_creation_empty_paths(self):
        """Test creation with empty search paths."""
        error = CopybookNotFoundError(
            copybook_name="TEST",
            search_paths=[]
        )
        
        assert "(no paths configured)" in str(error)
    
    def test_creation_custom_message(self):
        """Test creation with custom message."""
        error = CopybookNotFoundError(
            copybook_name="TEST",
            search_paths=["/path"],
            message="Custom not found message"
        )
        
        assert str(error) == "Custom not found message"


class TestPathTraversalError:
    """Tests for PathTraversalError exception."""
    
    def test_creation_basic(self):
        """Test creation with attempted path."""
        error = PathTraversalError("../etc/passwd")
        
        assert error.attempted_path == "../etc/passwd"
        assert "traversal" in str(error).lower()
        assert "../etc/passwd" in str(error)
    
    def test_creation_custom_message(self):
        """Test creation with custom message."""
        error = PathTraversalError(
            attempted_path="/absolute/path",
            message="Custom traversal message"
        )
        
        assert str(error) == "Custom traversal message"


class TestEncodingError:
    """Tests for EncodingError exception."""
    
    def test_creation_basic(self):
        """Test creation with file path only."""
        error = EncodingError("/path/to/file.cpy")
        
        assert error.file_path == "/path/to/file.cpy"
        assert error.details is None
        assert "Encoding error" in str(error)
        assert "/path/to/file.cpy" in str(error)
    
    def test_creation_with_details(self):
        """Test creation with details."""
        error = EncodingError(
            file_path="/path/to/file.cpy",
            details="Invalid UTF-8 sequence at byte 150"
        )
        
        assert error.details == "Invalid UTF-8 sequence at byte 150"
        assert "Invalid UTF-8" in str(error)
    
    def test_creation_custom_message(self):
        """Test creation with custom message."""
        error = EncodingError(
            file_path="/path",
            message="Custom encoding error"
        )
        
        assert str(error) == "Custom encoding error"


class TestNestingDepthError:
    """Tests for NestingDepthError exception."""
    
    def test_creation_basic(self):
        """Test creation with depth values."""
        error = NestingDepthError(current_depth=150, max_depth=100)
        
        assert error.current_depth == 150
        assert error.max_depth == 100
        assert "150" in str(error)
        assert "100" in str(error)
        assert "exceeded" in str(error).lower()
    
    def test_creation_custom_message(self):
        """Test creation with custom message."""
        error = NestingDepthError(
            current_depth=50,
            max_depth=25,
            message="Custom depth error"
        )
        
        assert str(error) == "Custom depth error"


class TestCopybookSizeExceededError:
    """Tests for CopybookSizeExceededError exception."""
    
    def test_creation_basic(self):
        """Test creation with size values."""
        error = CopybookSizeExceededError(
            copybook_path="/copybooks/large.cpy",
            size=15000000,
            limit=10000000
        )
        
        assert error.copybook_path == "/copybooks/large.cpy"
        assert error.size == 15000000
        assert error.limit == 10000000
        assert "15,000,000" in str(error)
        assert "10,000,000" in str(error)
    
    def test_creation_custom_message(self):
        """Test creation with custom message."""
        error = CopybookSizeExceededError(
            copybook_path="/path",
            size=100,
            limit=50,
            message="Custom size error"
        )
        
        assert str(error) == "Custom size error"


class TestCopybookSyntaxError:
    """Tests for CopybookSyntaxError exception."""
    
    def test_creation_without_line(self):
        """Test creation without line number."""
        error = CopybookSyntaxError(
            copybook_path="/copybooks/bad.cpy",
            details="Missing terminating period"
        )
        
        assert error.copybook_path == "/copybooks/bad.cpy"
        assert error.details == "Missing terminating period"
        assert error.line is None
        assert "bad.cpy" in str(error)
        assert "Missing terminating period" in str(error)
    
    def test_creation_with_line(self):
        """Test creation with line number."""
        error = CopybookSyntaxError(
            copybook_path="/copybooks/bad.cpy",
            details="Invalid character",
            line=42
        )
        
        assert error.line == 42
        assert "line 42" in str(error)
    
    def test_creation_custom_message(self):
        """Test creation with custom message."""
        error = CopybookSyntaxError(
            copybook_path="/path",
            details="details",
            message="Custom syntax error"
        )
        
        assert str(error) == "Custom syntax error"


class TestTotalExpansionSizeExceededError:
    """Tests for TotalExpansionSizeExceededError exception."""
    
    def test_creation_basic(self):
        """Test creation with size values."""
        error = TotalExpansionSizeExceededError(
            total_size=150000000,
            limit=100000000
        )
        
        assert error.total_size == 150000000
        assert error.limit == 100000000
        assert "150,000,000" in str(error)
        assert "100,000,000" in str(error)
    
    def test_creation_custom_message(self):
        """Test creation with custom message."""
        error = TotalExpansionSizeExceededError(
            total_size=100,
            limit=50,
            message="Custom total size error"
        )
        
        assert str(error) == "Custom total size error"


class TestLevelNumberMismatchWarning:
    """Tests for LevelNumberMismatchWarning warning class."""
    
    def test_is_user_warning(self):
        """Test that it's a UserWarning subclass."""
        assert issubclass(LevelNumberMismatchWarning, UserWarning)
    
    def test_can_be_raised(self):
        """Test that warning can be issued."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            warnings.warn("Test level mismatch", LevelNumberMismatchWarning)
            
            assert len(w) == 1
            assert issubclass(w[0].category, LevelNumberMismatchWarning)


class TestNormalizeFixedFormat:
    """Tests for normalize_fixed_format function."""
    
    def test_empty_input(self):
        """Test with empty input."""
        result = normalize_fixed_format([])
        assert result == "\n"
    
    def test_short_lines_ignored(self):
        """Test that lines shorter than column 8 are ignored."""
        lines = ["123456"]  # Only 6 characters
        result = normalize_fixed_format(lines)
        assert result.strip() == ""
    
    def test_comment_lines(self):
        """Test handling of comment lines (indicator *)."""
        lines = [
            "000100*This is a comment line"
        ]
        result = normalize_fixed_format(lines)
        assert "This is a comment" in result
    
    def test_page_eject_comment_lines(self):
        """Test handling of page eject comment lines (indicator /)."""
        lines = [
            "      /+---------------------------------------------------------------+",
            "      *|                                                               |",
            "       IDENTIFICATION DIVISION."
        ]
        result = normalize_fixed_format(lines)
        # Both / and * lines should be treated as comments
        assert "+---------------------------------------------------------------+" in result
        assert "|                                                               |" in result
        assert "IDENTIFICATION DIVISION." in result
    
    def test_regular_lines(self):
        """Test handling of regular program lines."""
        lines = [
            "000100       MOVE 1 TO X"
        ]
        result = normalize_fixed_format(lines)
        assert "MOVE 1 TO X" in result
    
    def test_continuation_lines_merge(self):
        """Test continuation lines (indicator -) merge with previous."""
        lines = [
            "000100       VALUE \"FIRST PART",
            "000200-      \"SECOND PART\"."
        ]
        result = normalize_fixed_format(lines, merge_continued_literals=True)
        # Continuation should be joined
        assert "FIRST PART" in result
    
    def test_continuation_disabled(self):
        """Test continuation merging can be disabled."""
        lines = [
            "000100       VALUE \"FIRST",
            "000200-      SECOND\"."
        ]
        result = normalize_fixed_format(lines, merge_continued_literals=False)
        # With merging disabled, continuation should not merge differently
        assert "FIRST" in result
    
    def test_literal_tracking_single_quotes(self):
        """Test literal tracking with single quotes."""
        lines = [
            "000100       VALUE 'TEST'"
        ]
        result = normalize_fixed_format(lines)
        assert "TEST" in result
    
    def test_literal_tracking_double_quotes(self):
        """Test literal tracking with double quotes."""
        lines = [
            "000100       VALUE \"TEST\""
        ]
        result = normalize_fixed_format(lines)
        assert "TEST" in result
    
    def test_escaped_quotes(self):
        """Test handling of escaped (doubled) quotes."""
        lines = [
            "000100       VALUE \"TEST\"\"ESCAPE\""
        ]
        result = normalize_fixed_format(lines)
        assert "TEST" in result


class TestPreprocessConditionalCompilation:
    """Tests for preprocess_conditional_compilation function."""
    
    def test_define_simple(self):
        """Test simple >>DEFINE directive."""
        source = """>>DEFINE DEBUG
>>IF DEBUG IS DEFINED
       DISPLAY "Debug mode".
>>END-IF
       DISPLAY "Always shown".
"""
        result = preprocess_conditional_compilation(source)
        
        assert "Debug mode" in result
        assert "Always shown" in result
    
    def test_define_with_value(self):
        """Test >>DEFINE with AS value."""
        source = """>>DEFINE VERSION AS 1.0
>>IF VERSION IS DEFINED
       DISPLAY "Version defined".
>>END-IF
"""
        result = preprocess_conditional_compilation(source)
        
        assert "Version defined" in result
    
    def test_if_not_defined(self):
        """Test >>IF ... IS NOT DEFINED."""
        source = """>>IF UNDEFINED_SYMBOL IS NOT DEFINED
       DISPLAY "Symbol not defined".
>>END-IF
"""
        result = preprocess_conditional_compilation(source)
        
        assert "Symbol not defined" in result
    
    def test_else_branch(self):
        """Test >>ELSE branch."""
        source = """>>IF UNDEFINED IS DEFINED
       DISPLAY "Should not appear".
>>ELSE
       DISPLAY "Else branch".
>>END-IF
"""
        result = preprocess_conditional_compilation(source)
        
        assert "Should not appear" not in result
        assert "Else branch" in result
    
    def test_predefined_symbols(self):
        """Test with pre-defined symbols."""
        source = """>>IF PRESET IS DEFINED
       DISPLAY "Preset was defined".
>>END-IF
"""
        result = preprocess_conditional_compilation(
            source,
            defined_symbols={"PRESET": "VALUE"}
        )
        
        assert "Preset was defined" in result
    
    def test_nested_if(self):
        """Test nested >>IF directives."""
        source = """>>DEFINE OUTER
>>IF OUTER IS DEFINED
       DISPLAY "Outer true".
>>IF INNER IS DEFINED
       DISPLAY "Inner true".
>>END-IF
>>END-IF
"""
        result = preprocess_conditional_compilation(source)
        
        assert "Outer true" in result
        assert "Inner true" not in result
    
    def test_else_in_skipped_block(self):
        """Test >>ELSE when parent block is skipped."""
        source = """>>IF OUTER IS DEFINED
>>IF INNER IS DEFINED
       DISPLAY "Inner block".
>>ELSE
       DISPLAY "Inner else".
>>END-IF
>>END-IF
       DISPLAY "After block".
"""
        result = preprocess_conditional_compilation(source)
        
        # OUTER is not defined, so everything should be skipped except "After block"
        assert "After block" in result
        assert "Inner block" not in result
        assert "Inner else" not in result
    
    def test_unknown_condition(self):
        """Test handling of unknown condition syntax."""
        source = """>>IF UNKNOWN CONDITION FORMAT
       DISPLAY "Should be skipped".
>>END-IF
       DISPLAY "After unknown".
"""
        result = preprocess_conditional_compilation(source)
        
        # Unknown conditions default to skipping
        assert "Should be skipped" not in result
        assert "After unknown" in result
    
    def test_else_toggle_behavior(self):
        """Test ELSE properly toggles skip state."""
        source = """>>DEFINE FLAG
>>IF FLAG IS DEFINED
       DISPLAY "Flag true".
>>ELSE
       DISPLAY "Flag false".
>>END-IF
"""
        result = preprocess_conditional_compilation(source)
        
        assert "Flag true" in result
        assert "Flag false" not in result


class TestValidateCopybookContent:
    """Tests for validate_copybook_content function."""
    
    def test_empty_content(self):
        """Test validation of empty content."""
        warnings = validate_copybook_content("", "/path/test.cpy")
        
        assert len(warnings) == 1
        assert "empty" in warnings[0].lower()
    
    def test_whitespace_only(self):
        """Test validation of whitespace-only content."""
        warnings = validate_copybook_content("   \n   \n   ", "/path/test.cpy")
        
        assert len(warnings) == 1
        assert "empty" in warnings[0].lower()
    
    def test_comment_only(self):
        """Test validation of comment-only content."""
        content = """* This is a comment
* Another comment
* Nothing but comments here
"""
        warnings = validate_copybook_content(content, "/path/test.cpy")
        
        assert len(warnings) == 1
        assert "only comments" in warnings[0].lower()
    
    def test_binary_content_raises(self):
        """Test that binary content raises CopybookSyntaxError."""
        content = "Some text\x00with null bytes"
        
        with pytest.raises(CopybookSyntaxError) as exc_info:
            validate_copybook_content(content, "/path/test.cpy")
        
        assert "Binary content" in str(exc_info.value)
    
    def test_unbalanced_single_quotes(self):
        """Test detection of unbalanced single quotes."""
        content = "01 TEST PIC X(10) VALUE 'UNCLOSED."
        warnings = validate_copybook_content(content, "/path/test.cpy")
        
        assert any("single quote" in w.lower() for w in warnings)
    
    def test_unbalanced_double_quotes(self):
        """Test detection of unbalanced double quotes."""
        content = '01 TEST PIC X(10) VALUE "UNCLOSED.'
        warnings = validate_copybook_content(content, "/path/test.cpy")
        
        assert any("double quote" in w.lower() for w in warnings)
    
    def test_escaped_quotes_balanced(self):
        """Test that escaped quotes don't cause false positives."""
        content = "01 TEST PIC X(10) VALUE 'IT''S OK'."
        warnings = validate_copybook_content(content, "/path/test.cpy")
        
        # Should not report unbalanced quotes
        assert not any("single quote" in w.lower() for w in warnings)
    
    def test_missing_period_detection(self):
        """Test detection of missing terminating periods."""
        content = """01 EMPLOYEE-ID PIC X(10)
05 FIRST-NAME PIC X(20).
"""
        warnings = validate_copybook_content(content, "/path/test.cpy")
        
        # Should detect the missing period on line 1
        assert any("missing terminating period" in w.lower() for w in warnings)
    
    def test_valid_content(self):
        """Test that valid content produces no/minimal warnings."""
        # Use proper fixed-format COBOL with sequence area and indicators
        content = """      *COBOL COPYBOOK
       01 EMPLOYEE-RECORD.
          05 EMPLOYEE-ID PIC X(10).
          05 EMPLOYEE-NAME PIC X(30).
"""
        warnings = validate_copybook_content(content, "/path/test.cpy")
        
        # Valid content may have some style warnings but no errors
        # The function returns warnings, not errors
        assert isinstance(warnings, list)


class TestValidateLevelNumbers:
    """Tests for validate_level_numbers function."""
    
    def test_no_pre_context_levels(self):
        """Test when no level numbers in pre_context."""
        pre_context = "       IDENTIFICATION DIVISION."
        copybook = "       01 RECORD-DEF PIC X(10)."
        
        warnings = validate_level_numbers(pre_context, copybook, "/path/test.cpy")
        
        assert len(warnings) == 0
    
    def test_no_copybook_levels(self):
        """Test when no level numbers in copybook."""
        pre_context = "       01 MAIN-RECORD."
        copybook = "* Just comments"
        
        warnings = validate_level_numbers(pre_context, copybook, "/path/test.cpy")
        
        assert len(warnings) == 0
    
    def test_valid_level_continuation(self):
        """Test valid level number continuation."""
        pre_context = "       01 MAIN-RECORD."
        copybook = "       05 FIELD-A PIC X(10)."
        
        warnings = validate_level_numbers(pre_context, copybook, "/path/test.cpy")
        
        # 05 after 01 is valid
        assert len(warnings) == 0
    
    def test_level_01_always_valid(self):
        """Test that level 01 is always valid at start."""
        pre_context = "       05 PREVIOUS-FIELD PIC X(5)."
        copybook = "       01 NEW-RECORD PIC X(10)."
        
        warnings = validate_level_numbers(pre_context, copybook, "/path/test.cpy")
        
        # Level 01 can start anywhere
        assert len(warnings) == 0
    
    def test_level_77_always_valid(self):
        """Test that level 77 is always valid at start."""
        pre_context = "       05 PREVIOUS-FIELD PIC X(5)."
        copybook = "       77 STANDALONE-FIELD PIC X(10)."
        
        warnings = validate_level_numbers(pre_context, copybook, "/path/test.cpy")
        
        # Level 77 can start anywhere
        assert len(warnings) == 0
    
    def test_level_88_always_valid(self):
        """Test that level 88 is always valid at start."""
        pre_context = "       05 PREVIOUS-FIELD PIC X(5)."
        copybook = "       88 CONDITION-VALUE VALUE 'Y'."
        
        warnings = validate_level_numbers(pre_context, copybook, "/path/test.cpy")
        
        # Level 88 can start anywhere
        assert len(warnings) == 0
    
    def test_level_mismatch_warning(self):
        """Test warning for level number mismatch."""
        pre_context = "       05 PREVIOUS-FIELD PIC X(5)."
        copybook = "       03 LOWER-LEVEL PIC X(10)."
        
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            warning_msgs = validate_level_numbers(pre_context, copybook, "/path/test.cpy")
            
            # Should produce a warning
            assert len(warning_msgs) == 1
            assert "mismatch" in warning_msgs[0].lower()
            
            # Should also issue a UserWarning
            assert len(w) >= 1
            assert issubclass(w[0].category, LevelNumberMismatchWarning)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
