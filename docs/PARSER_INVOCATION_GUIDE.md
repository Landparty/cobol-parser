# COBOL Parser Invocation Guide

A comprehensive reference guide for understanding how the COBOL parser is invoked, where programs are parsed, and how the parsing pipeline works.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Entry Points](#entry-points)
3. [Parsing Pipeline Overview](#parsing-pipeline-overview)
4. [Configuration & Initialization](#configuration--initialization)
5. [Source File Loading](#source-file-loading)
6. [Parser Invocation Methods](#parser-invocation-methods)
7. [Real-World Usage Examples](#real-world-usage-examples)
8. [Advanced Features](#advanced-features)
9. [File Locations Reference](#file-locations-reference)

---

## Quick Start

### Simplest Usage

```python
from cobolparser import parse_cobol

# Parse a COBOL string directly
cobol_code = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELLO-WORLD.
       PROCEDURE DIVISION.
           DISPLAY "Hello, World!".
           STOP RUN.
"""

result = parse_cobol(cobol_code)
if result.success:
    print(f"Program name: {result.ast.program_name}")
```

### Full Configuration

```python
from cobolparser import (
    CobolParser, 
    MemoryConfiguration, 
    ErrorRecoveryMode, 
    DialectType
)

# Create configured parser instance
config = MemoryConfiguration(max_memory_mb=1024)
parser = CobolParser(
    dialect=DialectType.IBM_ENTERPRISE,
    error_recovery=ErrorRecoveryMode.COLLECT_ALL,
    memory_config=config,
    free_form=False
)

# Parse from source string
result = parser.parse(cobol_code, filename="program.cbl")

# Or parse from file directly
result = parser.parse_file("path/to/program.cbl")
```

---

## Entry Points

There are three main entry points to invoke the COBOL parser:

### 1. Module-Level Convenience Function: `parse_cobol()`

**Location**: `cobolparser/parser.py` (line ~3551)

**Signature**:
```python
def parse_cobol(
    source: str, 
    filename: str = "<string>",
    dialect: DialectType = DialectType.IBM_ENTERPRISE,
    error_recovery: ErrorRecoveryMode = ErrorRecoveryMode.FAIL_FAST,
    free_form: bool = False,
    preprocess_fixed: bool | None = None,
) -> ParseResult
```

**Purpose**: High-level convenience function for simple parsing tasks

**When to Use**: 
- One-off parsing operations
- Simple integration scenarios
- When you don't need to reuse the parser instance
- Quick prototyping and testing

**Parameters**:
- `source` (str): COBOL source code to parse
- `filename` (str): Used in error reporting (default: `<string>`)
- `dialect` (DialectType): COBOL dialect (default: `IBM_ENTERPRISE`)
- `error_recovery` (ErrorRecoveryMode): Recovery mode (default: `FAIL_FAST`)
- `free_form` (bool): Treat source as free-form vs fixed-format (default: False)
- `preprocess_fixed` (bool | None): Auto-normalize fixed-format. Default `None` enables **auto-detection** based on sequence numbers and indicator area.

**Returns**: `ParseResult` object with AST and metadata

**Example**:
```python
from cobolparser import parse_cobol, ErrorRecoveryMode

# Simple parse (automatically detects and handles fixed-format if needed)
result = parse_cobol(my_cobol_code)

# Explicitly enable fixed-format preprocessing
result = parse_cobol(my_fixed_format_code, preprocess_fixed=True)

# Parse with lenient error handling
result = parse_cobol(my_code, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
```

---

### 2. Instance Method: `CobolParser.parse()`

**Location**: `cobolparser/parser.py` (line ~130)

**Class**: `CobolParser`

**Signature**:
```python
def parse(self, source: str, filename: str = "<string>") -> ParseResult
```

**Purpose**: Parse COBOL source code using configured parser instance

**When to Use**:
- Parsing multiple programs with same configuration
- Need to reuse parser instance for performance
- Want precise control over parser settings
- Building batch processing pipelines

**Parameters**:
- `source` (str): COBOL source code
- `filename` (str): Source filename for error reporting

**Returns**: `ParseResult` with AST and metadata

**Parsing Flow**:
1. Reset statistics
2. Create `CobolLexer` instance
3. Tokenize source code
4. Initialize parser state (token index = 0, state = INITIAL)
5. Call `parse_program()` to build AST
6. Record statistics (lines parsed, tokens processed, timing)
7. Return `ParseResult`

**Example**:
```python
from cobolparser import CobolParser, MemoryConfiguration, ErrorRecoveryMode

# Create reusable parser instance
parser = CobolParser(
    error_recovery=ErrorRecoveryMode.COLLECT_ALL,
    memory_config=MemoryConfiguration(max_memory_mb=512)
)

# Parse multiple programs
programs = ["program1.cbl", "program2.cbl", "program3.cbl"]
for prog_file in programs:
    with open(prog_file) as f:
        result = parser.parse(f.read(), filename=prog_file)
    if result.success:
        print(f"Parsed: {result.ast.program_name}")
```

---

### 3. Instance Method: `CobolParser.parse_file()`

**Location**: `cobolparser/parser.py` (line ~173)

**Class**: `CobolParser`

**Signature**:
```python
def parse_file(self, filepath: str) -> ParseResult
```

**Purpose**: Parse COBOL program directly from filesystem

**When to Use**:
- Reading programs from disk
- File-based batch processing
- Integration with file management systems
- When file path is known but content is not

**Parameters**:
- `filepath` (str): Absolute or relative path to COBOL file

**Returns**: `ParseResult` with AST and metadata

**Internal Flow**:
1. Open file with UTF-8 encoding
2. Read entire file content
3. Call `self.parse(source, filepath)` with file content
4. Return result (or error if file I/O fails)

**Error Handling**:
- IOError: Caught and converted to ParseError
- File encoding: Assumes UTF-8 (errors='replace' for invalid chars)

**Example**:
```python
from cobolparser import CobolParser

parser = CobolParser()

# Parse directly from file
result = parser.parse_file("c:\\programs\\PAYROLL.cbl")

if result.success:
    print(f"Successfully parsed: {result.ast.program_name}")
    for error in result.errors:
        print(f"  Error: {error.message} at line {error.line}")
else:
    for error in result.errors:
        print(f"Failed: {error.message}")
```

---

## Parsing Pipeline Overview

### Two-Stage Architecture

The COBOL parser follows a **lexer → parser → AST** architecture:

```
COBOL Source Code
        ↓
    LEXER STAGE
        ↓
   Token Stream
        ↓
   PARSER STAGE
        ↓
 Abstract Syntax Tree (AST)
        ↓
   JSON Export / Analysis
```

### Stage 1: Lexical Analysis (Tokenization)

**Component**: `CobolLexer` (in `cobolparser/lexer.py`)

**Responsibility**: Convert raw COBOL source into tokens

**Process**:
1. Read source character-by-character
2. Recognize COBOL keywords, identifiers, literals, operators
3. Generate `Token` objects with location information
4. Track line/column numbers for error reporting
5. Handle multi-line string literals with concatenation indicators (`-`) and doubled quotes as escape sequences.
6. Support intelligent auto-detection of fixed-format source.

**Key Methods**:
- `CobolLexer.__init__(source, filename, dialect, free_form=False)`
- `CobolLexer.tokenize()` → List[Token]
- `CobolLexer.has_errors()` → bool
- `CobolLexer.get_errors()` → List[LexerError]

**Output**: List of `Token` objects with:
- `type` (TokenType enum)
- `value` (string)
- `location` (SourceLocation: line, column)

**Example Token Stream**:
```python
[
    Token(type=TokenType.IDENTIFICATION_DIVISION, value='IDENTIFICATION DIVISION', location=SourceLocation(1, 1, 1)),
    Token(type=TokenType.PERIOD, value='.', location=SourceLocation(1, 30, 30)),
    Token(type=TokenType.NEWLINE, value='\n', location=SourceLocation(1, 31, 31)),
    Token(type=TokenType.PROGRAM_ID, value='PROGRAM-ID', location=SourceLocation(2, 8, 8)),
    # ... more tokens
]
```

### Stage 2: Syntax Analysis (Parsing)

**Component**: `CobolParser` (in `cobolparser/parser.py`)

**Responsibility**: Build Abstract Syntax Tree (AST) from token stream

**Process**:
1. Consume tokens one by one (via `advance_token()`)
2. Match patterns against COBOL grammar
3. Build AST nodes representing program structure
4. Track parse state (which division/section are we in?)
5. Collect errors or warnings

**Key Methods**:
- `parse()` - Entry point, orchestrates entire parsing
- `parse_program()` - Parse top-level program structure
- `parse_identification_division()` - Parse ID division
- `parse_data_division()` - Parse data definitions
- `parse_procedure_division()` - Parse executable statements
- `parse_statements()` - Parse individual statements
- `parse_data_items()` - Parse DATA DIVISION items

**Output**: `CobolProgram` AST node with:
- Program name
- Author, date written, etc.
- Divisions (IDENTIFICATION, ENVIRONMENT, DATA, PROCEDURE)
- Sections within each division
- Statements and data items
- Full source location tracking

---

## Configuration & Initialization

### Creating a Parser Instance

```python
from cobolparser import CobolParser
from cobolparser.plugins.core import (
    MemoryConfiguration,
    ErrorRecoveryMode,
    DialectType,
    SerializationConfig
)

# Minimal configuration (all defaults)
parser = CobolParser()

# Full configuration with all options
parser = CobolParser(
    dialect=DialectType.IBM_ENTERPRISE,           # COBOL dialect
    error_recovery=ErrorRecoveryMode.COLLECT_ALL,  # Error handling mode
    memory_config=MemoryConfiguration(
        max_memory_mb=1024,
        enable_streaming=True,
        chunk_size_kb=512
    ),
    serialization_config=SerializationConfig(
        include_metadata=True,
        include_source_locations=True,
        compact_format=False
    ),
    free_form=False,                               # Fixed vs free format
    plugin_manager=None                            # Optional custom plugins
)
```

### Configuration Options

#### 1. Dialect Selection

**Parameter**: `dialect: DialectType`

**Options**:
- `DialectType.IBM_ENTERPRISE` (default) - IBM COBOL with extensions (COMP-3, EXEC SQL, EXEC CICS)
- `DialectType.ANSI_COBOL` - Standard ANSI COBOL-85
- `DialectType.MICRO_FOCUS` - MicroFocus COBOL extensions

**Impact**: 
- Determines which keywords are recognized
- Affects handling of vendor-specific extensions
- Influences error reporting and recovery

**Example**:
```python
# For IBM mainframe programs
ibm_parser = CobolParser(dialect=DialectType.IBM_ENTERPRISE)

# For ANSI-compliant programs
ansi_parser = CobolParser(dialect=DialectType.ANSI_COBOL)
```

#### 2. Error Recovery Mode

**Parameter**: `error_recovery: ErrorRecoveryMode`

**Options**:
- `ErrorRecoveryMode.FAIL_FAST` (default) - Stop parsing on first error
- `ErrorRecoveryMode.COLLECT_ALL` - Continue parsing and collect all errors

**Use Cases**:
```python
# Production: Stop immediately on error (fast, strict)
prod_parser = CobolParser(error_recovery=ErrorRecoveryMode.FAIL_FAST)

# Development: Collect all errors for comprehensive reporting
dev_parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
```

#### 3. Memory Management

**Parameter**: `memory_config: MemoryConfiguration`

**Configuration Fields**:
```python
@dataclass
class MemoryConfiguration:
    max_memory_mb: int = 256           # Memory limit (64-8192 MB)
    enable_streaming: bool = False     # Stream large files
    chunk_size_kb: int = 512           # Processing chunk size
```

**Use Cases**:
```python
# Small programs (< 1MB)
small_config = MemoryConfiguration(max_memory_mb=64)

# Medium programs (1-10MB)
medium_config = MemoryConfiguration(max_memory_mb=256)

# Large programs with streaming (> 10MB)
large_config = MemoryConfiguration(
    max_memory_mb=2048,
    enable_streaming=True,
    chunk_size_kb=1024
)
```

#### 4. JSON Serialization

**Parameter**: `serialization_config: SerializationConfig`

**Configuration Fields**:
```python
@dataclass
class SerializationConfig:
    include_metadata: bool = True           # Parser version, timestamp
    include_source_locations: bool = True   # Line/column information
    compact_format: bool = False            # Pretty-print vs compact
```

#### 5. Format Type

**Parameter**: `free_form: bool`

**Options**:
- `False` (default) - Fixed-format COBOL (columns 1-72)
- `True` - Free-format COBOL (modern style)

**Fixed-Format Details**:
```
Columns:  1-6: Sequence numbers (ignored)
Column:   7:   Indicator area (* = comment, - = continuation)
Columns:  8-72: Program text
```

**Example**:
```python
# Fixed-format (legacy mainframe programs)
parser1 = CobolParser(free_form=False)
result1 = parser1.parse(fixed_format_code)

# Free-format (modern programs) with auto-normalization
parser2 = CobolParser(free_form=False)
result2 = parse_cobol(fixed_format_code, preprocess_fixed=True)

# Free-format input (no normalization needed)
parser3 = CobolParser(free_form=True)
result3 = parser3.parse(free_format_code)
```

---

## Source File Loading

### File Loading Methods

#### 1. Direct File Path (Recommended)

```python
parser = CobolParser()
result = parser.parse_file("c:\\programs\\EMPLOYEE.cbl")

# Handles:
# - File I/O
# - UTF-8 encoding with error replacement
# - Error wrapping in ParseError
```

#### 2. Manual File Reading

```python
# For custom encoding or preprocessing
parser = CobolParser()

with open("c:\\programs\\EMPLOYEE.cbl", 'r', encoding='utf-8') as f:
    source = f.read()

result = parser.parse(source, filename="EMPLOYEE.cbl")
```

#### 3. With Fixed-Format Normalization

```python
from cobolparser import parse_cobol

# Auto-normalize fixed-format to pseudo free-form
with open("legacy.cbl", 'r') as f:
    source = f.read()

# This normalizes fixed-format columns and produces free-form output
result = parse_cobol(source, preprocess_fixed=True, filename="legacy.cbl")
```

#### 4. With Copybook Expansion

```python
from cobolparser import parse_cobol_with_expansion

# Expand COPY statements before parsing
result = parse_cobol_with_expansion(
    source_code=cobol_source,
    filename="program.cbl",
    copybook_paths=[
        "c:\\copybooks",
        "c:\\shared-copybooks",
        "/usr/local/cobol/copybooks"
    ],
    max_nesting_depth=100
)
```

### Encoding Detection

**For Files with Unknown Encoding**:
```python
from cobolparser.preprocess.copybook_expander import detect_encoding

# Detects UTF-8, EBCDIC (CP037), or ASCII
encoding = detect_encoding("file.cbl")
print(f"Detected encoding: {encoding}")

# Read with detected encoding
with open("file.cbl", 'r', encoding=encoding) as f:
    source = f.read()
```

**Detection Priority**:
1. UTF-8 BOM (`\xef\xbb\xbf`)
2. UTF-8 valid sequences
3. EBCDIC indicators (0x40 for space)
4. Fallback to ASCII

---

## Parser Invocation Methods

### Method 1: Single-Use Convenience Function

**Best For**: One-off parsing, quick testing

```python
from cobolparser import parse_cobol

result = parse_cobol("""
    IDENTIFICATION DIVISION.
    PROGRAM-ID. TEST.
    DATA DIVISION.
    WORKING-STORAGE SECTION.
    01 VAR1 PIC 9(5).
    PROCEDURE DIVISION.
        DISPLAY "Hello".
        STOP RUN.
""")

print(f"Success: {result.success}")
if result.ast:
    print(f"Program: {result.ast.program_name}")
```

### Method 2: Configured Parser Instance

**Best For**: Batch processing, consistent configuration

```python
from cobolparser import CobolParser, ErrorRecoveryMode

parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)

# Parse multiple files
for filename in ["prog1.cbl", "prog2.cbl", "prog3.cbl"]:
    with open(filename) as f:
        result = parser.parse(f.read(), filename=filename)
    
    if not result.success:
        for error in result.errors:
            print(f"{filename}: {error.message}")
```

### Method 3: File-Based Parsing

**Best For**: Reading from filesystem directly

```python
from cobolparser import CobolParser

parser = CobolParser()

result = parser.parse_file("c:\\legacy\\PAYROLL.cbl")

if result.success:
    # Access AST
    program = result.ast
    
    # Iterate divisions
    for div_name, division in program.divisions.items():
        print(f"Division: {div_name}")
        
        # Access sections
        for section in division.sections:
            print(f"  Section: {section.section_name}")
```

### Method 4: With Copybook Expansion

**Best For**: Programs with COPY statements

```python
from cobolparser import parse_cobol_with_expansion

result = parse_cobol_with_expansion(
    source_code=cobol_source,
    filename="main.cbl",
    copybook_paths=["c:\\copybooks"],
    max_nesting_depth=50
)

if result.success:
    print(f"Expanded and parsed: {result.ast.program_name}")
else:
    for error in result.errors:
        print(f"Error: {error}")
```

---

## Real-World Usage Examples

### Example 1: Batch Parse Directory of COBOL Files

```python
from cobolparser import CobolParser, ErrorRecoveryMode
from pathlib import Path

parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
cobol_dir = Path("c:\\legacy-cobol")

# Parse all .cbl files in directory
for cobol_file in cobol_dir.glob("*.cbl"):
    result = parser.parse_file(str(cobol_file))
    
    print(f"File: {cobol_file.name}")
    print(f"  Success: {result.success}")
    print(f"  Errors: {len(result.errors)}")
    print(f"  Parse time: {result.statistics.total_time_ms}ms")
    
    if result.success and result.ast:
        print(f"  Program name: {result.ast.program_name}")
        print(f"  Divisions: {len(result.ast.divisions)}")
```

### Example 2: Parse with Error Collection and Detailed Reporting

```python
from cobolparser import CobolParser, ErrorRecoveryMode

parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)

result = parser.parse(cobol_source, filename="complex.cbl")

print(f"Parse Success: {result.success}")
print(f"Total Errors: {len(result.errors)}")
print(f"Total Warnings: {len(result.warnings)}")

# Report each error
for error in result.errors:
    print(f"ERROR at {error.line}:{error.column}: {error.message}")

# Report warnings
for warning in result.warnings:
    print(f"WARNING: {warning}")

# Report statistics
stats = result.statistics
print(f"Parse Statistics:")
print(f"  Lines parsed: {stats.lines_parsed}")
print(f"  Tokens processed: {stats.tokens_processed}")
print(f"  Parse time: {stats.total_time_ms}ms")
print(f"  Memory usage: {stats.memory_peak_mb}MB")
```

### Example 3: Parse and Export to JSON

```python
from cobolparser import parse_cobol
from cobolparser.plugins.core import SerializationConfig
import json

# Parse the program
result = parse_cobol(cobol_source, filename="program.cbl")

if result.success:
    # Export to JSON with metadata
    ast_dict = result.ast.to_dict()
    
    json_output = {
        "success": result.success,
        "program": ast_dict,
        "statistics": {
            "lines_parsed": result.statistics.lines_parsed,
            "tokens_processed": result.statistics.tokens_processed,
            "parse_time_ms": result.statistics.total_time_ms
        }
    }
    
    # Write to file
    with open("output.json", "w") as f:
        json.dump(json_output, f, indent=2)
```

### Example 4: Handle Large Programs with Streaming

```python
from cobolparser import CobolParser, MemoryConfiguration

# Configure for large program (up to 2GB)
config = MemoryConfiguration(
    max_memory_mb=4096,
    enable_streaming=True,
    chunk_size_kb=2048
)

parser = CobolParser(memory_config=config)

# Parse large file
result = parser.parse_file("huge_legacy_program.cbl")

if result.success:
    print(f"Successfully parsed {result.statistics.lines_parsed} lines")
    print(f"Peak memory: {result.statistics.memory_peak_mb}MB")
else:
    print(f"Parse failed: {result.errors[0].message}")
```

---

## Advanced Features

### 1. IBM Enterprise COBOL Extensions

**Automatically Supported** when using `DialectType.IBM_ENTERPRISE`:

```python
from cobolparser import CobolParser, DialectType

parser = CobolParser(dialect=DialectType.IBM_ENTERPRISE)

# Parser recognizes and handles:
# - COMP-3 packed decimal data types
# - EXEC SQL embedded SQL statements
# - EXEC CICS transaction commands
# - IBM intrinsic functions
# - z/OS platform-specific features

result = parser.parse("""
    IDENTIFICATION DIVISION.
    PROGRAM-ID. SQL-EXAMPLE.
    
    DATA DIVISION.
    WORKING-STORAGE SECTION.
    01 EMPLOYEE-ID COMP-3 PIC 9(9).
    01 EMPLOYEE-NAME PIC X(50).
    
    PROCEDURE DIVISION.
        EXEC SQL
            SELECT EMP_ID, EMP_NAME
            INTO :EMPLOYEE-ID, :EMPLOYEE-NAME
            FROM EMPLOYEES
            WHERE EMP_ID = 12345
        END-EXEC.
        STOP RUN.
""")
```

### 2. Copybook Expansion

**Expands COPY statements before parsing**:

```python
from cobolparser import parse_cobol_with_expansion

# Source with COPY statements
source = """
    IDENTIFICATION DIVISION.
    PROGRAM-ID. MAIN.
    DATA DIVISION.
    WORKING-STORAGE SECTION.
    COPY COMMON-DEFS.
    COPY EMPLOYEE-RECORD.
    PROCEDURE DIVISION.
        DISPLAY "Program".
        STOP RUN.
"""

result = parse_cobol_with_expansion(
    source_code=source,
    filename="main.cbl",
    copybook_paths=[
        "c:\\copybooks",
        "/opt/cobol/copybooks"
    ],
    max_nesting_depth=100
)

print(f"Expanded source: {result.statistics.lines_parsed} lines")
```

**Features**:
- Circular reference detection
- Nested copybook support
- Conditional compilation (`>>IF`, `>>DEFINE`)
- REPLACING clause support
- Source location tracking
- Encoding auto-detection

### 3. Source Location Tracking

**Every AST node has precise source location**:

```python
result = parser.parse(cobol_source)

if result.success:
    # Access source location for error reporting
    program = result.ast
    print(f"Program defined at: line {program.location.line}, col {program.location.column}")
    
    # Works for all AST nodes
    for div_name, division in program.divisions.items():
        print(f"{div_name} at line {division.location.line}")
        
        for section in division.sections:
            print(f"  {section.section_name} at line {section.location.line}")
```

### 4. JSON Export

**Complete AST serialization**:

```python
import json

result = parser.parse(cobol_source)

if result.success:
    # Entire AST to JSON
    json_data = result.ast.to_dict()
    
    # With custom serialization config
    from cobolparser.plugins.core import SerializationConfig
    
    config = SerializationConfig(
        include_metadata=True,
        include_source_locations=True,
        compact_format=False  # Pretty-print
    )
    
    # Export with metadata
    full_json = result.ast.to_json(config)
    print(json.dumps(full_json, indent=2))
```

### 5. Batch / Multi-File Parsing

**Parallel parsing of multiple files** using multiprocessing:

```python
from cobolparser import parse_files

paths = ["program1.cbl", "program2.cbl", "program3.cbl"]
results = parse_files(paths)   # parallel, uses multiprocessing

for r in results:
    if r.result and r.result.success:
        print(f"{r.path}: {r.result.ast.program_name}")
    else:
        error = r.read_error or r.result.errors[0].message
        print(f"{r.path}: FAILED — {error}")
```

**Features**:
- Parallel processing (one process per file)
- Automatic resource cleanup
- Per-file error handling
- Return type: `List[BatchResult]`

---

## File Locations Reference

### Core Parsing Components

| Component | Location | Responsibility |
|-----------|----------|-----------------|
| `parse_cobol()` | `cobolparser/parser.py:3551` | Module-level convenience function |
| `CobolParser` class | `cobolparser/parser.py:65` | Main parser class |
| `CobolParser.parse()` | `cobolparser/parser.py:130` | Parse source code |
| `CobolParser.parse_file()` | `cobolparser/parser.py:173` | Parse from file |
| `CobolLexer` class | `cobolparser/lexer.py:~500` | Tokenization engine |
| `CobolLexer.tokenize()` | `cobolparser/lexer.py:~600` | Generate token stream |

### AST Node Classes

| Node Type | Location | Represents |
|-----------|----------|------------|
| `CobolProgram` | `cobolparser/models/program.py:200` | Complete COBOL program |
| `CobolDivision` | `cobolparser/models/program.py:60` | Division (ID, DATA, PROCEDURE) |
| `CobolSection` | `cobolparser/models/program.py:20` | Section (WORKING-STORAGE, FILE, etc.) |
| `CobolDataItem` | `cobolparser/models/data_items.py:50` | Data definition (01, 02, etc.) |
| `CobolStatement` | `cobolparser/models/statements.py:50` | Executable statement (MOVE, DISPLAY) |

### Configuration & Plugins

| Configuration | Location | Purpose |
|---------------|----------|---------|
| `MemoryConfiguration` | `cobolparser/plugins/core.py:30` | Memory management settings |
| `ErrorRecoveryMode` | `cobolparser/plugins/core.py:16` | Error handling strategy |
| `DialectType` | `cobolparser/plugins/core.py:21` | COBOL dialect selection |
| `SerializationConfig` | `cobolparser/plugins/core.py:56` | JSON export settings |
| `ParseError` | `cobolparser/plugins/core.py:75` | Parse error representation |

### Preprocessing & Copybooks

| Component | Location | Purpose |
|-----------|----------|---------|
| `parse_cobol_with_expansion()` | `cobolparser/preprocess/copybook_expander.py:470` | Expand copybooks + parse |
| `expand_copybooks()` | `cobolparser/preprocess/copybook_expander.py:~300` | Expand COPY statements |
| `normalize_fixed_format()` | `cobolparser/preprocess/__init__.py:130` | Normalize fixed-format columns |
| `detect_encoding()` | `cobolparser/preprocess/copybook_expander.py:30` | Detect file encoding |

### Test Examples

| Test File | Location | Demonstrates |
|-----------|----------|--------------|
| `test_all_cobol_examples.py` | `tests/integration/` | Real-world file parsing |
| `test_advanced_constructs.py` | `tests/unit/` | Parser usage patterns |
| Integration tests | `tests/integration/` | End-to-end workflows |
| Contract tests | `tests/contracts/` | API compatibility |

---

## Summary

The COBOL parser invocation follows this flow:

1. **Entry Point**: Call `parse_cobol()`, `CobolParser.parse()`, or `CobolParser.parse_file()`

2. **Configuration**: Initialize parser with dialect, error recovery mode, memory config

3. **Lexical Analysis**: 
   - Create `CobolLexer` instance
   - Tokenize source into `Token` stream
   - Track source locations

4. **Syntax Analysis**:
   - Initialize parser state machine
   - Consume tokens and build AST
   - Create `CobolProgram` root node with divisions

5. **Return Results**: `ParseResult` with:
   - `ast`: Complete AST (or None if failed)
   - `errors`: List of `ParseError` objects
   - `warnings`: Non-critical warnings
   - `statistics`: Parse metrics

6. **Post-Processing**:
   - Export to JSON if needed
   - Traverse AST for analysis
   - Generate error reports

For advanced scenarios (copybooks, large files, custom dialects), configure appropriately before parsing.
