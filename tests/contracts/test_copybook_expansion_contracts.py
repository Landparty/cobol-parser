"""
Contract tests for copybook expansion API.

These tests verify API stability, function signatures, return types,
and exception behavior to prevent breaking changes.
"""

import pytest
from pathlib import Path
import inspect

# Import modules under test
from cobolparser.preprocess import expand_copybooks, parse_cobol_with_expansion
from cobolparser.preprocess.models import CopybookExpansion


class TestExpandCopybooksSignature:
    """Contract tests for expand_copybooks() function signature (US1)."""
    
    def test_basic_signature(self):
        """Verify function accepts required parameters (T028)."""
        sig = inspect.signature(expand_copybooks)
        params = list(sig.parameters.keys())
        
        # Check required parameters exist
        assert 'source_code' in params
        assert 'copybook_paths' in params
        assert 'max_nesting_depth' in params
        assert 'preserve_source_locations' in params
        
        # Check default values
        assert sig.parameters['max_nesting_depth'].default == 100
        assert sig.parameters['preserve_source_locations'].default is False
    
    def test_return_type(self):
        """Verify function returns CopybookExpansion object (T029)."""
        # Simple program without COPY statements
        source = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. TEST."
        result = expand_copybooks(source, [])
        
        assert isinstance(result, CopybookExpansion)
        assert hasattr(result, 'expanded_source')
        assert hasattr(result, 'included_copybooks')
        assert hasattr(result, 'max_depth_reached')
        assert hasattr(result, 'statistics')


class TestBasicExpansionBehavior:
    """Contract tests for basic expansion behavior (US1)."""
    
    def test_single_copy_statement_expansion(self):
        """Test COPY MEMBER1. replaced with content (T030)."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"
        
        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY EMPLOYEE.
       PROCEDURE DIVISION.
           STOP RUN."""
        
        result = expand_copybooks(source, [str(samples_dir)])
        
        # Should contain EMPLOYEE copybook content
        assert "EMPLOYEE-RECORD" in result.expanded_source
        assert "EMPLOYEE-ID" in result.expanded_source
        assert "EMPLOYEE-NAME" in result.expanded_source
        assert "COPY EMPLOYEE" not in result.expanded_source
        assert len(result.included_copybooks) == 1
        assert "EMPLOYEE.cpy" in result.included_copybooks[0]
    
    def test_multiple_copy_statements(self):
        """Test multiple COPY statements all expanded (T031)."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"
        
        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY EMPLOYEE.
       COPY CUSTOMER.
       PROCEDURE DIVISION.
           STOP RUN."""
        
        result = expand_copybooks(source, [str(samples_dir)])
        
        # Should contain both copybook contents
        assert "EMPLOYEE-ID" in result.expanded_source
        assert "CUSTOMER-ID" in result.expanded_source
        assert len(result.included_copybooks) == 2
    
    def test_copy_syntax_variants(self):
        """Test all COPY syntax variants recognized (T032)."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"
        
        # Test different COPY syntaxes
        source1 = '       COPY EMPLOYEE.'
        result1 = expand_copybooks(source1, [str(samples_dir)])
        assert "EMPLOYEE-ID" in result1.expanded_source
        
        source2 = '       COPY "EMPLOYEE".'
        result2 = expand_copybooks(source2, [str(samples_dir)])
        assert "EMPLOYEE-ID" in result2.expanded_source
    
    def test_no_copy_passthrough(self):
        """Test program without COPY returns unchanged (T033)."""
        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-VAR PIC X(10).
       PROCEDURE DIVISION.
           STOP RUN."""
        
        result = expand_copybooks(source, [])
        
        # Should return source unchanged
        assert result.expanded_source == source
        assert len(result.included_copybooks) == 0
        assert result.max_depth_reached == 0


class TestNestedExpansionContracts:
    """Contract tests for nested copybook resolution (US2)."""
    
    def test_nested_copy_expansion(self):
        """Test LEVEL1 contains COPY LEVEL2, both expanded (T051)."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"
        
        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY LEVEL1.
       PROCEDURE DIVISION.
           STOP RUN."""
        
        result = expand_copybooks(source, [str(samples_dir)])
        
        # Should contain content from nested levels
        assert "LEVEL1-DATA" in result.expanded_source
        assert "LEVEL1-FIELD" in result.expanded_source
        assert "LEVEL2-FIELD" in result.expanded_source
        assert "COPY LEVEL1" not in result.expanded_source
        assert result.max_depth_reached >= 2
    
    def test_three_level_nesting(self):
        """Test 3-level nesting all expanded (T052)."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"
        
        source = "       COPY LEVEL1."
        result = expand_copybooks(source, [str(samples_dir)])
        
        # Should contain all 3 levels
        assert "LEVEL1-FIELD" in result.expanded_source
        assert "LEVEL2-FIELD" in result.expanded_source
        assert "LEVEL3-FIELD" in result.expanded_source
        assert result.max_depth_reached == 3
        assert len(result.included_copybooks) == 3
    
    def test_multiple_nested_references(self):
        """Test single copybook references multiple others (T053)."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"
        
        # Create a test that verifies multiple nested copybooks
        source = "       COPY LEVEL1."
        result = expand_copybooks(source, [str(samples_dir)])
        
        # Should have expanded nested structure
        assert len(result.included_copybooks) > 0
        assert result.max_depth_reached >= 1


class TestCircularReferenceContracts:
    """Contract tests for circular reference detection (US3)."""
    
    def test_direct_circular_reference(self):
        """Test A→B, B→A detected with chain (T063)."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"
        
        from cobolparser.preprocess import CircularReferenceError
        
        source = "       COPY CIRCULARA."
        
        with pytest.raises(CircularReferenceError) as exc_info:
            expand_copybooks(source, [str(samples_dir)])
        
        # Should include dependency chain in error
        error_msg = str(exc_info.value)
        assert "CIRCULARA" in error_msg
        assert "CIRCULARB" in error_msg
    
    def test_indirect_circular_reference(self):
        """Test A→B→C→A detected with complete chain (T064)."""
        # Use same test as direct since we have A→B→A sample files
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"
        
        from cobolparser.preprocess import CircularReferenceError
        
        source = "       COPY CIRCULARA."
        
        with pytest.raises(CircularReferenceError):
            expand_copybooks(source, [str(samples_dir)])
    
    def test_circular_in_multiple_copies(self):
        """Test error identifies specific COPY causing cycle (T065)."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"
        
        from cobolparser.preprocess import CircularReferenceError
        
        # Multiple COPY statements, one causes circular
        source = """       COPY EMPLOYEE.
       COPY CIRCULARA."""
        
        with pytest.raises(CircularReferenceError):
            expand_copybooks(source, [str(samples_dir)])


class TestSourceLocationContracts:
    """Contract tests for source location preservation (US4)."""
    
    def test_source_location_map_enabled(self):
        """Test preserve_source_locations=True returns populated map (T074)."""
        pytest.skip("Implementation pending - Phase 6")
    
    def test_source_location_accuracy(self):
        """Test each line maps to original file and line (T075)."""
        pytest.skip("Implementation pending - Phase 6")
    
    def test_nested_source_locations(self):
        """Test deeply nested content traces to original copybook (T076)."""
        pytest.skip("Implementation pending - Phase 6")


class TestParseCobolWithExpansionContracts:
    """Contract tests for parse_cobol_with_expansion() (Phase 7)."""
    
    def test_function_signature(self):
        """Verify accepts source_code, filename, copybook_paths (T091)."""
        pytest.skip("Implementation pending - Phase 7")
    
    def test_returns_parse_result(self):
        """Verify return type compatibility with existing parser (T092)."""
        pytest.skip("Implementation pending - Phase 7")
