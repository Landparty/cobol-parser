# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## OKF Hooks Setup (one-time)

Run this once after cloning to enable the pre-commit staleness check:

```bash
git config core.hooksPath .githooks
```

The hook warns (and blocks the commit) when source files change without a corresponding OKF update. Bypass with `git commit --no-verify` when you intentionally skip the OKF.

A Claude Code `PostToolUse` hook also prints a one-line reminder inline when Claude edits OKF-covered source files. See `.claude/settings.json`.

## Open Knowledge Format (OKF)

This repo uses a structured knowledge base at `.okf/`. **Load `.okf/index.md` at the start of every session** — it tells you which sub-file to load for your task:

| Task type | Load |
|-----------|------|
| Tokenization, `TokenType`, Cython fast-path | `.okf/lexer.md` |
| Parser, `DivisionParserFactory`, statement parsers | `.okf/parser.md` |
| `normalize_fixed_format`, copybook expansion | `.okf/preprocessing.md` |
| `ASTNode` hierarchy, `CobolProgram`, `to_dict()` | `.okf/ast-models.md` |
| Static analysis (`DeadCodeAnalyzer`, `ProgramFlowAnalyzer`, etc.) | `.okf/analysis.md` |
| Flowcharts, copybook → CSV test data (`CopybookDataGenerator`) | `.okf/generators.md` |
| `parse_files`, `parse_files_with_copybooks`, batch fault isolation | `.okf/batch.md` |
| CLI subcommands and flags | `.okf/cli.md` |
| Test layout, markers, coverage floor | `.okf/tests.md` |

The OKF is more specific and more current than this file for the above topics. When they conflict, trust the OKF.

## Project Overview

**cobolparser** is a comprehensive COBOL parser for Python with IBM Enterprise COBOL focus. It converts COBOL source code into a traversable AST with JSON export, error recovery, and batch multi-file parsing support. Version 1.0.0, authored by Samuel Dion.

## Backend Integration

This library is **vendored** into `backend/_vendor/cobol-parser/` — it is not installed from PyPI. Changes to this standalone repo must be manually copied before they reach the backend:
```bash
cp -r cobolparser/ ../backend/_vendor/cobol-parser/cobolparser/
```

**Interface contract:** [`interface-contract.md`](interface-contract.md) — documents exactly which functions/classes the backend adapter calls, what attributes it reads off the AST, and what the `program_structure` dict it produces looks like. Read this before changing public API shapes.

## Commands

```bash
# Requires Python >= 3.11 (supports 3.11, 3.12, 3.13)

# Install for development
pip install -e ".[dev,docs]"

# Optional: build Cython-accelerated hot-path modules in place
pip install -e ".[fast]"
python setup.py build_ext --inplace

# Skip the C extension build entirely (no compiler / no Cython available)
COBOLPARSER_SKIP_EXT=1 pip install -e ".[dev]"

# Run all tests with coverage (81% minimum enforced; ~5,969 tests across 226 files)
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
cobol-parser gen-data <file.cpy> [--rows N] [--seed N] [--record NAME] [--describe] [-o out.csv]
cobol-parser gen-fixtures <file.cbl> [--copybook-path DIR] [--callee-path DIR] [--rows N] [--seed N] [--scenarios happy|branches|all] [--format json|csv-dir] [--list-boundaries] [--strict] [-o out]
cobol-parser analyze <file.cbl>
cobol-parser dead-code <file.cbl>
cobol-parser program-flow <file.cbl>
cobol-parser batch prog1.cbl prog2.cbl [--stats]
cobol-parser io-sequence <file.cbl>
cobol-parser move-type-check <file.cbl>
cobol-parser linkage-check <file.cbl>
cobol-parser language-env <file.cbl>
cobol-parser ims-dli <file.cbl>
```

## Architecture

The parser is a multi-stage pipeline: **preprocessing -> lexing -> parsing -> AST**.

```
COBOL source (.cbl/.cob)
  -> preprocess/          (normalize_fixed_format, copybook expansion, conditional compilation)
  -> lexer.py             (CobolLexer -> List[Token], 236 TokenType values)
  -> parser.py            (CobolParser -> ParseResult)
  -> models/              (AST node classes with to_dict()/to_json())
```

### Key Packages

**`cobolparser/lexer.py`** -- Tokenizes COBOL text into `Token` objects with `TokenType` enum (236 types). Handles fixed vs. free format, string continuations, figurative constants. Fixed-format comment lines (column 7 `*`/`/`) must be stripped by the preprocessor before the lexer sees them. When `cobolparser._lexer_fast` is compiled (see Cython acceleration below), the lexer transparently uses the Cython-accelerated subclass for hot-path methods; otherwise it falls back to pure Python.

**`cobolparser/_lexer_fast.pyx`** / **`cobolparser/_preprocess_fast.pyx`** / **`cobolparser/_data_fast.pyx`** -- Optional Cython modules that subclass the pure-Python lexer/preprocessor (and accelerate the DATA DIVISION `PICTURE` / data-item clause loops) by overriding the inner hot-path methods with C-typed implementations. Built via `setup.py build_ext --inplace`; the corresponding `.c` files are checked in so the extension builds without re-running Cython. Setting `COBOLPARSER_SKIP_EXT=1` at install time skips the C build and falls back to the pure-Python paths.

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
- `crud_matrix.py` -- CRUD matrix generation for file operations
- `dead_code.py` -- Unreferenced paragraph/section detection
- `host_var_resolver.py` -- SQL host variable resolution
- `ims_segment_analyzer.py` -- IMS DLI segment analysis
- `language_env_analyzer.py` -- IBM Language Environment detection
- `linkage_checker.py` -- LINKAGE SECTION validation
- `move_type_checker.py` -- MOVE statement type compatibility checking
- `program_flow/` -- Control flow graph analysis package (`models.py`, `scanner.py`, `edges.py`, `cycles.py`, `graph.py`, `analyzer.py`; public API re-exported from the package `__init__.py`)
- `boundary_inventory.py` -- `BoundaryInventoryAnalyzer` (Phase 2 of the `gen-fixtures` program-scoped test-data initiative): walks PROCEDURE DIVISION and inventories every mockable boundary (CALL/DYNCALL with a 4-rung argument-direction ladder, the eight file-op verbs, SQL/CICS/DLI, console ACCEPT), keyed the same way mockymock's `mock_surface` keys them. Takes a Phase 1 `ProgramLayoutIndex` to resolve each boundary's record/field layout. See `.okf/analysis.md`
- `constraints.py` / `domains.py` -- `ConstraintExtractor` + `domains.solve()` (Phase 4 of the `gen-fixtures` initiative): walks IF/EVALUATE/SEARCH conditions and PERFORM UNTIL loop guards into `FieldConstraint`s (relational/level-88/figurative/class-sign forms, AND/OR/NOT via De Morgan) and `SequenceConstraint`s (the READ/AT-END/loop-flag EOF idiom); `domains.py` is a small zero-dependency domain-propagation solver (numeric interval / text allow-deny / level-88 enum) that picks a deterministic witness always rendered through `ValueFactory.render()`. Takes a Phase 1 `ProgramLayoutIndex` and a Phase 2 `BoundaryReport`. See `.okf/analysis.md`
- `const_fold.py` -- `ConstantFolder` (Phase 7 of the `gen-fixtures` initiative): a single forward walk of a program's entry paragraph chain, seeded by one scenario's own mock-supplied inputs, tracking which data items hold a knowable literal value after a MOVE or a simple arithmetic/COMPUTE statement -- "exact by construction, or absent" throughout (a loop/branch poisons every field its body could write rather than guess which arm runs; DIVIDE is poisoned unconditionally since the AST does not record BY vs INTO; a numeric result is only kept when it fits its target field's PICTURE with no rounding/truncation/sign coercion). Wired into `ProgramFixtureGenerator` as `Expectation(kind="field_equals")` for every field still knowable at a DISPLAY/WRITE. See `.okf/analysis.md`

**`cobolparser/generators/`** -- Code generation utilities:
- `flowchart.py` -- Generates flowchart representations from parsed AST
- `copybook_data.py` -- Backwards-compatible re-export shim for copybook → CSV test data generation (implementation in `data/` package). The generator honors PICTURE/USAGE/OCCURS/REDEFINES/level-88/VALUE. Deterministic per `seed`. Backs the `gen-data` CLI subcommand
- `data/` -- Modular implementation: `options.py` (DataGeneratorOptions), `errors.py` (CopybookLayoutError, ProgramLayoutError), `layout.py` (FieldCategory, FieldSpec, flatten_record), `values.py` (ValueFactory), `dataset.py` (GeneratedDataset), `copybook.py` (parse_copybook_records, CopybookDataGenerator), `program_layout.py` (FileFacts, ResolvedField, ProgramLayoutIndex -- Phase 1 of the `gen-fixtures` program-scoped test-data initiative; resolves a whole program's FD/record/field names to layout facts), `bundle.py` (BUNDLE_VERSION, Expectation, BoundaryFixture, CoverageSummary, Scenario, FixtureBundle -- Phase 3's serializable output shapes, including `FixtureBundle.write_csv_dir()`). See `docs/plans/2026-08-02-program-data-generation-*.md` and `.okf/generators.md`
- `program_fixtures.py` -- `ProgramFixtureGenerator` (Phase 3/6/7 of the `gen-fixtures` initiative): combines a `ProgramLayoutIndex` (Phase 1) and a `BoundaryReport` (Phase 2) into a `FixtureBundle`. `generate`/`generate_from_file` produce one "happy path" `Scenario` with generated in-data per IN/BIDIRECTIONAL boundary and assert-on `Expectation` stubs per OUT boundary, using per-boundary deterministic sub-seeding. `generate_with_scenarios`/`generate_with_scenarios_from_file` (Phase 6) additionally accept `mode="branches"|"all"`, routing through Phase 5's `ScenarioPlanner` and pinning each `PlannedScenario`'s witnesses/sequence-lengths/status-overrides into an otherwise normally-generated fixture set; `mode="happy"` delegates to `generate()` unchanged (byte-identical). Every scenario's `expectations` also carries tier 1 (`Expectation(kind="call_count", ...)`, derived exactly from that scenario's own generated sequence length) and tier 2 (`Expectation(kind="field_equals", ...)`, from `analysis.const_fold.ConstantFolder` seeded with the scenario's own single-invocation mocked inputs) -- Phase 7. Backs the `gen-fixtures` CLI subcommand. See `.okf/generators.md`, `.okf/analysis.md`, and `docs/fixture-bundle-schema.md`
- `scenarios.py` -- `ScenarioPlanner` (Phase 5 of the `gen-fixtures` initiative): turns a Phase 4 `ConstraintReport` and `ProgramFlowAnalyzer`'s CFG into a set of named `PlannedScenario`s -- one (or a merge of several) per reachable, satisfiable branch arm, plus fixed families (empty-input/error-status/boundary-values) for `mode="all"` -- with exact arm-coverage accounting (`ScenarioCoverage`: targeted + merged + missed == total, every miss carrying a reason). Wired into the `gen-fixtures` CLI as of Phase 6 via `program_fixtures.py`'s `generate_with_scenarios`. See `.okf/generators.md`

**`cobolparser/batch.py`** -- `parse_files(paths)` for parallel multi-file parsing using `ProcessPoolExecutor`. Returns `List[BatchResult]`. Supports executor reuse for repeated batches. `parse_files_with_copybooks(paths, copybook_paths=...)` parses each file with copybook expansion enabled.

**`cobolparser/profiling.py`** -- `ProfilerContext` wraps any parse call with `cProfile`, `tracemalloc`, and optional `psutil` CPU accounting. Returns `ProfilingResult` (wall-clock, CPU, peak memory, top `FunctionProfile` entries). Install the `profiling` extra (`pip install -e ".[profiling]"`) to enable CPU accounting; the module imports `psutil` lazily so the package remains usable without it.

**`cobolparser/cli/`** -- Command-line interface:
- `parse.py` -- Implements all CLI subcommands: parse, tokenize, preprocess, expand, analyze, dead-code, program-flow, batch, io-sequence, move-type-check, linkage-check, language-env, ims-dli
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
| `simple_statement_parsers.py` | ALTER, CANCEL, COMMIT, CONTINUE, EJECT, EXIT, GENERATE, GOBACK, RELEASE, RETURN, ROLLBACK, USE |
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
| `misc.py` | `SelectStatement`, `CopyStatement`, `ContinueStatement`, `EjectStatement`, `ExitStatement`, `GobackStatement`, `CancelStatement`, `AlterStatement`, `GenerateStatement`, `ReleaseStatement`, `ReturnStatement`, `UseStatement`, `SortStatement`, `MergeStatement`, `CommitStatement`, `RollbackStatement` |

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

# Parallel parsing with copybook expansion
from cobolparser.batch import parse_files_with_copybooks
results = parse_files_with_copybooks(["a.cbl"], copybook_paths=["/path/to/copybooks"])

# Profiling a parse
from cobolparser.profiling import ProfilerContext
with ProfilerContext() as prof:
    parse_cobol(source)
profile = prof.result   # ProfilingResult with FunctionProfile entries

# Copybook expansion
from cobolparser import expand_copybooks, parse_cobol_with_expansion
result = expand_copybooks(source, copybook_paths=["/path/to/copybooks"])
parse_result = parse_cobol_with_expansion(source, copybook_paths=["/path"])

# Dynamic call analysis
from cobolparser.analysis import DynamicCallAnalyzer
DynamicCallAnalyzer().analyze(parse_result.ast)

# Analyzers exported from the top-level package — all follow the same
# `<Analyzer>().analyze(ast) -> <Report>` shape (HostVariableResolver
# uses `.resolve(ast)` instead):
from cobolparser import (
    DeadCodeAnalyzer,           # report.dead_items
    ProgramFlowAnalyzer,        # report.edges (typed PERFORM/GO TO/CALL/fall-through; THRU range_members; classified cycle_details)
    IOLogger,                   # report.operations
    IOSequenceAnalyzer,         # report.violations
    MoveTypeChecker,            # report.violations
    LinkageChecker,             # report.violations
    LanguageEnvironmentAnalyzer,# .le_functions / .service_calls
    CRUDMatrixGenerator,        # matrix.entries, .to_csv(), .to_json()
)
from cobolparser.analysis import IMSSegmentAnalyzer, HostVariableResolver

# Synthetic CSV test data from a copybook record layout
from cobolparser.generators import CopybookDataGenerator, DataGeneratorOptions
dataset = CopybookDataGenerator(
    DataGeneratorOptions(rows=100, seed=7)
).generate_from_file("CUSTOMER.cpy")
dataset.to_csv()               # header row + 100 generated records
dataset.write_csv("out.csv")
dataset.fields                 # list[FieldSpec] — the resolved layout
dataset.seed                   # replay this run with DataGeneratorOptions(seed=...)

# Whole-program layout index (Phase 1 of program-scoped test-data generation)
from cobolparser.generators import ProgramLayoutIndex
index = ProgramLayoutIndex.from_file("INVUPDT.cbl")   # or .build(ast)
index.record_for_file("INV-FILE")      # CobolDataItem | None, via FD -> record
index.file_facts("INV-FILE")           # FileFacts: organization/keys/record size/FD-or-SD
index.resolve("INV-QTY OF INV-REC")    # ResolvedField | None (bare/qualified/level-88 names)
index.record_named("INV-REC")          # CobolDataItem | None (whole record, any section)
index.unresolved                       # reasons nothing was silently dropped

# Boundary inventory (Phase 2): every mockable touchpoint of a program
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
report = BoundaryInventoryAnalyzer().analyze(ast, index)
report.boundaries                      # list[Boundary]: category/key, direction,
                                        # record_names, status_field, handlers, call_args
report.boundaries[0].call_args         # CALL/DYNCALL only: per-argument IN/OUT/
                                        # BIDIRECTIONAL direction + provenance

# Program fixture bundle (Phase 3): generated mock data + expectation stubs
from cobolparser.generators import ProgramFixtureGenerator
bundle = ProgramFixtureGenerator().generate_from_file("INVUPDT.cbl", seed=7)
bundle.scenarios[0].fixtures           # list[BoundaryFixture]: generated rows per boundary
bundle.scenarios[0].expectations       # list[Expectation]: assert-on stubs for OUT boundaries
bundle.coverage                        # CoverageSummary: total/resolved/unresolved boundaries
bundle.unresolved                      # merged Phase 1 + Phase 2 + Phase 3 resolution gaps
bundle.to_json()                       # byte-identical for the same (program, seed)
bundle.write_csv_dir("fixtures/")      # one CSV per file-shaped fixture + MANIFEST.json

# Constraint extraction + solving (Phase 4): what branches require of boundary data
from cobolparser.analysis.constraints import ConstraintExtractor
from cobolparser.analysis.domains import Witness, solve

creport = ConstraintExtractor().extract(ast, index, report)
creport.branches               # list[BranchConstraints]: one per IF/EVALUATE/SEARCH
creport.sequence_constraints   # list[SequenceConstraint]: READ/AT-END/PERFORM-UNTIL EOF idiom
creport.unsupported            # program-level gaps (never silently dropped)

branch = creport.branches[0]
witness = solve(branch.arms["THEN"][0].field.spec, branch.arms["THEN"])
if isinstance(witness, Witness):
    witness.value               # a value satisfying every conjunct, PICTURE-valid

# Scenario planning (Phase 5): constraints + CFG -> a named scenario set
from cobolparser.analysis.program_flow import ProgramFlowAnalyzer
from cobolparser.generators.scenarios import ScenarioPlanner

flow_report = ProgramFlowAnalyzer().analyze(ast)
plan = ScenarioPlanner().plan(creport, flow_report, report, mode="all")
plan.scenarios                 # list[PlannedScenario]: field_constraints, witnesses,
                                # sequence_constraints, status_overrides, arm_keys
plan.coverage                  # ScenarioCoverage: total_arms == targeted + merged + missed
plan.coverage.details          # list[ArmOutcome]: one per arm, a reason on every miss

# Wired end-to-end (Phase 6): scenario planning -> a populated FixtureBundle
bundle = ProgramFixtureGenerator().generate_with_scenarios_from_file(
    "INVUPDT.cbl", mode="all", seed=7,   # mode: "happy" | "branches" | "all"
)
bundle.scenarios                # one Scenario per PlannedScenario, each with real
                                 # BoundaryFixtures (witnesses/sequence-lengths/status
                                 # pinned, everything else generated as usual)
bundle.scenario_coverage        # ScenarioCoverage.to_dict(), None for mode="happy"

# Every scenario's own expectations (Phase 7): structural + computed, not just stubs
for e in bundle.scenarios[0].expectations:
    e.kind    # "call_count" (Tier 1, exact from the sequence length) |
              # "field_equals" (Tier 2, constant-folded) | "stub" (everything else)

# Tier 2 standalone: constant-fold a program's entry-paragraph chain
from cobolparser.analysis.const_fold import ConstantFolder

fold = ConstantFolder().fold(ast, index, seed_values={"WS-QTY": "622"})
fold.known                      # dict[qualified_name, str]: fields still knowable
                                 # at a DISPLAY/WRITE by the end of the walk
```

Full JSON shape, key by key, with a worked example: `docs/fixture-bundle-schema.md`.

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

~5,969 tests across 226 files in 5 directories:

```
tests/
  conftest.py            # Shared fixtures: parser(), samples_dir()
  test_all_samples.py    # Smoke-tests all sample COBOL programs
  unit/                  # Unit tests - individual components
    analysis/            # IO coverage reporter, diagnostics, all analyzers
    cli/                 # CLI command tests
    generators/          # Flowchart generator tests
    io_statements/       # IO parser unit tests
  integration/           # Integration tests - end-to-end parsing
    test_shamrice_examples.py  # Parametrized: all *.cbl in examples/cobol/shamrice/ must parse error-free
    io/                  # IO coverage reporting integration
    io_statements/       # IO statement parsing, VSAM
  contracts/             # API contract tests - stability guarantees
    io_statements/       # IO statement contracts
  regression/            # Regression tests - backward compatibility
  performance/           # Performance benchmarks (factory, parser)
  samples/               # Shared COBOL test fixtures
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

- `tests/samples/` -- ~48 COBOL sample programs covering all statement types (plus copybook and IO sub-directories)
- `examples/cobol/` -- NIST COBOL-85 test suite (459 .CBL files) and copybooks (.CPY)
- `examples/cobol/shamrice/` -- 24 IBM COBOL programs from shamrice/COBOL-Examples (ACCEPT variants, COMP types, SEARCH, SORT/MERGE, SQL, JSON/XML GENERATE, sub-programs); all parse cleanly under FAIL_FAST

## Additional Directories

- `.okf/` -- OKF knowledge bundle (lexer, parser, preprocessing, AST models, analysis, CLI, tests). Load `.okf/index.md` at the start of every session.
- `tools/` -- Utility scripts grouped by area:
  - `io_catalog/validate_catalog.py` -- Validates the IO operation catalog
  - `io_coverage/` -- `generate_artifact.py` and `render_markdown.py` for IO coverage reports
  - `metrics/io_ticket_tracker.py` -- Tracks IO-related work items
  - `perf/io_threshold_guard.py` -- Guards IO performance against thresholds
- `scripts/validate_io_coverage.py` -- Standalone IO coverage validator
- `baselines/` -- Stored coverage baselines (`current-coverage.json`, `final.json`) for regression comparison
- `benchmarks/` -- Performance benchmark programs
- `reports/` -- Audit reports
- `setup.py` -- Builds the optional Cython extension modules (`_lexer_fast`, `_preprocess_fast`, `_data_fast`). Compile in place with `python setup.py build_ext --inplace`; both `.pyx` and pre-generated `.c` files are checked into the repo so the build does not require Cython at install time. Set `COBOLPARSER_SKIP_EXT=1` to opt out of the C build entirely.
- `.pre-commit-config.yaml` -- Hooks for `ruff` (with `--fix`), `ruff-format`, `black`, and `mypy cobolparser/` (with `--ignore-missing-imports`). The CI lint/typecheck jobs duplicate these checks, so running `pre-commit run --all-files` locally catches the same issues.
- `CHANGELOG.md` -- Keep-a-Changelog history. The Unreleased section is the source of truth for which analyzers and CLI subcommands are wired up beyond the 1.0.0 baseline.
