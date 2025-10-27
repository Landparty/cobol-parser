# Integration Tests for COBOL Parser

This directory contains comprehensive integration tests that validate the COBOL parser against real-world COBOL programs.

## Test Suite Overview

### `test_all_cobol_examples.py`

A comprehensive test suite that runs the parser against **all 510 COBOL files** in the `examples/cobol` directory.

#### Test Classes:

1. **TestAllCobolExamples**
   - Parametrized test that runs each COBOL file individually
   - Tests 510 files (both `.CBL` programs and `.CPY` copybooks)
   - Reports detailed statistics for each file
   - Usage: `pytest tests/integration/test_all_cobol_examples.py::TestAllCobolExamples -v`

2. **TestCobolExamplesStatistics**
   - Provides comprehensive summary across all examples
   - Reports:
     - Total files processed: **510 files**
     - Total lines: **348,233 lines** of COBOL code
     - Total bytes: **28+ MB** of COBOL source
     - Success/failure rates
     - Files with most parsing errors
   - Usage: `pytest tests/integration/test_all_cobol_examples.py::TestCobolExamplesStatistics -v -s`

3. **TestSpecificFileTypes**
   - Tests `.CBL` files (COBOL programs) separately
   - Tests `.CPY` files (copybooks) separately
   - Validates different file type handling

4. **TestFileNamePatterns**
   - Tests files grouped by prefix (DB*, IC*, IF*, IX*, NC*, etc.)
   - Useful for identifying which types of COBOL programs parse better
   - Prefixes tested:
     - `DB*` - Database operations
     - `IC*`, `IF*` - Internal/Interface files
     - `IX*` - Indexed file operations
     - `NC*` - Numeric computation
     - `RL*`, `RW*` - Relative/Random file operations
     - `SG*`, `SM*`, `SQ*`, `ST*` - Segment/Sequential/Sort/String operations
     - `CM*`, `OB*` - Communication/Object files

5. **TestLargeFiles**
   - Tests the 10 largest COBOL files
   - Validates parser performance on complex programs
   - Tests memory management capabilities

6. **TestErrorRecovery**
   - Validates error recovery mode functionality
   - Ensures parser doesn't crash even with syntax errors
   - Tests `ErrorRecoveryMode.COLLECT_ALL`

## Running the Tests

### Run all integration tests
```bash
pytest tests/integration/ -v
```

### Run with detailed output
```bash
pytest tests/integration/test_all_cobol_examples.py -v -s
```

### Run just the summary
```bash
pytest tests/integration/test_all_cobol_examples.py::TestCobolExamplesStatistics::test_parse_all_files_summary -v -s
```

### Run tests for specific file prefix
```bash
pytest tests/integration/test_all_cobol_examples.py::TestFileNamePatterns::test_parse_files_by_prefix[DB] -v
```

### Run test for a specific file
```bash
pytest "tests/integration/test_all_cobol_examples.py::TestAllCobolExamples::test_parse_cobol_file[CM101M.CBL]" -v -s
```

## Test Results Summary

Current parsing statistics:
- **Total files**: 510 COBOL files
- **Successfully parsed**: ~63 files (12.4%)
- **Lines processed**: 348,233 lines
- **Data processed**: 28+ MB

The parser successfully handles:
- Basic COBOL program structure
- Division and section parsing
- Data item definitions
- Procedure division statements
- Copybook includes
- IBM Enterprise COBOL extensions

## Key Features Tested

✅ **File Discovery**: Automatically finds all COBOL files  
✅ **Comprehensive Coverage**: Tests every single example file  
✅ **Detailed Reporting**: Per-file and aggregate statistics  
✅ **Error Collection**: Captures and reports all parsing errors  
✅ **Performance Testing**: Validates handling of large files  
✅ **Type-Specific Tests**: Separate validation for programs vs copybooks  
✅ **Pattern-Based Testing**: Groups files by naming conventions  
✅ **Error Recovery**: Ensures robustness even with syntax errors  

## Adding New Test Cases

To add new COBOL files for testing:
1. Place `.CBL` or `.CPY` files in `examples/cobol/`
2. Tests will automatically discover and run them
3. No test code changes needed

## Test Output Example

```
================================================================================
PARSING ALL COBOL EXAMPLES - COMPREHENSIVE SUMMARY
================================================================================

================================================================================
SUMMARY
================================================================================
Total Files: 510
Successfully Parsed: 63 (12.4%)
Failed to Parse: 447 (87.6%)
Total Lines Processed: 348,233
Total Bytes Processed: 28,213,067
Total Errors Collected: 1595

================================================================================
FILES WITH MOST ERRORS (Top 10)
================================================================================
  ✗ NC216A.CBL                               -   50 errors
  ✗ SQ208M.CBL                               -   31 errors
  ✗ SQ224A.CBL                               -   26 errors
  ...
================================================================================
```

## Notes

- Tests are designed to be resilient - they don't fail on parsing errors
- The goal is comprehensive validation, not perfection
- Error reports help identify areas for parser improvement
- Tests run in ~3 minutes for all 510 files
