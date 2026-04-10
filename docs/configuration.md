# Configuration

All configuration options can be set through the Python API or via the CLI.

## Memory Configuration

Controls memory limits and streaming behavior for large files.

### Python API

```python
from cobolparser.plugins.core import MemoryConfiguration

config = MemoryConfiguration(
    max_memory_mb=1024,    # 64MB–8GB
    chunk_size_kb=512,     # processing chunk size
    enable_streaming=True  # required for files > available RAM
)

result = parse_cobol(source, memory_config=config)
```

## Error Recovery

Controls whether parsing stops at the first error or continues to collect all errors.

### CLI

```bash
# Fail-fast mode (stop on first error) — faster, use in production
cobol-parser parse program.cbl --error-recovery fail-fast

# Collect-all mode (gather every error) — default, best for debugging
cobol-parser parse program.cbl --error-recovery collect-all
```

### Python API

```python
from cobolparser.plugins.core import ErrorRecoveryMode

# Stop on first error — faster, use in production
result = parse_cobol(source, error_recovery=ErrorRecoveryMode.FAIL_FAST)

# Collect all errors — slower, use for debugging
result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
```

## Dialect Selection

Selects the COBOL dialect, which determines which keywords and extensions are recognized.

### CLI

```bash
# IBM Enterprise COBOL (default — supports COMP-3, EXEC SQL, EXEC CICS)
cobol-parser parse program.cbl --dialect ibm-enterprise
```

### Python API

```python
from cobolparser.plugins.core import DialectType

result = parse_cobol(source, dialect=DialectType.IBM_ENTERPRISE)
```

## Source Format

Determines whether the source is fixed-format (columns 1-72) or free-form.

### CLI

```bash
# Fixed-format (default — standard mainframe layout)
cobol-parser parse program.cbl

# Free-form COBOL
cobol-parser parse program.cbl --free-form

# Preprocess fixed-format to free-form text
cobol-parser preprocess program.cbl
```

### Python API

```python
# Fixed-format (default)
result = parse_cobol(source, free_form=False)

# Free-form
result = parse_cobol(source, free_form=True)

# Auto-detect and normalize fixed-format
result = parse_cobol(source, preprocess_fixed=True)
```

## JSON Serialization

Controls the JSON output format for AST export.

### CLI

```bash
# Pretty-printed JSON (default)
cobol-parser parse program.cbl

# Compact single-line JSON
cobol-parser parse program.cbl --compact

# Include errors and statistics in the output
cobol-parser parse program.cbl --errors --stats
```

### Python API

```python
from cobolparser.plugins.core import SerializationConfig

config = SerializationConfig(
    include_metadata=True,         # parser version, timestamp
    include_source_locations=True, # line/column info per node
    compact_format=False           # pretty-print vs compact JSON
)
```

## Conditional Compilation

Define symbols for `>>IF`/`>>DEFINE` conditional compilation directives.

### CLI

```bash
# Define a symbol (defaults to TRUE)
cobol-parser parse program.cbl --define DEBUG

# Define a symbol with a value
cobol-parser parse program.cbl --define ENV=PRODUCTION

# Multiple definitions
cobol-parser parse program.cbl --define DEBUG --define ENV=PRODUCTION

# Preprocess with conditional compilation
cobol-parser preprocess program.cbl --define DEBUG
```

## Copybook Expansion

Configure where copybooks are searched and how deeply nesting is allowed.

### CLI

```bash
# Expand COPY statements from a single directory
cobol-parser expand program.cbl --copybook-path ./copybooks

# Multiple search directories
cobol-parser expand program.cbl --copybook-path ./copybooks --copybook-path ./shared

# Limit nesting depth (default: 100)
cobol-parser expand program.cbl --copybook-path ./copybooks --max-depth 10

# Parse with copybook expansion
cobol-parser parse program.cbl --copybook-path ./copybooks
```

### Python API

```python
from cobolparser import parse_cobol_with_expansion

result = parse_cobol_with_expansion(
    source,
    filename="program.cbl",
    copybook_paths=["./copybooks", "./shared"],
    max_nesting_depth=100,
)
```

## Full CobolParser Constructor

```python
from cobolparser import CobolParser
from cobolparser.plugins.core import (
    MemoryConfiguration, ErrorRecoveryMode, SerializationConfig, DialectType
)

parser = CobolParser(
    memory_config=MemoryConfiguration(max_memory_mb=2048),
    error_recovery=ErrorRecoveryMode.COLLECT_ALL,
    dialect=DialectType.IBM_ENTERPRISE,
    serialization_config=SerializationConfig(include_source_locations=True)
)

result = parser.parse(source, filename="program.cob")
```

## parse_cobol() Convenience Function

```python
from cobolparser import parse_cobol

result = parse_cobol(
    source,
    filename="prog.cob",
    preprocess_fixed=True,         # auto-detect and normalize fixed-format
    error_recovery=ErrorRecoveryMode.FAIL_FAST,
    memory_config=MemoryConfiguration()
)
```

## Batch / Parallel Parsing

Parse multiple files in parallel using multiprocessing.

### CLI

```bash
# Parse all .cbl files in parallel
cobol-parser batch prog1.cbl prog2.cbl prog3.cbl

# Specify number of worker processes
cobol-parser batch *.cbl --workers 4

# Include per-file errors and statistics
cobol-parser batch *.cbl --errors --stats

# Custom encoding
cobol-parser batch *.cbl --encoding cp1252
```

### Python API

```python
from cobolparser import parse_files

results = parse_files(["a.cbl", "b.cbl", "c.cbl"])
for r in results:
    print(r.filename, r.result.success)
```
