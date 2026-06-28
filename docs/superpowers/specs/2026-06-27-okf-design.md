# OKF Design Spec — 2026-06-27

## Purpose

Implement an **Organizational Knowledge File (OKF)** under `docs/` that gives Claude (and human contributors) a complete, always-accurate structural picture of the `cobol-parser` repo. The OKF serves as persistent memory that Claude can load surgically at the start of any session, replacing the need to re-derive repo structure from scratch each time.

## Decisions

| Dimension | Decision | Rationale |
|-----------|----------|-----------|
| Format | Linked Markdown set | Human-readable, grepping-friendly, works naturally as Claude context |
| Maintenance | Claude-updated on demand | Zero developer maintenance burden; Claude regenerates from codebase state |
| Depth | Full structural detail | Every file's purpose, class/function inventory, test org, CLI commands, error hierarchy, config flags |
| Structure | Flat per-subsystem | Mirrors package layout; Claude loads only the relevant file per task |

---

## File Layout

```
docs/
  OKF.md                   ← master index: nav + repo-at-a-glance + pipeline diagram + refresh protocol
  okf/
    lexer.md               ← CobolLexer, TokenType enum, fixed/free-form rules, Cython fast-path
    preprocessing.md       ← normalize_fixed_format, copybook expansion, copy_statement_parser, path_resolver
    parser.md              ← CobolParser, DivisionParserFactory, TokenStream, StatementParserRegistry
    ast-models.md          ← ASTNode hierarchy, every model file, to_dict() contract, ASTNodeFactory
    analysis.md            ← all 15 analyzers: purpose, input/output, exported class names
    cli.md                 ← every subcommand, flags, examples, coverage CLI
    tests.md               ← directory map, markers, fixtures, coverage floor, how to run subsets
    batch.md               ← parse_files, parse_files_with_copybooks, ProcessPoolExecutor usage
    dialects.md            ← IBMEnterpriseCobol, DialectType enum, EXEC SQL/CICS/IMS support
    conventions.md         ← code style, import rules, error hierarchy, vendoring instructions
```

---

## Content Structure

### `docs/OKF.md` (master index)

Sections:
1. **Repo at a Glance** — language, Python range (3.11–3.13), zero-runtime-deps contract, vendoring model (copied to `backend/_vendor/`)
2. **Pipeline Overview** — ASCII/text diagram: `preprocess → lex → parse → AST → analysis`
3. **Navigation Table** — one row per subsystem file with a one-line description and link
4. **Refresh Protocol** — instructions for Claude: how to read the codebase, detect drift, and patch OKF files in place

### `docs/okf/*.md` (per-subsystem files)

Every subsystem file follows this template:

```markdown
# <Subsystem>
> One-line purpose statement

## Files
| File | Purpose |
|------|---------|
| path/to/file.py | ... |

## Key Classes / Functions
| Name | Location | Description |
|------|----------|-------------|
...

## Data Flow / Lifecycle
Step-by-step narrative of how data moves through this subsystem.

## Public API (exported symbols)
What external code imports from this subsystem.

## Gotchas / Invariants
Non-obvious constraints, hidden couplings, known quirks.

## Refresh Checklist
- [ ] Items Claude should verify when refreshing this file
```

---

## Per-File Content Outline

### `okf/lexer.md`
- `cobolparser/lexer.py` — `CobolLexer`, `Token`, `TokenType` (236 values)
- `cobolparser/_lexer_fast.pyx` — Cython subclass, hot-path override, build/fallback mechanics
- Fixed vs. free-form column layout, comment stripping, figurative constants, string continuations
- How `_lexer_fast` is detected and loaded transparently
- Refresh checklist: count of `TokenType` values, new token additions

### `okf/preprocessing.md`
- `cobolparser/preprocess/__init__.py` — `normalize_fixed_format`, `preprocess_conditional_compilation`, `validate_copybook_content`, `validate_level_numbers`
- `cobolparser/preprocess/copybook_expander.py` — `expand_copybooks`, `parse_cobol_with_expansion`, circular reference detection, encoding detection, caching
- `cobolparser/preprocess/copy_statement_parser.py` — `CopyStatementLexer`, REPLACING clause, continuation lines
- `cobolparser/preprocess/path_resolver.py` — secure path resolution, traversal prevention
- `cobolparser/preprocess/models.py` — `CopybookExpansion`, `CopyStatement`, `CopybookSearchPath`, `ExpansionStatistics`
- `cobolparser/_preprocess_fast.pyx` — Cython acceleration for hot-path preprocessing
- Refresh checklist: new preprocess functions, new models

### `okf/parser.md`
- `cobolparser/parser.py` — `CobolParser`, `ParseResult` (ast, errors, warnings, statistics)
- `cobolparser/core/token_stream.py` — `TokenStream`, `peek()`, `consume()`, `expect()`, configurable lookahead
- `cobolparser/core/registry.py` — `StatementParserRegistry`, first-match dispatch
- `cobolparser/core/interfaces.py` — `ITokenStream`, `IDivisionParser`, `IStatementParser` ABCs, `ParserHost`, `ParseContext`
- `cobolparser/parsers/divisions/factory.py` — `DivisionParserFactory`, `DivisionType` enum
- `cobolparser/parsers/divisions/` — one file per division (identification, environment, data, procedure)
- `cobolparser/parsers/statements/` — 26 statement parser files (full table)
- `cobolparser/parsers/statements/_utils.py` — shared clause utilities
- `cobolparser/core/ast_factory.py` — `ASTNodeFactory`, `get_factory()`, `create_node()`, error types
- Refresh checklist: new statement parsers, division changes, new `DivisionType` values

### `okf/ast-models.md`
- `cobolparser/models/ast_base.py` — `ASTNode`, `SourceLocation`, `ASTValidator`
- `cobolparser/models/program.py` — `CobolProgram`, `CobolDivision`, `CobolSection`, `CobolParagraph`
- `cobolparser/models/data_items.py` — `CobolDataItem`, `PictureClause`, `OccursClause`
- `cobolparser/models/sql_statements.py` — SQL AST nodes
- `cobolparser/models/statements/` — 6 category files (arithmetic, call, control, data, io, misc) with full class inventory
- `cobolparser/_data_fast.pyx` — Cython acceleration for DATA DIVISION picture/clause loops
- `to_dict()` / `to_json()` contract, `find_all_by_type()` traversal
- Refresh checklist: new node classes, new `to_dict()` fields

### `okf/analysis.md`
- All 15 analyzers in `cobolparser/analysis/` with: purpose, input, output type, exported symbol
- `DynamicCallAnalyzer` — MOVE/VALUE tracking for dynamic CALL targets
- `DeadCodeAnalyzer`, `ProgramFlowAnalyzer`, `IOLogger`, `IOSequenceAnalyzer`
- `MoveTypeChecker`, `LinkageChecker`, `LanguageEnvironmentAnalyzer`, `CRUDMatrixGenerator`
- `IMSSegmentAnalyzer`, `HostVariableResolver` (uses `.resolve()` not `.analyze()`)
- `IOCoverageReporter`, `IODiagnostics`, `CoverageAnalyzer`, `TestPlanGenerator`
- Top-level `generate_cobolcheck_tests()` pipeline
- Refresh checklist: new analyzers, API shape changes

### `okf/cli.md`
- All subcommands: parse, tokenize, preprocess, expand, analyze, dead-code, program-flow, batch, generate-tests, io-sequence, move-type-check, linkage-check, language-env, ims-dli
- Every flag per subcommand with description and example invocation
- `cobolparser/cli/coverage.py` — IO coverage CLI tools
- Entry point: `cobol-parser` console script
- Refresh checklist: new subcommands, changed flags

### `okf/tests.md`
- Directory map: unit/, integration/, contracts/, regression/, performance/, samples/
- Pytest markers: `integration`, `slow`, `contract`, `io`
- Shared fixtures: `parser()`, `samples_dir()`
- Coverage floor: 81% line coverage enforced (`--cov-fail-under=81`)
- How to run subsets: by directory, by marker, by test name, single file
- `test_all_samples.py` — smoke-tests all sample programs
- `test_shamrice_examples.py` — parametrized, all `*.cbl` in `examples/cobol/shamrice/` must parse FAIL_FAST clean
- Sample directories: `tests/samples/`, `examples/cobol/` (NIST 459 files), `examples/cobol/shamrice/` (24 IBM programs)
- Refresh checklist: new test directories, new markers, coverage floor changes

### `okf/batch.md`
- `cobolparser/batch.py` — `parse_files(paths)`, `parse_files_with_copybooks(paths, copybook_paths)`
- `ProcessPoolExecutor` usage, executor reuse, `BatchResult` structure
- `cobolparser/profiling.py` — `ProfilerContext`, `ProfilingResult`, `FunctionProfile`, `psutil` optional dep
- Refresh checklist: new batch entry points, profiling API changes

### `okf/dialects.md`
- `cobolparser/dialects/ibm_enterprise.py` — `IBMEnterpriseCobol`, `DialectType` enum
- Supported extensions: COMP-3, EXEC SQL, EXEC CICS, EXEC IMS DLI, IBM intrinsic functions
- How dialects are passed to `CobolParser` / `parse_cobol()`
- Refresh checklist: new dialect entries, new IBM extensions

### `okf/conventions.md`
- Formatter: Black (line length 88, `py311`)
- Linter: Ruff (pycodestyle, pyflakes, isort, bugbear, comprehensions, pyupgrade; E501 ignored)
- Type checker: mypy strict (`disallow_untyped_defs`, `strict_equality`; tests exempted)
- Python: `>=3.11`, modern syntax (`list[]`, `dict[]`, `X | None`)
- Zero runtime dependencies contract
- Import conventions: `__init__.py` F401 ignored; circular import guard via `_errors.py`
- Error hierarchy: `ParseError` (base in `_errors.py`) → `TokenMismatch`, `UnexpectedEndOfInput`, `DivisionNotFoundError`, `UnknownStatementError`, `ValidationError`; `ASTNodeFactory` raises `NodeTypeError`, `FieldValidationError`
- Cython fast-path pattern: `COBOLPARSER_SKIP_EXT=1` opt-out, `.pyx` + pre-generated `.c` both checked in
- Vendoring: copy `cobolparser/` → `backend/_vendor/cobol-parser/cobolparser/` manually
- Pre-commit: ruff (--fix), ruff-format, black, mypy
- Refresh checklist: style rule changes, new error types, new env vars

---

## Refresh Protocol (stored in `docs/OKF.md`)

When Claude starts a session or is asked to refresh:

1. Read `cobolparser/__init__.py` to check exported symbols
2. `glob cobolparser/**/*.py` — identify any new/removed files
3. For each changed subsystem, read the relevant source files and update the corresponding `docs/okf/*.md`
4. Update the navigation table in `docs/OKF.md` if files were added/removed
5. Commit with message: `docs(okf): refresh OKF — <brief description of what changed>`

The OKF is the source of truth for structural knowledge. Code is the source of truth for implementation detail. When they conflict, trust the code.

---

## Implementation Steps

1. Populate `docs/OKF.md` (master index) by reading existing code and CLAUDE.md
2. For each subsystem file, read the relevant source files in `cobolparser/` and write full detail
3. Commit all 11 files together as `docs(okf): initial OKF — full structural knowledge base`

---

## Success Criteria

- Claude can open `docs/OKF.md`, navigate to the right subsystem file, and answer any structural question without reading source files
- Refreshing a single subsystem file takes < 5 minutes of Claude work
- No placeholder or vague entry exists — every class, function, and file is named explicitly
