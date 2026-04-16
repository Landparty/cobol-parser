# Architecture

## Pipeline

```
COBOL source (.cbl/.cob)
  → preprocess/__init__.py   normalize_fixed_format(), copybook expansion, conditional compilation
  → lexer.py                 CobolLexer → List[Token] (235 TokenType values)
  → parser.py                CobolParser → ParseResult
  → models/                  AST node classes with to_dict()/to_json()
```

1. `normalize_fixed_format(lines)` converts fixed-format COBOL (72-column lines) to free-form text. Comment lines (column 7 `*`/`/`) are silently dropped. Continuation lines (`-`) are merged.
2. `CobolLexer(text).tokenize()` produces `List[Token]` with 235 `TokenType` values.
3. `TokenStream(tokens)` wraps the list with `peek()`, `consume()`, `expect()`, and configurable lookahead.
4. `CobolParser.parse()` calls `DivisionParserFactory.parse_division()` per division encountered.
5. Each division parser uses `StatementParserRegistry.find_parser()` (first-match dispatch) to route individual statements.
6. Returns `ParseResult(ast, errors, warnings, statistics)`.

### Seeing the Pipeline in Action (CLI)

Each stage of the pipeline is accessible via the CLI:

```bash
# Stage 1: Preprocessing — convert fixed-format to free-form
cobol-parser preprocess program.cbl

# Stage 1b: Copybook expansion — inline COPY statements
cobol-parser expand program.cbl --copybook-path ./copybooks

# Stage 2: Tokenization — see every token
cobol-parser tokenize program.cbl

# Stages 2-3: Full parse — get the final AST
cobol-parser parse program.cbl
```

## Fixed-Format Column Layout

| Columns | Purpose |
|---------|---------|
| 1–6 | Sequence number (ignored) |
| 7 | Indicator: space=code, `*`/`/`=comment, `-`=continuation |
| 8–11 | Area A (division/section/paragraph headers, level 01/77) |
| 12–72 | Area B (statements, subordinate data items) |
| 73–80 | Identification (ignored) |

## Key Packages

**`cobolparser/lexer.py`** — Tokenises COBOL text. Handles fixed vs. free format, string continuations, figurative constants. Comment lines must be stripped by the preprocessor before the lexer runs.

**`cobolparser/preprocess/__init__.py`** — `normalize_fixed_format()` and `expand_copybooks()` (inlines `COPY` statements recursively).

**`cobolparser/parser.py`** — Top-level parse loop. Delegates to `DivisionParserFactory` which routes to division-specific parsers.

**`cobolparser/core/`** — Infrastructure only:
- `interfaces.py` — `ITokenStream`, `IDivisionParser`, `IStatementParser` protocols
- `token_stream.py` — `TokenStream`
- `registry.py` — `StatementParserRegistry`
- `exceptions.py` — `TokenMismatch`, `UnexpectedEndOfInput`, etc.
- `ast_factory.py` — `ASTNodeFactory`; use `get_factory()` / `create_node()` rather than instantiating nodes directly

**`cobolparser/parsers/`** — All statement and division parsers:
- `divisions/` — One parser per COBOL division
- `statements/` — One file per statement verb or verb group

**`cobolparser/models/`** — All AST node classes. Every node extends `ASTNode` and implements `to_dict()`:
- `ast_base.py` — `ASTNode`, `SourceLocation`, `ASTValidator`
- `program.py` — `CobolProgram`, `CobolDivision`, `CobolSection`, `CobolParagraph`
- `data_items.py` — `CobolDataItem`, `PictureClause`, `OccursClause`
- `statements/` — `arithmetic.py`, `call.py`, `control.py`, `data.py`, `io.py`, `misc.py`, `base.py`

**`cobolparser/dialects/ibm_enterprise.py`** — COMP-3, EXEC SQL/CICS, IBM intrinsic functions.

**`cobolparser/batch.py`** — `parse_files(paths)` for parallel multi-file parsing via multiprocessing.

**`cobolparser/analysis/`** — Static and dynamic analysis passes that run against a parsed AST. Each analyzer is a self-contained module exposing `.analyze(ast)` (or `.resolve(ast)` for the host-variable resolver) and returning a report dataclass with `to_dict()`:

- `value_tracker.py` — `DynamicCallAnalyzer` (dynamic CALL target tracking via MOVE/VALUE)
- `dead_code.py` — `DeadCodeAnalyzer` (unreferenced paragraphs/sections)
- `program_flow.py` — `ProgramFlowAnalyzer` (control-flow graph with typed edges)
- `io_logger.py` — `IOLogger` (CALL/SQL/FILE-IO/CONSOLE-IO/ENTRY extraction)
- `io_sequence.py` — `IOSequenceAnalyzer` (file lifecycle violations)
- `move_type_checker.py` — `MoveTypeChecker` (data category compatibility)
- `linkage_checker.py` — `LinkageChecker` (CALL ↔ ENTRY ↔ LINKAGE correlation)
- `language_env_analyzer.py` — `LanguageEnvironmentAnalyzer` (IBM LE calls/services)
- `crud_matrix.py` — `CRUDMatrixGenerator` (program × file/table CRUD matrix; CSV/JSON export)
- `ims_segment_analyzer.py` — `IMSSegmentAnalyzer` (DLI segment name resolution)
- `host_var_resolver.py` — `HostVariableResolver` (EXEC SQL `:host-var` → DATA DIVISION / DCLGEN)
- `coverage_analyzer.py` / `test_plan.py` — `CoverageAnalyzer` / `TestPlanGenerator` (coverage targets and test plans)
- `io_coverage_reporter.py` — `IOCoverageReporter` (machine-readable IO coverage artifacts)
- `io_diagnostics.py` — lower-level IO operation diagnostics

**`cobolparser/generators/cobolcheck.py`** — `CobolCheckGenerator` renders a `TestPlan` to a CobolCheck `.cut` file.

**`cobolparser/cli/`** — Command-line interface entry points:

- `parse.py` — the `cobol-parser` command (9 subcommands: `parse`, `batch`, `tokenize`, `preprocess`, `expand`, `analyze`, `dead-code`, `program-flow`, `generate-tests`)
- `coverage.py` — `python -m cobolparser.cli.coverage` (`status`, `generate`, `validate`, `render`)

## Adding a New Statement Parser

1. Create `cobolparser/parsers/statements/foo_parser.py` implementing `IStatementParser`.
2. Register it in `cobolparser/core/registry.py`.
3. Add a `TokenType` entry in `lexer.py` if the verb is new.
4. Add AST node(s) in the appropriate `cobolparser/models/statements/<category>.py` with `to_dict()`; use `ASTNodeFactory` to instantiate nodes.
