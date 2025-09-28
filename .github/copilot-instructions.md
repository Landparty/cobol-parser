# COBOL Parser Development Guidelines

A comprehensive Python 3.13+ COBOL parser with IBM Enterprise COBOL focus, enhanced memory management, JSON export, and TDD architecture.

## Architecture Overview

This is a **two-stage parsing pipeline**: Lexer → Parser → AST with sophisticated memory management and error recovery.

```
cobolparser/
├── lexer.py             # Tokenization (680 lines) - converts source to tokens
├── parser.py            # AST generation (712 lines) - converts tokens to AST  
├── models/              # AST node hierarchy
│   ├── program.py       # Program/Division/Section structure
│   ├── statements.py    # MOVE, DISPLAY, PERFORM statements
│   └── data_items.py    # PictureClause, COMP-3, data definitions
├── dialects/
│   └── ibm_enterprise.py # IBM COBOL extensions (COMP-3, EXEC SQL/CICS)
└── plugins/core.py      # Memory config, error recovery, serialization
```

## Key Development Patterns

### 1. AST Node Hierarchy
All AST nodes inherit from `ASTNode` with mandatory `to_dict()` for JSON serialization:

```python
from .models.ast_base import ASTNode, SourceLocation

class MyCobolNode(ASTNode):
    def __init__(self, name: str, location: SourceLocation):
        super().__init__("MyNodeType", location)
        self.name = name
    
    def to_dict(self) -> Dict[str, Any]:  # Required for JSON export
        return {
            "node_type": self.node_type,
            "name": self.name,
            "location": self.location.to_dict(),
            "metadata": self._metadata
        }
```

### 2. Memory Management Configuration
Use `MemoryConfiguration` for large COBOL programs (64MB-8GB limits):

```python
from cobolparser.plugins.core import MemoryConfiguration
config = MemoryConfiguration(max_memory_mb=1024, enable_streaming=True)
```

### 3. Error Recovery Modes
Choose between `FAIL_FAST` (production) vs `COLLECT_ALL` (development):

```python
from cobolparser import CobolParser, ErrorRecoveryMode
parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
```

## Essential Commands

```bash
# Run tests (114 total: 38 contract, 17 integration, 59 unit)
python -m pytest tests/ -v

# Test with coverage (90%+ required)
python -m pytest --cov=cobolparser --cov-fail-under=90

# Code quality checks
ruff check . && black . && mypy cobolparser/

# Integration test (uses test_program.cob)
python test_integration.py
```

## Test Organization Patterns

```
tests/
├── unit/           # Component tests (lexer, parser, models)  
├── integration/    # End-to-end workflows
├── contracts/      # API contract validation (38 tests)
└── samples/        # COBOL test programs
```

**Critical**: All new features need contract tests for API stability.

## IBM Enterprise COBOL Priority

This parser prioritizes **IBM Enterprise COBOL** dialect features:

```python
# IBM-specific patterns to support
from cobolparser.dialects.ibm_enterprise import IBMEnterpriseCobol

# COMP-3 packed decimal (calculate_storage_size() method required)
# EXEC SQL embedded SQL blocks  
# EXEC CICS transaction commands
# IBM intrinsic functions (LENGTH, NUMVAL, etc.)
```

## JSON Export Architecture

All AST nodes must support JSON serialization for cross-platform interoperability:

```python
from cobolparser.plugins.core import SerializationConfig
config = SerializationConfig(include_metadata=True, include_source_locations=True)
ast_json = result.ast.to_json(config)
```

## Development Workflow

1. **Always use Python 3.13+ features** (dataclasses, typing, enum)
2. **TDD approach**: Write failing test → implement → pass test (90%+ coverage)
3. **Memory awareness**: Large COBOL programs require streaming/chunking
4. **Error collection**: Use `COLLECT_ALL` mode during development for comprehensive validation
5. **Dialect support**: IBM Enterprise COBOL takes priority over ANSI COBOL

## Parser State Machine

The parser uses `ParseState` enum to track current parsing context:
- `IDENTIFICATION_DIVISION` → `DATA_DIVISION` → `PROCEDURE_DIVISION`
- Each division contains sections with specific parsing rules
- `WORKING_STORAGE_SECTION` vs `PROCEDURE_DIVISION` have different statement types

## Performance Considerations

- **Memory limits**: Configure based on COBOL program size (default 256MB)
- **Streaming**: Enable for programs >1MB to avoid memory issues
- **Token caching**: Lexer optimizations for large files
- **Statistics tracking**: Built-in performance monitoring via `ParseStatistics`
