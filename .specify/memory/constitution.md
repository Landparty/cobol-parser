# COBOL Parser Constitution

**This file is a reference to the LegacyLens Platform Constitution.**

## Master Constitution

All development in this project MUST comply with the **LegacyLens Platform Constitution** defined at:
   
   📄 [`../../backend/.specify/memory/constitution.md`](../../backend/.specify/memory/constitution.md)

The seven universal principles (Type Safety, TDD, Modular Architecture, Performance, Observability, Security, Reliability) apply equally to all projects.

---

## Project-Specific Stack & Guidance

This project is **COBOL Parser** — a Python 3.13+ lexer/parser pipeline for IBM Enterprise COBOL.

### Technology Stack

- **Language**: Python 3.13+
- **Testing**: pytest + coverage.py
- **Type checking**: mypy with strict mode
- **Architecture**: Two-stage pipeline (Lexer → Tokens → Parser → AST)
- **Memory**: Streaming and chunking for large programs
- **Error recovery**: Configurable modes (FAIL_FAST or COLLECT_ALL)
- **Export**: JSON serialization via `to_dict()` on all AST nodes
- **Dialect**: IBM Enterprise COBOL as priority

### Mandatory Rules

**Type Safety (Principle I)**:
- Type hints on all public functions and class methods (mypy strict mode).
- No `Any` types without documented justification.

**TDD (Principle II)**:
- All new features MUST have tests written first (red-green-refactor).
- Minimum 81% line coverage required for all new code.
- Test layers: unit (isolated), integration (real COBOL samples), contract (API stability).

**Modular Architecture (Principle III)**:
- Lexer and Parser as separate stages.
- Statement-specific parsers for complex constructs.
- Division-specific parsing via factory pattern with legacy fallback.
- All AST nodes inherit `ASTNode` and implement `to_dict()`.

**Performance (Principle IV)**:
- Memory configuration via `MemoryConfiguration` for programs >1MB.
- Streaming enabled for large files (configurable limits).
- No unnecessary token re-scanning or AST re-construction.

**Observability (Principle V)**:
- Structured logging via `structlog` or Python's logging module.
- Parse statistics and performance metrics collected.
- Error recovery mode documented in logs.

**Security (Principle VI)**:
- Input validation for COBOL source files (encoding, length).
- No arbitrary code execution via copybook paths.
- Secure file handling (no path traversal vulnerabilities).

**Reliability (Principle VII)**:
- Graceful error handling with error collection mode.
- Copybook expansion with cycle detection.
- Idempotent parsing (same input → same AST).

### Key Patterns

**AST Node Hierarchy**:
```python
from cobolparser.models.ast_base import ASTNode, SourceLocation

class MyCobolNode(ASTNode):
    def __init__(self, name: str, location: SourceLocation):
        super().__init__("MyNodeType", location)
        self.name = name
    
    def to_dict(self) -> Dict[str, Any]:  # Required for JSON export
        return {
            "node_type": self.node_type,
            "name": self.name,
            "location": self.location.to_dict(),
        }
```

**Memory Configuration**:
```python
from cobolparser.plugins.core import MemoryConfiguration
config = MemoryConfiguration(max_memory_mb=1024, enable_streaming=True)
```

**Error Recovery Modes**:
```python
from cobolparser import CobolParser, ErrorRecoveryMode
parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
```

**Division Parsing Factory**:
```python
from cobolparser.parsers.divisions.factory import DivisionParserFactory
factory = DivisionParserFactory()
# Orchestrates division parsing with optional legacy fallback
```

### Code Review Gates (COBOL Parser-Specific)

- [ ] Type hints on all new/modified public methods.
- [ ] 81%+ coverage for new code (unit + integration + contract).
- [ ] All AST nodes implement `to_dict()`.
- [ ] Memory tests included for programs >1MB.
- [ ] Contract tests validate API stability.
- [ ] Copybook expansion tested with nested callees.
- [ ] Error recovery mode (FAIL_FAST / COLLECT_ALL) verified.
- [ ] Performance benchmarks run for large programs.

### Development Workflow

1. **Write test** (red) — failing unit test for the feature.
2. **Define AST node** — if adding a new statement or construct, create `ASTNode` subclass.
3. **Implement parser** — statement-specific or division-specific parsing logic.
4. **Verify `to_dict()`** — ensure JSON export works.
5. **Integration test** — end-to-end with real COBOL programs.
6. **Contract test** — API stability and edge cases.
7. **Refactor** — improve clarity and performance while tests pass.

### IBM Enterprise COBOL Priority

This parser prioritizes IBM Enterprise COBOL features:
- COMP-3 packed decimal (calculate_storage_size() required).
- EXEC SQL and EXEC CICS embedded blocks.
- IBM intrinsic functions (LENGTH, NUMVAL, etc.).
- Enhanced IO statements with backward compatibility.
- Dialect-specific parsing strategies.

### Testing Commands

```bash
# All tests
python -m pytest tests/ -v

# Coverage (81%+ required)
python -m pytest --cov=cobolparser --cov-fail-under=81

# Code quality
ruff check . && black . && mypy cobolparser/

# Integration test
python test_integration.py

# Copybook expansion test
python -m pytest tests/integration/test_copybook_expansion_integration.py
```

### Additional Resources

- **Main Platform Constitution**: [`../../backend/.specify/memory/constitution.md`](../../backend/.specify/memory/constitution.md)
- **Project Instructions**: [`.github/copilot-instructions.md`](.github/copilot-instructions.md)
- **Development Guide**: [`README.md`](README.md)

---

**Version**: 2.0.0 (follows platform v2.0.0) | **Synced**: 2026-03-16
