"""Integration tests for all COBOL examples in examples/cobol folder.

This test suite runs the parser against all real-world COBOL programs
in the examples/cobol directory to ensure comprehensive compatibility
and identify any parsing issues with actual COBOL code.
"""

import os
import pytest
from pathlib import Path
from typing import List, Tuple

from cobolparser import CobolParser, parse_cobol
from cobolparser.plugins.core import ErrorRecoveryMode

pytestmark = [pytest.mark.integration, pytest.mark.slow]


# Get the path to examples/cobol directory
EXAMPLES_DIR = Path(__file__).parent.parent.parent / "examples" / "cobol"


def get_cobol_files() -> List[Path]:
    """Get all COBOL files from the examples directory.
    
    Returns:
        List of Path objects for .CBL and .CPY files
    """
    if not EXAMPLES_DIR.exists():
        pytest.skip(f"Examples directory not found: {EXAMPLES_DIR}")
    
    # Get all .CBL (COBOL programs) and .CPY (copybooks) files
    cobol_files = list(EXAMPLES_DIR.glob("*.CBL")) + list(EXAMPLES_DIR.glob("*.CPY"))
    
    if not cobol_files:
        pytest.skip("No COBOL files found in examples directory")
    
    return sorted(cobol_files)


def get_file_stats(file_path: Path) -> dict:
    """Get statistics about a COBOL file.
    
    Args:
        file_path: Path to the COBOL file
        
    Returns:
        Dictionary with file statistics
    """
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    
    return {
        'size_bytes': len(content.encode('utf-8')),
        'lines': len(content.splitlines()),
        'path': str(file_path.name)
    }


# Parametrize the test with all COBOL files
cobol_files = get_cobol_files() if EXAMPLES_DIR.exists() else []


class TestAllCobolExamples:
    """Test suite for parsing all COBOL examples."""
    
    @pytest.mark.parametrize("cobol_file", cobol_files, ids=lambda f: f.name)
    def test_parse_cobol_file(self, cobol_file: Path):
        """Test that each COBOL file can be parsed without critical errors.
        
        This test:
        - Loads the COBOL file
        - Attempts to parse it
        - Verifies basic parsing success
        - Reports any errors found
        
        Args:
            cobol_file: Path to the COBOL file to test
        """
        # Read the file
        try:
            with open(cobol_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except Exception as e:
            pytest.fail(f"Failed to read file {cobol_file.name}: {e}")
        
        # Get file stats for reporting
        stats = get_file_stats(cobol_file)
        
        # Parse the file with error collection mode
        result = parse_cobol(content)
        
        # Assert that we got a result
        assert result is not None, f"Parser returned None for {cobol_file.name}"
        
        # Report parsing statistics
        print(f"\n{'='*60}")
        print(f"File: {cobol_file.name}")
        print(f"Size: {stats['size_bytes']} bytes, {stats['lines']} lines")
        print(f"Success: {result.success}")
        print(f"Errors: {len(result.errors)}")
        
        if result.ast:
            # Get AST statistics if available
            if hasattr(result.ast, 'get_statistics'):
                ast_stats = result.ast.get_statistics()
                if ast_stats:
                    print(f"Program: {result.ast.program_name or 'N/A'}")
                    print(f"Divisions: {ast_stats.get('divisions', 0)}")
                    print(f"Sections: {ast_stats.get('sections', 0)}")
                    print(f"Statements: {ast_stats.get('statements', 0)}")
        
        # Print first few errors if any
        if result.errors:
            print(f"\nFirst 3 errors:")
            for i, error in enumerate(result.errors[:3]):
                print(f"  {i+1}. Line {error.line}: {error.message}")
        
        print(f"{'='*60}\n")
        
        # The test passes as long as we got a result
        # We don't require perfect parsing, just no crashes
        assert result is not None


class TestCobolExamplesStatistics:
    """Test suite for collecting statistics across all examples."""
    
    def test_parse_all_files_summary(self):
        """Parse all files and provide a comprehensive summary.
        
        This test provides an overview of parsing success across all examples.
        """
        cobol_files = get_cobol_files()
        
        total_files = len(cobol_files)
        successful_parses = 0
        failed_parses = 0
        total_errors = 0
        total_lines = 0
        total_bytes = 0
        
        results: List[Tuple[str, bool, int]] = []
        
        print(f"\n{'='*80}")
        print(f"PARSING ALL COBOL EXAMPLES - COMPREHENSIVE SUMMARY")
        print(f"{'='*80}\n")
        
        for cobol_file in cobol_files:
            try:
                with open(cobol_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                stats = get_file_stats(cobol_file)
                total_lines += stats['lines']
                total_bytes += stats['size_bytes']
                
                result = parse_cobol(content)
                
                if result.success:
                    successful_parses += 1
                else:
                    failed_parses += 1
                
                error_count = len(result.errors)
                total_errors += error_count
                
                results.append((cobol_file.name, result.success, error_count))
                
            except Exception as e:
                failed_parses += 1
                results.append((cobol_file.name, False, 0))
                print(f"ERROR parsing {cobol_file.name}: {e}")
        
        # Print summary
        print(f"\n{'='*80}")
        print(f"SUMMARY")
        print(f"{'='*80}")
        print(f"Total Files: {total_files}")
        print(f"Successfully Parsed: {successful_parses} ({successful_parses/total_files*100:.1f}%)")
        print(f"Failed to Parse: {failed_parses} ({failed_parses/total_files*100:.1f}%)")
        print(f"Total Lines Processed: {total_lines:,}")
        print(f"Total Bytes Processed: {total_bytes:,}")
        print(f"Total Errors Collected: {total_errors}")
        
        if results:
            print(f"\n{'='*80}")
            print(f"FILES WITH MOST ERRORS (Top 10)")
            print(f"{'='*80}")
            sorted_by_errors = sorted(results, key=lambda x: x[2], reverse=True)[:10]
            for filename, success, error_count in sorted_by_errors:
                status = "✓" if success else "✗"
                print(f"  {status} {filename:40s} - {error_count:4d} errors")
        
        print(f"\n{'='*80}\n")
        
        # Test passes if we can parse at least some files
        assert successful_parses > 0, "Failed to successfully parse any COBOL files"
        
        # Optional: Uncomment to require high success rate
        # success_rate = successful_parses / total_files
        # assert success_rate >= 0.50, f"Success rate too low: {success_rate:.1%}"


class TestSpecificFileTypes:
    """Test suite for specific file type patterns."""
    
    def test_parse_all_cbl_files(self):
        """Test parsing of all .CBL (COBOL program) files."""
        cbl_files = list(EXAMPLES_DIR.glob("*.CBL"))
        assert len(cbl_files) > 0, "No .CBL files found"
        
        successful = 0
        for cbl_file in cbl_files:
            with open(cbl_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            result = parse_cobol(content)
            if result and result.success:
                successful += 1
        
        success_rate = successful / len(cbl_files) if cbl_files else 0
        print(f"\nCBL Files: {successful}/{len(cbl_files)} successful ({success_rate:.1%})")
        
        # At least some CBL files should parse
        assert successful > 0
    
    def test_parse_all_cpy_files(self):
        """Test parsing of all .CPY (copybook) files."""
        cpy_files = list(EXAMPLES_DIR.glob("*.CPY"))
        
        if not cpy_files:
            pytest.skip("No .CPY files found")
        
        successful = 0
        for cpy_file in cpy_files:
            with open(cpy_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            result = parse_cobol(content)
            # Copybooks may not have full program structure, so we're lenient
            if result:
                successful += 1
        
        success_rate = successful / len(cpy_files) if cpy_files else 0
        print(f"\nCPY Files: {successful}/{len(cpy_files)} parsed ({success_rate:.1%})")
        
        # At least we should be able to attempt parsing all copybooks
        assert successful > 0


class TestFileNamePatterns:
    """Test suite for specific file naming patterns."""
    
    @pytest.mark.parametrize("prefix", ["DB", "IC", "IF", "IX", "NC", "RL", "RW", "SG", "SM", "SQ", "ST", "CM", "OB"])
    def test_parse_files_by_prefix(self, prefix: str):
        """Test parsing files with specific prefixes.
        
        Args:
            prefix: File name prefix to test (e.g., 'DB' for database files)
        """
        pattern_files = [f for f in get_cobol_files() if f.name.startswith(prefix)]
        
        if not pattern_files:
            pytest.skip(f"No files found with prefix {prefix}")
        
        successful = 0
        for file in pattern_files:
            with open(file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            result = parse_cobol(content)
            if result:
                successful += 1
        
        success_rate = successful / len(pattern_files)
        print(f"\n{prefix}* Files: {successful}/{len(pattern_files)} parsed ({success_rate:.1%})")
        
        # Should be able to parse at least some files with this prefix
        assert successful > 0, f"Failed to parse any {prefix}* files"


class TestLargeFiles:
    """Test suite for handling large COBOL files."""
    
    def test_parse_largest_files(self):
        """Test parsing the 10 largest COBOL files."""
        cobol_files = get_cobol_files()
        
        # Sort by file size
        files_with_size = [(f, get_file_stats(f)['size_bytes']) for f in cobol_files]
        largest_files = sorted(files_with_size, key=lambda x: x[1], reverse=True)[:10]
        
        print(f"\n{'='*80}")
        print(f"TESTING 10 LARGEST FILES")
        print(f"{'='*80}\n")
        
        successful = 0
        for file, size in largest_files:
            with open(file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            result = parse_cobol(content)
            status = "✓" if (result and result.success) else "✗"
            
            print(f"  {status} {file.name:40s} - {size:,} bytes")
            
            if result and result.success:
                successful += 1
        
        print(f"\nSuccessfully parsed {successful}/10 largest files")
        
        # Should be able to attempt parsing large files (may have errors)
        # Just verify we didn't crash
        assert len(largest_files) > 0, "No large files found to test"


class TestErrorRecovery:
    """Test suite for error recovery capabilities."""
    
    def test_parse_with_error_collection(self):
        """Test that parser can collect errors without crashing."""
        cobol_files = get_cobol_files()
        
        # Test first 10 files with error collection
        test_files = cobol_files[:10]
        
        for cobol_file in test_files:
            with open(cobol_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # Parse with error collection enabled
            parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
            result = parser.parse(content)
            
            # Should always return a result, even with errors
            assert result is not None, f"Parser returned None for {cobol_file.name}"
            assert hasattr(result, 'errors'), "Result should have errors attribute"
            assert isinstance(result.errors, list), "Errors should be a list"


if __name__ == "__main__":
    # Allow running this test file directly
    pytest.main([__file__, "-v", "-s"])
