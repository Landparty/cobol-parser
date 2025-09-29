# COBOL Parser for Python

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-618%20passing-green.svg)](#testing)
[![Coverage](https://img.shields.io/badge/coverage-57%2B%25%20parser-yellow.svg)](#testing)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![IBM COBOL](https://img.shields.io/badge/IBM%20Enterprise%20COBOL-supported-blue.svg)](#ibm-enterprise-cobol-support)

A comprehensive COBOL source code parser for Python 3.13+ with enhanced features including configurable memory management, JSON export, IBM Enterprise COBOL dialect support, and advanced error recovery. Built following Test-Driven Development (TDD) principles with comprehensive test coverage (618 tests, 57%+ parser coverage).

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Advanced Usage](#advanced-usage)
- [Architecture](#architecture)
- [IBM Enterprise COBOL Support](#ibm-enterprise-cobol-support)
- [Configuration Options](#configuration-options)
- [API Reference](#api-reference)
- [Testing](#testing)
- [Performance](#performance)
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
- 🔍 **Lexical Analysis** - Complete tokenization with comprehensive COBOL verb support (75+ verbs) and error reporting
- 🏗️ **AST Generation** - Full Abstract Syntax Tree with source location tracking

## Installation

### Requirements

- Python 3.13 or higher
- No external dependencies (pure Python)

### Install from Source

```bash
# Clone the repository
git clone https://github.com/Landparty/cobol-parser.git
cd cobol-parser

# Install in development mode
pip install -e .

# Optional: Install development dependencies
pip install -e ".[dev]"
```

### Development Setup

```bash
# Install all development tools
pip install -e ".[dev,docs]"

# Run tests to verify installation
python -m pytest tests/ -v

# Check code quality
ruff check .
black --check .
mypy cobolparser/
```

## Quick Start

### Basic Parsing

```python
from cobolparser import parse_cobol

# Simple COBOL program
cobol_code = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELLO-WORLD.
       
       PROCEDURE DIVISION.
           DISPLAY "Hello, World!".
           STOP RUN.
"""

# Parse the program
result = parse_cobol(cobol_code, filename="hello.cob")

if result.success:
    print(f"Successfully parsed: {result.ast.program_name}")
    print(f"Divisions: {len(result.ast.divisions)}")
else:
    print("Parsing failed:")
    for error in result.errors:
        print(f"  {error}")
```

### Working with AST

```python
from cobolparser import parse_cobol

result = parse_cobol(cobol_code)

if result.ast:
    # Access program structure
    program = result.ast

    print(f"Program: {program.program_name}")
    print(f"Author: {program.author}")

    # Iterate through divisions
    for div_name, division in program.divisions.items():
        print(f"Division: {division.division_name}")
        print(f"  Sections: {len(division.sections)}")

        # Access sections and their contents
        for sec_name, section in division.sections.items():
            print(f"  Section: {section.section_name}")
            print(f"    Items: {len(section.children)}")
```

## Advanced Usage

### Memory Management for Large Programs

```python
from cobolparser import CobolParser, MemoryConfiguration

# Configure for large COBOL programs (up to 2GB)
memory_config = MemoryConfiguration(
    max_memory_mb=2048,      # 2GB memory limit
    chunk_size_kb=1024,      # 1MB processing chunks
    enable_streaming=True    # Enable streaming for very large files
)

parser = CobolParser(memory_config=memory_config)

# Parse large program
with open('large_program.cob', 'r') as f:
    result = parser.parse(f.read(), filename='large_program.cob')

print(f"Memory used: {result.statistics.memory_peak_mb:.1f}MB")
print(f"Parse time: {result.statistics.total_time_ms:.2f}ms")
```

### Error Recovery Modes

```python
from cobolparser import CobolParser, ErrorRecoveryMode

# Strict mode - fail on first error
strict_parser = CobolParser(error_recovery=ErrorRecoveryMode.FAIL_FAST)

# Lenient mode - collect all errors
lenient_parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)

# Parse program with errors
buggy_cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. BUGGY.

       PROCEDURE DIVISION.
           DISPLAY "This is fine".
           MISSPELLED STATEMENT.
           DISPLAY "This won't be reached in strict mode".
"""

# Strict parsing stops at first error
strict_result = strict_parser.parse(buggy_cobol)
print(f"Strict mode - Errors: {len(strict_result.errors)}")

# Lenient parsing continues and collects all errors
lenient_result = lenient_parser.parse(buggy_cobol)
print(f"Lenient mode - Errors: {len(lenient_result.errors)}")
```

### IBM Enterprise COBOL Features

```python
from cobolparser import CobolParser
from cobolparser.dialects import IBMEnterpriseCobol
from cobolparser.plugins.core import DialectType

# Use IBM Enterprise COBOL dialect
ibm_parser = CobolParser(dialect=DialectType.IBM_ENTERPRISE)

# COBOL program with IBM-specific features
ibm_cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. EMPLOYEE-DB.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-EMPLOYEE-REC.
           05  WS-EMP-ID        PIC 9(6) COMP-3.
           05  WS-EMP-NAME      PIC X(30).
           05  WS-EMP-SALARY    PIC 9(7)V99 COMP-3.

       PROCEDURE DIVISION.
       MAIN-PROCESS.
           EXEC SQL
               SELECT EMP_ID, EMP_NAME, SALARY
               INTO :WS-EMP-ID, :WS-EMP-NAME, :WS-EMP-SALARY
               FROM EMPLOYEE
               WHERE EMP_ID = 123456
           END-EXEC.

           IF SQLCODE = 0
               DISPLAY 'Employee found: ' WS-EMP-NAME
           ELSE
               DISPLAY 'Employee not found'
           END-IF.

           STOP RUN.
"""

result = ibm_parser.parse(ibm_cobol, filename="employee.cob")

# Access IBM-specific features
if result.ast:
    data_div = result.ast.get_division_by_name("DATA")
    ws_section = data_div.get_section_by_name("WORKING-STORAGE")

    for item in ws_section.children:
        if hasattr(item, 'usage') and item.usage == 'COMP-3':
            print(f"COMP-3 field: {item.name} (size: {item.calculate_storage_size()} bytes)")
```

### JSON Export and Serialization

```python
from cobolparser import parse_cobol
from cobolparser.plugins.core import SerializationConfig
import json

# Configure JSON serialization
serialization_config = SerializationConfig(
    include_metadata=True,        # Include parser metadata
    include_source_locations=True, # Include line/column info
    compact_format=False          # Pretty-print JSON
)

# Parse and export to JSON
result = parse_cobol(cobol_code, serialization_config=serialization_config)

if result.ast:
    # Export AST to JSON
    ast_json = result.ast.to_json(serialization_config)

    # Save to file
    with open('program_ast.json', 'w', encoding='utf-8') as f:
        json.dump(ast_json, f, indent=2, ensure_ascii=False)

    print("AST exported to JSON:")
    print(f"  Program: {ast_json['program_name']}")
    print(f"  Divisions: {ast_json['division_count']}")
    print(f"  Lines: {ast_json['source_lines']}")
    print(f"  Metadata: {bool(ast_json.get('metadata'))}")
```

### Lexical Analysis

```python
from cobolparser import CobolLexer, TokenType

# Create lexer
lexer = CobolLexer(cobol_code, filename="example.cob")

# Tokenize source
tokens = lexer.tokenize()

print(f"Lexical Analysis:")
print(f"  Total tokens: {len(tokens)}")
print(f"  Lexer errors: {len(lexer.get_errors())}")

# Analyze token distribution
token_counts = {}
for token in tokens:
    token_type = token.type.name
    token_counts[token_type] = token_counts.get(token_type, 0) + 1

print("Token Distribution:")
for token_type, count in sorted(token_counts.items(), key=lambda x: x[1], reverse=True):
    print(f"  {token_type}: {count}")

# Show sample tokens
print("Sample Tokens:")
for i, token in enumerate(tokens[:10]):
    print(f"  {i+1:2d}. {token.type.name:15s} '{token.value}' @ {token.location.line}:{token.location.column}")
```

### Data Item Analysis

```python
from cobolparser import parse_cobol

# COBOL program with various data types
data_cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. DATA-TYPES.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-NUMERIC-DATA.
           05  WS-INTEGER       PIC 9(5).
           05  WS-DECIMAL       PIC 9(7)V99.
           05  WS-PACKED        PIC 9(5) COMP-3.
           05  WS-BINARY        PIC 9(8) COMP.

       01  WS-STRING-DATA.
           05  WS-NAME          PIC X(30).
           05  WS-ADDRESS       PIC X(50).

       01  WS-ARRAYS.
           05  WS-MONTHS        PIC X(3) OCCURS 12 TIMES.
           05  WS-SALES         PIC 9(7)V99 OCCURS 12 TIMES.
"""

result = parse_cobol(data_cobol)

if result.ast:
    data_div = result.ast.get_division_by_name("DATA")
    ws_section = data_div.get_section_by_name("WORKING-STORAGE")

    def analyze_data_items(items, indent=0):
        for item in items:
            if hasattr(item, 'name') and hasattr(item, 'level'):
                prefix = "  " * indent
                size = item.calculate_storage_size() if hasattr(item, 'calculate_storage_size') else 0
                usage = getattr(item, 'usage', 'DISPLAY')
                picture = item.picture_clause.pattern if item.picture_clause else 'N/A'

                print(f"{prefix}{item.level:02d} {item.name}")
                print(f"{prefix}   Picture: {picture}")
                print(f"{prefix}   Usage: {usage}")
                print(f"{prefix}   Size: {size} bytes")

                if hasattr(item, 'children') and item.children:
                    analyze_data_items(item.children, indent + 1)

    analyze_data_items(ws_section.children)
```

## Architecture

The COBOL parser follows a two-stage pipeline architecture:

```
COBOL Source Code
        ↓
    Lexer (Tokenization)
        ↓
    Parser (AST Generation)
        ↓
Abstract Syntax Tree (AST)
        ↓
   JSON Export / Analysis
```

### Core Components

```
cobolparser/
├── __init__.py           # Main package interface and exports
├── lexer.py             # COBOL tokenization with 75+ verb support (416 statements)
├── parser.py            # AST generation and parsing logic (1176 lines, 636 statements)
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

## IBM Enterprise COBOL Support

The parser prioritizes IBM Enterprise COBOL dialect features:

### Supported Features

- ✅ **COMP-3 Packed Decimal** - Native support with automatic storage size calculation
- ✅ **EXEC SQL** - Embedded SQL statement parsing with host variable detection
- ✅ **EXEC CICS** - CICS transaction commands and API calls
- ✅ **Intrinsic Functions** - 25+ IBM-specific functions (LENGTH, NUMVAL, etc.)
- ✅ **Data Types** - COMP, COMP-1/2/3/4/5, POINTER types
- ✅ **z/OS Extensions** - Platform-specific features and reserved words

### IBM-Specific Data Types

```python
from cobolparser.dialects.ibm_enterprise import IBMEnterpriseCobol, IBMDataType

ibm = IBMEnterpriseCobol()

# Check supported data types
print("IBM Data Types:")
for dtype in IBMDataType:
    print(f"  {dtype.value}")

# COMP-3 storage calculation
comp3_item = ibm.create_comp3_data_item('WS-AMOUNT', '9(7)V99', SourceLocation('test.cob', 1, 1))
print(f"COMP-3 field storage: {comp3_item.calculate_storage_size()} bytes")
```

### EXEC SQL Support

```python
# The parser recognizes and parses EXEC SQL blocks
exec_sql = """
EXEC SQL
    SELECT EMP_ID, EMP_NAME, SALARY
    INTO :WS-EMP-ID, :WS-EMP-NAME, :WS-EMP-SALARY
    FROM EMPLOYEE
    WHERE EMP_ID = :SEARCH-ID
END-EXEC.
"""

result = parse_cobol(exec_sql)
# Host variables are automatically detected and tracked
```

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
Convenience function for simple parsing.

```python
from cobolparser import parse_cobol

result = parse_cobol(source_code, filename="program.cob")
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

## Performance

### Memory Efficiency

- **Configurable Limits**: 64MB to 8GB memory limits
- **Streaming Support**: Handle programs larger than available RAM
- **Chunked Processing**: Process large files in configurable chunks
- **Automatic Cleanup**: Efficient memory usage with garbage collection

### Benchmarks

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

## Contributing

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

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built following Test-Driven Development (TDD) principles
- Designed for IBM Enterprise COBOL compatibility with comprehensive verb support
- Supports modern Python 3.13+ features
- Comprehensive test coverage with 618 test cases across all components
- Memory-efficient parsing for large legacy codebases
- Enhanced lexer supporting 75+ COBOL verbs including all major IBM Enterprise verbs

## Support

- **Issues**: [GitHub Issues](https://github.com/Landparty/cobol-parser/issues)
- **Discussions**: [GitHub Discussions](https://github.com/Landparty/cobol-parser/discussions)
- **Documentation**: [Read the Docs](https://cobolparser.readthedocs.io)

---

**COBOL Parser Team** - Modernizing legacy code, one parse at a time.