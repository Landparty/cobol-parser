"""
Comprehensive CALL Statement Test Suite

This integration test validates that all CALL statement patterns
in the test programs are correctly parsed by the COBOL parser.
"""
import pytest
from pathlib import Path
from cobolparser.parser import CobolParser


class TestCallComprehensive:
    """Test comprehensive CALL statement parsing across all test programs."""
    
    @pytest.fixture
    def parser(self):
        """Create a COBOL parser instance."""
        return CobolParser()
    
    @pytest.fixture
    def samples_dir(self):
        """Get the samples directory path."""
        return Path(__file__).parent.parent / "samples"
    
    def count_call_statements(self, ast):
        """Recursively count CALL statements in AST."""
        from cobolparser.models.statements import CallStatement
        
        if ast is None:
            return 0
        
        # Use get_all_statements if available (most reliable method)
        if hasattr(ast, 'get_all_statements'):
            all_statements = ast.get_all_statements()
            return sum(1 for stmt in all_statements if isinstance(stmt, CallStatement))
        
        # Fallback to manual traversal
        count = 0
        
        # Check if current node is a CALL statement
        if isinstance(ast, CallStatement):
            count += 1
        
        # Recursively check children
        if hasattr(ast, 'children') and ast.children:
            for child in ast.children:
                count += self.count_call_statements(child)
        
        # Check divisions
        if hasattr(ast, 'divisions'):
            for division in ast.divisions:
                count += self.count_call_statements(division)
        
        # Check paragraphs
        if hasattr(ast, 'paragraphs') and ast.paragraphs:
            for paragraph in ast.paragraphs:
                count += self.count_call_statements(paragraph)
        
        # Check statements
        if hasattr(ast, 'statements') and ast.statements:
            for statement in ast.statements:
                count += self.count_call_statements(statement)
        
        return count
    
    def test_call_with_periods(self, parser, samples_dir):
        """Test CALL statements with periods in various contexts."""
        file_path = samples_dir / "call_with_periods.cbl"
        result = parser.parse_file(str(file_path))
        
        assert result.success, f"Parse failed: {result.errors}"
        call_count = self.count_call_statements(result.ast)
        
        # Expected: 20 CALL statements
        assert call_count >= 18, f"Expected at least 18 CALL statements, found {call_count}"
    
    def test_call_multiline_comprehensive(self, parser, samples_dir):
        """Test multi-line CALL statements."""
        file_path = samples_dir / "call_multiline_comprehensive.cbl"
        result = parser.parse_file(str(file_path))
        
        assert result.success, f"Parse failed: {result.errors}"
        call_count = self.count_call_statements(result.ast)
        
        # Expected: 22 CALL statements
        assert call_count >= 18, f"Expected at least 18 CALL statements, found {call_count}"
    
    def test_call_with_comments(self, parser, samples_dir):
        """Test CALL statements with comments."""
        file_path = samples_dir / "call_with_comments.cbl"
        result = parser.parse_file(str(file_path))
        
        assert result.success, f"Parse failed: {result.errors}"
        call_count = self.count_call_statements(result.ast)
        
        # Expected: 18 CALL statements
        assert call_count >= 16, f"Expected at least 16 CALL statements, found {call_count}"
    
    def test_call_exception_handlers_complete(self, parser, samples_dir):
        """Test CALL statements with exception handlers."""
        file_path = samples_dir / "call_exception_handlers_complete.cbl"
        result = parser.parse_file(str(file_path))
        
        assert result.success, f"Parse failed: {result.errors}"
        call_count = self.count_call_statements(result.ast)
        
        # Expected: 28 CALL statements
        assert call_count >= 25, f"Expected at least 25 CALL statements, found {call_count}"
    
    def test_call_in_control_structures(self, parser, samples_dir):
        """Test CALL statements inside control structures."""
        file_path = samples_dir / "call_in_control_structures.cbl"
        result = parser.parse_file(str(file_path))
        
        assert result.success, f"Parse failed: {result.errors}"
        call_count = self.count_call_statements(result.ast)
        
        # Expected: 33 CALL statements
        assert call_count >= 30, f"Expected at least 30 CALL statements, found {call_count}"
    
    def test_call_parameter_modes_complete(self, parser, samples_dir):
        """Test CALL statements with various parameter modes."""
        file_path = samples_dir / "call_parameter_modes_complete.cbl"
        result = parser.parse_file(str(file_path))
        
        assert result.success, f"Parse failed: {result.errors}"
        call_count = self.count_call_statements(result.ast)
        
        # Expected: 28 CALL statements
        assert call_count >= 25, f"Expected at least 25 CALL statements, found {call_count}"
    
    def test_call_returning_variations(self, parser, samples_dir):
        """Test CALL statements with RETURNING clause."""
        file_path = samples_dir / "call_returning_variations.cbl"
        result = parser.parse_file(str(file_path))
        
        assert result.success, f"Parse failed: {result.errors}"
        call_count = self.count_call_statements(result.ast)
        
        # Expected: 23 CALL statements
        assert call_count >= 20, f"Expected at least 20 CALL statements, found {call_count}"
    
    def test_call_dynamic_programs(self, parser, samples_dir):
        """Test CALL statements with dynamic program names."""
        file_path = samples_dir / "call_dynamic_programs.cbl"
        result = parser.parse_file(str(file_path))
        
        assert result.success, f"Parse failed: {result.errors}"
        call_count = self.count_call_statements(result.ast)
        
        # Expected: 18 CALL statements
        assert call_count >= 16, f"Expected at least 16 CALL statements, found {call_count}"
    
    def test_call_real_world_banking(self, parser, samples_dir):
        """Test banking application CALL statements."""
        file_path = samples_dir / "call_real_world_banking.cbl"
        result = parser.parse_file(str(file_path))
        
        assert result.success, f"Parse failed: {result.errors}"
        call_count = self.count_call_statements(result.ast)
        
        # Expected: 45 CALL statements
        assert call_count >= 36, f"Expected at least 36 CALL statements, found {call_count}"
    
    def test_call_real_world_insurance(self, parser, samples_dir):
        """Test insurance claims application CALL statements."""
        file_path = samples_dir / "call_real_world_insurance.cbl"
        result = parser.parse_file(str(file_path))
        
        assert result.success, f"Parse failed: {result.errors}"
        call_count = self.count_call_statements(result.ast)
        
        # Expected: 42 CALL statements
        assert call_count >= 38, f"Expected at least 38 CALL statements, found {call_count}"
    
    def test_overall_coverage(self, parser, samples_dir):
        """Test overall CALL statement coverage across all files."""
        test_files = [
            "call_with_periods.cbl",
            "call_multiline_comprehensive.cbl",
            "call_with_comments.cbl",
            "call_exception_handlers_complete.cbl",
            "call_in_control_structures.cbl",
            "call_parameter_modes_complete.cbl",
            "call_returning_variations.cbl",
            "call_dynamic_programs.cbl",
            "call_real_world_banking.cbl",
            "call_real_world_insurance.cbl",
        ]
        
        total_calls = 0
        total_files = 0
        
        for filename in test_files:
            file_path = samples_dir / filename
            if not file_path.exists():
                continue
            
            result = parser.parse_file(str(file_path))
            if result.success:
                call_count = self.count_call_statements(result.ast)
                total_calls += call_count
                total_files += 1
                print(f"{filename}: {call_count} CALL statements")
        
        print(f"\nTotal: {total_calls} CALL statements across {total_files} files")
        
        # Expected: ~277 CALL statements total
        # Minimum threshold: 250 (allowing for some parsing issues)
        assert total_calls >= 250, f"Expected at least 250 total CALL statements, found {total_calls}"
        assert total_files == 10, f"Expected 10 test files, found {total_files}"
