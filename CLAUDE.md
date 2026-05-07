# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**cobolparser** is a comprehensive COBOL parser for Python with IBM Enterprise COBOL focus. It converts COBOL source code into a traversable AST with JSON export, error recovery, and batch multi-file parsing support. Version 1.0.0, authored by Samuel Dion.

## Commands

```bash
# Requires Python >= 3.11 (supports 3.11, 3.12, 3.13)

# Install for development
pip install -e ".[dev,docs]"

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

# Run by test directory (no dedicated marker)
python -m pytest tests/regression/ -v
python -m pytest tests/contracts/ -v
python -m pytest tests/performance/ -v

# Lint and format
python -m ruff check .
python -m ruff check . --fix
python -m black .
python -m mypy cobolparser/

# CLI subcommands
cobol-parser parse <file.cbl> [path] [--compact] [--free-form] [--dialect ibm-enterprise] [--errors] [--stats]
cobol-parser tokenize <file.cbl>
cobol-parser preprocess <file.cbl> [--define DEBUG]
cobol-parser expand <file.cbl> --copybook-path ./copybooks
cobol-parser analyze <file.cbl>
cobol-parser dead-code <file.cbl>
cobol-parser program-flow <file.cbl>
cobol-parser batch prog1.cbl prog2.cbl [--stats]
cobol-parser generate-tests <file.cbl> -o <file.cut>
```

## Architecture

The parser is a multi-stage pipeline: **preprocessing -> lexing -> parsing -> AST**.

```
COBOL source (.cbl/.cob)
  -> preprocess/          (normalize_fixed_format, copybook expansion, conditional compilation)
  -> lexer.py             (CobolLexer -> List[Token], 235 TokenType values)
  -> parser.py            (CobolParser -> ParseResult)
  -> models/              (AST node classes with to_dict()/to_json())
```

### Key Packages

**`cobolparser/lexer.py`** -- Tokenizes COBOL text into `Token` objects with `TokenType` enum (235 types). Handles fixed vs. free format, string continuations, figurative constants. Fixed-format comment lines (column 7 `*`/`/`) must be stripped by the preprocessor before the lexer sees them.

**`cobolparser/preprocess/`** -- Preprocessing pipeline:
- `__init__.py` -- `normalize_fixed_format()` converts fixed-format COBOL to free-form text (comment lines silently dropped). Also: `preprocess_conditional_compilation()`, `validate_copybook_content()`, `validate_level_numbers()`
- `copybook_expander.py` -- `expand_copybooks()` and `parse_cobol_with_expansion()` for recursive COPY statement inlining with circular reference detection, encoding detection, content validation, and caching
- `copy_statement_parser.py` -- `CopyStatementLexer`, REPLACING clause handling, continuation line normalization
- `path_resolver.py` -- Secure copybook path resolution with traversal prevention
- `models.py` -- `CopybookExpansion`, `CopyStatement`, `CopybookSearchPath`, `ExpansionStatistics`

**`cobolparser/parser.py`** -- `CobolParser` orchestrates parsing via `DivisionParserFactory`. Returns `ParseResult(ast, errors, warnings, statistics)`.

**`cobolparser/core/`** -- Infrastructure:
- `interfaces.py` -- `ITokenStream`, `IDivisionParser`, `IStatementParser` ABCs; `ParserHost` protocol; `ParseContext` for nested statement parsing
- `token_stream.py` -- `TokenStream` wraps `List[Token]` with `peek()`, `consume()`, `expect()`, configurable lookahead
- `registry.py` -- `StatementParserRegistry` with first-match dispatch strategy
- `exceptions.py` -- `TokenMismatch`, `UnexpectedEndOfInput`, `DivisionNotFoundError`, `UnknownStatementError`, `ValidationError` (all extend `ParseError`)
- `ast_factory.py` -- `ASTNodeFactory` for validated AST node creation; use `get_factory()` / `create_node()` rather than instantiating nodes directly. Raises `NodeTypeError`, `FieldValidationError`

**`cobolparser/_errors.py`** -- Canonical `ParseError` base class with zero internal dependencies (avoids circular imports between `plugins.core` and `core.exceptions`).

**`cobolparser/parsers/`** -- All division and statement parsers:
- `divisions/factory.py` -- `DivisionParserFactory` with `DivisionType` enum (IDENTIFICATION, ENVIRONMENT, DATA, PROCEDURE)
- `divisions/base.py` -- Base division parser with error recovery
- `divisions/identification.py` -- IDENTIFICATION DIVISION parser
- `divisions/environment.py` -- ENVIRONMENT DIVISION parser
- `divisions/data.py` -- DATA DIVISION parser
- `divisions/procedure.py` -- PROCEDURE DIVISION parser with `StatementParserRegistry`
- `statements/` -- 26 statement parser files (see "Statement Parsers" section below)
- `statements/_utils.py` -- Shared clause collection utilities

**`cobolparser/models/`** -- AST node classes. Every node extends `ASTNode` (from `ast_base.py`) and must implement `to_dict()`:
- `ast_base.py` -- `ASTNode`, `SourceLocation`, `ASTValidator`
- `program.py` -- `CobolProgram`, `CobolDivision`, `CobolSection`, `CobolParagraph`
- `data_items.py` -- `CobolDataItem`, `PictureClause`, `OccursClause`
- `sql_statements.py` -- SQL statement AST nodes
- `statements/` -- Statement node classes split by category (see "AST Statement Models" below)

**`cobolparser/plugins/core.py`** -- Configuration: `ErrorRecoveryMode` (FAIL_FAST / COLLECT_ALL), `DialectType`, `MemoryConfiguration`, `SerializationConfig`, `ParseStatistics`, `PluginManager`.

**`cobolparser/dialects/ibm_enterprise.py`** -- `IBMEnterpriseCobol` dialect: COMP-3, EXEC SQL/CICS/IMS DLI, IBM intrinsic functions.

**`cobolparser/analysis/`** -- 16 static analysis modules:
- `value_tracker.py` -- `DynamicCallAnalyzer` tracks possible values for variables in dynamic CALL statements via MOVE and VALUE clause analysis
- `io_coverage_reporter.py` -- Machine-readable IO coverage reports (`CoverageStatus`, `TestType`)
- `io_diagnostics.py` -- IO operation diagnostics
- `io_logger.py` -- IO operation logging
- `io_sequence.py` -- IO sequence validation
- `coverage_analyzer.py` -- Test coverage analysis
- `crud_matrix.py` -- CRUD matrix generation for file operations
- `dead_code.py` -- Unreferenced paragraph/section detection
- `host_var_resolver.py` -- SQL host variable resolution
- `ims_segment_analyzer.py` -- IMS DLI segment analysis
- `language_env_analyzer.py` -- IBM Language Environment detection
- `linkage_checker.py` -- LINKAGE SECTION validation
- `move_type_checker.py` -- MOVE statement type compatibility checking
- `program_flow.py` -- Control flow graph analysis
- `test_plan.py` -- Test plan generation from AST

**`cobolparser/generators/`** -- Code generation utilities:
- `cobolcheck.py` -- Generates CobolCheck `.cut` test files from parsed AST
- `flowchart.py` -- Generates flowchart representations from parsed AST

**`cobolparser/batch.py`** -- `parse_files(paths)` for parallel multi-file parsing using `ProcessPoolExecutor`. Returns `List[BatchResult]`. Supports executor reuse for repeated batches.

**`cobolparser/cli/`** -- Command-line interface:
- `parse.py` -- Implements all CLI subcommands: parse, tokenize, preprocess, expand, analyze, dead-code, program-flow, batch, generate-tests
- `coverage.py` -- IO coverage CLI tools

### Statement Parsers (cobolparser/parsers/statements/)

| File | COBOL Verbs |
|------|------------|
| `accept_parser.py` | ACCEPT |
| `arithmetic_parsers.py` | ADD, SUBTRACT, MULTIPLY, DIVIDE, COMPUTE |
| `call_parser.py` | CALL |
| `close_parser.py` | CLOSE |
| `delete_parser.py` | DELETE |
| `display_parser.py` | DISPLAY |
| `entry_parser.py` | ENTRY |
| `evaluate_parser.py` | EVALUATE |
| `go_parser.py` | GO TO |
| `ibm_exec_statements.py` | EXEC SQL, EXEC CICS, EXEC IMS DLI |
| `if_parser.py` | IF |
| `initialize_inspect_parsers.py` | INITIALIZE, INSPECT |
| `move_parser.py` | MOVE |
| `open_parser.py` | OPEN |
| `perform_parser.py` | PERFORM |
| `read_parser.py` | READ |
| `rewrite_parser.py` | REWRITE |
| `search_parser.py` | SEARCH |
| `set_parser.py` | SET |
| `simple_statement_parsers.py` | ALTER, CANCEL, CONTINUE, EXIT, GENERATE, GOBACK, RELEASE, RETURN, USE |
| `sort_merge_parsers.py` | SORT, MERGE |
| `start_parser.py` | START |
| `stop_parser.py` | STOP |
| `string_unstring_parsers.py` | STRING, UNSTRING |
| `unlock_parser.py` | UNLOCK |
| `write_parser.py` | WRITE |

### AST Statement Models (cobolparser/models/statements/)

| File | Node Classes |
|------|-------------|
| `base.py` | `CobolStatement`, `CobolExpression`, `ArithmeticExpression`, `ConditionalExpression`, `LogicalExpression`, `FunctionCall` |
| `arithmetic.py` | `ArithmeticStatement`, `AddStatement`, `SubtractStatement`, `MultiplyStatement`, `DivideStatement`, `ComputeStatement` |
| `call.py` | `CallStatement`, `EntryStatement`, `CallParameter` |
| `control.py` | `IfStatement`, `EvaluateStatement`, `WhenClause`, `PerformStatement`, `GoStatement`, `StopStatement`, `SearchStatement` |
| `data.py` | `MoveStatement`, `DisplayStatement`, `InitializeStatement`, `InspectStatement`, `SetStatement`, `StringStatement`, `UnstringStatement` |
| `io.py` | `IOReadStatement`, `IOWriteStatement`, `IOOpenStatement`, `IOCloseStatement`, `IOAcceptStatement`, `IORewriteStatement`, `IODeleteStatement`, `IOStartStatement`, `IOUnlockStatement` |
| `misc.py` | `SelectStatement`, `CopyStatement`, `ContinueStatement`, `ExitStatement`, `GobackStatement`, `CancelStatement`, `AlterStatement`, `GenerateStatement`, `ReleaseStatement`, `ReturnStatement`, `UseStatement`, `SortStatement`, `MergeStatement` |

### Data Flow Detail

1. `normalize_fixed_format(lines)` -> free-form text string (comment lines dropped)
2. `CobolLexer(text).tokenize()` -> `List[Token]`
3. `TokenStream(tokens)` wraps the list with lookahead
4. `CobolParser.parse()` -> `DivisionParserFactory.parse_division()` per division
5. Each division parser calls `StatementParserRegistry.find_parser()` (first-match) to dispatch statements
6. Returns `ParseResult(ast, errors, warnings, statistics)`

### Public API

```python
from cobolparser import parse_cobol, CobolParser, ErrorRecoveryMode, MemoryConfiguration

# Simple
result = parse_cobol(source, filename="prog.cob")

# Configurable
config = MemoryConfiguration(max_memory_mb=256)
parser = CobolParser(memory_config=config, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
result = parser.parse(source)

ast = result.ast          # CobolProgram
result.errors             # List[ParseError]
result.warnings           # List[str]
result.statistics         # ParseStatistics (timings, counts)
result.success            # True if ast is not None and no errors
ast.to_json()             # JSON export
ast.find_all_by_type("MoveStatement")

# Parallel multi-file parsing
from cobolparser import parse_files
results = parse_files(["a.cbl", "b.cbl"])   # List[BatchResult]

# Copybook expansion
from cobolparser import expand_copybooks, parse_cobol_with_expansion
result = expand_copybooks(source, copybook_paths=["/path/to/copybooks"])
parse_result = parse_cobol_with_expansion(source, copybook_paths=["/path"])

# Dynamic call analysis
from cobolparser.analysis import DynamicCallAnalyzer
analyzer = DynamicCallAnalyzer()
analyzer.analyze(parse_result.ast)

# Dead code detection
from cobolparser.analysis import dead_code
unreferenced = dead_code.find_dead_code(parse_result.ast)

# Program flow graph
from cobolparser.analysis import program_flow
graph = program_flow.build_flow_graph(parse_result.ast)

# CobolCheck test generation
from cobolparser import generate_cobolcheck_tests
generate_cobolcheck_tests(source, output_path="program.cut")
```

### Adding a New Statement Parser

1. Create `cobolparser/parsers/statements/foo_parser.py` implementing `IStatementParser` (must have `parse()` and `matches()` methods)
2. Register it in the `ProcedureDivisionParser` (or via the `StatementParserRegistry`)
3. Add a `TokenType` entry in `lexer.py` if the verb isn't already a keyword
4. Add AST node(s) in the appropriate `cobolparser/models/statements/<category>.py` with `to_dict()`; use `ASTNodeFactory` from `core/ast_factory.py` to instantiate nodes
5. Export the parser from `cobolparser/parsers/statements/__init__.py`
6. Export the AST node from `cobolparser/models/statements/__init__.py`

### Fixed-Format COBOL Column Layout

| Columns | Purpose |
|---------|---------|
| 1-6 | Sequence number (ignored) |
| 7 | Indicator: space=code, `*`/`/`=comment, `-`=continuation |
| 8-11 | Area A (division/section/paragraph headers, level 01/77) |
| 12-72 | Area B (statements, subordinate data items) |
| 73-80 | Identification (ignored) |

`normalize_fixed_format` extracts columns 8-72, drops comment lines, and merges continuation lines.

## Test Structure

**3,456 tests** across 5 directories (152 test files total):

```
tests/
  conftest.py            # Shared fixtures: parser(), samples_dir()
  test_all_samples.py    # Smoke-tests all sample COBOL programs
  unit/                  # Unit tests (135 files) - individual components
    analysis/            # IO coverage reporter, diagnostics, all analyzers
    cli/                 # CLI command tests
    generators/          # CobolCheck and flowchart generator tests
    io_statements/       # IO parser unit tests
  integration/           # Integration tests (14 files) - end-to-end parsing
    io/                  # IO coverage reporting integration
    io_statements/       # IO statement parsing, VSAM
  contracts/             # API contract tests (17 files) - stability guarantees
    io_statements/       # IO statement contracts
  regression/            # Regression tests - backward compatibility
  performance/           # Performance benchmarks (factory, parser)
  samples/               # Shared COBOL test fixtures (69 files)
    copybook_programs/   # Programs with COPY statements
    copybooks/           # Copybook files (.CPY)
    io/                  # IO test samples
      positive/          # Valid IO operations
      negative/          # Invalid IO patterns
```

### Pytest Markers

- `integration` -- Integration tests
- `slow` -- Slow-running tests
- `contract` -- API contract tests
- `io` -- IO statement tests (OPEN, CLOSE, READ, WRITE, REWRITE, DELETE, START, ACCEPT, DISPLAY, UNLOCK)

### Shared Fixtures (tests/conftest.py)

- `parser()` -- Fresh `CobolParser` instance
- `samples_dir()` -- Path to `tests/samples/`

### Coverage Requirement

81% line coverage is enforced by pytest (`--cov-fail-under=81`). Branch coverage is enabled. When running only a subset of tests, expect this check to fail -- that is normal.

## CI/CD

GitHub Actions (`.github/workflows/ci.yml`) runs on push/PR to `main`:

1. **lint** -- `ruff check .` + `black --check .` (Python 3.13)
2. **typecheck** -- `mypy cobolparser/` (Python 3.13)
3. **test** -- `pytest tests/ -v` on matrix: Python 3.11, 3.12, 3.13

## Code Style and Conventions

- **Formatter**: Black (line length 88, target py311)
- **Linter**: Ruff (pycodestyle, pyflakes, isort, bugbear, comprehensions, pyupgrade; E501 ignored)
- **Type checker**: mypy with strict settings (`disallow_untyped_defs`, `strict_equality`, etc.; tests are exempted from typed def requirements)
- **Python**: `>=3.11`, uses modern syntax (`list[]`, `dict[]`, `X | None` unions)
- **No runtime dependencies**: zero external dependencies for the core library
- **Imports**: `__init__.py` files may have unused imports (F401 ignored via ruff per-file config)

## File Organization Conventions

- One parser file per COBOL verb or verb group
- AST models grouped by category (arithmetic, control, data, io, call, misc)
- All parsers implement `IStatementParser` with `parse()` and `matches()` methods
- All AST nodes extend `ASTNode` and implement `to_dict()`
- Exception hierarchy rooted at `ParseError` in `_errors.py`

## Example COBOL Files

- `tests/samples/` -- 69 COBOL sample programs covering all statement types
- `examples/cobol/` -- NIST COBOL-85 test suite (400+ .CBL files) and copybooks (.CPY)

## Additional Directories

- `docs/` -- 20+ markdown documentation files (architecture, API reference, dialect guides, etc.)
- `tools/` -- Utility scripts for IO cataloging, coverage analysis, code metrics, and performance profiling
- `baselines/` -- Stored test baselines for regression comparison
- `benchmarks/` -- Performance benchmark programs
- `setup.py` -- Optional mypyc compilation support (compiles 20 core modules to C extensions)
