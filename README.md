# COBOL Parser for Python

A comprehensive COBOL source code parser for Python 3.13+ with enhanced features including configurable memory management, JSON export, IBM Enterprise COBOL dialect support, and advanced error recovery.

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-114%20passing-green.svg)](#testing)
[![Coverage](https://img.shields.io/badge/coverage-46.68%25-orange.svg)](#coverage)
[![IBM COBOL](https://img.shields.io/badge/IBM%20Enterprise%20COBOL-supported-blue.svg)](#ibm-enterprise-cobol-support)

## Features

- 🚀 **Modern Python 3.13+** - Built with latest Python features
- 💾 **Memory Management** - Configurable limits from 64MB to 8GB
- 📄 **JSON Export** - Cross-platform AST serialization with metadata
- 🔧 **Error Recovery** - Fail-fast or collect-all error modes
- 🏢 **IBM Enterprise COBOL** - Priority support for COMP-3, EXEC SQL, EXEC CICS
- 🧩 **Plugin Architecture** - Extensible design for custom dialects
- 📊 **Statistics** - Detailed parsing metrics and performance monitoring
- ✅ **TDD Compliant** - 114 comprehensive tests ensuring reliability

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/your-username/cobol-parser.git
cd cobol-parser

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install pytest coverage
```

### Basic Usage

```python
from cobolparser import parse_cobol

# Parse COBOL source code
cobol_source = '''
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELLO-WORLD.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-MESSAGE    PIC X(20) VALUE "Hello, World!".
       
       PROCEDURE DIVISION.
       DISPLAY WS-MESSAGE.
       STOP RUN.
'''

# Parse the program
result = parse_cobol(cobol_source, filename="hello.cob")

if result.success:
    print(f"✅ Successfully parsed program: {result.ast.program_name}")
    print(f"📁 Divisions found: {len(result.ast.divisions)}")
    
    # Access program structure
    for div_name, division in result.ast.divisions.items():
        print(f"  📂 {division.division_name}")
        for sec_name, section in division.sections.items():
            print(f"    📄 {section.section_name} ({len(section.children)} items)")
else:
    print("❌ Parsing failed:")
    for error in result.errors:
        print(f"  {error}")
```

## Advanced Examples

### 1. Memory Management & Error Recovery

```python
from cobolparser import CobolParser, MemoryConfiguration, ErrorRecoveryMode

# Configure parser with memory limits and error handling
memory_config = MemoryConfiguration(
    max_memory_mb=256,      # 256MB limit
    chunk_size_kb=1024,     # 1MB chunks
    enable_streaming=True   # Enable streaming for large files
)

parser = CobolParser(
    memory_config=memory_config,
    error_recovery=ErrorRecoveryMode.COLLECT_ALL  # Collect all errors
)

# Parse with advanced configuration
result = parser.parse(cobol_source, "large_program.cob")

print(f"📊 Statistics:")
print(f"  ⏱️  Parse time: {result.statistics.total_time_ms:.2f}ms")
print(f"  📏 Lines parsed: {result.statistics.lines_parsed}")
print(f"  🔢 Tokens processed: {result.statistics.tokens_processed}")
print(f"  💾 Peak memory: {result.statistics.memory_peak_mb:.2f}MB")
print(f"  ❌ Errors: {result.statistics.error_count}")
print(f"  ⚠️  Warnings: {result.statistics.warning_count}")
```

### 2. IBM Enterprise COBOL Features

```python
from cobolparser import CobolParser, IBMEnterpriseCobol
from cobolparser.plugins.core import DialectType

# Use IBM Enterprise COBOL dialect
ibm_dialect = IBMEnterpriseCobol()
parser = CobolParser(dialect=DialectType.IBM_ENTERPRISE)

# Sample IBM COBOL program with COMP-3 and EXEC SQL
ibm_cobol = '''
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EMPLOYEE-DB.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-EMPLOYEE-REC.
           05  WS-EMP-ID        PIC 9(6) COMP-3.
           05  WS-EMP-NAME      PIC X(30).
           05  WS-EMP-SALARY    PIC 9(7)V99 COMP-3.
       
       01  SQLCA                COPY SQLCA.
       
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           EXEC SQL
               SELECT EMP_ID, EMP_NAME, SALARY
               INTO :WS-EMP-ID, :WS-EMP-NAME, :WS-EMP-SALARY
               FROM EMPLOYEE
               WHERE EMP_ID = :WS-EMP-ID
           END-EXEC.
           
           IF SQLCODE = 0
               DISPLAY 'Employee found: ' WS-EMP-NAME
           ELSE
               DISPLAY 'Employee not found'
           END-IF.
'''

result = parser.parse(ibm_cobol, "employee.cob")

# Validate IBM-specific features
if result.ast:
    data_division = result.ast.get_division_by_name("DATA")
    if data_division:
        ws_section = data_division.get_section_by_name("WORKING-STORAGE")
        for item in ws_section.children:
            if hasattr(item, 'usage') and item.usage == 'COMP-3':
                print(f"💰 COMP-3 field: {item.name}")

print(f"🏢 IBM Dialect Features:")
print(f"  📋 Reserved words: {len(ibm_dialect.IBM_RESERVED_WORDS)}")
print(f"  🔧 Intrinsic functions: {len(ibm_dialect.IBM_INTRINSIC_FUNCTIONS)}")
print(f"  🌐 CICS commands: {len(ibm_dialect.CICS_COMMANDS)}")
```

### 3. JSON Export & Cross-Platform Compatibility

```python
from cobolparser import parse_cobol
from cobolparser.plugins.core import SerializationConfig
import json

# Configure JSON serialization
serialization_config = SerializationConfig(
    include_metadata=True,
    include_source_locations=True,
    compact_format=False
)

# Parse program
result = parse_cobol(cobol_source, serialization_config=serialization_config)

if result.ast:
    # Export to JSON
    ast_json = result.ast.to_json(serialization_config)
    
    # Save to file
    with open('program_ast.json', 'w') as f:
        json.dump(ast_json, f, indent=2)
    
    print("📤 AST exported to JSON:")
    print(f"  📁 Program: {ast_json['program_name']}")
    print(f"  📊 Divisions: {ast_json['division_count']}")
    print(f"  📏 Lines: {ast_json['source_lines']}")
    
    # JSON structure example
    print("\n📋 JSON Structure:")
    print("```json")
    print(json.dumps({
        "program_name": ast_json["program_name"],
        "divisions": list(ast_json["divisions"].keys()),
        "metadata": {
            "parser_version": ast_json.get("metadata", {}).get("parser_version"),
            "dialect": ast_json.get("metadata", {}).get("dialect"),
            "parsed_at": ast_json.get("metadata", {}).get("parsed_at")
        }
    }, indent=2))
    print("```")
```

### 4. Lexical Analysis & Token Inspection

```python
from cobolparser import CobolLexer, TokenType

# Create lexer
lexer = CobolLexer(cobol_source, filename="example.cob")

# Tokenize source
tokens = lexer.tokenize()

print(f"🔍 Lexical Analysis:")
print(f"  📊 Total tokens: {len(tokens)}")
print(f"  ❌ Lexer errors: {len(lexer.get_errors())}")

# Analyze token types
token_counts = {}
for token in tokens:
    token_type = token.type.name
    token_counts[token_type] = token_counts.get(token_type, 0) + 1

print(f"\n🏷️  Token Distribution:")
for token_type, count in sorted(token_counts.items()):
    print(f"  {token_type}: {count}")

# Show sample tokens
print(f"\n📝 Sample Tokens:")
for i, token in enumerate(tokens[:10]):
    print(f"  {i+1:2d}. {token.type.name:20s} '{token.value}' @ {token.location.line}:{token.location.column}")
```

### 5. Data Item Analysis

```python
from cobolparser import parse_cobol

# COBOL program with various data types
data_cobol = '''
       IDENTIFICATION DIVISION.
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
           05  WS-PHONE         PIC 9(10).
       
       01  WS-ARRAY-DATA.
           05  WS-MONTHS        PIC X(3) OCCURS 12 TIMES.
           05  WS-SALES         PIC 9(7)V99 OCCURS 12 TIMES.
'''

result = parse_cobol(data_cobol)

if result.ast:
    data_div = result.ast.get_division_by_name("DATA")
    ws_section = data_div.get_section_by_name("WORKING-STORAGE")
    
    print("📊 Data Item Analysis:")
    
    def analyze_data_items(items, indent=0):
        for item in items:
            if hasattr(item, 'name') and hasattr(item, 'level'):
                prefix = "  " * indent
                size = item.calculate_storage_size() if hasattr(item, 'calculate_storage_size') else 0
                usage = getattr(item, 'usage', 'DISPLAY')
                picture = item.picture_clause.pattern if item.picture_clause else 'N/A'
                
                print(f"{prefix}📁 {item.level:02d} {item.name}")
                print(f"{prefix}   📏 Picture: {picture}")
                print(f"{prefix}   💾 Usage: {usage}")
                print(f"{prefix}   📐 Size: {size} bytes")
                
                if hasattr(item, 'children') and item.children:
                    analyze_data_items(item.children, indent + 1)
    
    analyze_data_items(ws_section.children)
```

### 6. Error Handling & Diagnostics

```python
from cobolparser import parse_cobol, ErrorRecoveryMode

# COBOL program with intentional errors
buggy_cobol = '''
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BUGGY-PROG.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-DATA          PIC X(10)  # Missing period
       01  WS-AMOUNT        PIC 9(5V99.  # Invalid picture
       
       PROCEDURE DIVISION.
       DISPLAY WS-DATA
       MOVE "ABC" TO WS-AMOUNT.  # Type mismatch
       STOP RUN.
'''

# Parse with error collection
result = parse_cobol(buggy_cobol, error_recovery=ErrorRecoveryMode.COLLECT_ALL)

print("🔍 Error Analysis:")
print(f"  ✅ Parse completed: {result.success}")
print(f"  ❌ Errors found: {len(result.errors)}")
print(f"  ⚠️  Warnings: {len(result.warnings)}")

if result.errors:
    print("\n📋 Error Details:")
    for i, error in enumerate(result.errors, 1):
        print(f"  {i}. Line {error.line}, Col {error.column}: {error.message}")

if result.warnings:
    print("\n⚠️  Warnings:")
    for i, warning in enumerate(result.warnings, 1):
        print(f"  {i}. {warning}")

# Show partial AST even with errors
if result.ast:
    print(f"\n🏗️  Partial AST Available:")
    print(f"    Program: {result.ast.program_name}")
    print(f"    Divisions: {len(result.ast.divisions)}")
```

## Testing

The parser includes a comprehensive test suite with 114 tests:

```bash
# Run all tests
python -m pytest tests/ -v

# Run with coverage
python -m coverage run -m pytest tests/
python -m coverage report
python -m coverage html  # Generate HTML report
```

### Test Categories

- **Contract Tests (38)**: API contract compliance
- **Integration Tests (17)**: End-to-end workflows  
- **Unit Tests (59)**: Component-specific functionality

## Architecture

```
cobolparser/
├── __init__.py           # Main package interface
├── lexer.py             # COBOL tokenization
├── parser.py            # Core parsing logic
├── models/              # AST node definitions
│   ├── ast_base.py     # Base AST classes
│   ├── program.py      # Program structure
│   ├── statements.py   # Statement nodes
│   └── data_items.py   # Data definition nodes
├── dialects/           # Dialect-specific support
│   ├── __init__.py
│   └── ibm_enterprise.py  # IBM Enterprise COBOL
└── plugins/            # Configuration & plugins
    ├── __init__.py
    └── core.py         # Core configurations
```

## IBM Enterprise COBOL Support

### Supported Features

- ✅ **COMP-3 Packed Decimal** - Native support with size calculation
- ✅ **EXEC SQL** - Embedded SQL statement parsing
- ✅ **EXEC CICS** - CICS transaction commands
- ✅ **Intrinsic Functions** - 25+ IBM-specific functions
- ✅ **Data Types** - COMP, COMP-1/2/3/4/5, POINTER types
- ✅ **z/OS Extensions** - Platform-specific features

### Example IBM Features

```python
from cobolparser.dialects.ibm_enterprise import IBMEnterpriseCobol

ibm = IBMEnterpriseCobol()

# Check IBM-specific features
print(f"COMP-3 reserved: {ibm.is_reserved_word('COMP-3')}")
print(f"LENGTH function: {ibm.is_intrinsic_function('LENGTH')}")
print(f"CICS READ: {ibm.is_cics_command('READ')}")

# Get function signature
length_sig = ibm.get_intrinsic_function_signature('LENGTH')
print(f"LENGTH function: {length_sig}")

# Create COMP-3 data item
from cobolparser.models.ast_base import SourceLocation
loc = SourceLocation('test.cob', 1, 1)
comp3_item = ibm.create_comp3_data_item('WS-AMOUNT', '9(7)V99', loc)
print(f"Storage size: {comp3_item.calculate_storage_size()} bytes")
```

## Configuration Options

### Memory Management

```python
from cobolparser.plugins.core import MemoryConfiguration

config = MemoryConfiguration(
    max_memory_mb=1024,    # Maximum memory usage (64MB - 8GB)
    chunk_size_kb=512,     # Processing chunk size
    enable_streaming=True   # Enable streaming for large files
)
```

### Error Recovery

```python
from cobolparser.plugins.core import ErrorRecoveryMode

# Fail on first error (default)
parser = CobolParser(error_recovery=ErrorRecoveryMode.FAIL_FAST)

# Collect all errors
parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
```

### JSON Serialization

```python
from cobolparser.plugins.core import SerializationConfig

config = SerializationConfig(
    include_metadata=True,        # Include parser metadata
    include_source_locations=True, # Include line/column info
    compact_format=False          # Pretty-print JSON
)
```

## Performance

- **Memory Efficient**: Configurable 64MB-8GB limits
- **Streaming Support**: Handle large COBOL programs
- **Fast Parsing**: Optimized lexer and parser
- **Statistics**: Built-in performance monitoring

```python
# Example performance metrics
result = parse_cobol(large_cobol_program)
stats = result.statistics

print(f"Parse time: {stats.total_time_ms}ms")
print(f"Peak memory: {stats.memory_peak_mb}MB")
print(f"Lines/second: {stats.lines_parsed / (stats.total_time_ms / 1000)}")
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## License

MIT License - see LICENSE file for details.

## Acknowledgments

- Built following Test-Driven Development (TDD) principles
- Designed for IBM Enterprise COBOL compatibility
- Supports modern Python 3.13+ features
- Comprehensive test coverage with 114 test cases