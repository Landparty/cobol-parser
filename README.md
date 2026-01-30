# COBOL Parser for Python

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-618%20passing-green.svg)](#testing)
[![Coverage](https://img.shields.io/badge/coverage-57%2B%25%20parser-yellow.svg)](#testing)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![IBM COBOL](https://img.shields.io/badge/IBM%20Enterprise%20COBOL-supported-blue.svg)](#ibm-enterprise-cobol-support)

A comprehensive COBOL source code parser for Python 3.13+ with enhanced features including configurable memory management, JSON export, IBM Enterprise COBOL dialect support, and advanced error recovery. Built following Test-Driven Development (TDD) principles with comprehensive test coverage (618 tests, 57%+ parser coverage).

## 🚀 Quick Start

**Problem**: Legacy COBOL systems contain millions of lines of code that need modernization, but parsing COBOL syntax is complex due to its unique structure and dialect variations.

**Solution**: Our parser provides a robust, memory-efficient way to convert COBOL source code into structured, machine-readable AST representations for analysis, migration, and modernization projects.

**Key Benefits**:
- ✅ **Modern Python 3.13+** - Built with latest Python features
- ✅ **IBM Enterprise COBOL Focus** - Priority support for enterprise dialects
- ✅ **Memory Efficient** - Configurable limits from 64MB to 8GB
- ✅ **Error Recovery** - Robust parsing with multiple recovery modes
- ✅ **JSON Export** - Cross-platform AST serialization
- ✅ **TDD Compliant** - 618 comprehensive tests ensuring reliability

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [IBM Enterprise COBOL Support](#ibm-enterprise-cobol-support)
- [Configuration Options](#configuration-options)
- [API Reference](#api-reference)
- [Testing](#testing)
- [Performance](#performance)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

## Features

- 🚀 **Modern Python 3.13+** - Built with latest Python features (dataclasses, typing, enums)
- 💾 **Memory Management** - Configurable limits from 64MB to 8GB with streaming support
- 📄 **JSON Export** - Cross-platform AST serialization with metadata and source locations
- 🔧 **Error Recovery** - Fail-fast or collect-all error modes for robust parsing
- 🏢 **IBM Enterprise COBOL** - Priority support for COMP-3, EXEC SQL, EXEC CICS
- 🧩 **Plugin Architecture** - Extensible design for custom dialects and features
- 📊 **Statistics** - Detailed parsing metrics and performance monitoring
- ✅ **TDD Compliant** - 618 comprehensive tests ensuring reliability
- 🔍 **Lexical Analysis** - Complete tokenization with comprehensive COBOL verb support (75+ verbs), multi-line string continuation, and robust error reporting
- ⚡ **Auto-Detection** - Intelligent auto-detection of fixed-format COBOL with automatic preprocessing
- 🏗️ **AST Generation** - Full Abstract Syntax Tree with source location tracking

## Documentation

Full documentation index is available at [docs/README.md](docs/README.md). It contains a comprehensive index of all guides, including installation, quick-start, and per-topic deep dives.

> [!TIP]
> 🍳 **Check out the [Cookbook](docs/cookbook.md)!**
> It features fresh, real-world recipes for:
> - Extracting SQL statements
> - Validating File Descriptors
> - Generating Call Graphs
> - Handling massive files with streaming

**Archived Documentation**: Historical documentation including coverage reports, planning documents, and completed feature specifications have been archived to `archived_docs/` for compliance and reference. See [archived_docs/ARCHIVE_INDEX.md](archived_docs/ARCHIVE_INDEX.md) for the complete inventory.

## 📋 System Requirements

### Minimum Requirements
- **Python**: 3.13 or higher
- **Memory**: 256MB RAM (for small programs)
- **Storage**: 50MB free space
- **OS**: Windows 10+, macOS 10.15+, Linux (any modern distribution)

### Verification
To verify compatibility on your specific environment (especially macOS), you can run the provided verification script:
```bash
python verify_mac.py
```

### Recommended Requirements
- **Python**: 3.13.1 or higher
- **Memory**: 1GB RAM (for medium programs)
- **Storage**: 100MB free space
- **Virtual Environment**: Recommended for isolation

### Installation

#### Quick Install
```bash
# Install from PyPI (when available)
pip install cobolparser

# Or install from source
git clone https://github.com/Landparty/cobol-parser.git
cd cobol-parser
pip install -e .
```

#### Development Installation
```bash
# Clone the repository
git clone https://github.com/Landparty/cobol-parser.git
cd cobol-parser

# Install in development mode with all dependencies
pip install -e ".[dev,docs]"

# Verify installation
python -c "from cobolparser import parse_cobol; print('Installation successful!')"
```

#### Virtual Environment Setup (Recommended)
```bash
# Create virtual environment
python -m venv cobol-parser-env

# Activate virtual environment
# On Windows:
cobol-parser-env\Scripts\activate
# On macOS/Linux:
source cobol-parser-env/bin/activate

# Install the parser
pip install -e .
```

## 🚀 Quick Start

### Basic Parsing Example
```python
from cobolparser import parse_cobol

# Realistic COBOL program with multiple divisions
cobol_code = """       IDENTIFICATION DIVISION.
        PROGRAM-ID. EMPLOYEE-PROCESSOR.
        AUTHOR. COBOL Parser Team.
        
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT EMPLOYEE-FILE ASSIGN TO "EMP.DAT"
                ORGANIZATION IS SEQUENTIAL.
        
        DATA DIVISION.
        FILE SECTION.
        FD EMPLOYEE-FILE.
        01 EMPLOYEE-RECORD.
            05 EMP-ID         PIC X(10).
            05 EMP-NAME       PIC X(30).
            05 EMP-SALARY     PIC 9(7)V99 COMP-3.
        
        WORKING-STORAGE SECTION.
        01 WS-COUNTER       PIC 9(4) VALUE 0.
        01 WS-TOTAL-SALARY  PIC 9(10)V99 COMP-3 VALUE 0.
        
        PROCEDURE DIVISION.
        MAIN-PARA.
            OPEN INPUT EMPLOYEE-FILE.
            READ EMPLOYEE-FILE
                AT END DISPLAY "No records found"
                NOT AT END PERFORM PROCESS-RECORDS.
            CLOSE EMPLOYEE-FILE.
            DISPLAY "Total salary: " WS-TOTAL-SALARY.
            STOP RUN.
            
        PROCESS-RECORDS.
            PERFORM UNTIL WS-COUNTER > 100
                ADD 1 TO WS-COUNTER
                ADD EMP-SALARY TO WS-TOTAL-SALARY
                READ EMPLOYEE-FILE
                    AT END EXIT PERFORM
                    NOT AT END CONTINUE.
```

# Parse the program
result = parse_cobol(cobol_code, filename="employee_processor.cob")

if result.success:
    print(f"✅ Successfully parsed: {result.ast.program_name}")
    print(f"   Divisions: {len(result.ast.divisions)}")
    print(f"   Parse time: {result.statistics.total_time_ms}ms")
    
    # Access parsed data
    data_div = result.ast.get_division("DATA")
    if data_div:
        data_items = result.ast.get_data_items()
        print(f"   Data items: {len(data_items)}")
else:
    print("❌ Parsing failed:")
    for error in result.errors:
        print(f"   Line {error.line}: {error.message}")
```

### Error Handling Example
```python
from cobolparser import parse_cobol
from cobolparser.plugins.core import ErrorRecoveryMode

# Parse with different error recovery modes
cobol_with_errors = """       IDENTIFICATION DIVISION.
        PROGRAM-ID. ERROR-EXAMPLE.
        
        PROCEDURE DIVISION.
            DISPLAY "This will have errors".
            INVALID-COBOL-STATEMENT.  # This will cause an error
            STOP RUN.
"""

# Fail-fast mode (default)
result_strict = parse_cobol(cobol_with_errors, error_recovery=ErrorRecoveryMode.FAIL_FAST)

# Collect-all mode (for debugging)
result_lenient = parse_cobol(cobol_with_errors, error_recovery=ErrorRecoveryMode.COLLECT_ALL)

print(f"Strict mode errors: {len(result_strict.errors)}")
print(f"Lenient mode errors: {len(result_lenient.errors)}")
```

## 🏗️ Architecture

The COBOL parser follows a robust two-stage pipeline architecture designed for enterprise-scale COBOL processing:

### Processing Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│                    COBOL Source Code                        │
│  (Legacy mainframe programs, copybooks, dialect variants)   │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                    Lexer (Tokenization)                     │
│  • 75+ COBOL verbs recognized                              │
│  • IBM Enterprise COBOL dialect support                    │
│  • Error detection and reporting                           │
│  • Memory-efficient streaming                              │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                    Parser (AST Generation)                  │
│  • Hierarchical AST construction                           │
│  • Source location tracking                                │
│  • Error recovery modes                                    │
│  • Memory management                                       │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                 Abstract Syntax Tree (AST)                  │
│  • Structured representation                               │
│  • Cross-platform compatibility                            │
│  • Metadata preservation                                   │
│  • Extensible node types                                   │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                 JSON Export / Analysis                      │
│  • Machine-readable output                                 │
│  • Integration with modern tools                           │
│  • Code analysis and metrics                               │
│  • Migration and modernization                             │
└─────────────────────────────────────────────────────────────┘
```

### Core Components

```bash
cobolparser/
├── __init__.py           # Main package interface and exports
├── lexer.py             # COBOL tokenization with 75+ verb support
├── parser.py            # AST generation and parsing logic
├── models/              # AST node hierarchy
│   ├── ast_base.py     # Base AST classes and SourceLocation
│   ├── program.py      # Program/Division/Section structure
│   ├── statements.py   # MOVE, DISPLAY, PERFORM statements
│   └── data_items.py   # PictureClause, COMP-3, data definitions
├── dialects/           # Dialect-specific support
│   └── ibm_enterprise.py # IBM Enterprise COBOL extensions
└── plugins/            # Configuration and plugins
    └── core.py         # Memory config, error recovery, serialization
```

### Key Design Patterns

1. **AST Node Hierarchy**: All AST nodes inherit from `ASTNode` with mandatory `to_dict()` for JSON serialization
2. **Memory Management**: Configurable limits with streaming support for large programs
3. **Error Recovery**: Choice between fail-fast and collect-all modes
4. **Plugin Architecture**: Extensible design for dialects and custom features
5. **Source Location Tracking**: Line/column information preserved throughout parsing
```

### Key Design Patterns

1. **AST Node Hierarchy**: All AST nodes inherit from `ASTNode` with mandatory `to_dict()` for JSON serialization
2. **Memory Management**: Configurable limits with streaming support for large programs
3. **Error Recovery**: Choice between fail-fast and collect-all modes
4. **Plugin Architecture**: Extensible design for dialects and custom features
5. **Source Location Tracking**: Line/column information preserved throughout parsing

## IBM Enterprise COBOL Support

The parser prioritizes IBM Enterprise COBOL dialect features:

### Supported Features

- ✅ **COMP-3 Packed Decimal** - Native support with automatic storage size calculation
- ✅ **EXEC SQL** - Embedded SQL statement parsing with host variable detection
- ✅ **EXEC CICS** - CICS transaction commands and API calls
- ✅ **Intrinsic Functions** - 25+ IBM-specific functions (LENGTH, NUMVAL, etc.)
- ✅ **Data Types** - COMP, COMP-1/2/3/4/5, POINTER types
- ✅ **z/OS Extensions** - Platform-specific features and reserved words

## Configuration Options

### Memory Configuration

```python
from cobolparser.plugins.core import MemoryConfiguration

config = MemoryConfiguration(
    max_memory_mb=1024,    # Maximum memory usage (64MB - 8GB)
    chunk_size_kb=512,     # Processing chunk size in KB
    enable_streaming=True  # Enable streaming for large files
)
```

### Error Recovery

```python
from cobolparser.plugins.core import ErrorRecoveryMode

# Fail on first error (production default)
strict_parser = CobolParser(error_recovery=ErrorRecoveryMode.FAIL_FAST)

# Collect all errors (development/debugging)
lenient_parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
```

### JSON Serialization

```python
from cobolparser.plugins.core import SerializationConfig

config = SerializationConfig(
    include_metadata=True,        # Include parser version, timestamp, etc.
    include_source_locations=True, # Include line/column information
    compact_format=False          # Pretty-print vs compact JSON
)
```

## API Reference

### Core Classes

#### CobolParser
Main parser class with configuration options.

```python
parser = CobolParser(
    memory_config=MemoryConfiguration(),
    error_recovery=ErrorRecoveryMode.COLLECT_ALL,
    dialect=DialectType.IBM_ENTERPRISE,
    serialization_config=SerializationConfig()
)

result = parser.parse(source_code, filename="program.cob")
```

#### ParseResult
Contains parsing results and metadata.

```python
class ParseResult:
    success: bool          # True if parsing completed without critical errors
    ast: CobolProgram      # Abstract Syntax Tree (None if failed)
    errors: List[ParseError]     # Parsing errors encountered
    warnings: List[str]    # Non-critical warnings
    statistics: ParseStatistics  # Performance and metrics data
```

#### CobolProgram
Root AST node representing a complete COBOL program.

```python
class CobolProgram(ASTNode):
    program_name: str
    author: str
    divisions: Dict[str, CobolDivision]
    source_location: SourceLocation

    def get_division_by_name(self, name: str) -> Optional[CobolDivision]
    def to_json(self, config: SerializationConfig) -> Dict[str, Any]
```

### Utility Functions

#### parse_cobol()
Convenience function for simple parsing. Now supports auto-detection of fixed-format COBOL.

```python
from cobolparser import parse_cobol

# Basic usage (defaults to auto-detection of fixed-format)
result = parse_cobol(source_code, filename="program.cob")

# Explicitly disable preprocessing if needed
result = parse_cobol(source_code, preprocess_fixed=False)

# File path usage
result = parse_cobol("path/to/program.cbl")
```

#### tokenize_cobol()
Direct lexical analysis.

```python
from cobolparser import tokenize_cobol

tokens = tokenize_cobol(source_code, filename="program.cob")
```

## Testing

The parser includes a comprehensive test suite with 618 tests organized by category:

### Test Categories

- **Unit Tests (500+)**: Component-specific functionality testing including comprehensive parser coverage
- **Integration Tests (75+)**: End-to-end workflow validation
- **Contract Tests (38)**: API contract compliance and stability

### Running Tests

```bash
# Run all tests
python -m pytest tests/ -v

# Run with coverage report
python -m pytest --cov=cobolparser --cov-report=html

# Run specific test categories
python -m pytest tests/unit/ -v          # Unit tests only
python -m pytest tests/integration/ -v  # Integration tests only
python -m pytest tests/contracts/ -v    # Contract tests only

# Run tests in parallel (requires pytest-xdist)
python -m pytest -n auto tests/
```

### Test Coverage

The project includes comprehensive test coverage with detailed test cases covering:

- **Lexer**: Comprehensive COBOL verb recognition (75+ verbs including all IBM Enterprise verbs)
- **Parser**: 57%+ statement coverage with detailed AST generation testing (417/636 statements covered)
- **Memory management** under various conditions and large program scenarios
- **Error recovery** behavior in both fail-fast and collect-all modes
- **IBM Enterprise COBOL** dialect features including COMP-3, EXEC SQL, EXEC CICS
- **JSON serialization/deserialization** with metadata and source location tracking
- **Performance characteristics** and edge case handling

### Integration Test

```bash
# Run the integration test
python test_integration.py
```

This test validates that all components work together correctly with real COBOL code.

## ⚡ Performance & Optimization

### Memory Efficiency

- **Configurable Limits**: 64MB to 8GB memory limits
- **Streaming Support**: Handle programs larger than available RAM
- **Chunked Processing**: Process large files in configurable chunks
- **Automatic Cleanup**: Efficient memory usage with garbage collection

### Performance Benchmarks

Typical performance characteristics:

- **Small Programs** (< 1MB): < 100ms parse time
- **Medium Programs** (1-10MB): 100ms - 1s parse time
- **Large Programs** (10MB+): 1-10s with streaming enabled
- **Memory Usage**: 2-5x source code size during parsing

### Performance Monitoring

```python
result = parse_cobol(large_program)

stats = result.statistics
print(f"Parse time: {stats.total_time_ms}ms")
print(f"Peak memory: {stats.memory_peak_mb}MB")
print(f"Lines/second: {stats.lines_parsed / (stats.total_time_ms / 1000):.0f}")
print(f"Tokens/second: {stats.tokens_processed / (stats.total_time_ms / 1000):.0f}")
```

### Performance Optimization Tips

#### 1. **Memory Configuration for Large Programs**
```python
from cobolparser.plugins.core import MemoryConfiguration

# Optimize for large legacy programs
config = MemoryConfiguration(
    max_memory_mb=4096,    # 4GB for large programs
    chunk_size_kb=2048,    # 2MB chunks for better throughput
    enable_streaming=True  # Essential for >10MB files
)
```

#### 2. **Error Recovery for Performance**
```python
# Use fail-fast mode for production (faster)
result = parse_cobol(cobol_code, error_recovery=ErrorRecoveryMode.FAIL_FAST)

# Use collect-all only for debugging (slower but comprehensive)
result = parse_cobol(cobol_code, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
```

#### 3. **Batch Processing Optimization**
```python
def process_multiple_files(file_list):
    """Process multiple COBOL files efficiently"""
    results = []
    for file_path in file_list:
        with open(file_path, 'r') as f:
            result = parse_cobol(f.read(), filename=file_path)
            results.append(result)
    
    # Analyze overall performance
    total_time = sum(r.statistics.total_time_ms for r in results)
    total_lines = sum(r.statistics.lines_parsed for r in results)
    
    print(f"Processed {len(results)} files in {total_time}ms")
    print(f"Average throughput: {total_lines / (total_time/1000):.0f} lines/second")
    
    return results
```

#### 4. **Parallel Processing**
```python
from concurrent.futures import ThreadPoolExecutor
from cobolparser import parse_cobol

def parallel_parse(file_list, max_workers=4):
    """Parse multiple files in parallel"""
    def parse_file(file_path):
        with open(file_path, 'r') as f:
            return parse_cobol(f.read(), filename=file_path)
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(parse_file, file_list))
    
    return results
```

## 🔧 Troubleshooting

### Common Issues and Solutions

#### **Issue**: "MemoryError" when parsing large files
**Cause**: File size exceeds memory limits
**Solution**: Enable streaming mode
```python
config = MemoryConfiguration(
    max_memory_mb=8192,    # Increase limit
    enable_streaming=True  # Enable streaming
)
result = parse_cobol(large_file, memory_config=config)
```

#### **Issue**: "Unknown verb" errors for valid COBOL
**Cause**: Dialect incompatibility or unsupported verb
**Solution**: Check dialect support and version
```python
from cobolparser.models import DialectType, get_supported_verbs

# Check IBM Enterprise COBOL support
ibm_verbs = get_supported_verbs(DialectType.IBM_ENTERPRISE)
print(f"IBM Enterprise COBOL supports {len(ibm_verbs)} verbs")

# Try different dialect
result = parse_cobol(cobol_code, dialect=DialectType.IBM_ENTERPRISE)
```

#### **Issue**: Slow parsing performance
**Cause**: Large files, complex syntax, or suboptimal configuration
**Solution**: Optimize configuration and use parallel processing
```python
# Optimize memory configuration
config = MemoryConfiguration(
    max_memory_mb=2048,
    chunk_size_kb=1024,
    enable_streaming=True
)

# Use fail-fast mode for better performance
result = parse_cobol(cobol_code,
                    memory_config=config,
                    error_recovery=ErrorRecoveryMode.FAIL_FAST)
```

#### **Issue**: Missing data in AST output
**Cause**: Parsing errors or incomplete error recovery
**Solution**: Check error recovery mode and validate input
```python
# Use collect-all mode to see all issues
result = parse_cobol(cobol_code, error_recovery=ErrorRecoveryMode.COLLECT_ALL)

# Check for parsing errors
if result.errors:
    print(f"Found {len(result.errors)} parsing errors:")
    for error in result.errors:
        print(f"  Line {error.line}: {error.message}")

# Validate AST completeness
if result.ast:
    completeness = check_ast_completeness(result.ast)
    print(f"AST completeness: {completeness}%")
```

#### **Issue**: Import errors or missing dependencies
**Cause**: Installation issues or Python version incompatibility
**Solution**: Verify installation and Python version
```bash
# Check Python version
python --version  # Must be 3.13+

# Reinstall with development dependencies
pip uninstall cobolparser
pip install -e ".[dev]"

# Verify installation
python -c "from cobolparser import parse_cobol; print('Installation successful')"
```

### Debug Mode

Enable debug mode for detailed parsing information:
```python
import logging
logging.basicConfig(level=logging.DEBUG)

result = parse_cobol(cobol_code, debug=True)
```

### Getting Help

- **Documentation**: [Read the Docs](https://cobolparser.readthedocs.io)
- **Issues**: [GitHub Issues](https://github.com/Landparty/cobol-parser/issues)
- **Discussions**: [GitHub Discussions](https://github.com/Landparty/cobol-parser/discussions)
- **Examples**: See the [`docs/`](docs/) folder for comprehensive examples
```

## Documentation

The `docs/` folder contains comprehensive examples of parsed COBOL constructs showing the complete AST output for various statement types and language features.

### Available Examples

- **[CALL Statements](docs/call-statements.md)** - Function/procedure calls with parameters and exception handling
- **[PERFORM Statements](docs/perform-statements.md)** - Loop and subroutine execution constructs (SIMPLE, TIMES, UNTIL, VARYING)
- **[SQL Statements](docs/sql-statements.md)** - Embedded SQL (EXEC SQL) parsing with host variables
- **[COPY Statements](docs/copy-statements.md)** - Copybook inclusion and text replacement
- **[Data Items](docs/data-items.md)** - Variable declarations, COMP-3, arrays, and group structures
- **[Complete Program](docs/complete-program.md)** - Full COBOL program parsing example with comprehensive AST output
- **[IBM Enterprise Features](docs/ibm-enterprise.md)** - COMP-3, EXEC CICS, EXEC SQL, and other IBM-specific constructs
- **[File Control](docs/file-control.md)** - SELECT statements, file organizations, and access modes
- **[Parser Invocation Guide](docs/PARSER_INVOCATION_GUIDE.md)** - Complete API reference and usage patterns

Each documentation file includes:
- COBOL source code examples
- Complete JSON AST output
- Key property explanations
- Usage examples for code analysis

## 🎯 Common Use Cases

### 1. **Code Migration and Modernization**
```python
from cobolparser import parse_cobol
import json

# Parse legacy COBOL for migration analysis
with open('legacy_program.cob', 'r') as f:
    cobol_source = f.read()

result = parse_cobol(cobol_source)
if result.success:
    # Export to JSON for analysis tools
    ast_json = result.ast.to_json()
    
    # Analyze data structures for database migration
    data_items = result.ast.get_data_items()
    print(f"Found {len(data_items)} data definitions")
    
    # Identify SQL statements for database integration
    sql_statements = result.ast.get_sql_statements()
    print(f"Found {len(sql_statements)} embedded SQL statements")
```

### 2. **Documentation Generation**
```python
from cobolparser import parse_cobol

def generate_program_documentation(cobol_file):
    with open(cobol_file, 'r') as f:
        result = parse_cobol(f.read(), filename=cobol_file)
    
    if result.success:
        doc = f"""
# {result.ast.program_name} Documentation

**Author**: {result.ast.author}
**Parse Date**: {result.statistics.timestamp}

## Program Structure
"""
        for division_name, division in result.ast.divisions.items():
            doc += f"### {division_name}\n"
            if hasattr(division, 'sections'):
                for section_name in division.sections:
                    doc += f"- {section_name}\n"
        
        return doc
```

### 3. **Code Quality Analysis**
```python
from cobolparser import parse_cobol

def analyze_code_quality(cobol_source):
    result = parse_cobol(cobol_source)
    
    if result.success:
        metrics = {
            'total_lines': result.statistics.lines_parsed,
            'total_tokens': result.statistics.tokens_processed,
            'divisions': len(result.ast.divisions),
            'complexity_score': calculate_complexity(result.ast),
            'performance_issues': detect_performance_issues(result.ast)
        }
        return metrics
```

### 4. **Legacy System Integration**
```python
from cobolparser import parse_cobol
from cobolparser.models import CobolProgram

def integrate_with_modern_system(cobol_program_path):
    # Parse COBOL program
    with open(cobol_program_path, 'r') as f:
        result = parse_cobol(f.read())
    
    if result.success:
        # Extract interface definitions
        interfaces = extract_interfaces(result.ast)
        
        # Generate API documentation
        api_docs = generate_api_docs(interfaces)
        
        # Create data mapping
        data_mapping = create_data_mapping(result.ast)
        
        return {
            'interfaces': interfaces,
            'api_docs': api_docs,
            'data_mapping': data_mapping
        }
```

## 🚨 Error Handling and Troubleshooting

### Error Recovery Modes

The parser supports two error recovery modes for different scenarios:

#### Fail-Fast Mode (Production Default)
```python
from cobolparser import parse_cobol
from cobolparser.plugins.core import ErrorRecoveryMode

# Stop on first critical error
result = parse_cobol(cobol_code, error_recovery=ErrorRecoveryMode.FAIL_FAST)

if not result.success:
    print(f"Critical error at line {result.errors[0].line}: {result.errors[0].message}")
    # Handle critical parsing failure
```

#### Collect-All Mode (Development/Debugging)
```python
# Collect all errors for comprehensive analysis
result = parse_cobol(cobol_code, error_recovery=ErrorRecoveryMode.COLLECT_ALL)

if not result.success:
    print(f"Found {len(result.errors)} errors:")
    for error in result.errors:
        print(f"  Line {error.line}: {error.message}")
    
    # Continue with partial AST if available
    if result.ast:
        print("Partial parsing successful - AST available for analysis")
```

### Common Error Scenarios

#### 1. **Syntax Errors**
```python
# Example: Missing period at end of statement
cobol_with_syntax_error = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ERROR-EXAMPLE.
       
       PROCEDURE DIVISION.
           DISPLAY "Missing period"
           STOP RUN.
"""

result = parse_cobol(cobol_with_syntax_error)
# Error: Expected period at end of statement
```

#### 2. **Memory Issues**
```python
from cobolparser.plugins.core import MemoryConfiguration

# Configure memory limits for large programs
config = MemoryConfiguration(
    max_memory_mb=2048,    # 2GB limit
    chunk_size_kb=1024,    # 1MB chunks
    enable_streaming=True  # Enable streaming for large files
)

result = parse_cobol(large_cobol_program, memory_config=config)
```

#### 3. **Dialect Compatibility**
```python
from cobolparser import parse_cobol
from cobolparser.models import DialectType

# Parse with specific dialect
result = parse_cobol(cobol_code, dialect=DialectType.IBM_ENTERPRISE)

# Handle dialect-specific features
if result.ast.has_ibm_extensions():
    print("IBM Enterprise COBOL extensions detected")
    handle_ibm_extensions(result.ast)
```

### Troubleshooting Guide

#### **Issue**: Parser fails with "Memory limit exceeded"
**Solution**: Increase memory limits or enable streaming
```python
config = MemoryConfiguration(
    max_memory_mb=4096,    # Increase to 4GB
    enable_streaming=True  # Enable streaming mode
)
```

#### **Issue**: Parser reports "Unknown verb" errors
**Solution**: Check COBOL dialect and version compatibility
```python
# Verify dialect support
supported_verbs = get_supported_verbs(DialectType.IBM_ENTERPRISE)
print(f"Supported verbs: {len(supported_verbs)}")
```

#### **Issue**: Slow parsing performance
**Solution**: Optimize configuration and check for performance bottlenecks
```python
# Enable performance monitoring
result = parse_cobol(cobol_code)
print(f"Parse time: {result.statistics.total_time_ms}ms")
print(f"Lines/second: {result.statistics.lines_parsed / (result.statistics.total_time_ms/1000):.0f}")
```

#### **Issue**: Missing data in parsed AST
**Solution**: Check error recovery mode and validate input
```python
# Use collect-all mode to see all issues
result = parse_cobol(cobol_code, error_recovery=ErrorRecoveryMode.COLLECT_ALL)

# Validate AST completeness
if result.ast:
    completeness = check_ast_completeness(result.ast)
    print(f"AST completeness: {completeness}%")
```

## 🛠️ Contributing

We welcome contributions! Please follow these guidelines:

### Development Setup

1. Fork the repository
2. Clone your fork: `git clone https://github.com/your-username/cobol-parser.git`
3. Create a feature branch: `git checkout -b feature/your-feature`
4. Install development dependencies: `pip install -e ".[dev]"`

### Development Workflow

1. **Write Tests First** (TDD approach)
   ```bash
   # Add test for new feature
   python -m pytest tests/ -k "new_feature" -v
   ```

2. **Implement Feature**
   ```python
   # Implement the feature following existing patterns
   ```

3. **Run Full Test Suite**
   ```bash
   python -m pytest tests/ --cov=cobolparser --cov-fail-under=90
   ```

4. **Code Quality Checks**
   ```bash
   ruff check .
   black .
   mypy cobolparser/
   ```

5. **Update Documentation**
   - Update docstrings
   - Update README if needed
   - Update examples

### Code Standards

- **Python 3.13+** features only
- **Type hints** required for all public APIs
- **Docstrings** for all public functions/classes
- **Comprehensive test coverage** maintained (618 tests, 57%+ parser coverage)
- **Black formatting** enforced
- **Ruff linting** passes

### Pull Request Process

1. Ensure all tests pass
2. Update CHANGELOG.md with your changes
3. Submit PR with clear description
4. Address review feedback

### Adding New Features

When adding new COBOL language features:

1. **Check IBM Enterprise COBOL compatibility first**
2. **Add comprehensive tests** (unit + integration)
3. **Update AST models** if needed
4. **Document in README** with examples
5. **Maintain backward compatibility**

## 🔒 Security & Compliance

### Security Considerations

When using the COBOL parser in enterprise environments, consider the following security best practices:

#### Input Validation
```python
from cobolparser import parse_cobol
import os

def secure_parse_cobol(file_path):
    """Securely parse COBOL files with validation"""
    
    # Validate file path
    if not os.path.abspath(file_path).startswith('/safe/directory'):
        raise ValueError("File path not in allowed directory")
    
    # Check file size
    file_size = os.path.getsize(file_path)
    if file_size > 100 * 1024 * 1024:  # 100MB limit
        raise ValueError("File too large")
    
    # Parse with secure configuration
    with open(file_path, 'r', encoding='utf-8') as f:
        result = parse_cobol(f.read(), filename=file_path)
    
    return result
```

#### Memory Safety
```python
from cobolparser.plugins.core import MemoryConfiguration

# Configure secure memory limits
secure_config = MemoryConfiguration(
    max_memory_mb=1024,    # 1GB limit for security
    chunk_size_kb=512,     # Smaller chunks for better control
    enable_streaming=True  # Prevent memory exhaustion
)
```

### Compliance for Enterprise Use

#### Data Handling
- **No External Dependencies**: Pure Python implementation reduces supply chain risks
- **Memory Isolation**: Configurable memory limits prevent resource exhaustion
- **Input Sanitization**: Built-in validation for malformed COBOL code
- **Audit Trail**: Comprehensive logging and statistics for compliance

#### Enterprise Integration
```python
# Example: Secure enterprise integration
from cobolparser import parse_cobol
import logging

# Configure secure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('cobol_parser_audit.log'),
        logging.StreamHandler()
    ]
)

def enterprise_parse_workflow(cobol_source, user_id):
    """Enterprise-grade parsing workflow"""
    
    # Log parsing request
    logging.info(f"User {user_id} requested parsing of {len(cobol_source)} characters")
    
    # Parse with enterprise configuration
    result = parse_cobol(
        cobol_source,
        filename=f"user_{user_id}_program.cob",
        memory_config=MemoryConfiguration(
            max_memory_mb=2048,
            enable_streaming=True
        )
    )
    
    # Log parsing result
    if result.success:
        logging.info(f"Successfully parsed program for user {user_id}")
    else:
        logging.warning(f"Failed to parse program for user {user_id}: {len(result.errors)} errors")
    
    return result
```

### Regulatory Compliance

The parser is designed to support compliance with common enterprise requirements:

- **SOX Compliance**: Complete audit trails and change tracking
- **GDPR Compliance**: No personal data collection or storage
- **HIPAA Compliance**: No healthcare data processing
- **PCI DSS**: No payment card data handling

## 📋 License

MIT License - see [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Built following Test-Driven Development (TDD) principles
- Designed for IBM Enterprise COBOL compatibility with comprehensive verb support
- Supports modern Python 3.13+ features
- Comprehensive test coverage with 618 test cases across all components
- Memory-efficient parsing for large legacy codebases
- Enhanced lexer supporting 75+ COBOL verbs including all major IBM Enterprise verbs

## 🆘 Support

### Getting Help

- **Documentation**: [Read the Docs](https://cobolparser.readthedocs.io)
- **Issues**: [GitHub Issues](https://github.com/Landparty/cobol-parser/issues) - For bugs and feature requests
- **Discussions**: [GitHub Discussions](https://github.com/Landparty/cobol-parser/discussions) - For questions and community support
- **Examples**: See the [`docs/`](docs/) folder for comprehensive examples

### Enterprise Support

For enterprise users requiring dedicated support, SLAs, or custom features:

- **Priority Support**: Fast-track issue resolution
- **Custom Development**: Feature development and customization
- **Training**: Team training and workshops
- **Consulting**: Architecture and integration consulting

Contact us through GitHub Discussions for enterprise support inquiries.

---

**COBOL Parser Team** - Modernizing legacy code, one parse at a time. 🚀

## 📈 Recent Enhancements

### FILE-CONTROL SELECT Parsing
The parser now correctly handles multi-line `SELECT` statements in the `FILE-CONTROL` paragraph where the `ASSIGN [TO]` target appears on the following line, e.g.:

```
FILE-CONTROL.
    SELECT PRINT-FILE ASSIGN TO
        PRINTER01.
```

It also supports optional `ORGANIZATION [IS] <type>` and `ACCESS [MODE] [IS] <mode>` clause variants on the same or subsequent lines.

### Performance Improvements
- Enhanced memory management for large programs
- Optimized tokenization for better throughput
- Improved error recovery algorithms
- Streamlined AST generation process

### New Features
- Enhanced IBM Enterprise COBOL dialect support
- Better JSON serialization with metadata
- Improved source location tracking
- Advanced statistics and monitoring