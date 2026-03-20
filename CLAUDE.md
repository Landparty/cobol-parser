# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run all tests with coverage (81% minimum enforced)
python -m pytest tests/ -v

# Run a single test file or test
python -m pytest tests/unit/test_lexer.py -v
python -m pytest tests/integration/test_call_comprehensive.py::TestCallComprehensive::test_call_with_periods -xvs

# Run by marker
python -m pytest -m "integration"   # integration tests
python -m pytest -m "slow"          # slow tests
python -m pytest -m "contract"      # API contract tests
python -m pytest -m "io"            # IO statement tests

# Lint and format
python -m ruff check .
python -m ruff check . --fix
python -m black .
python -m mypy cobolparser/

# Install for development
pip install -e ".[dev,docs]"
```

## Architecture

The parser is a two-stage pipeline: **preprocessing → lexing → parsing → AST**.

```
COBOL source
  → preprocess/__init__.py  (normalize_fixed_format, copybook expansion)
  → lexer.py                (CobolLexer → List[Token])
  → parser.py               (CobolParser → ParseResult)
  → models/                 (AST node classes)
```

### Key packages

**`cobolparser/lexer.py`** — Tokenises COBOL text into `Token` objects with `TokenType` enum (150+ types). Handles fixed vs. free format, string continuations, figurative constants. Fixed-format comment lines (column 7 `*`/`/`) must be stripped by the preprocessor before the lexer sees them — the lexer itself only handles free-form text.

**`cobolparser/preprocess/__init__.py`** — `normalize_fixed_format()` converts fixed-format COBOL (72-column lines, area A/B, indicator column) to free-form text. Comment lines are **silently dropped** (not emitted) so the lexer never tokenises them. `expand_copybooks()` inlines `COPY` statements recursively.

**`cobolparser/parser.py`** — `CobolParser` owns the top-level parse loop. It delegates to `DivisionParserFactory` which routes tokens to division-specific parsers (`IdentificationDivisionParser`, `DataDivisionParser`, `ProcedureDivisionParser`, etc.).

**`cobolparser/core/`** — Infrastructure only:
- `interfaces.py` — `ITokenStream`, `IDivisionParser`, `IStatementParser` protocols
- `token_stream.py` — `TokenStream` wraps `List[Token]` with `peek()`, `consume()`, `expect()`
- `registry.py` — `StatementParserRegistry` dynamically dispatches to statement parsers
- `exceptions.py` — Typed parse exceptions (`TokenMismatch`, `UnexpectedEndOfInput`, etc.)

**`cobolparser/parsers/`** — All statement and division parsers live here:
- `divisions/` — One parser per COBOL division (identification, environment, data, procedure)
- `statements/` — One file per statement verb or verb group (call_parser.py, if_parser.py, arithmetic_parsers.py, etc.)

**`cobolparser/models/`** — All AST node classes. Every node extends `ASTNode` (from `ast_base.py`) and must implement `to_dict()`. Key files:
- `ast_base.py` — `ASTNode`, `SourceLocation`, `ASTValidator`
- `program.py` — `CobolProgram`, `CobolDivision`, `CobolSection`, `CobolParagraph`
- `data_items.py` — `CobolDataItem`, `PictureClause`, `OccursClause`
- `statements.py` — `CobolStatement` and concrete statement nodes

**`cobolparser/plugins/core.py`** — Configuration objects: `ErrorRecoveryMode` (FAIL_FAST / COLLECT_ALL), `DialectType`, `MemoryConfiguration`, `SerializationConfig`.

**`cobolparser/dialects/ibm_enterprise.py`** — IBM Enterprise COBOL extensions: COMP-3, EXEC SQL/CICS, IBM intrinsic functions.

### Data flow detail

1. `normalize_fixed_format(lines)` → free-form text string (comment lines dropped)
2. `CobolLexer(text).tokenize()` → `List[Token]`
3. `TokenStream(tokens)` wraps the list
4. `CobolParser.parse()` → calls `DivisionParserFactory.parse_division()` per division encountered
5. Each division parser calls `StatementParserRegistry.get_parser()` to dispatch individual statements
6. Returns `ParseResult(ast, errors, warnings, statistics)`

### Public API

```python
from cobolparser import parse_cobol, CobolParser, ErrorRecoveryMode

# Simple
result = parse_cobol(source, filename="prog.cob")

# Configurable
parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
result = parser.parse(source)

ast = result.ast          # CobolProgram
result.errors             # List[ParseError]
result.statistics         # ParseStatistics (timings, counts)
ast.to_json()             # JSON export
ast.find_all_by_type("MoveStatement")
```

### Adding a new statement parser

1. Create `cobolparser/parsers/statements/foo_parser.py` implementing `IStatementParser`
2. Register it in `cobolparser/core/registry.py` (or via the registry's discovery mechanism)
3. Add a `TokenType` entry in `lexer.py` if the verb isn't already a keyword
4. Add AST node(s) in `cobolparser/models/statements.py` with `to_dict()`

### Fixed-format COBOL column layout

| Columns | Purpose |
|---------|---------|
| 1–6 | Sequence number (ignored) |
| 7 | Indicator: space=code, `*`/`/`=comment, `-`=continuation |
| 8–11 | Area A (division/section/paragraph headers, level 01/77) |
| 12–72 | Area B (statements, subordinate data items) |
| 73–80 | Identification (ignored) |

`normalize_fixed_format` extracts columns 8–72, drops comment lines, and merges continuation lines.

### Coverage requirement

81% line coverage is enforced by pytest (`--cov-fail-under=81`). When running only a subset of tests, expect this check to fail — that is normal.
