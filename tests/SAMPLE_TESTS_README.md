# COBOL Sample Tests Documentation

## Overview

This directory contains comprehensive tests for all COBOL sample programs. The tests are organized into three categories:

- **Integration Tests** (`integration/test_sample_programs.py`) - End-to-end parsing tests for complete sample programs
- **Unit Tests** (`unit/test_sample_features.py`) - Tests for specific COBOL language features
- **Contract Tests** (`contracts/test_sample_api_contracts.py`) - API stability and backward compatibility tests

## Sample Files Tested

The following 18 COBOL sample files are covered by these tests:

### Basic Features
1. `figurative_constants.cbl` - ALL, ZERO, SPACE, HIGH-VALUE, LOW-VALUE, QUOTE
2. `multiline_strings.cbl` - Continuation lines, multi-line VALUE clauses
3. `picture_clauses.cbl` - Comprehensive PICTURE variations (numeric, signed, edited, decimal)
4. `occurs_variations.cbl` - Fixed OCCURS, DEPENDING ON, INDEXED BY, nested tables
5. `redefines_test.cbl` - Simple/multiple/nested REDEFINES, union-like structures

### File Operations
6. `file_operations.cbl` - Sequential, indexed, relative files with FD/SD clauses
7. `sort_merge_operations.cbl` - SORT, MERGE, INPUT/OUTPUT PROCEDURE, RELEASE, RETURN

### Control Flow & Arithmetic
8. `control_flow.cbl` - IF, EVALUATE, PERFORM, GO TO, SEARCH statements
9. `arithmetic_operations.cbl` - ADD, SUBTRACT, MULTIPLY, DIVIDE, COMPUTE with all variations

### String Operations
10. `string_operations.cbl` - STRING, UNSTRING, INSPECT, MOVE CORRESPONDING

### IBM Extensions
11. `ibm_extensions.cbl` - EXEC SQL, EXEC CICS, EXEC IMS, COMP-3, intrinsic functions

### I/O Operations
12. `accept_display_operations.cbl` - ACCEPT FROM DATE/TIME/DAY, DISPLAY variations

### Advanced Features
13. `declaratives_section.cbl` - DECLARATIVES, USE AFTER ERROR, exception handling
14. `special_names_config.cbl` - SPECIAL-NAMES, CURRENCY SIGN, DECIMAL-POINT, ALPHABET
15. `report_writer.cbl` - REPORT SECTION, control breaks, SUM clauses
16. `communication_module.cbl` - COMMUNICATION SECTION (legacy feature)
17. `screen_section_io.cbl` - SCREEN SECTION, full-screen I/O, field attributes

### Error Recovery
18. `error_recovery_tests.cbl` - **Intentionally malformed code** for parser error recovery testing

## Running Tests

### Run All Sample Tests
```bash
python -m pytest tests/integration/test_sample_programs.py tests/unit/test_sample_features.py tests/contracts/test_sample_api_contracts.py -v
```

### Or use the test runner script
```bash
python tests/test_all_samples.py
```

### Run with Coverage
```bash
python tests/test_all_samples.py coverage
```

### Run Specific Categories
```bash
# Basic features
python tests/test_all_samples.py category basic

# File operations
python tests/test_all_samples.py category files

# Control flow and arithmetic
python tests/test_all_samples.py category control

# String operations
python tests/test_all_samples.py category strings

# IBM extensions
python tests/test_all_samples.py category ibm

# Advanced features
python tests/test_all_samples.py category advanced

# Error recovery
python tests/test_all_samples.py category errors

# API contracts
python tests/test_all_samples.py category contracts
```

### Run Individual Test Files
```bash
# Integration tests
python -m pytest tests/integration/test_sample_programs.py -v

# Unit tests
python -m pytest tests/unit/test_sample_features.py -v

# Contract tests
python -m pytest tests/contracts/test_sample_api_contracts.py -v
```

### Run Specific Test Class
```bash
python -m pytest tests/integration/test_sample_programs.py::TestBasicSamples -v
```

### Run Specific Test Method
```bash
python -m pytest tests/integration/test_sample_programs.py::TestBasicSamples::test_figurative_constants -v
```

## Test Organization

### Integration Tests (`test_sample_programs.py`)

Tests complete sample programs end-to-end:

- **TestBasicSamples** - Basic COBOL features (figurative constants, PICTURE, OCCURS, REDEFINES)
- **TestFileOperations** - File handling samples (sequential, indexed, relative, SORT, MERGE)
- **TestControlFlow** - Control flow statements (IF, EVALUATE, PERFORM)
- **TestStringOperations** - String manipulation (STRING, UNSTRING, INSPECT)
- **TestIBMExtensions** - IBM Enterprise COBOL extensions
- **TestAcceptDisplay** - ACCEPT/DISPLAY operations
- **TestAdvancedFeatures** - Advanced features (DECLARATIVES, SPECIAL-NAMES, REPORT, COMMUNICATION, SCREEN)
- **TestErrorRecovery** - Error recovery capabilities
- **TestJSONSerialization** - JSON export functionality
- **TestMemoryManagement** - Memory configuration and streaming
- **TestParseStatistics** - Statistics tracking

Also includes a parametrized test that validates **all 17 valid samples** parse successfully.

### Unit Tests (`test_sample_features.py`)

Tests specific COBOL language features in isolation:

- **TestFigurativeConstants** - Tokenization of ALL, ZERO, SPACE, QUOTE, HIGH-VALUE, LOW-VALUE
- **TestPictureClausesParsing** - PICTURE clause parsing (numeric, signed, decimal, edited)
- **TestOccursClause** - OCCURS clause variations (fixed, DEPENDING ON, INDEXED BY)
- **TestRedefinesClause** - REDEFINES clause (simple, nested)
- **TestFileControlParsing** - FILE-CONTROL section (sequential, indexed, relative files)
- **TestArithmeticStatements** - Arithmetic operations (ADD, SUBTRACT, MULTIPLY, DIVIDE, COMPUTE)
- **TestStringStatements** - String statements (STRING, UNSTRING, INSPECT)
- **TestControlFlowStatements** - Control flow (IF, EVALUATE, PERFORM)
- **TestIBMExtensionsParsing** - IBM extensions (COMP-3, EXEC SQL, EXEC CICS)
- **TestSpecialFeatures** - Special features (ACCEPT FROM DATE, DISPLAY UPON, SORT)

### Contract Tests (`test_sample_api_contracts.py`)

Tests API stability and backward compatibility:

- **TestParserAPIContract** - Parser API consistency (parse, parse_file, error_recovery, memory_config)
- **TestASTNodeContract** - AST node structure consistency (Program, Divisions, to_dict)
- **TestJSONSerializationContract** - JSON serialization contract (to_json, SerializationConfig)
- **TestErrorHandlingContract** - Error handling consistency (errors list, error attributes)
- **TestStatisticsContract** - Statistics contract (total_lines, parse_time_ms)
- **TestMemoryConfigContract** - Memory configuration contract
- **TestDivisionContract** - Division node structure
- **TestBackwardCompatibility** - Backward compatibility with existing API

Also includes a parametrized test ensuring **all 10 core samples** maintain the API contract.

## Test Counts

- **Integration Tests**: ~30 tests (including parametrized)
- **Unit Tests**: ~40 tests
- **Contract Tests**: ~45 tests (including parametrized)
- **Total**: ~115 tests

## Expected Test Results

### Valid Samples (17 files)
All samples **except** `error_recovery_tests.cbl` should:
- Parse successfully with no errors
- Produce a valid AST
- Have a non-null program_id
- Support JSON serialization
- Maintain API contracts

### Error Recovery Sample (1 file)
`error_recovery_tests.cbl` should:
- Fail with FAIL_FAST mode
- Collect errors with COLLECT_ALL mode
- Still attempt to produce an AST in COLLECT_ALL mode

## Coverage Goals

These tests target **90%+ code coverage** for:
- Lexer tokenization (`cobolparser/lexer.py`)
- Parser AST generation (`cobolparser/parser.py`)
- AST models (`cobolparser/models/`)
- IBM dialect support (`cobolparser/dialects/ibm_enterprise.py`)
- Plugin core functionality (`cobolparser/plugins/core.py`)

## Test Maintenance

When adding new sample files:

1. Add the file to `tests/samples/`
2. Add integration test in `test_sample_programs.py`
3. Add feature-specific unit tests in `test_sample_features.py`
4. Add to parametrized contract test if it's a valid sample
5. Update this README

## Common Test Patterns

### Testing a Sample Parses Successfully
```python
def test_my_sample(self):
    sample_path = SAMPLES_DIR / "my_sample.cbl"
    parser = CobolParser(error_recovery=ErrorRecoveryMode.FAIL_FAST)
    
    result = parser.parse_file(str(sample_path))
    
    assert result.ast is not None
    assert result.errors == []
    assert result.ast.program_id == "EXPECTED-ID"
```

### Testing a Feature is Recognized
```python
def test_feature(self):
    parser = CobolParser()
    source = """
    IDENTIFICATION DIVISION.
    PROGRAM-ID. TEST.
    DATA DIVISION.
    WORKING-STORAGE SECTION.
    01  WS-FIELD PIC 9(5).
    """
    
    result = parser.parse(source)
    assert result.ast is not None
```

### Testing Error Recovery
```python
def test_error_recovery(self):
    sample_path = SAMPLES_DIR / "error_recovery_tests.cbl"
    parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    
    result = parser.parse_file(str(sample_path))
    
    assert len(result.errors) > 0
    for error in result.errors:
        assert error.message is not None
```

## Debugging Failed Tests

### View Full Traceback
```bash
python -m pytest tests/integration/test_sample_programs.py -v --tb=long
```

### Run with Print Statements
```bash
python -m pytest tests/integration/test_sample_programs.py -v -s
```

### Run Single Failing Test
```bash
python -m pytest tests/integration/test_sample_programs.py::TestBasicSamples::test_figurative_constants -v
```

### Enable Parser Debug Output
Modify test to add debug flag:
```python
parser = CobolParser(debug=True)
```
