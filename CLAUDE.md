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
| Parser, `DivisionParserFactory`, statement parsers | `.okf/parser.md` (routing page for `.okf/parser/`) |
| `normalize_fixed_format`, copybook expansion | `.okf/preprocessing.md` |
| `ASTNode` hierarchy, `CobolProgram`, `to_dict()` | `.okf/ast-models.md` |
| Static analysis (`DeadCodeAnalyzer`, `ProgramFlowAnalyzer`, `LintAnalyzer`, `XrefAnalyzer`, `ProgramSignatureExtractor`, `CodebaseGraphBuilder`, `SqlCicsAnalyzer`, `ProgramDiffer`, etc.) | `.okf/analysis.md` (routing page for `.okf/analysis/`) |
| Dialects, EXEC SQL/CICS/IMS nodes, LE/intrinsic signature lookups | `.okf/dialects.md` |
| Flowcharts, copybook → CSV/record-image data (`CopybookDataGenerator`), decode/compare, `gen-fixtures` bundles and scenarios | `.okf/generators.md` (routing page for `.okf/generators/`) |
| `parse_files`, `parse_files_with_copybooks`, `scan_files`, batch fault isolation | `.okf/batch.md` |
| z/OS JCL: jobs/steps, DD → dataset bindings (read by jcl-parser) | `.okf/jcl.md` |
| CLI subcommands and flags, the `cobol.yml` project config | `.okf/cli.md` |
| The MCP server for AI agents (`cobol-parser mcp`), its tools, envelope and caveats | `.okf/mcp.md` |
| Test layout, markers, coverage floor | `.okf/tests.md` |
| Backend adapter dict shape (summary of `interface-contract.md`) | `.okf/integration.md` |

The OKF is more specific and more current than this file for the above topics. When they conflict, trust the OKF. Point-in-time history lives in `.okf/history/` and `.okf/log.md` and is not loaded by default. The pre-commit hook also runs `scripts/okf_check.py`, which tests what the OKF files (and this one) claim against the code; `python scripts/okf_check.py --write` refreshes its generated `<!-- okf:gen -->` spans.

## Project Overview

**cobolparser** is a comprehensive COBOL parser for Python with IBM Enterprise COBOL focus. It converts COBOL source code into a traversable AST with JSON export, error recovery, and batch multi-file parsing support. See `pyproject.toml` for the current version (release-please keeps it current); authored by Samuel Dion. License is AGPL-3.0-or-later (see `LICENSE`).

## Backend Integration

This library is **vendored** into `backend/_vendor/cobol-parser/` — the `backend/` repo does not install it from PyPI. Changes to this standalone repo must be manually copied before they reach the backend:
```bash
cp -r cobolparser/ ../backend/_vendor/cobol-parser/cobolparser/
```

There is a *separate* PyPI package, `cobol-parser` (`pip install cobol-parser`), published as compiled wheels plus an sdist (see "Release & Distribution" below) — it exists for the sibling `mocky-mock` repo and other external consumers, and does not change or replace the backend's vendoring flow.

**Interface contract:** [`interface-contract.md`](interface-contract.md) — documents exactly what two external consumers call: (1) the backend adapter (`backend/src/parsers/cobol/parser.py`) — which functions/classes it calls, what attributes it reads off the AST, and what `program_structure` dict shape it expects back; (2) `mocky-mock`'s generators surface (`mockymock generate --with-data` / `mockymock fixtures`) — which calls `ProgramFixtureGenerator` directly and gates on `FixtureBundle`'s `bundle_version`. Read this before changing public API shapes; a breaking change to either surface means bumping the relevant version field.

## Commands

```bash
# Requires Python >= 3.11 (supports 3.11, 3.12, 3.13)

# Install for development
pip install -e ".[dev,docs]"

# Pure Python is the default backend: nothing is compiled and no compiler is
# needed. The Cython hot-path modules are an opt-in, COBOLPARSER_ACCEL=1, read
# at build time (setup.py compiles them) AND at import time (they are used):
pip install -e ".[fast]"
COBOLPARSER_ACCEL=1 python setup.py build_ext --inplace
COBOLPARSER_ACCEL=1 python -m pytest tests/ --no-cov   # suite on the fast paths

# Run all tests with coverage (90% minimum; ~14,700 tests across 554 files).
# Measure coverage on a pure-Python build -- see "Coverage Requirement".
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
# Every subcommand also takes the two global config flags, on either side of
# the subcommand: [--config FILE] to read a specific cobol.yml, [--no-config]
# to ignore any of them. See "Project Config" below and docs/project-config.md
cobol-parser config [--json]
cobol-parser parse <file.cbl> [path] [--compact] [--source-format auto|fixed|free] [--free-form] [--debug-lines] [--dialect ibm-enterprise] [--copybook-path DIR] [--define SYMBOL[=VALUE]] [--errors] [--stats] [--find-type NODE_TYPE] [--profile] [-o out.json]
cobol-parser tokenize <file.cbl>
cobol-parser preprocess <file.cbl> [--define DEBUG]
cobol-parser expand <file.cbl> --copybook-path ./copybooks [--keep-comments] [--source-map] [--max-depth N] [--define SYMBOL[=VALUE]]
cobol-parser gen-data <file.cpy> [--rows N] [--seed N] [--record NAME] [--describe] [--format csv|json|record|hex] [--charset ascii|ebcdic] [--endian auto|big|little|native] [--record-format fixed|variable|variable-bare|auto] [--record-varying MIN:MAX] [--record-separator none|newline] [-o out.csv]
cobol-parser decode [data-file] --copybook <file.cpy> [--record NAME] [--view NAME] [--list-views] [--format csv|json|hex] [--charset ascii|ebcdic] [--endian auto|big|little|native] [--record-format fixed|variable|variable-bare|auto] [--record-length N] [--record-separator none|newline] [--max-records N] [--skip N] [--strict] [-o out]
cobol-parser compare <expected> <actual> --copybook <file.cpy> [--record NAME] [--view NAME] [--key FIELD]... [--ignore FIELD]... [--compare-bytes] [--max-differences N] [--format text|json] [--charset ascii|ebcdic] [--endian auto|big|little|native] [--record-format fixed|variable|variable-bare|auto] [--record-length N] [--record-separator none|newline] [-o out]   # exit 0 equal / 1 different / 2 trouble
cobol-parser gen-fixtures <file.cbl> [--copybook-path DIR] [--callee-path DIR] [--rows N] [--seed N] [--max-occurs N] [--scenarios happy|branches|all] [--format json|csv-dir] [--list-boundaries] [--strict] [-o out]
cobol-parser lint <file.cbl> [--rule RULE]... [--min-severity error|warning|info] [--fail-on error|warning|info|never] [--format json|text] [--copybook-path DIR] [--program NAME]
cobol-parser dclgen-check <file.cbl>
cobol-parser analyze <file.cbl>
cobol-parser dead-code <file.cbl>
# every analyzer subcommand above/below also takes [--program NAME] to pick one
# program unit in a file holding several PROGRAM-IDs (default: the outermost)
cobol-parser unused-variables <file.cbl> [--copybook-path DIR] [--exclude-copybook-variables]
cobol-parser program-flow <file.cbl>
cobol-parser recursion-check <file.cbl>
cobol-parser complexity <file.cbl>
cobol-parser health <file.cbl>
cobol-parser business-rules <file.cbl> [--format json|text] [--include-technical]
cobol-parser lineage <file.cbl> [--field NAME] [--direction forward|backward] [--format json|text]
cobol-parser field-impact [FIELD] PATH... [--program NAME] [--table T.C | --dataset DSN] [--direction forward|backward] [--depth N] [--jcl PATH]... [--proc-path DIR]... [--bindings FILE.json] [--key-relationships] [--format json|text] [--copybook-path DIR] [--source-format auto|fixed|free] [--define SYMBOL[=VALUE]]
cobol-parser redundancy <file.cbl> [--min-clone-statements N]
cobol-parser batch prog1.cbl prog2.cbl [--stats]
cobol-parser scan FILE... [--glob PATTERN] [--files-from LIST] [--analyzer health|redundancy|complexity|dead-code|unused-variables|lineage] [--clones] [--min-clone-members N] [--min-clone-statements N] [--workers N] [--copybook-path DIR] [--define SYMBOL[=VALUE]] [--encoding ENC] [--source-format auto|fixed|free] [--output FILE] [--compact]
cobol-parser io-sequence <file.cbl>
cobol-parser move-type-check <file.cbl>
cobol-parser linkage-check <file.cbl>
cobol-parser language-env <file.cbl>
cobol-parser le-info [NAME...] [--kind service|function|all] [--compact] [-o out.json]
cobol-parser ims-dli <file.cbl>
cobol-parser data-items <file.cbl>
cobol-parser program-signature <file.cbl>
cobol-parser xref <file.cbl>
cobol-parser sql-cics-check <file.cbl>
cobol-parser diff <old.cbl> <new.cbl> [--format json|text] [--rename-threshold RATIO]
cobol-parser codebase-graph PATH... [--format json|dot|mermaid] [--extension EXT] [--workers N] [--copybook-path DIR]
cobol-parser copybook-impact <member> PATH... [--extension EXT] [--workers N] [--copybook-path DIR]
cobol-parser jcl <job.jcl> [--dd-map] [--bindings] [--program NAME] [--proc-path DIR]... [--strict]   # needs the [jcl] extra
cobol-parser mcp [--root DIR] [--cache-size N] [--tools auto|all|GROUP,TOOL...]   # MCP server on stdio for AI agents; needs the [mcp] extra ([mcp,jcl] for the JCL tools)
# Parsing subcommands also take [--error-recovery fail-fast|collect-all] (default collect-all)
```

## Architecture

The parser is a multi-stage pipeline: **preprocessing -> lexing -> parsing -> AST**.

```
COBOL source (.cbl/.cob)
  -> preprocess/          (normalize_fixed_format, copybook expansion, conditional compilation)
  -> lexer.py             (CobolLexer -> List[Token])
  -> parser.py            (CobolParser -> ParseResult)
  -> models/              (AST node classes with to_dict()/to_json())
```

### Key Packages

**`cobolparser/lexer.py`** -- Tokenizes COBOL text into `Token` objects with `TokenType` enum (<!-- okf:gen tokentype-count -->244<!-- /okf:gen --> members). Handles fixed vs. free format, string continuations, figurative constants. Fixed-format comment lines (column 7 `*`/`/`) must be stripped by the preprocessor before the lexer sees them. Pure Python by default; when `cobolparser._lexer_fast` is compiled *and* `COBOLPARSER_ACCEL=1` is set (see `cobolparser/_accel.py`), the lexer uses the Cython-accelerated subclass for hot-path methods.

**`cobolparser/_lexer_fast.pyx`** / **`cobolparser/_preprocess_fast.pyx`** / **`cobolparser/_data_fast.pyx`** -- Optional Cython modules that subclass the pure-Python lexer/preprocessor (and accelerate the DATA DIVISION `PICTURE` / data-item clause loops) by overriding the inner hot-path methods with C-typed implementations. Opt-in: built only when `COBOLPARSER_ACCEL=1` is set (`COBOLPARSER_ACCEL=1 python setup.py build_ext --inplace`), and used only when it is set at import time too (`cobolparser/_accel.py`'s `accelerators_enabled()`), so pure Python is the default even with a `.so` present. The corresponding `.c` files are checked in so the extension builds without re-running Cython. `COBOLPARSER_SKIP_EXT=1` (the old opt-out) is still honoured. The PyPI wheels still ship compiled, so wheel users opt in with the variable alone.

**`cobolparser/preprocess/`** -- Preprocessing pipeline:
- `__init__.py` -- `normalize_fixed_format()` converts fixed-format COBOL to free-form text (comment lines silently dropped). Also: `preprocess_conditional_compilation()`, `validate_copybook_content()`, `validate_level_numbers()`
- `copybook_expander.py` -- `expand_copybooks()` and `parse_cobol_with_expansion()` for recursive COPY statement inlining with circular reference detection, encoding detection, content validation, and caching. Also owns the **source map**: one `(file, original line)` per expanded line, carried through continuation merging, the COPY splice and the width wrap, exposed as `CopybookExpansion.source_location_map` (`preserve_source_locations=True`) and as `ParseResult.expansion_source_map`; and `preserve_comments=True`, which puts each comment line's text back into the listing afterwards (`expand --keep-comments`). See `.okf/preprocessing.md`
- `source_format.py` -- `detect_fixed_format()` decides whether a source is fixed-format (and so needs `normalize_fixed_format`) from its sequence area / indicator column; `normalize_with_recovery()` normalizes with the unterminated-literal retry. The one copy of both decisions, used by `CobolParser` (and so `parse_cobol`), the lexer and the CLI
- `copy_statement_parser.py` -- `CopyStatementLexer`, REPLACING clause handling, continuation line normalization
- `_normalize.py` -- implementation behind `normalize_fixed_format`, directive stripping and the conditional-compilation evaluator (re-exported from `__init__.py`)
- `replace_statement.py` -- `REPLACE` statement application (incl. IBM `==:TAG:==` partial words)
- `path_resolver.py` -- Secure copybook path resolution with traversal prevention
- `models.py` -- `CopybookExpansion`, `CopyStatement`, `CopybookSearchPath`, `ExpansionStatistics`

**`cobolparser/parser.py`** -- `CobolParser` orchestrates parsing via `DivisionParserFactory`. Returns `ParseResult(ast, errors, warnings, statistics, expansion_source_map)`. `CobolParser` / `parse_cobol` default to `ErrorRecoveryMode.FAIL_FAST`; the CLI defaults to collect-all. Multi-unit compilation units (nested/stacked `PROGRAM-ID`s, and IBM object-oriented `CLASS-ID` units with their `FACTORY` / `OBJECT` / `METHOD-ID` units, `CobolProgram.unit_kind`) parse into `contained_programs`; `program_units()` enumerates them all. Conditional compilation (`>>DEFINE` / `>>IF` / `>>EVALUATE`) and `REPLACE` (including IBM `==:TAG:==` partial words) are applied before lexing.

**`cobolparser/core/`** -- Infrastructure:
- `interfaces.py` -- `ITokenStream`, `IDivisionParser`, `IStatementParser` ABCs; `ParseContext` for nested statement parsing
- `token_stream.py` -- `TokenStream` wraps `List[Token]` with `peek()`, `consume()`, `expect()`, configurable lookahead
- `registry.py` -- `StatementParserRegistry` with first-match dispatch strategy
- `exceptions.py` -- `TokenMismatch`, `UnexpectedEndOfInput`, `DivisionNotFoundError`, `UnknownStatementError`, `ValidationError` (all extend `ParseError`)
- `ast_factory.py` -- `ASTNodeFactory` for validated AST node creation; use `get_factory()` / `create_node()` rather than instantiating nodes directly. Raises `NodeTypeError`, `FieldValidationError`

**`cobolparser/_lines.py`** -- `split_source_lines()`: the one line splitter for source text, on `\n` / `\r\n` / `\r` only. `str.splitlines()` also breaks on form feed / NEL / U+2028, which shifted every later line number when one sat inside a record; never use it on source text.

**`cobolparser/_errors.py`** -- Canonical `ParseError` base class with zero internal dependencies (avoids circular imports between `plugins.core` and `core.exceptions`).

**`cobolparser/parsers/`** -- All division and statement parsers:
- `divisions/factory.py` -- `DivisionParserFactory` with `DivisionType` enum (IDENTIFICATION, ENVIRONMENT, DATA, PROCEDURE)
- `divisions/base.py` -- Base division parser with error recovery
- `divisions/identification.py` -- IDENTIFICATION DIVISION parser
- `divisions/environment.py` -- ENVIRONMENT DIVISION parser
- `divisions/data.py` -- DATA DIVISION parser (FILE / WORKING-STORAGE / LOCAL-STORAGE / LINKAGE / REPORT sections; SCREEN and COMMUNICATION are recognized and skipped with a warning). `data_clauses.py` (data-item clauses incl. REPORT SECTION report-group clauses), `data_file_description.py` (FD/SD clauses), `data_report_description.py` (RD clauses), `data_special_entries.py` (level-88/66, data-division EXEC SQL) are its collaborators
- `divisions/procedure.py` -- PROCEDURE DIVISION parser with `StatementParserRegistry`
- `statements/` -- <!-- okf:gen statement-parser-file-count -->33<!-- /okf:gen --> statement parser files (plus the `_utils.py` / `_conditions.py` helpers) (see "Statement Parsers" section below)
- `statements/_utils.py` -- Shared clause collection utilities

**`cobolparser/models/`** -- AST node classes. Every node extends `ASTNode` (from `ast_base.py`) and must implement `to_dict()`:
- `ast_base.py` -- `ASTNode`, `SourceLocation`, `ASTValidator`
- `program.py` -- `CobolProgram`, `CobolDivision`, `CobolSection`, `CobolParagraph`
- `data_items.py` -- `CobolDataItem`, `PictureClause`, `OccursClause`
- `sql_statements.py` -- SQL statement AST nodes
- `statements/` -- Statement node classes split by category (see "AST Statement Models" below)

**`cobolparser/plugins/core.py`** -- Configuration: `ErrorRecoveryMode` (FAIL_FAST / COLLECT_ALL), `DialectType`, `MemoryConfiguration`, `SerializationConfig`, `ParseStatistics`, `PluginManager`.

**`cobolparser/dialects/ibm_enterprise.py`** -- `IBMEnterpriseCobol` dialect: COMP-3, EXEC SQL/CICS/IMS DLI, IBM intrinsic functions.

**`cobolparser/dialects/le_signatures.py`** -- Call signatures for IBM Language Environment callable services and COBOL intrinsic functions: per operand, its direction, its exact COBOL declaration, whether it may be omitted, and whether it repeats. Coverage of the LE services is partial *and reported* (`services_without_signature()`), so "no signature catalogued" is never mistaken for "not an LE service"; the intrinsic half is complete and pinned by a test. `IBM_LE_SERVICE_INFO` is derived from it. Backs the `le-info` CLI subcommand and the COBOL Analyzer extension's LE hover. See `.okf/analysis.md`

**`cobolparser/analysis/`** -- <!-- okf:gen analysis-module-count -->33<!-- /okf:gen --> static analysis modules (plus the `program_flow/` package and the private helpers <!-- okf:gen analysis-private-helpers -->`_cics.py`, `_files.py`, `_names.py`, `_procedures.py`, `_sql_flow.py`, `_sql_whenever.py`<!-- /okf:gen -->). The list below covers the ones with their own entry here; `.okf/analysis.md` is the complete and current index:
- `value_tracker.py` -- `DynamicCallAnalyzer` tracks possible values for variables in dynamic CALL statements via MOVE and VALUE clause analysis
- `io_coverage_reporter.py` -- Machine-readable IO coverage reports (`CoverageStatus`, `TestType`)
- `io_diagnostics.py` -- IO operation diagnostics
- `io_logger.py` -- IO operation logging
- `io_sequence.py` -- IO sequence validation
- `crud_matrix.py` -- CRUD matrix generation for file operations
- `dead_code.py` -- Unreferenced paragraph/section detection
- `unused_variables.py` -- `UnusedVariableAnalyzer` detects DATA DIVISION items (FILE/WORKING-STORAGE/LOCAL-STORAGE/LINKAGE) never referenced in PROCEDURE DIVISION, including group items, level-88 condition names, REDEFINES propagation, and OCCURS ... DEPENDING ON. Backs the `unused-variables` CLI subcommand
- `host_var_resolver.py` -- SQL host variable resolution
- `dclgen_check.py` -- `DclgenChecker` cross-checks every EXEC SQL `:host-var` against the DCLGEN `DECLARE TABLE` column of its name (matching `CUST_ID` to `CUST-ID` the way DCLGEN itself does), grading category / scale / precision / length / usage / sign / missing-null-indicator mismatches -- the ones a DB2 precompiler accepts and a runtime quietly acts on. Backs the `dclgen-check` CLI subcommand and the `dclgen-check` lint rule. Reports what it could *not* check per host variable, so a quiet report is never mistaken for a checked one. See `.okf/analysis.md`
- `ims_segment_analyzer.py` -- IMS DLI segment analysis
- `language_env_analyzer.py` -- IBM Language Environment detection
- `linkage_checker.py` -- LINKAGE SECTION validation
- `move_type_checker.py` -- MOVE statement type compatibility checking
- `program_flow/` -- Control flow graph analysis package (<!-- okf:gen program-flow-modules -->`analyzer.py`, `condition_text.py`, `cycles.py`, `edges.py`, `graph.py`, `models.py`, `scanner.py`, `statement_text.py`<!-- /okf:gen -->; public API re-exported from the package `__init__.py`)
- `recursion_risk.py` -- `RecursionRiskAnalyzer` detects recursion-driven infinite-loop risks: PERFORM/GO TO cycles (reusing `ProgramFlowAnalyzer`'s `cycle_details`, graded HIGH/MEDIUM by whether the cycle has an escape route) and self-recursive CALL statements (static or dynamic, targeting the program's own PROGRAM-ID). Backs the `recursion-check` CLI subcommand. See `.okf/analysis.md`
- `complexity.py` -- `ComplexityAnalyzer` computes per-paragraph/section McCabe cyclomatic complexity (from a dedicated statement-tree walk, not the inter-paragraph CFG), an AND/OR-aware `extended_complexity`, max nesting depth, fan-in/fan-out (from `ProgramFlowAnalyzer` edges), and LOW/MODERATE/HIGH ratings. Backs the `complexity` CLI subcommand. See `.okf/analysis.md`
- `redundancy.py` -- `RedundancyAnalyzer` combines `DeadCodeAnalyzer`/`UnusedVariableAnalyzer` ratios with whole-paragraph Type-1 (exact) / Type-2 (renamed-identifier) duplicate-code clone detection. Also reports `paragraph_fingerprints` -- each clone-eligible paragraph's two structural digests -- which is what lets clone groups be merged *across* programs (`scan.cross_file_clone_groups`); `clone_groups` alone can only ever answer "which paragraphs in this one file duplicate each other", and the commoner shape of COBOL copy-paste is a paragraph cloned into a different program. Backs the `redundancy` CLI subcommand. See `.okf/analysis.md`
- `technical_debt.py` -- `TechnicalDebtAnalyzer` composite 0-100 technical-debt score (A-F grade) combining complexity, redundancy, control-flow smells (GO TO density, ALTER usage, no-escape recursion cycles, unreachable nodes), and size, as a `DebtWeights`-weighted, fully explainable rollup with a `top_offenders` list. Backs the `health` CLI subcommand. See `.okf/analysis.md`
- `boundary_inventory.py` -- `BoundaryInventoryAnalyzer` (Phase 2 of the `gen-fixtures` program-scoped test-data initiative): walks PROCEDURE DIVISION and inventories every mockable boundary (CALL/DYNCALL with a 4-rung argument-direction ladder, the eight file-op verbs, SQL/CICS/DLI, console ACCEPT), keyed the same way mockymock's `mock_surface` keys them. Takes a Phase 1 `ProgramLayoutIndex` to resolve each boundary's record/field layout. See `.okf/analysis.md`
- `constraints.py` / `domains.py` -- `ConstraintExtractor` + `domains.solve()` (Phase 4 of the `gen-fixtures` initiative): walks IF/EVALUATE/SEARCH conditions and PERFORM UNTIL loop guards into `FieldConstraint`s (relational/level-88/figurative/class-sign forms, AND/OR/NOT via De Morgan) and `SequenceConstraint`s (the READ/AT-END/loop-flag EOF idiom); `domains.py` is a small zero-dependency domain-propagation solver (numeric interval / text allow-deny / level-88 enum) that picks a deterministic witness always rendered through `ValueFactory.render()`. Takes a Phase 1 `ProgramLayoutIndex` and a Phase 2 `BoundaryReport`. See `.okf/analysis.md`
- `field_lineage.py` / `lineage_graph.py` / `lineage_jcl.py` / `_sql_flow.py` -- field-level data lineage. `FieldFlowAnalyzer` builds one program's value-flow graph (MOVE byte overlays, arithmetic, READ INTO / WRITE FROM, SORT, CALL arguments, linkage parameters, SQL host variables <-> columns, ACCEPT/DISPLAY) between data items and *ports* (file DD byte ranges, `CALLEE#n`, `PROGRAM#n`, `TABLE.COLUMN`, console), with a port-to-port summary and key uses. `LineageGraph` joins many programs' reports through datasets (bindings from jcl-parser via `lineage_jcl`, or supplied; GDG and `&&` temporaries normalized; DFSORT SUM ranges are aggregates, reformats stop the flow), CALL arguments and DB2 columns, and answers forward/backward impact queries plus candidate key relationships. OCCURS table fields map to every occurrence's bytes, inexactly; a literal subscript (`AMT(3)`) gets its own exact node (`LINEAGE_VERSION` "2"). `graph.join_state()` / `LineageGraph(reports, join_edges=..., join_caveats=..., unjoined=...)` store and restore the joins with their caveats. `field-impact` exits 1 when nothing parsed or the start matches nothing. Backs the `lineage` and `field-impact` CLI subcommands and `scan --analyzer lineage`. Design: `docs/plans/2026-10-08-field-lineage-design.md`. See `.okf/analysis.md`
- `business_rules.py` -- `BusinessRuleExtractor` extracts the program's business rules: every IF/EVALUATE/SEARCH as a decision table (one `RuleBranch` per arm: condition + actions), promoted to `validation` when an arm rejects (error literal, reject/abend path, class test), and paragraph-level arithmetic as `calculation` rules with a normalized formula. Level-88 names spelled out in a glossary, `guards` (enclosing arm conditions), `reached_via` (the arm elsewhere that PERFORMs the rule's paragraph), inputs/outputs via xref's role mapping, and a `data_lineage` inversion. Technical rules (file status, READ AT END flags, SQLCODE/EIB*) are detected from the program and excluded by default but counted. Backs the `business-rules` CLI subcommand. See `.okf/analysis.md`
- `lint.py` -- `LintAnalyzer` runs several of the analyzers above over **one** parse and flattens their differently-shaped reports into a single severity-graded `LintFinding` stream (`rule`, `severity`, `message`, `location`, `symbol`, `kind`), ordered by source position. Rule ids are the analyzer subcommand names (<!-- okf:gen lint-rules -->`dead-code`, `unused-variables`, `move-type-check`, `io-sequence`, `linkage-check`, `recursion-check`, `complexity`, `dclgen-check`, `sql-cics-check`<!-- /okf:gen -->); severity is per finding where the underlying analyzer grades itself. Lints **every program unit** in the file (a contained program left unexamined would read as a clean one), and `apply_source_map()` stamps each finding with the file and line it really came from when copybooks were expanded. Re-implements no analysis -- every rule is a mapping from an existing report. `LintReport` also carries `caveats` (what could not be checked, e.g. MOVE operands whose category never resolved) and `failed_rules` (a rule that raised costs only its own findings), so a quiet report is never mistaken for a clean program. Backs the `lint` CLI subcommand. See `.okf/analysis.md`
- `const_fold.py` -- `ConstantFolder` (Phase 7 of the `gen-fixtures` initiative): a single forward walk of a program's entry paragraph chain, seeded by one scenario's own mock-supplied inputs, tracking which data items hold a knowable literal value after a MOVE or a simple arithmetic/COMPUTE statement -- "exact by construction, or absent" throughout (a loop/branch poisons every field its body could write rather than guess which arm runs; DIVIDE folds when `DivideStatement.division_mode` says BY vs INTO and is poisoned otherwise; a numeric result is only kept when it fits its target field's PICTURE with no rounding/truncation/sign coercion). Wired into `ProgramFixtureGenerator` as `Expectation(kind="field_equals")` for every field with one known value at every DISPLAY/WRITE that shows it (the value at that site, not at program end). See `.okf/analysis.md`

**`cobolparser/generators/`** -- Code generation utilities:
- `flowchart.py` -- Generates flowchart representations from parsed AST
- `copybook_data.py` -- Backwards-compatible re-export shim for copybook → CSV test data generation (implementation in `data/` package). The generator honors PICTURE/USAGE/OCCURS/REDEFINES/level-88/VALUE. Deterministic per `seed`. Backs the `gen-data` CLI subcommand
- `data/` -- Modular implementation: `options.py` (DataGeneratorOptions, incl. `for_record_image()`), `errors.py` (CopybookLayoutError, ProgramLayoutError), `layout.py` (FieldCategory, FieldSpec incl. `storage_size`, flatten_record), `storage.py` (re-export shim over `cobolparser/_storage.py`: `storage_size()` / `binary_byte_length()` / `packed_byte_length()` -- the package's single authority on how many bytes a data item occupies, also used by `CobolDataItem.calculate_size`; `layout.py`, `layout_offsets.py` and `encoding.py` all defer to it so record images and `data-items` offsets cannot drift apart), `encoding.py` (record-image encoding: COMP-3 packed nibbles, COMP/COMP-4 big-endian binary, COMP-5 and COMP-1/2 in host order, zoned/overpunched signed DISPLAY, ASCII or EBCDIC cp037; `EncodingOptions`, `encode_record()`, `hex_dump()`, `encoding_caveats()` -- every encoding verified against GnuCOBOL, see `.okf/generators.md`. Also owns **fixed vs. variable record length**: `RecordFormat` (`fixed` = RECFM=F/FB, the default; `variable` = RECFM=V/VB with a 4-byte RDW; `variable-bare`; `auto`), `encode_rdw()`, `minimum_record_length()`, `row_record_length()`. Under a variable format only the `OCCURS ... DEPENDING ON` occurrences a row's own counter names are written -- `layout.py`'s `OdoControl` / `present_indexes()` decide which those are, and `ValueFactory` draws the counter from the table's own bounds so it always names a real occurrence. The *other* way a record varies -- `FD ... RECORD VARYING FROM min TO max DEPENDING ON item`, where the layout is flat and nothing in the record says how long it is -- is `layout.py`'s `VaryingLength`: the range is read off the FD when the source is a whole program (or from `DataGeneratorOptions.record_varying` for a bare copybook), one length per row is drawn at generation time from the seeded RNG, and `encode_record(..., data_length=N)` cuts the body to it), `values.py` (ValueFactory), `editing.py` (numeric-edited PICTURE editing/de-editing: `edit_numeric`, `deedit_numeric`), `dataset.py` (GeneratedDataset, incl. `to_records()` / `write_records()` / `to_hex_dump()`), `copybook.py` (parse_copybook_records, CopybookDataGenerator), `program_layout.py` (FileFacts, ResolvedField, ProgramLayoutIndex -- Phase 1 of the `gen-fixtures` program-scoped test-data initiative; resolves a whole program's FD/record/field names to layout facts), `bundle.py` (BUNDLE_VERSION, Expectation, BoundaryFixture, CoverageSummary, Scenario, FixtureBundle -- Phase 3's serializable output shapes, including `FixtureBundle.write_csv_dir()`), `views.py` (`build_record_views()` -- the offset-annotated byte map a decoder reads a record through, with one `RecordView` per `REDEFINES` so an overlay can be switched without re-parsing the copybook; offsets are a running sum of the same widths `encode_record()` concatenates, so a decoded offset and an encoded byte position cannot drift), `decoding.py` (the inverse of `encoding.py`: `RecordDecoder`, `decode_field()`/`decode_record()`, `DecodedField`/`DecodedRecord`/`DecodeResult`, `decoded_hex_dump()` -- reads a real record image / EBCDIC flat file back through a copybook, `decode(encode(row)) == row`, with bad bytes reported per field rather than silently zeroed; backs the `decode` CLI subcommand), `compare.py` (`compare_records()` / `compare_files()` -- two decoded files through one view compared field by field, paired by key or by position, `CompareResult` with exact changed/missing/extra counts; backs the `compare` CLI subcommand -- Phase 1 of the test-data-environments initiative, design in the backend repo), `layout_offsets.py` (`compute_program_data_items()` -- record-relative byte offset/length, multi-hop REDEFINES chains, and per-entry level-88 condition values for every data item in a program; backs the `data-items` CLI subcommand). See `docs/plans/2026-08-02-program-data-generation-*.md` and `.okf/generators.md`
- `program_fixtures.py` -- `ProgramFixtureGenerator` (Phase 3/6/7 of the `gen-fixtures` initiative): combines a `ProgramLayoutIndex` (Phase 1) and a `BoundaryReport` (Phase 2) into a `FixtureBundle`. `generate`/`generate_from_file` produce one "happy path" `Scenario` with generated in-data per IN/BIDIRECTIONAL boundary and assert-on `Expectation` stubs per OUT boundary, using per-boundary deterministic sub-seeding. `generate_with_scenarios`/`generate_with_scenarios_from_file` (Phase 6) additionally accept `mode="branches"|"all"`, routing through Phase 5's `ScenarioPlanner` and pinning each `PlannedScenario`'s witnesses/sequence-lengths/status-overrides into an otherwise normally-generated fixture set; `mode="happy"` delegates to `generate()` unchanged (byte-identical). Every scenario's `expectations` also carries tier 1 (`Expectation(kind="call_count", ...)`, one per mocked boundary and only when exact: `analysis.invocation_counts` counts the invoking statements on the unconditional path, and a read-until-EOF loop reads the scenario's whole sequence plus one) and tier 2 (`Expectation(kind="field_equals", ...)`, from `analysis.const_fold.ConstantFolder` seeded with the scenario's own single-invocation mocked inputs) -- Phase 7. Backs the `gen-fixtures` CLI subcommand. See `.okf/generators.md`, `.okf/analysis.md`, and `docs/fixture-bundle-schema.md`
- `scenarios.py` -- `ScenarioPlanner` (Phase 5 of the `gen-fixtures` initiative): turns a Phase 4 `ConstraintReport` and `ProgramFlowAnalyzer`'s CFG into a set of named `PlannedScenario`s -- one (or a merge of several) per reachable, satisfiable branch arm, plus fixed families (empty-input/error-status/boundary-values) for `mode="all"` -- with exact arm-coverage accounting (`ScenarioCoverage`: targeted + merged + missed == total, every miss carrying a reason). Wired into the `gen-fixtures` CLI as of Phase 6 via `program_fixtures.py`'s `generate_with_scenarios`. See `.okf/generators.md`. Arm reachability here is CFG-shaped (`flow_report.unreachable_nodes`), never data-shaped, so an arm reachable only via a *correlation between records* gets a scenario named for it that never reaches it; `PlannedScenario.row_witnesses` is the (unpopulated) groundwork for expressing those -- see `docs/plans/2026-09-04-cross-record-correlation-design.md`

**`cobolparser/batch.py`** -- `parse_files(paths)` for parallel multi-file parsing using `ProcessPoolExecutor`. Returns `List[BatchResult]`. Supports executor reuse for repeated batches. `parse_files_with_copybooks(paths, copybook_paths=...)` parses each file with copybook expansion enabled.

**`cobolparser/scan.py`** -- `scan_files(paths, ScanOptions(...))` runs *analyzers* (not just the parse) over many files in one process: the parse and the analysis both happen inside the worker and only the small report dicts come back, so a worker's peak memory is one file's AST rather than the whole shop's -- which is why this is a separate module from `batch.py` rather than another entry point on it. Per-file fault isolation, every program unit reported (contained programs included, each with its `depth`), and an analyzer that raises named in that unit's `failed_analyzers` with its other reports intact. `cross_file_clone_groups(report)` merges every scanned paragraph's fingerprints into clone groups spanning programs, ranked by duplicated volume (statements x members) rather than by how many files they span -- boilerplate `0000-MAIN-PROCESS` scaffolding spreads across every file in a shop and would otherwise bury the real findings. Backs the `scan` CLI subcommand and the COBOL Analyzer extension's Analyze Workspace. See `.okf/batch.md`

**`cobolparser/profiling.py`** -- `ProfilerContext` wraps any parse call with `cProfile`, `tracemalloc`, and optional `psutil` CPU accounting. Returns `ProfilingResult` (wall-clock, CPU, peak memory, top `FunctionProfile` entries). Install the `profiling` extra (`pip install -e ".[profiling]"`) to enable CPU accounting; the module imports `psutil` lazily so the package remains usable without it.

**`cobolparser/config/`** -- The **universal project config file**, `cobol.yml` (or `cobol.yaml`), read by every tool in the family: this CLI, the `mockymock` CLI, and the COBOL Analyzer VS Code extension. A shop states its copybook directories, source format, dialect and record encoding once at the project root instead of on every invocation. Discovery walks up from the cwd the way `git` walks up looking for `.git`; paths inside resolve against the config file's own directory, not the cwd. Precedence is always **explicit CLI flag > config file > built-in default**. `project.py` owns the schema and the discovery; `_yaml.py` is a stdlib-only reader for the strict YAML subset a config file needs (the package has no runtime dependencies, so PyYAML is not an option) that **rejects** anchors, tags, block scalars, merge keys, multi-document files, tabs in indentation and duplicate keys with a line number rather than guessing. `mockymock:` / `analyzer:` sections are carried through verbatim for the tools that own them. User-facing reference: [`docs/project-config.md`](docs/project-config.md). See `.okf/cli.md`

**`cobolparser/mcp/`** -- The **MCP server** (`cobol-parser mcp --root DIR`, stdio) that lets AI agents question COBOL source: `program_brief`, `explain_symbol`, `callers_of`, `record_layout`, `lint`, `read_source`, and across every program under the root `codebase_overview`, `callers_of` (program level), `impact_of_change` (copybook member or field) and `where_from`. With the `[jcl]` extra it also reads the JCL under the root (`jcl_tools.py`): `jobs_running` (every step that runs a program, its SELECT files bound to DDs and datasets, DDs the step does not code), `dataset_users` (who reads or writes a dataset, by DISP) and `jcl_job` (one JCL file's jobs, steps and DDs, cataloged procedures cited in their member); without the extra they answer with the install command. Tools answer questions rather than mirror subcommands, every location is a `file:line` on disk (copybooks named as themselves, through the expansion source map and `analysis/lint.py`'s `source_column_offsets()`), and every answer carries a closed-vocabulary `caveats` list and a `truncated` list (`envelope.py`). `workspace.py` guards paths (root + `cobol.yml` copybook dirs only), reads `cobol.yml` from the root (re-read when it changes), and caches parses -- and the analyzer reports computed from them -- until a program or one of its copybooks changes. `codebase_index.py` builds the three root-wide indexes (call/COPY graph, field lineage joined through the JCL under the root, health and cross-program clones) on first use and keeps each until a file it read changes. `tools.py` imports no SDK, so the backend can call `CobolTools` directly; only `server.py` imports the `[mcp]` extra (`mcp>=1.10,<2`). User guide: [`docs/mcp-server.md`](docs/mcp-server.md); design and later phases: `docs/plans/2026-10-15-mcp-server-design.md`. See `.okf/mcp.md`

**`cobolparser/cli/`** -- Command-line interface:
- `parse.py` -- Implements all CLI subcommands (see "Commands" above for the full list); most analyzer subcommands share argument-building via `_build_analyzer_parser()`
- `_project_config.py` -- Merges `cobol.yml` into the parsed arguments, in one place, so every `_cmd_*` keeps reading `args.copybook_path` unchanged. Also owns `--config`/`--no-config`, which are stripped from argv *before* argparse so they work on either side of the subcommand and cannot be mistaken for a source file by `main()`'s legacy "prepend parse" rewrite. Telling "the user typed `--charset ascii`" from "`--charset` defaulted to ascii" is done by re-parsing argv against a parser whose optional defaults are sentinels -- most flags here have a non-`None` default, so `is None` cannot answer it
- `coverage.py` -- IO coverage CLI tools

### Statement Parsers (cobolparser/parsers/statements/)

| File | COBOL Verbs |
|------|------------|
| `accept_parser.py` | ACCEPT |
| `allocate_free_parsers.py` | ALLOCATE, FREE |
| `arithmetic_parsers.py` | ADD, SUBTRACT, MULTIPLY, DIVIDE, COMPUTE |
| `call_parser.py` | CALL |
| `close_parser.py` | CLOSE |
| `communication_parsers.py` | SEND, RECEIVE, ENABLE, DISABLE, PURGE (COBOL-85 Communication Module) |
| `delete_parser.py` | DELETE |
| `display_parser.py` | DISPLAY |
| `entry_parser.py` | ENTRY |
| `evaluate_parser.py` | EVALUATE |
| `exception_parsers.py` | RAISE, RESUME, VALIDATE (COBOL 2002) |
| `go_parser.py` | GO TO |
| `ibm_exec_statements.py` | EXEC SQL, EXEC CICS, EXEC IMS DLI |
| `if_parser.py` | IF |
| `initialize_inspect_parsers.py` | INITIALIZE, INSPECT |
| `invoke_parser.py` | INVOKE |
| `legacy_verb_parsers.py` | EXHIBIT, EXAMINE, TRANSFORM (OS/VS), ENTER, NOTE (COBOL-74), CHAIN (Micro Focus), READY TRACE / RESET TRACE, SERVICE LABEL / SERVICE RELOAD, TITLE (IBM compiler-directing) |
| `move_parser.py` | MOVE |
| `open_parser.py` | OPEN |
| `perform_parser.py` | PERFORM |
| `read_parser.py` | READ |
| `report_writer_parsers.py` | INITIATE, TERMINATE, SUPPRESS (Report Writer; GENERATE lives in `simple_statement_parsers.py`) |
| `rewrite_parser.py` | REWRITE |
| `search_parser.py` | SEARCH |
| `set_parser.py` | SET |
| `simple_statement_parsers.py` | ALTER, CANCEL, COMMIT, CONTINUE, EJECT, EXIT, GENERATE, GOBACK, RELEASE, RETURN, ROLLBACK, SKIP1, SKIP2, SKIP3, USE |
| `sort_merge_parsers.py` | SORT, MERGE |
| `start_parser.py` | START |
| `stop_parser.py` | STOP |
| `string_unstring_parsers.py` | STRING, UNSTRING |
| `unlock_parser.py` | UNLOCK |
| `write_parser.py` | WRITE |
| `xml_json_parser.py` | XML GENERATE, XML PARSE, JSON GENERATE, JSON PARSE |

`_utils.py` (clause collection) and `_conditions.py` (shared condition-expression building for IF/EVALUATE/PERFORM UNTIL) are shared helpers, not verb parsers.

Every COBOL verb now has a registered parser. `procedure_recovery.UNSUPPORTED_VERBS` (the warn-and-discard path) holds only `EXECUTE`, `GOTO`, `RECOVER` -- verb-shaped reserved words with no statement behind them in any dialect. `ExecCicsStatement` / `ExecImsStatement` are `CobolStatement`s (node_type kept as `EXEC_CICS` / `EXEC_IMS`), so `get_all_statements()` returns them like every other statement.

### AST Statement Models (cobolparser/models/statements/)

| File | Node Classes |
|------|-------------|
| `base.py` | `CobolStatement`, `CobolExpression`, `ArithmeticExpression`, `ConditionalExpression`, `LogicalExpression`, `FunctionCall` |
| `arithmetic.py` | `ArithmeticStatement`, `AddStatement`, `SubtractStatement`, `MultiplyStatement`, `DivideStatement`, `ComputeStatement` |
| `call.py` | `CallStatement`, `EntryStatement`, `CallParameter` |
| `communication.py` | `SendStatement`, `ReceiveStatement`, `EnableStatement`, `DisableStatement`, `PurgeStatement` |
| `control.py` | `IfStatement`, `EvaluateStatement`, `WhenClause`, `PerformStatement`, `GoStatement`, `StopStatement`, `SearchStatement`, `RaiseStatement`, `ResumeStatement` |
| `data.py` | `MoveStatement`, `DisplayStatement`, `InitializeStatement`, `InspectStatement`, `SetStatement`, `StringStatement`, `UnstringStatement`, `ValidateStatement` |
| `io.py` | `IOReadStatement`, `IOWriteStatement`, `IOOpenStatement`, `IOCloseStatement`, `IOAcceptStatement`, `IORewriteStatement`, `IODeleteStatement`, `IOStartStatement`, `IOUnlockStatement` |
| `legacy.py` | `ExhibitStatement`, `ExamineStatement`, `TransformStatement`, `EnterStatement`, `NoteStatement`, `ChainStatement`, `TraceStatement`, `ServiceStatement`, `TitleStatement` |
| `misc.py` | `SelectStatement`, `CopyStatement`, `ContinueStatement`, `EjectStatement`, `SkipStatement`, `ExitStatement`, `GobackStatement`, `CancelStatement`, `AlterStatement`, `GenerateStatement`, `XmlJsonStatement`, `ReleaseStatement`, `ReturnStatement`, `UseStatement`, `SortStatement`, `MergeStatement`, `CommitStatement`, `RollbackStatement`, `InvokeStatement`, `AllocateStatement`, `FreeStatement`, `NextSentenceStatement` |
| `report_writer.py` | `InitiateStatement`, `TerminateStatement`, `SuppressStatement` |

### Data Flow Detail

1. `normalize_fixed_format(lines)` -> free-form text string (comment lines dropped)
2. `CobolLexer(text).tokenize()` -> `List[Token]`
3. `TokenStream(tokens)` wraps the list with lookahead
4. `CobolParser.parse()` -> `DivisionParserFactory.parse_division()` per division
5. Each division parser calls `StatementParserRegistry.find_parser()` (first-match) to dispatch statements
6. Returns `ParseResult(ast, errors, warnings, statistics, expansion_source_map)`

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
parse_result = parse_cobol_with_expansion(source, "prog.cbl", copybook_paths=["/path"])

# Dynamic call analysis
from cobolparser.analysis import DynamicCallAnalyzer
DynamicCallAnalyzer().analyze(parse_result.ast)

# Analyzers exported from the top-level package — all follow the same
# `<Analyzer>().analyze(ast) -> <Report>` shape (HostVariableResolver
# uses `.resolve(ast)`; LinkageChecker and MoveTypeChecker use `.check(ast)`):
from cobolparser import (
    DeadCodeAnalyzer,           # report.dead_items
    UnusedVariableAnalyzer,     # report.unused_items (DATA DIVISION items never referenced)
    ProgramFlowAnalyzer,        # report.edges (typed PERFORM/GO TO/CALL/fall-through; THRU range_members; classified cycle_details)
    RecursionRiskAnalyzer,      # report.risks — PERFORM/GO TO cycles + self-recursive CALLs that risk an infinite loop
    ComplexityAnalyzer,         # report.procedures — per-paragraph cyclomatic/extended complexity, fan-in/fan-out, rating
    RedundancyAnalyzer,         # report.dead_items / .unused_items / .clone_groups — dead code, unused vars, duplicate paragraphs
    TechnicalDebtAnalyzer,      # report.score / .grade / .components / .top_offenders — composite debt score
    IOLogger,                   # report.operations
    IOSequenceAnalyzer,         # report.violations
    MoveTypeChecker,            # report.violations
    LinkageChecker,             # report.violations
    LanguageEnvironmentAnalyzer,# .intrinsic_usages (FUNCTION refs) / .le_service_calls (CALL CEE*)
    CRUDMatrixGenerator,        # matrix.entries, .to_csv(), .to_json()
)
from cobolparser.analysis import IMSSegmentAnalyzer, HostVariableResolver

# What a CEE service (or an intrinsic FUNCTION) needs at the call site
from cobolparser.dialects.le_signatures import le_service_signature, intrinsic_signature

sig = le_service_signature("CEEDAYS")      # None when the name has no signature
sig.call_example()          # 'CALL "CEEDAYS" USING input_char_date, ...'
sig.required_parameters     # the operands that may not be omitted
sig.parameters[0].direction # "input" | "output" | "input/output"
sig.parameters[0].data_type.declaration      # 'halfword length + PIC X(n) text'
sig.parameters[0].data_type.snippet          # a full WORKING-STORAGE entry
intrinsic_signature("NUMVAL-C").returns      # "numeric"

# Business rules: decisions (as decision tables), validations, calculations
from cobolparser import BusinessRuleExtractor
rules = BusinessRuleExtractor().analyze(parse_result.ast)  # include_technical=False
rules.rules[0].branches     # list[RuleBranch]: label / condition / actions
rules.condition_names       # POL-AUTO -> "POL-TYPE = 'A'"
rules.data_lineage          # {"WS-RATE": {"read_by": [...], "written_by": [...]}}
rules.technical_rules_excluded
print(rules.to_text())

# One pass, every rule, one severity-graded list of findings
from cobolparser import LintAnalyzer
report = LintAnalyzer().analyze(parse_result.ast)          # or LintAnalyzer(["dead-code"])
report.findings            # list[LintFinding]: rule/severity/message/location/symbol/kind
report.caveats             # what could not be checked (an unresolved COPY, ...)
report.failed_rules        # rules that raised; the rest still ran
report.worst_severity()    # "error" | "warning" | "info" | None -- backs `lint --fail-on`

# Reading a real record image back: the inverse of the encoder above
from cobolparser.generators import RecordDecoder, build_record_views

decoder = RecordDecoder.from_copybook_file("CUSTOMER.cpy")
result = decoder.decode_file(
    "CUSTOMER.DAT", opts=EncodingOptions(charset=Charset.EBCDIC)
)
result.to_csv()                # the same table gen-data would have written
result.records[0].values()     # {"CUST-ID": "339564", ...}
result.records[0].fields[2]    # DecodedField: offset/length/hex/value/error
result.error_count             # fields whose bytes are not what the PIC says
result.trailing                # bytes that are not a whole record

# REDEFINES: one run of bytes, several meanings -- switch overlay, same bytes
result.views                   # ["CUST-REC", "CUST-REC.ADDR-OVERSEAS"]
decoder.decode_file("CUSTOMER.DAT", view="ADDR-OVERSEAS")
build_record_views(record).base.fields   # [PlacedField(spec, offset), ...]

# Expected vs actual output of a batch run, field by field
from cobolparser.generators.data import compare_files
diff = compare_files(decoder, "CUST.EXPECTED", "CUST.ACTUAL",
                     key=["CUST-ID"], ignore=["LAST-UPDATE-TS"])
diff.equal                     # False
diff.changed_count, diff.missing_count, diff.extra_count
diff.differences[0].fields     # [FieldDifference(name, offset, expected, actual, ...)]

# DCLGEN <-> host variable type checking
from cobolparser import DclgenChecker

report = DclgenChecker().check(parse_result.ast)
report.violations          # kind: category/scale/precision/length/usage/
                            # sign/null-indicator, each with expected vs actual
report.unchecked           # host variables no DECLARE TABLE could speak for

# Synthetic CSV test data from a copybook record layout
from cobolparser.generators import CopybookDataGenerator, DataGeneratorOptions
dataset = CopybookDataGenerator(
    DataGeneratorOptions(rows=100, seed=7)
).generate_from_file("CUSTOMER.cpy")
dataset.to_csv()               # header row + 100 generated records
dataset.write_csv("out.csv")
dataset.fields                 # list[FieldSpec] — the resolved layout
dataset.seed                   # replay this run with DataGeneratorOptions(seed=...)

# The same layout as real record bytes (COMP-3 packed, COMP big-endian, ...)
from cobolparser.generators import Charset, EncodingOptions
image_opts = DataGeneratorOptions(rows=100, seed=7).for_record_image()
dataset = CopybookDataGenerator(image_opts).generate_from_file("CUSTOMER.cpy")
dataset.write_records("CUSTOMER.BIN", EncodingOptions(charset=Charset.EBCDIC))
dataset.to_hex_dump()          # the same image, annotated field by field

# Variable-length records (RECFM=V/VB). Two mechanisms, both honoured:
#   1. OCCURS ... DEPENDING ON -- only the occurrences the counter names
#   2. FD RECORD VARYING FROM n TO m -- a flat record cut to a per-record
#      length, read off the FD when the source is a whole program
from cobolparser.generators import RecordFormat
vb = EncodingOptions(charset=Charset.EBCDIC, record_format=RecordFormat.VARIABLE)
dataset = CopybookDataGenerator(image_opts).generate_from_file("ORDER.cpy")
dataset.write_records("ORDER.VB", vb)
dataset.is_variable_length     # True iff the layout has a DEPENDING ON table
dataset.record_length()        # LRECL: every occurrence present
dataset.minimum_record_length()# every DEPENDING ON table at its minimum
dataset.record_lengths(vb)     # one length per row, RDW included

# FD RECORD VARYING FROM 47 TO 80 DEPENDING ON EMPREC-LEN, no OCCURS at all:
# the range is picked up from the FD because the source is a whole program
dataset = CopybookDataGenerator(image_opts).generate_from_file("EMPVL.cbl")
dataset.varying                # VaryingLength(47, 80, "EMPREC-LEN") | None
dataset.declared_lengths       # one drawn length per row, or None
# For a bare copybook there is no FD to read, so state the range:
DataGeneratorOptions(rows=100, seed=7, record_varying=(47, 80))

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
report.boundaries                      # list[Boundary]: ref (.category/.key/.paragraph/.line),
                                        # direction, record_names, status_field, handlers,
                                        # call_args, unresolved (category/key are top-level
                                        # only in to_dict())
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
                                # row_witnesses, sequence_constraints,
                                # status_overrides, arm_keys
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
fold.known                      # dict[qualified_name, str]: the value each field
                                 # held at the DISPLAY/WRITE sites that showed it
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

~14,700 tests across 554 `test_*.py` files (see `.okf/tests.md` for the per-directory breakdown):

```
tests/
  conftest.py            # Shared fixtures: parser(), samples_dir()
  test_all_samples.py    # Smoke-tests all sample COBOL programs
  unit/                  # Unit tests - individual components
    analysis/            # IO coverage reporter, diagnostics, all analyzers
    cli/                 # CLI command tests
    generators/          # Generator tests (data/ encoders, scenario verification, row witnesses)
    io_statements/       # IO parser unit tests
  integration/           # Integration tests - end-to-end parsing
    test_shamrice_examples.py  # Parametrized: all *.cbl in examples/cobol/shamrice/ must parse error-free
    test_enterprise_program_types.py  # tests/samples/enterprise/: FAIL_FAST clean parse, every analyzer,
                                      # gen-fixtures, scan, and per-program-type traits
    io/                  # IO coverage reporting integration
    io_statements/       # IO statement parsing, VSAM
  contracts/             # API contract tests - stability guarantees
    io_statements/       # IO statement contracts
  regression/            # Regression tests - backward compatibility
  performance/           # Performance benchmarks (factory, parser)
  samples/               # Shared COBOL test fixtures
    copybook_programs/   # Programs with COPY statements
    copybooks/           # Copybook files (.CPY)
    enterprise/          # One program per IBM Enterprise COBOL program type
                         # (batch, VSAM, CICS, IMS, DB2, MQ, OO, Report Writer,
                         # DECLARATIVES, ...) -- see docs/enterprise-program-types.md
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

90% line coverage is enforced by `--cov-fail-under=90` in `pyproject.toml`'s `addopts`, and branch coverage is enabled. Full-suite total as of 2026-09-16: **93.04%** (31,613 statements, ~11,100 tests).

**Measure it on the pure-Python backend** (the default since 2026-10-15: a built `.so` is ignored unless `COBOLPARSER_ACCEL=1` is set). coverage.py cannot see into a compiled Cython extension, so with the accelerators enabled the pure-Python bodies they shadow read as unexecuted: the same suite, on one commit (2026-09-07), reported 54.32% with the extensions built and 91.76% without. CI splits the two accordingly — the `build` matrix runs the suite `--no-cov` after `build_ext` (its job is to exercise the extensions), and a separate `coverage` job installs with `COBOLPARSER_SKIP_EXT=1` and enforces the floor. Locally, just leave `COBOLPARSER_ACCEL` unset before trusting a coverage number.

When running only a subset of tests, expect the check to fail -- that is normal and unrelated.

## CI/CD

**Currently disabled:** every line of `.github/workflows/ci.yml` is commented out (commit 315d474), so no CI runs on push or PR -- run lint, typecheck and the suite locally. When enabled, GitHub Actions (`.github/workflows/ci.yml`) runs on push/PR to `main`, nightly (`schedule`), and manual `workflow_dispatch`; push/PR skip docs-only changes (`paths-ignore`: `docs/**`, `.okf/**`, `reports/**`, `**/*.md`):

1. **lint** -- `ruff check .` + `black --check .` (Python 3.13, pinned versions matching `.pre-commit-config.yaml`)
2. **typecheck** -- `mypy cobolparser/` (Python 3.13, pinned version)
3. **build** -- `pip install -e ".[dev,fast]"` + `COBOLPARSER_ACCEL=1 python setup.py build_ext --inplace` + `COBOLPARSER_ACCEL=1 python -m pytest tests/ -q -p no:randomly -n auto --no-cov` on matrix: Python 3.11, 3.12, 3.13 (verifies install, the Cython extension build, and the suite against those extensions). Full suite on all three for pushes to `main`, nightly and dispatch; on a PR only 3.13 runs the full suite and 3.11/3.12 run a smoke subset (`tests/unit/test_lexer.py tests/test_all_samples.py tests/unit/test_program_fixtures.py`)
4. **coverage** -- `COBOLPARSER_SKIP_EXT=1 pip install -e ".[dev]"` + the full suite on Python 3.13, enforcing `--cov-fail-under=90` (PRs, nightly and dispatch; not on push to `main`)

The suite runs *after* `build_ext`, so CI exercises the Cython extensions rather than the pure-Python fallback -- with `--no-cov`, because coverage.py cannot see into a compiled extension (54.32% with them built vs 91.76% without, measured together on 2026-09-07). The `coverage` job is where `--cov-fail-under=90` is enforced, on a pure-Python install. A push to `main` runs lint, typecheck and the full `build` matrix (no coverage gate). Run the suite locally during development too (`python -m pytest tests/ -v`).

## Release & Distribution

`release-please` (`.github/workflows/release-please.yml`, driven by Conventional Commits, config in `release-please-config.json` / `.release-please-manifest.json`) automates versioning and `CHANGELOG.md` on every push to `main`. When it cuts a release, the same workflow also builds and publishes **binary wheels and an sdist** to PyPI as `cobol-parser` (`pip install cobol-parser`):

- The wheels are built with `COBOLPARSER_ACCEL=1` (`[tool.cibuildwheel] environment`), so they ship compiled accelerators, but an installed wheel still runs pure Python unless `COBOLPARSER_ACCEL=1` is set at run time. The sdist builds pure Python by default.
- Source is **not** hidden: only the 3 hot-path accelerators (`_lexer_fast`, `_preprocess_fast`, `_data_fast`) are Cython-compiled; every other module ships as plain `.py`. `[tool.setuptools.exclude-package-data]` in `pyproject.toml` keeps only the generated `.c`/`.pyx`/`.h` out of wheels.
- `cibuildwheel` (`[tool.cibuildwheel]` in `pyproject.toml`) builds one wheel each for manylinux x86_64, macOS arm64, and Windows AMD64, across Python 3.11-3.13 (9 wheels total); its `test-command` imports the three accelerators and runs a fast pytest subset against the installed wheel. A `build-sdist` job publishes the sdist alongside them.
- Use `workflow_dispatch` with `target: testpypi` on `.github/workflows/release-please.yml` to rehearse the whole build-all-9-wheels-and-publish pipeline against test.pypi.org (one-time Trusted Publisher registration required there first) before trusting a real release.
- This is a wholly separate release artifact from the backend's vendoring flow (see "Backend Integration" above) -- publishing to PyPI does not change how `backend/` consumes this library.
- Design history (superseded: the closed-source approach was dropped): `docs/superpowers/specs/2026-08-14-pypi-closed-source-release-design.md` and `docs/superpowers/plans/2026-08-14-pypi-closed-source-release.md`.

## Code Style and Conventions

- **Formatter**: Black (line length 88, target py311)
- **Linter**: Ruff (pycodestyle, pyflakes, isort, bugbear, comprehensions, pyupgrade; E501 ignored)
- **Type checker**: mypy with strict settings (`disallow_untyped_defs`, `strict_equality`, etc.; tests are exempted from typed def requirements)
- **Python**: `>=3.11`, uses modern syntax (`list[]`, `dict[]`, `X | None` unions)
- **No runtime dependencies**: zero external dependencies for the core library. The one optional extra, `[jcl]`, installs `jcl-parser`, which `cobolparser.jcl` reads JCL through -- never re-implement JCL parsing here
- **Imports**: `__init__.py` files may have unused imports (F401 ignored via ruff per-file config)

## File Organization Conventions

- One parser file per COBOL verb or verb group
- AST models grouped by category (arithmetic, control, data, io, call, misc)
- All parsers implement `IStatementParser` with `parse()` and `matches()` methods
- All AST nodes extend `ASTNode` and implement `to_dict()`
- Exception hierarchy rooted at `ParseError` in `_errors.py` (except the preprocessing errors -- `PreprocessingError` and its subclasses extend plain `Exception`)

## Example COBOL Files

- `tests/samples/` -- ~48 COBOL sample programs covering all statement types (plus copybook and IO sub-directories)
- `tests/samples/enterprise/` -- 22 programs, one per IBM Enterprise COBOL *program type* (QSAM batch/SORT, VSAM, CICS pseudo-conversational / channels / translated LINK server, IMS DL/I batch / MPP / EXEC DLI, DB2 batch / stored procedure, MQ, subprogram, nested programs, Report Writer, OO class + client, XML/JSON, DECLARATIVES, LE services, compiler directives, 6.x data, copybooks); all parse FAIL_FAST with no warnings and run through every analyzer. Matrix: `docs/enterprise-program-types.md`
- `examples/cobol/` -- NIST COBOL-85 test suite (459 .CBL files) and copybooks (.CPY)
- `examples/cobol/shamrice/` -- 24 IBM COBOL programs from shamrice/COBOL-Examples (ACCEPT variants, COMP types, SEARCH, SORT/MERGE, SQL, JSON/XML GENERATE, sub-programs); all parse cleanly under FAIL_FAST

## Additional Directories

- `.okf/` -- OKF knowledge bundle: topic files (lexer, preprocessing, `parser/`, AST models, `analysis/`, dialects, `generators/`, batch, JCL, CLI, tests, integration), `history/` archives, `log.md`. Load `.okf/index.md` at the start of every session.
- `tools/` -- Utility scripts grouped by area:
  - `io_catalog/validate_catalog.py` -- Validates the IO operation catalog
  - `io_coverage/` -- `generate_artifact.py` and `render_markdown.py` for IO coverage reports
  - `metrics/io_ticket_tracker.py` -- Tracks IO-related work items
  - `perf/io_threshold_guard.py` -- Guards IO performance against thresholds
- `scripts/validate_io_coverage.py` -- Standalone IO coverage validator
- `benchmarks/` -- Performance benchmark programs
- `reports/` -- Audit reports
- `setup.py` -- Builds the optional Cython extension modules (`_lexer_fast`, `_preprocess_fast`, `_data_fast`) only under `COBOLPARSER_ACCEL=1`; a default install compiles nothing. Compile in place with `COBOLPARSER_ACCEL=1 python setup.py build_ext --inplace`; both `.pyx` and pre-generated `.c` files are checked into the repo so the build does not require Cython at install time.
- `.pre-commit-config.yaml` -- Hooks for `ruff` (with `--fix`), `ruff-format`, `black`, and `mypy cobolparser/` (with `--ignore-missing-imports`). The CI lint/typecheck jobs duplicate these checks, so running `pre-commit run --all-files` locally catches the same issues.
- `CHANGELOG.md` -- Keep-a-Changelog history. The Unreleased section is the source of truth for which analyzers and CLI subcommands are wired up beyond the 1.0.0 baseline.
