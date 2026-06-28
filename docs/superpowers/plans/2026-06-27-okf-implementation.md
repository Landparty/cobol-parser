# OKF Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create 11 linked Markdown files (`docs/OKF.md` + `docs/okf/*.md`) that serve as Claude's persistent structural memory of the `cobol-parser` repo, capturing every file's purpose, class/function inventory, data flows, and conventions.

**Architecture:** Master index (`docs/OKF.md`) provides repo-at-a-glance, pipeline diagram, navigation table, and refresh protocol. Ten per-subsystem files under `docs/okf/` each follow a standard template: Files table → Key Classes/Functions table → Data Flow/Lifecycle → Public API → Gotchas/Invariants → Refresh Checklist.

**Tech Stack:** Markdown only. No code changes. Verification by `grep`.

## Global Constraints

- All paths are relative to repo root (`C:\Users\samdi\Documents\workspace\legacylens\cobol-parser`)
- Content is derived from `cobolparser/` source — every named class and function must actually exist
- No placeholders: every section must be filled with real names
- Files committed individually per task with message format `docs(okf): add <filename>`

---

### Task 1: Create `docs/OKF.md` — master index

**Files:**
- Create: `docs/OKF.md`
- Create: `docs/okf/` directory

**Interfaces:**
- Produces: Navigation table linking all 10 subsystem files; refresh protocol used by Tasks 2–11

- [ ] **Step 1: Create the docs/okf/ directory**

```bash
mkdir -p docs/okf
```

- [ ] **Step 2: Write `docs/OKF.md`**

Write the following content exactly to `docs/OKF.md`:

```markdown
# Organizational Knowledge File (OKF)

> Persistent structural memory for the `cobol-parser` repository.
> Load the relevant subsystem file at the start of any Claude session rather than re-deriving structure from source.

## Repo at a Glance

| Attribute | Value |
|-----------|-------|
| Language | Python >=3.11 (3.11, 3.12, 3.13 tested in CI) |
| Package | `cobolparser` |
| Version | 1.1.0 |
| Runtime deps | **None** (zero external dependencies for core library) |
| Optional extras | `[dev]` tests/lint, `[docs]` docs, `[fast]` Cython build, `[profiling]` psutil |
| Cython fast-paths | `_lexer_fast`, `_preprocess_fast`, `_data_fast` — opt-out: `COBOLPARSER_SKIP_EXT=1` |
| Vendored into | `backend/_vendor/cobol-parser/cobolparser/` (manual copy — never auto-synced) |
| Tests | ~5,969 tests across 226 files; 81% line coverage floor enforced |
| Entry point | `cobol-parser` CLI (console_scripts in setup) |
| Focus dialect | IBM Enterprise COBOL |

## Pipeline Overview

```
COBOL source (.cbl / .cob)
  │
  ▼
preprocess/normalize_fixed_format()
  ├─ extracts columns 8–72 from fixed-format lines
  ├─ drops comment lines (col 7 = * or /)
  └─ merges continuation lines (col 7 = -)
  │
  ▼ (optional)
preprocess/expand_copybooks()
  └─ inlines COPY statements recursively, applies REPLACING clauses
  │
  ▼
CobolLexer(text).tokenize()  →  List[Token]
  └─ TokenType enum (100+ types); Cython fast-path via _lexer_fast if compiled
  │
  ▼
TokenStream(tokens)
  └─ peek() / consume() / expect() with configurable lookahead
  │
  ▼
CobolParser.parse()
  └─ DivisionParserFactory dispatches to:
       IdentificationDivisionParser
       EnvironmentDivisionParser
       DataDivisionParser  ←  _data_fast Cython path for PICTURE/clause loops
       ProcedureDivisionParser
         └─ StatementParserRegistry (first-match dispatch → 26+ statement parsers)
  │
  ▼
ParseResult(ast, errors, warnings, statistics)
  ├─ ast: CobolProgram  →  .to_json() / .find_all_by_type()
  ├─ errors: List[ParseError]
  ├─ warnings: List[str]
  └─ statistics: ParseStatistics
  │
  ▼ (optional post-parse)
analysis/  →  15+ analyzers (DeadCodeAnalyzer, ProgramFlowAnalyzer, IOLogger, …)
```

## Navigation

| File | Covers |
|------|--------|
| [okf/lexer.md](okf/lexer.md) | CobolLexer, Token, TokenType, Cython fast-path (`_lexer_fast`) |
| [okf/preprocessing.md](okf/preprocessing.md) | normalize_fixed_format, copybook expansion, COPY statement parsing, path resolution |
| [okf/parser.md](okf/parser.md) | CobolParser, DivisionParserFactory, TokenStream, StatementParserRegistry, all 26 statement parsers, core infrastructure |
| [okf/ast-models.md](okf/ast-models.md) | ASTNode hierarchy, every model class by category, to_dict() contract, ASTNodeFactory |
| [okf/analysis.md](okf/analysis.md) | All 15 analyzers with purpose, input/output, exported symbols |
| [okf/cli.md](okf/cli.md) | Every CLI subcommand, flags, and usage examples |
| [okf/tests.md](okf/tests.md) | Test directory layout, pytest markers, fixtures, coverage floor, how to run subsets |
| [okf/batch.md](okf/batch.md) | parse_files(), parse_files_with_copybooks(), ProcessPoolExecutor, profiling |
| [okf/dialects.md](okf/dialects.md) | IBMEnterpriseCobol, DialectType enum, EXEC SQL/CICS/IMS support |
| [okf/conventions.md](okf/conventions.md) | Code style, error hierarchy, Cython fast-path pattern, import rules, vendoring |

## Refresh Protocol

When starting a session or explicitly asked to refresh the OKF:

1. Read `cobolparser/__init__.py` — check exported symbols against `okf/` files
2. `glob cobolparser/**/*.py` — identify new or removed files
3. For each changed subsystem, read the relevant source files and patch the corresponding `docs/okf/*.md`
4. Update the Navigation table above if subsystem files were added or removed
5. Commit: `git commit -m "docs(okf): refresh OKF — <brief description of what changed>"`

**Invariant:** OKF is the source of truth for structural knowledge.
Code is the source of truth for implementation detail.
When they conflict, trust the code and update the OKF.
```

- [ ] **Step 3: Verify**

```bash
grep -c "okf/lexer.md" docs/OKF.md
grep -c "Refresh Protocol" docs/OKF.md
grep -c "Pipeline Overview" docs/OKF.md
```

Expected: each returns `1`.

- [ ] **Step 4: Commit**

```bash
git add docs/OKF.md docs/okf/
git commit -m "docs(okf): add OKF master index"
```

---

### Task 2: Create `docs/okf/lexer.md`

**Files:**
- Create: `docs/okf/lexer.md`
- Reference (read only): `cobolparser/lexer.py`, `cobolparser/_lexer_fast.pyx`

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces: lexer subsystem reference used by Task 4 (parser.md) cross-links

- [ ] **Step 1: Write `docs/okf/lexer.md`**

```markdown
# Lexer
> Tokenizes COBOL source text into a flat `List[Token]` with full column-layout awareness.

## Files

| File | Purpose |
|------|---------|
| `cobolparser/lexer.py` | Pure-Python `CobolLexer`, `Token` dataclass, `TokenType` IntEnum (100+ types), `LexerError`, `tokenize_cobol()` helper |
| `cobolparser/_lexer_fast.pyx` | Cython subclass of `CobolLexer`; overrides hot-path methods (`check_division_header`, `read_word_from_text`, `tokenize_program_text`) with C-typed implementations |

## Key Classes / Functions

| Name | Location | Description |
|------|----------|-------------|
| `CobolLexer` | `lexer.py` | Main lexer class; instantiated with source text; call `.tokenize()` |
| `Token` | `lexer.py` | Dataclass: `type: TokenType`, `value: str`, `line: int`, `column: int` |
| `TokenType` | `lexer.py` | `IntEnum` with 100+ members covering every COBOL keyword, literal type, and punctuation |
| `LexerError` | `lexer.py` | Raised on unrecoverable tokenization errors; extends `ParseError` |
| `tokenize_cobol()` | `lexer.py` | Convenience wrapper: `tokenize_cobol(text) -> List[Token]` |
| `CobolLexer` (Cython) | `_lexer_fast.pyx` | Subclass replacing inner loops with C-typed code; transparent drop-in |

## Data Flow / Lifecycle

1. Caller passes preprocessed free-form COBOL text (columns 1–6 and 73–80 already stripped by `normalize_fixed_format`).
2. `CobolLexer(text)` stores the text; no parsing yet.
3. `.tokenize()` iterates character-by-character:
   - Recognizes division/section/paragraph headers via `check_division_header()`
   - Reads words/identifiers via `read_word_from_text()`
   - Classifies each word against `TokenType` keyword table
   - Handles string literals (single-quoted and double-quoted), numeric literals, figurative constants (`ZERO`, `SPACE`, `HIGH-VALUE`, etc.)
   - Produces a `Token` for each meaningful unit; skips whitespace (not emitted)
4. Returns `List[Token]` — the input to `TokenStream` in `cobolparser/core/token_stream.py`.

**Cython fast-path:** If `cobolparser._lexer_fast` is importable (compiled via `python setup.py build_ext --inplace`), the module transparently replaces the pure-Python `CobolLexer` class. If not compiled or if `COBOLPARSER_SKIP_EXT=1` was set at install time, the pure-Python version is used unchanged. No caller code changes.

## Fixed-Format Column Layout (handled by preprocessor, not lexer)

| Columns | Purpose |
|---------|---------|
| 1–6 | Sequence number (ignored) |
| 7 | Indicator: space=code, `*`/`/`=comment, `-`=continuation |
| 8–11 | Area A (division/section/paragraph headers, level 01/77) |
| 12–72 | Area B (statements, subordinate data items) |
| 73–80 | Identification (ignored) |

The lexer receives text that has already been normalized to free-form; it does NOT handle fixed-format column layout itself.

## Public API (exported symbols)

```python
from cobolparser import CobolLexer, Token, TokenType
from cobolparser.lexer import LexerError, tokenize_cobol
```

## Gotchas / Invariants

- Comment lines (col 7 = `*` or `/`) must be stripped by `normalize_fixed_format()` BEFORE the lexer runs — if they reach the lexer, tokenization breaks.
- `TokenType` uses `IntEnum`, so tokens can be compared with `==` to either the enum member or its integer value.
- The Cython subclass is loaded transparently; never import `_lexer_fast` directly.
- Figurative constants (`ZERO`, `ZEROS`, `ZEROES`, `SPACE`, `SPACES`, `HIGH-VALUE`, `HIGH-VALUES`, `LOW-VALUE`, `LOW-VALUES`, `QUOTE`, `QUOTES`, `ALL`) are recognized as `TokenType` keywords, not literals.

## Refresh Checklist

- [ ] Count `TokenType` members in `lexer.py`; update "100+ types" if the count changed significantly
- [ ] Check for new methods on `CobolLexer` not listed in Key Classes
- [ ] Verify `_lexer_fast.pyx` still subclasses `CobolLexer` and overrides the same three methods
- [ ] Check `__init__.py` still exports `CobolLexer`, `Token`, `TokenType`
```

- [ ] **Step 2: Verify**

```bash
grep -c "CobolLexer" docs/okf/lexer.md
grep -c "TokenType" docs/okf/lexer.md
grep -c "Refresh Checklist" docs/okf/lexer.md
```

Expected: each returns at least `1`.

- [ ] **Step 3: Commit**

```bash
git add docs/okf/lexer.md
git commit -m "docs(okf): add lexer subsystem file"
```

---

### Task 3: Create `docs/okf/preprocessing.md`

**Files:**
- Create: `docs/okf/preprocessing.md`
- Reference (read only): `cobolparser/preprocess/__init__.py`, `cobolparser/preprocess/copybook_expander.py`, `cobolparser/preprocess/copy_statement_parser.py`, `cobolparser/preprocess/path_resolver.py`, `cobolparser/preprocess/models.py`, `cobolparser/_preprocess_fast.pyx`

**Interfaces:**
- Produces: preprocessing reference; cross-linked from `okf/parser.md`

- [ ] **Step 1: Write `docs/okf/preprocessing.md`**

```markdown
# Preprocessing
> Converts fixed-format COBOL to free-form text and optionally inlines COPY statements before lexing.

## Files

| File | Purpose |
|------|---------|
| `cobolparser/preprocess/__init__.py` | Module hub; exports preprocessing functions and exception hierarchy |
| `cobolparser/preprocess/copybook_expander.py` | Core copybook inlining engine with LRU file cache |
| `cobolparser/preprocess/copy_statement_parser.py` | Lexes COPY statements and applies REPLACING clauses |
| `cobolparser/preprocess/path_resolver.py` | Resolves copybook paths securely (prevents directory traversal) |
| `cobolparser/preprocess/models.py` | Data structures for copybook expansion |
| `cobolparser/_preprocess_fast.pyx` | Cython override of `normalize_fixed_format()` hot-path |

## Key Classes / Functions

| Name | Location | Description |
|------|----------|-------------|
| `normalize_fixed_format()` | `preprocess/__init__.py` | Converts fixed-format COBOL lines to free-form text string; drops comment lines |
| `preprocess_conditional_compilation()` | `preprocess/__init__.py` | Processes `>>IF` / `>>ELSE` / `>>END-IF` directives |
| `validate_copybook_content()` | `preprocess/__init__.py` | Validates a copybook file's content before expansion |
| `validate_level_numbers()` | `preprocess/__init__.py` | Checks level-number sequencing in data definitions |
| `strip_compiler_directives()` | `preprocess/__init__.py` | Strips IBM compiler directives before parsing |
| `expand_copybooks()` | `copybook_expander.py` | Expands COPY statements in source text; returns `CopybookExpansion` |
| `parse_cobol_with_expansion()` | `copybook_expander.py` | Full pipeline: expand + parse in one call |
| `clear_file_cache()` | `copybook_expander.py` | Clears the LRU file cache |
| `set_file_cache_size()` | `copybook_expander.py` | Sets max entries in the LRU cache |
| `get_file_cache_stats()` | `copybook_expander.py` | Returns hit/miss statistics for the file cache |
| `read_file_with_encoding()` | `copybook_expander.py` | Reads a file detecting encoding (UTF-8, EBCDIC, Latin-1) |
| `CopyStatementLexer` | `copy_statement_parser.py` | Tokenizes a COPY statement line |
| `apply_replacing_clauses()` | `copy_statement_parser.py` | Applies REPLACING text substitutions to copybook content |
| `normalize_continuation_lines()` | `copy_statement_parser.py` | Merges fixed-format continuation lines |
| `strip_sequence_area()` | `copy_statement_parser.py` | Removes columns 1–6 from a line |
| `remove_comment_lines()` | `copy_statement_parser.py` | Removes lines where column 7 is `*` or `/` |
| `PathResolver` | `path_resolver.py` | Resolves copybook names to filesystem paths within allowed directories |
| `normalize_path()` | `path_resolver.py` | Normalizes and canonicalizes a path |
| `validate_path_within_directory()` | `path_resolver.py` | Raises `PathTraversalError` if path escapes the allowed root |
| `get_available_copybooks()` | `path_resolver.py` | Lists all `.cpy`/`.CPY` files in the search path |
| `CopybookExpansion` | `models.py` | Result dataclass: `expanded_source`, `copy_statements`, `statistics` |
| `CopyStatement` | `models.py` | Parsed COPY statement: `name`, `library`, `replacing_clauses`, `suppress` |
| `CopybookSearchPath` | `models.py` | A directory to search for copybooks |
| `ExpansionContext` | `models.py` | Tracks nesting depth and visited copybooks during recursive expansion |
| `ExpansionStatistics` | `models.py` | Metrics: files_expanded, bytes_expanded, cache_hits, etc. |
| `ReplacingClause` | `models.py` | A single `REPLACING old BY new` pair |
| `SuppressClause` | `models.py` | Models `COPY … SUPPRESS` clause |

## Exception Hierarchy

```
PreprocessingError  (base, in preprocess/__init__.py)
  ├── CircularReferenceError    — copybook A copies B copies A
  ├── CopybookNotFoundError     — COPY name not found on any search path
  ├── PathTraversalError        — copybook path escapes allowed directories
  ├── EncodingError             — cannot detect or decode file encoding
  ├── NestingDepthError         — recursive COPY nesting too deep
  ├── CopybookSizeExceededError — file exceeds MAX_COPYBOOK_SIZE_BYTES
  └── CopybookSyntaxError       — copybook content fails validation
```

Constants in `models.py`: `MAX_COPYBOOK_SIZE_BYTES`, `MAX_TOTAL_EXPANSION_BYTES`

## Data Flow / Lifecycle

**Stage 1 — normalize_fixed_format:**
1. Input: raw COBOL source as `List[str]` (one line per element)
2. For each line, extract columns 8–72; skip if column 7 is `*` or `/`
3. Handle continuation lines (column 7 = `-`): strip leading whitespace and append to previous line
4. Join all lines and return a single free-form text string
5. Output: `str` ready for `CobolLexer`

**Stage 2 — expand_copybooks (optional):**
1. Input: free-form text + `copybook_paths: list[str]`
2. `CopyStatementLexer` scans for `COPY <name>` patterns
3. For each COPY statement:
   a. `PathResolver` finds the copybook file
   b. File read with encoding detection via `read_file_with_encoding()`
   c. Content cached in LRU cache
   d. REPLACING clauses applied via `apply_replacing_clauses()`
   e. Copybook content recursively expanded (circular reference detection via `ExpansionContext`)
4. Returns `CopybookExpansion` with fully expanded source text

## Public API (exported symbols)

```python
from cobolparser import expand_copybooks, parse_cobol_with_expansion, normalize_fixed_format
from cobolparser.preprocess import (
    PreprocessingError, CircularReferenceError, CopybookNotFoundError,
    PathTraversalError, validate_copybook_content, validate_level_numbers,
)
```

## Gotchas / Invariants

- `normalize_fixed_format()` must run before `CobolLexer` — the lexer has no fixed-format awareness.
- The LRU cache (`_cached_read_file`) caches file content by absolute path. Call `clear_file_cache()` in long-running processes to avoid stale content after file edits.
- `PathResolver` validates that resolved paths do not escape any of the specified `copybook_paths` directories. Symlinks are resolved before the check.
- Nesting depth is limited to prevent stack overflow on malformed inputs with circular COPY chains.
- `_preprocess_fast.pyx` overrides only `normalize_fixed_format()`; everything else remains pure Python.

## Refresh Checklist

- [ ] Check `preprocess/__init__.py` for new exported functions
- [ ] Verify `models.py` dataclass fields match documentation
- [ ] Check if new exception types were added to the exception hierarchy
- [ ] Verify `MAX_COPYBOOK_SIZE_BYTES` and `MAX_TOTAL_EXPANSION_BYTES` constants still exist in `models.py`
- [ ] Check `copybook_expander.py` for new cache management functions
```

- [ ] **Step 2: Verify**

```bash
grep -c "expand_copybooks" docs/okf/preprocessing.md
grep -c "CopybookExpansion" docs/okf/preprocessing.md
grep -c "PathTraversalError" docs/okf/preprocessing.md
```

Expected: each returns at least `1`.

- [ ] **Step 3: Commit**

```bash
git add docs/okf/preprocessing.md
git commit -m "docs(okf): add preprocessing subsystem file"
```

---

### Task 4: Create `docs/okf/parser.md`

**Files:**
- Create: `docs/okf/parser.md`
- Reference (read only): `cobolparser/parser.py`, `cobolparser/core/token_stream.py`, `cobolparser/core/registry.py`, `cobolparser/core/interfaces.py`, `cobolparser/core/ast_factory.py`, `cobolparser/core/exceptions.py`, `cobolparser/parsers/divisions/factory.py`, `cobolparser/parsers/divisions/procedure.py`, `cobolparser/parsers/statements/__init__.py`

**Interfaces:**
- Produces: parser reference cross-linked from `okf/ast-models.md`

- [ ] **Step 1: Write `docs/okf/parser.md`**

```markdown
# Parser
> Orchestrates division parsers and statement parsers to produce a `ParseResult` from a `List[Token]`.

## Files

| File | Purpose |
|------|---------|
| `cobolparser/parser.py` | `CobolParser` orchestrator; `parse_cobol()` convenience function |
| `cobolparser/core/token_stream.py` | `TokenStream` — navigable wrapper over `List[Token]` with lookahead |
| `cobolparser/core/registry.py` | `StatementParserRegistry` — first-match dispatch for statement parsers |
| `cobolparser/core/interfaces.py` | ABCs: `ITokenStream`, `IStatementParser`, `IDivisionParser`; `ParseContext` |
| `cobolparser/core/ast_factory.py` | `ASTNodeFactory` — centralized, validated AST node creation |
| `cobolparser/core/exceptions.py` | Structured exception types (imports `ParseError` from `_errors.py`) |
| `cobolparser/parsers/divisions/factory.py` | `DivisionParserFactory`, `DivisionType` enum |
| `cobolparser/parsers/divisions/base.py` | `BaseDivisionParser` abstract class |
| `cobolparser/parsers/divisions/identification.py` | `IdentificationDivisionParser` |
| `cobolparser/parsers/divisions/environment.py` | `EnvironmentDivisionParser` |
| `cobolparser/parsers/divisions/data.py` | `DataDivisionParser` |
| `cobolparser/parsers/divisions/procedure.py` | `ProcedureDivisionParser` + statement dispatch |
| `cobolparser/parsers/statements/_utils.py` | Shared clause utilities: `parse_condition_value()`, `parse_expression_operand()` |

## Statement Parser Files (26 parsers)

| File | Parsers |
|------|---------|
| `accept_parser.py` | `AcceptStatementParser` |
| `arithmetic_parsers.py` | `AddStatementParser`, `SubtractStatementParser`, `MultiplyStatementParser`, `DivideStatementParser`, `ComputeStatementParser` |
| `call_parser.py` | `CallStatementParser` |
| `close_parser.py` | `CloseStatementParser` |
| `delete_parser.py` | `DeleteStatementParser` |
| `display_parser.py` | `DisplayStatementParser` |
| `entry_parser.py` | `EntryStatementParser` |
| `evaluate_parser.py` | `EvaluateStatementParser` |
| `go_parser.py` | `GoStatementParser` |
| `ibm_exec_statements.py` | `ExecSqlStatementParser`, `ExecCicsStatementParser`, `ExecImsStatementParser` |
| `if_parser.py` | `IfStatementParser` |
| `initialize_inspect_parsers.py` | `InitializeStatementParser`, `InspectStatementParser` |
| `move_parser.py` | `MoveStatementParser` |
| `open_parser.py` | `OpenStatementParser` |
| `perform_parser.py` | `PerformStatementParser` |
| `read_parser.py` | `ReadStatementParser` |
| `rewrite_parser.py` | `RewriteStatementParser` |
| `search_parser.py` | `SearchStatementParser` |
| `set_parser.py` | `SetStatementParser` |
| `simple_statement_parsers.py` | `ContinueStatementParser`, `ExitStatementParser`, `GobackStatementParser`, `CancelStatementParser`, `AlterStatementParser`, `GenerateStatementParser`, `ReleaseStatementParser`, `ReturnStatementParser`, `UseStatementParser`, `CommitStatementParser`, `RollbackStatementParser` |
| `sort_merge_parsers.py` | `SortStatementParser`, `MergeStatementParser` |
| `start_parser.py` | `StartStatementParser` |
| `stop_parser.py` | `StopStatementParser` |
| `string_unstring_parsers.py` | `StringStatementParser`, `UnstringStatementParser` |
| `unlock_parser.py` | `UnlockStatementParser` |
| `write_parser.py` | `WriteStatementParser` |

## Key Classes / Functions

| Name | Location | Description |
|------|----------|-------------|
| `CobolParser` | `parser.py` | Top-level parser; `.parse(source, filename) -> ParseResult` |
| `ParseResult` | `parser.py` | Dataclass: `ast: CobolProgram`, `errors: list[ParseError]`, `warnings: list[str]`, `statistics: ParseStatistics`, `success: bool` |
| `parse_cobol()` | `parser.py` | `parse_cobol(source, filename="") -> ParseResult` convenience wrapper |
| `TokenStream` | `core/token_stream.py` | Wraps `List[Token]`; `peek(n=0)`, `consume()`, `expect(type)`, `match(type)`, `is_empty()`, `skip_whitespace_and_comments()`, `save_position()`, `restore_position()` |
| `StatementParserRegistry` | `core/registry.py` | Holds ordered list of `IStatementParser`; `find_parser(stream) -> IStatementParser \| None` (first-match) |
| `ITokenStream` | `core/interfaces.py` | ABC defining the token stream contract |
| `IStatementParser` | `core/interfaces.py` | ABC; implementors must define `parse(stream) -> CobolStatement` and `matches(stream) -> bool` |
| `IDivisionParser` | `core/interfaces.py` | ABC for division parsers |
| `ParseContext` | `core/interfaces.py` | Context object passed to nested statement parsers |
| `ASTNodeFactory` | `core/ast_factory.py` | `create_node(node_type, **fields)` creates and validates AST nodes |
| `get_factory()` | `core/ast_factory.py` | Returns the singleton `ASTNodeFactory` instance |
| `set_factory()` | `core/ast_factory.py` | Replaces the singleton (used in tests for mocking) |
| `create_node()` | `core/ast_factory.py` | Module-level shortcut: `create_node(type, **fields)` |
| `NodeTypeError` | `core/ast_factory.py` | Raised for unknown AST node types |
| `FieldValidationError` | `core/ast_factory.py` | Raised for invalid field values |
| `DivisionParserFactory` | `parsers/divisions/factory.py` | Selects the right division parser based on `DivisionType` |
| `DivisionType` | `parsers/divisions/factory.py` | Enum: `IDENTIFICATION`, `ENVIRONMENT`, `DATA`, `PROCEDURE` |

## Exception Hierarchy (core/exceptions.py)

```
ParseError  (canonical base — defined in cobolparser/_errors.py, re-exported here)
  ├── TokenMismatch          — unexpected token type encountered
  ├── UnexpectedEndOfInput   — stream exhausted before parsing completed
  ├── DivisionNotFoundError  — required division missing from source
  ├── UnknownStatementError  — no registered parser matched the token stream
  └── ValidationError        — AST validation failed
```

`ParseError` is defined in `_errors.py` (zero internal imports) to break the circular dependency between `plugins/core.py` and `core/exceptions.py`.

## Data Flow / Lifecycle

1. `CobolParser.parse(source)` calls `normalize_fixed_format(source.splitlines())` to get free-form text
2. `CobolLexer(text).tokenize()` returns `List[Token]`
3. `TokenStream(tokens)` wraps the list
4. `DivisionParserFactory.parse_divisions(stream)` iterates over `DivisionType` values:
   - Skips tokens until a division header keyword is found
   - Delegates to the appropriate division parser
5. `ProcedureDivisionParser` uses `StatementParserRegistry`:
   - Calls `registry.find_parser(stream)` for each statement position
   - The matching parser's `.parse(stream)` is called to consume tokens and return a node
6. Returns `ParseResult(ast=CobolProgram(...), errors=..., warnings=..., statistics=...)`

## Public API (exported symbols)

```python
from cobolparser import CobolParser, ParseResult, parse_cobol, ErrorRecoveryMode, MemoryConfiguration
from cobolparser.core import TokenStream, StatementParserRegistry, ASTNodeFactory
from cobolparser.core.exceptions import (
    ParseError, TokenMismatch, UnexpectedEndOfInput,
    DivisionNotFoundError, UnknownStatementError, ValidationError,
)
```

## Gotchas / Invariants

- `StatementParserRegistry` uses **first-match** dispatch: parser registration order matters. More specific parsers must be registered before more general ones.
- Every `IStatementParser.matches(stream)` must be non-destructive — it must not consume tokens, only peek.
- `ASTNodeFactory` is a singleton. Tests that need to inject a mock factory call `set_factory(mock)` and must restore afterward.
- `_errors.py` defines `ParseError` with zero imports to avoid circular dependency. Never import `ParseError` from `core.exceptions` in `plugins/core.py` — use `_errors.py` directly.
- `ParseResult.success` is `True` only when `ast is not None` AND `errors` is empty.

## Refresh Checklist

- [ ] Verify the list of statement parser files and exported classes against `parsers/statements/__init__.py`
- [ ] Check `DivisionType` enum values in `parsers/divisions/factory.py`
- [ ] Verify `TokenStream` method list against `core/token_stream.py`
- [ ] Check `ParseResult` fields against `parser.py` definition
- [ ] Check if any new exception types were added to `core/exceptions.py`
```

- [ ] **Step 2: Verify**

```bash
grep -c "StatementParserRegistry" docs/okf/parser.md
grep -c "DivisionParserFactory" docs/okf/parser.md
grep -c "IStatementParser" docs/okf/parser.md
```

Expected: each returns at least `1`.

- [ ] **Step 3: Commit**

```bash
git add docs/okf/parser.md
git commit -m "docs(okf): add parser subsystem file"
```

---

### Task 5: Create `docs/okf/ast-models.md`

**Files:**
- Create: `docs/okf/ast-models.md`
- Reference (read only): `cobolparser/models/ast_base.py`, `cobolparser/models/program.py`, `cobolparser/models/data_items.py`, `cobolparser/models/sql_statements.py`, `cobolparser/models/statements/`

**Interfaces:**
- Produces: AST model reference; cross-linked from `okf/analysis.md`

- [ ] **Step 1: Write `docs/okf/ast-models.md`**

```markdown
# AST Models
> The typed node hierarchy produced by parsing; every node extends `ASTNode` and implements `to_dict()`.

## Files

| File | Purpose |
|------|---------|
| `cobolparser/models/ast_base.py` | `ASTNode` abstract base, `SourceLocation`, `ASTValidator`, `ValidationResult` |
| `cobolparser/models/program.py` | Top-level program structure nodes |
| `cobolparser/models/data_items.py` | DATA DIVISION item nodes |
| `cobolparser/models/sql_statements.py` | EXEC SQL statement models |
| `cobolparser/models/statements/base.py` | `CobolStatement` abstract base and expression nodes |
| `cobolparser/models/statements/arithmetic.py` | Arithmetic statement nodes |
| `cobolparser/models/statements/call.py` | `CallStatement`, `EntryStatement`, `CallParameter` |
| `cobolparser/models/statements/control.py` | Control-flow statement nodes |
| `cobolparser/models/statements/data.py` | Data-manipulation statement nodes |
| `cobolparser/models/statements/io.py` | I/O statement nodes |
| `cobolparser/models/statements/misc.py` | Miscellaneous statement nodes |
| `cobolparser/_data_fast.pyx` | Cython acceleration for DATA DIVISION PICTURE/clause loops |

## Key Classes — Base

| Name | Location | Description |
|------|----------|-------------|
| `ASTNode` | `ast_base.py` | Abstract base; requires `to_dict() -> dict`; provides `to_json()`, `find_all_by_type(type_name)` |
| `SourceLocation` | `ast_base.py` | Dataclass: `line: int`, `column: int`, `length: int` |
| `ValidationResult` | `ast_base.py` | Dataclass: `is_valid: bool`, `errors: list[str]` |
| `ASTValidator` | `ast_base.py` | Validates an AST tree; `.validate(node) -> ValidationResult` |

## Key Classes — Program Structure

| Name | Location | Description |
|------|----------|-------------|
| `CobolProgram` | `program.py` | Root node: `divisions: list[CobolDivision]`, `program_id: str` |
| `CobolDivision` | `program.py` | A COBOL division: `name: str`, `sections: list[CobolSection]` |
| `CobolSection` | `program.py` | A section: `name: str`, `paragraphs: list[CobolParagraph]` |
| `CobolParagraph` | `program.py` | A paragraph: `name: str`, `statements: list[CobolStatement]` |

## Key Classes — Data Items

| Name | Location | Description |
|------|----------|-------------|
| `CobolDataItem` | `data_items.py` | A data definition: `level: int`, `name: str`, `picture: PictureClause`, `occurs: OccursClause`, `value`, `children` |
| `PictureClause` | `data_items.py` | Parsed PICTURE string: `pattern: str`, `category: DataCategory` |
| `OccursClause` | `data_items.py` | Array dimensions: `min_times`, `max_times`, `depending_on` |
| `ConditionNameItem` | `data_items.py` | Level-88 condition name: `name: str`, `values: list` |
| `RenamesItem` | `data_items.py` | Level-66 RENAMES entry |

## Key Classes — Statement Models

**base.py:**
| Name | Description |
|------|-------------|
| `CobolStatement` | Abstract base for all statements; has `location: SourceLocation` |
| `CobolExpression` | Abstract expression base |
| `ArithmeticExpression` | Arithmetic expression tree |
| `ConditionalExpression` | A boolean condition |
| `LogicalExpression` | AND/OR combination of conditions |
| `FunctionCall` | COBOL intrinsic function call |

**arithmetic.py:**
| Name | Description |
|------|-------------|
| `ArithmeticStatement` | Abstract base for arithmetic verbs |
| `AddStatement` | ADD … TO … (GIVING …) |
| `SubtractStatement` | SUBTRACT … FROM … |
| `MultiplyStatement` | MULTIPLY … BY … |
| `DivideStatement` | DIVIDE … INTO … |
| `ComputeStatement` | COMPUTE identifier = expression |

**call.py:**
| Name | Description |
|------|-------------|
| `CallStatement` | CALL with ON EXCEPTION/ON OVERFLOW handling |
| `EntryStatement` | ENTRY 'name' USING … |
| `CallParameter` | A single USING parameter with BY REFERENCE/CONTENT/VALUE |

**control.py:**
| Name | Description |
|------|-------------|
| `IfStatement` | IF condition THEN … ELSE … END-IF |
| `EvaluateStatement` | EVALUATE subject WHEN … END-EVALUATE |
| `WhenClause` | A WHEN arm in EVALUATE |
| `PerformStatement` | PERFORM paragraph / PERFORM VARYING / inline PERFORM |
| `GoStatement` | GO TO paragraph |
| `StopStatement` | STOP RUN / STOP literal |
| `SearchStatement` | SEARCH / SEARCH ALL |

**data.py:**
| Name | Description |
|------|-------------|
| `MoveStatement` | MOVE source TO destination(s) |
| `DisplayStatement` | DISPLAY items |
| `InitializeStatement` | INITIALIZE identifier |
| `InspectStatement` | INSPECT tallying/replacing/converting |
| `SetStatement` | SET identifier TO value |
| `StringStatement` | STRING … DELIMITED BY … INTO … |
| `UnstringStatement` | UNSTRING source INTO … |

**io.py:**
| Name | Description |
|------|-------------|
| `IOAcceptStatement` | ACCEPT identifier (FROM device) |
| `IOReadStatement` | READ file (INTO …) (AT END …) |
| `IOWriteStatement` | WRITE record (FROM …) |
| `IOOpenStatement` | OPEN mode file |
| `IOCloseStatement` | CLOSE file |
| `IODeleteStatement` | DELETE file RECORD |
| `IORewriteStatement` | REWRITE record |
| `IOStartStatement` | START file KEY IS … |
| `IOUnlockStatement` | UNLOCK file |

**misc.py:**
| Name | Description |
|------|-------------|
| `GobackStatement` | GOBACK |
| `CancelStatement` | CANCEL program |
| `AlterStatement` | ALTER paragraph TO PROCEED TO paragraph |
| `GenerateStatement` | GENERATE report |
| `ReleaseStatement` | RELEASE record |
| `ReturnStatement` | RETURN file |
| `UseStatement` | USE AFTER ERROR PROCEDURE |
| `SortStatement` | SORT file ON KEY … |
| `MergeStatement` | MERGE file ON KEY … |
| `CommitStatement` | COMMIT |
| `RollbackStatement` | ROLLBACK |
| `ContinueStatement` | CONTINUE |
| `ExitStatement` | EXIT (PROGRAM / PERFORM / SECTION) |
| `SelectStatement` | SELECT file ASSIGN TO device |
| `CopyStatement` | COPY copybook-name (structural, not the preprocessor) |

## SQL Models (`sql_statements.py`)

| Name | Description |
|------|-------------|
| `SQLStatementInfo` | Parsed SQL block: `statement_type`, `raw_sql`, `host_variables` |
| `SQLStatementType` | Enum: SELECT, INSERT, UPDATE, DELETE, DECLARE, FETCH, OPEN, CLOSE, EXECUTE, COMMIT, ROLLBACK, other |
| `ExecSQLStatement` | EXEC SQL … END-EXEC block node |
| `DeclareCursorStatement` | EXEC SQL DECLARE cursor CURSOR FOR … |
| `FetchStatement` | EXEC SQL FETCH cursor INTO … |
| `DynamicSQLStatement` | EXEC SQL EXECUTE (dynamic) |
| `TransactionControlStatement` | COMMIT / ROLLBACK inside EXEC SQL |
| `parse_exec_sql()` | Parses raw SQL text into `SQLStatementInfo` |

## `to_dict()` Contract

Every `ASTNode` subclass must implement `to_dict() -> dict`. Rules:
- Keys are snake_case strings
- `SourceLocation` serializes to `{"line": n, "column": n, "length": n}` (or `None`)
- Child nodes recursively call their own `to_dict()`
- Lists of children serialize to `list[dict]`
- `to_json()` (on `ASTNode` base) is `json.dumps(self.to_dict(), indent=2)`
- `find_all_by_type("MoveStatement")` does a depth-first search for nodes whose class name matches

## ASTNodeFactory

Use `ASTNodeFactory` (via `create_node()`) rather than instantiating nodes directly:

```python
from cobolparser.core import create_node
node = create_node("MoveStatement", source=..., destinations=[...], location=loc)
```

Raises `NodeTypeError` for unknown type names, `FieldValidationError` for invalid fields.

## Public API (exported symbols)

```python
from cobolparser import (
    CobolProgram, CobolDivision, CobolSection,
    CobolDataItem, PictureClause, OccursClause,
    MoveStatement, DisplayStatement, PerformStatement,
    CallStatement, IfStatement, EvaluateStatement,
)
from cobolparser.models.sql_statements import SQLStatementInfo, parse_exec_sql
```

## Gotchas / Invariants

- `ASTNode.to_dict()` is abstract — forgetting to implement it on a new node class causes a runtime error, not a type error.
- `find_all_by_type()` matches on class **name**, not class identity — string argument must match exactly.
- `_data_fast.pyx` accelerates DATA DIVISION parsing (picture clause and data item clause loops) but does not change the model classes — it only speeds up how `DataDivisionParser` populates them.
- Level-88 items (`ConditionNameItem`) are children of their parent `CobolDataItem`, not siblings.
- `WhenClause` contains a list of conditions; the last WHEN can be `WHEN OTHER`.

## Refresh Checklist

- [ ] Check `models/statements/` for any new statement node files or classes
- [ ] Verify `SQLStatementType` enum values against `sql_statements.py`
- [ ] Check `CobolDataItem` fields against `data_items.py`
- [ ] Check `ASTNode.to_dict()` signature — it must remain `-> dict`
- [ ] Verify `_data_fast.pyx` still exists and still accelerates the DATA DIVISION parser
```

- [ ] **Step 2: Verify**

```bash
grep -c "CobolProgram" docs/okf/ast-models.md
grep -c "to_dict" docs/okf/ast-models.md
grep -c "IOReadStatement" docs/okf/ast-models.md
```

Expected: each returns at least `1`.

- [ ] **Step 3: Commit**

```bash
git add docs/okf/ast-models.md
git commit -m "docs(okf): add ast-models subsystem file"
```

---

### Task 6: Create `docs/okf/analysis.md`

**Files:**
- Create: `docs/okf/analysis.md`
- Reference (read only): `cobolparser/analysis/__init__.py`, individual analyzer files

**Interfaces:**
- Produces: analyzer reference; cross-linked from `okf/cli.md`

- [ ] **Step 1: Write `docs/okf/analysis.md`**

```markdown
# Analysis
> 15 post-parse analyzers that extract structural insights from a `CobolProgram` AST.

All analyzers follow the pattern `Analyzer().analyze(ast) -> Report`, except `HostVariableResolver` which uses `.resolve(ast)`.

## Files

| File | Purpose |
|------|---------|
| `cobolparser/analysis/__init__.py` | Lazy-loaded exports for all analyzers |
| `cobolparser/analysis/coverage_analyzer.py` | Test coverage branch analysis |
| `cobolparser/analysis/test_plan.py` | Test plan generation from coverage map |
| `cobolparser/analysis/dead_code.py` | Unreferenced paragraph/section detection |
| `cobolparser/analysis/value_tracker.py` | Value flow for dynamic CALL target analysis |
| `cobolparser/analysis/program_flow.py` | Control flow graph: edges typed PERFORM/GO TO/CALL/fall-through |
| `cobolparser/analysis/io_logger.py` | I/O operation inventory |
| `cobolparser/analysis/io_sequence.py` | I/O sequence state-machine validation |
| `cobolparser/analysis/io_coverage_reporter.py` | I/O operation coverage reporting |
| `cobolparser/analysis/io_diagnostics.py` | I/O operation diagnostics |
| `cobolparser/analysis/move_type_checker.py` | MOVE statement type compatibility validation |
| `cobolparser/analysis/linkage_checker.py` | LINKAGE SECTION usage validation |
| `cobolparser/analysis/language_env_analyzer.py` | IBM Language Environment CALL detection |
| `cobolparser/analysis/host_var_resolver.py` | SQL host variable resolution |
| `cobolparser/analysis/crud_matrix.py` | File/table CRUD matrix generation |
| `cobolparser/analysis/ims_segment_analyzer.py` | IMS DLI call and segment analysis |

## Analyzer Reference

### DeadCodeAnalyzer
- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> DeadCodeReport`
- **Output:** `DeadCodeReport` with `dead_items: list[DeadCodeItem]`
- `DeadCodeItem`: `name: str`, `item_type: str` (paragraph/section), `location: SourceLocation`
- **What it finds:** Paragraphs and sections that are never referenced by PERFORM, GO TO, or CALL

### ProgramFlowAnalyzer
- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> ProgramFlowReport`
- **Output:** `ProgramFlowReport` with `nodes: list[FlowNode]`, `edges: list[FlowEdge]`, `cycle_details`, `range_members`
- `FlowEdge`: `source`, `target`, `edge_type: FlowEdgeType`
- `FlowEdgeType`: PERFORM, GO_TO, CALL, FALL_THROUGH
- `BranchNode`: a paragraph with multiple outgoing edges; includes `BranchArm` objects

### DynamicCallAnalyzer
- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> dict`
- **What it does:** Tracks MOVE and VALUE clauses to resolve possible values for identifier-based CALL targets

### IOLogger
- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> IOLogReport`
- **Output:** `IOLogReport` with `operations: list[IOOperation]`
- `IOOperation`: `verb`, `file_name`, `record_name`, `location`

### IOSequenceAnalyzer
- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> IOSequenceReport`
- **Output:** `IOSequenceReport` with `violations: list[IOSequenceViolation]`
- `IOSequenceViolation`: `kind: IOViolationKind`, `file_name`, `location`
- `IOViolationKind`: OPEN_BEFORE_READ, READ_BEFORE_OPEN, CLOSE_AFTER_CLOSE, etc.

### IOCoverageReporter
- **Input:** `CobolProgram` + test file references
- **Method:** `.analyze(ast)` — returns a coverage report dict
- Classifies each I/O operation by `CoverageStatus` (covered/uncovered/partial) and `TestType`

### IODiagnostics
- **Input:** `CobolProgram`
- **Method:** `.analyze(ast)` — returns diagnostics dict
- Reports malformed I/O patterns, mismatched OPEN/CLOSE, missing AT END clauses

### MoveTypeChecker
- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> MoveTypeReport`
- **Output:** `MoveTypeReport` with `violations: list[MoveTypeViolation]`
- `MoveTypeViolation`: `kind: MoveViolationKind`, `source_category: DataCategory`, `target_category: DataCategory`, `location`
- `DataCategory`: ALPHABETIC, ALPHANUMERIC, NUMERIC, NUMERIC_EDITED, ALPHANUMERIC_EDITED, NATIONAL, etc.
- `MoveViolationKind`: INCOMPATIBLE_CATEGORIES, TRUNCATION_RISK, etc.

### LinkageChecker
- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> LinkageReport`
- **Output:** `LinkageReport` with `violations: list[LinkageViolation]`
- `LinkageViolation`: `kind: LinkageViolationKind`, `name`, `location`
- `LinkageViolationKind`: UNDEFINED_IN_LINKAGE, NOT_PASSED_IN_CALL, etc.

### LanguageEnvironmentAnalyzer
- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> LEAnalysisResult`
- **Output:** `LEAnalysisResult` with `le_functions: list[LEFunctionUsage]`, `service_calls: list[LEServiceCall]`
- Detects CALL to IBM LE functions (CEE*, IGZEDT*, etc.)

### CRUDMatrixGenerator
- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> CRUDMatrix`
- **Output:** `CRUDMatrix` with `entries` (list of `FileEntry` or `TableEntry`), `.to_csv()`, `.to_json()`
- `CRUDFlags`: `create: bool`, `read: bool`, `update: bool`, `delete: bool`

### HostVariableResolver
- **Input:** `CobolProgram`
- **Method:** `.resolve(ast) -> HostVarResolutionReport`  ← note: `.resolve()` not `.analyze()`
- **Output:** `HostVarResolutionReport` with `variables: list[HostVariableInfo]`
- `HostVariableInfo`: `name`, `cobol_data_item`, `sql_usage_locations`

### IMSSegmentAnalyzer
- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> list[IMSDLICall]`
- **Output:** list of `IMSDLICall` objects with `function_code`, `pcb_name`, `segment_name`, `location`
- Also identifies `IMSEntryPoint` objects (ENTRY 'DLITCBL' USING)

### CoverageAnalyzer
- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> CoverageMap`
- **Output:** `CoverageMap` with `BranchPoint` objects per paragraph/section

### TestPlanGenerator
- **Input:** `CoverageMap`
- **Method:** `.generate(coverage_map) -> TestPlan`
- **Output:** `TestPlan` with test case specifications per branch type

## Top-Level Pipeline

```python
from cobolparser import generate_cobolcheck_tests
output = generate_cobolcheck_tests(source, strategies=["paragraph", "branch", "boundary"])
# Internally: CoverageAnalyzer → TestPlanGenerator → CobolCheckGenerator
```

## Public API (exported symbols)

```python
from cobolparser import (
    DeadCodeAnalyzer, ProgramFlowAnalyzer, IOLogger, IOSequenceAnalyzer,
    MoveTypeChecker, LinkageChecker, LanguageEnvironmentAnalyzer,
    CRUDMatrixGenerator, CoverageAnalyzer, TestPlanGenerator,
    generate_cobolcheck_tests,
)
from cobolparser.analysis import (
    IMSSegmentAnalyzer, HostVariableResolver, DynamicCallAnalyzer,
    IOCoverageReporter, IODiagnostics,
)
```

## Gotchas / Invariants

- `HostVariableResolver.resolve()` — not `.analyze()`. This is the only analyzer that deviates from the standard shape.
- Analyzers are stateless — create a new instance per program, or call `.analyze()` with a fresh AST each time.
- `DynamicCallAnalyzer` only tracks MOVE-to-identifier and literal VALUES — it does not execute the program, so results are conservative (may report multiple possible targets).
- `ProgramFlowAnalyzer` includes `range_members` for PERFORM … THRU ranges and `cycle_details` for detected control flow cycles.
- `CRUDMatrixGenerator` tracks file-level operations (OPEN/READ/WRITE/REWRITE/DELETE) as CRUD flags; it does NOT analyze SQL DML.

## Refresh Checklist

- [ ] Verify analyzer count in `analysis/__init__.py` — should be 15+
- [ ] Check `HostVariableResolver` still uses `.resolve()` not `.analyze()`
- [ ] Check `FlowEdgeType` enum values in `program_flow.py`
- [ ] Verify `generate_cobolcheck_tests()` is still exported from top-level `__init__.py`
- [ ] Check for new analyzer classes not listed above
```

- [ ] **Step 2: Verify**

```bash
grep -c "HostVariableResolver" docs/okf/analysis.md
grep -c "DeadCodeAnalyzer" docs/okf/analysis.md
grep -c "CRUDMatrix" docs/okf/analysis.md
```

Expected: each returns at least `1`.

- [ ] **Step 3: Commit**

```bash
git add docs/okf/analysis.md
git commit -m "docs(okf): add analysis subsystem file"
```

---

### Task 7: Create `docs/okf/cli.md`

**Files:**
- Create: `docs/okf/cli.md`
- Reference (read only): `cobolparser/cli/parse.py`, `cobolparser/cli/coverage.py`, `cobolparser/cli/__init__.py`

**Interfaces:**
- Produces: CLI reference for developers and Claude

- [ ] **Step 1: Write `docs/okf/cli.md`**

```markdown
# CLI
> `cobol-parser` — command-line interface to every parser feature.

## Files

| File | Purpose |
|------|---------|
| `cobolparser/cli/__init__.py` | Module hub; exports `main()` |
| `cobolparser/cli/parse.py` | All subcommand implementations |
| `cobolparser/cli/coverage.py` | IO coverage subcommand handlers |

## Entry Point

```
cobol-parser <subcommand> [options]
```

Registered as a `console_scripts` entry point in `setup.cfg`/`pyproject.toml`.

## Subcommands

### `parse <file.cbl> [json_path] [flags]`
Parse a single COBOL file and print the AST.

| Flag | Description |
|------|-------------|
| `--compact` | Compact JSON output (no indentation) |
| `--free-form` | Treat input as free-form (skip fixed-format normalization) |
| `--dialect ibm-enterprise` | Enable IBM Enterprise COBOL extensions |
| `--errors` | Print only errors, not the full AST |
| `--stats` | Print parse statistics |

Example:
```bash
cobol-parser parse examples/cobol/hello.cbl
cobol-parser parse examples/cobol/hello.cbl programs[0].program_id
cobol-parser parse examples/cobol/hello.cbl --dialect ibm-enterprise --stats
```

### `tokenize <file.cbl>`
Print token stream as JSON array of `{type, value, line, column}`.

```bash
cobol-parser tokenize src/PAYROLL.cbl
```

### `preprocess <file.cbl> [--define NAME[=VALUE]]`
Print preprocessed (fixed-format normalized) source text.

```bash
cobol-parser preprocess src/PAYROLL.cbl
cobol-parser preprocess src/PAYROLL.cbl --define DEBUG=1
```

### `expand <file.cbl> --copybook-path <dir> [--copybook-path <dir2>]`
Expand COPY statements inline and print the result.

```bash
cobol-parser expand src/PAYROLL.cbl --copybook-path ./copybooks
```

### `analyze <file.cbl>`
Print high-level program analysis (paragraphs, sections, data items, call graph).

```bash
cobol-parser analyze src/PAYROLL.cbl
```

### `dead-code <file.cbl>`
List paragraphs and sections that are never referenced.

```bash
cobol-parser dead-code src/PAYROLL.cbl
```

### `program-flow <file.cbl>`
Print control flow graph as JSON (nodes, edges, cycles).

```bash
cobol-parser program-flow src/PAYROLL.cbl
```

### `batch <file1.cbl> [file2.cbl ...] [--stats]`
Parse multiple files in parallel and print combined results.

```bash
cobol-parser batch src/*.cbl --stats
```

### `generate-tests <file.cbl> -o <output.cut>`
Generate CobolCheck test stubs from program structure.

```bash
cobol-parser generate-tests src/PAYROLL.cbl -o tests/PAYROLL.cut
```

### `io-sequence <file.cbl>`
Validate I/O operation sequencing (OPEN before READ, etc.).

```bash
cobol-parser io-sequence src/PAYROLL.cbl
```

### `move-type-check <file.cbl>`
Validate MOVE statement source/destination type compatibility.

```bash
cobol-parser move-type-check src/PAYROLL.cbl
```

### `linkage-check <file.cbl>`
Validate LINKAGE SECTION usage against CALL statements.

```bash
cobol-parser linkage-check src/PAYROLL.cbl
```

### `language-env <file.cbl>`
Detect IBM Language Environment function calls.

```bash
cobol-parser language-env src/PAYROLL.cbl
```

### `ims-dli <file.cbl>`
Analyze IMS DLI calls and entry points.

```bash
cobol-parser ims-dli src/PAYROLL.cbl
```

## Coverage Subcommands (`cli/coverage.py`)

These are wired into the CLI for IO coverage reporting:
- Analyze coverage status per I/O operation
- Output machine-readable JSON or human-readable markdown

## Gotchas / Invariants

- `--dialect ibm-enterprise` enables EXEC SQL, EXEC CICS, EXEC IMS DLI parsing and IBM data types (COMP-3, etc.). Without this flag, EXEC blocks may cause parse errors.
- `batch` uses `ProcessPoolExecutor` internally; on Windows, the calling script must be protected with `if __name__ == "__main__"` if calling programmatically.
- JSON path argument in `parse` uses dot notation and bracket notation: `programs[0].divisions[1].sections`.

## Refresh Checklist

- [ ] List all subcommands from `cli/parse.py`; add any new ones above
- [ ] Verify every flag for the `parse` subcommand
- [ ] Check if `coverage.py` added new subcommands
```

- [ ] **Step 2: Verify**

```bash
grep -c "ibm-enterprise" docs/okf/cli.md
grep -c "generate-tests" docs/okf/cli.md
grep -c "ims-dli" docs/okf/cli.md
```

Expected: each returns at least `1`.

- [ ] **Step 3: Commit**

```bash
git add docs/okf/cli.md
git commit -m "docs(okf): add CLI subsystem file"
```

---

### Task 8: Create `docs/okf/tests.md`

**Files:**
- Create: `docs/okf/tests.md`
- Reference (read only): `tests/conftest.py`, `tests/SAMPLE_TESTS_README.md`, `tests/integration/README.md`

**Interfaces:**
- Produces: test-suite reference

- [ ] **Step 1: Write `docs/okf/tests.md`**

```markdown
# Tests
> ~5,969 tests across 226 files in 5 directories; 81% line coverage floor.

## Files

| File | Purpose |
|------|---------|
| `tests/conftest.py` | Shared fixtures: `parser()`, `samples_dir()` |
| `tests/test_all_samples.py` | Smoke-test: every file in `tests/samples/` must parse without error |
| `tests/integration/test_shamrice_examples.py` | Parametrized: all `*.cbl` in `examples/cobol/shamrice/` must parse FAIL_FAST clean |

## Directory Map

```
tests/
  conftest.py                  ← shared fixtures
  test_all_samples.py          ← smoke-tests all sample programs
  unit/                        ← unit tests — no external I/O required
    analysis/                  ← tests for all 15 analyzers
    cli/                       ← CLI subcommand tests
    generators/                ← CobolCheck and flowchart generator tests
    io_statements/             ← I/O parser unit tests
  integration/                 ← end-to-end parsing tests
    test_shamrice_examples.py  ← all shamrice/*.cbl must parse clean
    io/                        ← IO coverage reporting integration
    io_statements/             ← IO statement parsing, VSAM
  contracts/                   ← API contract tests — stability guarantees
    io_statements/             ← IO statement contracts
  regression/                  ← backward compatibility tests
  performance/                 ← benchmarks (factory, parser)
  samples/                     ← shared COBOL test fixtures
    copybook_programs/         ← programs with COPY statements
    copybooks/                 ← copybook files (.CPY)
    io/                        ← IO test samples
      positive/                ← valid IO operations
      negative/                ← invalid IO patterns
```

## Sample & Example Programs

| Directory | Contents |
|-----------|----------|
| `tests/samples/` | ~48 COBOL programs covering all statement types |
| `examples/cobol/` | NIST COBOL-85 test suite (459 .CBL files + copybooks) |
| `examples/cobol/shamrice/` | 24 IBM COBOL programs (ACCEPT variants, COMP types, SEARCH, SORT/MERGE, SQL, JSON/XML GENERATE, sub-programs) |

## Pytest Markers

| Marker | Meaning | How to run |
|--------|---------|------------|
| `integration` | Integration / end-to-end tests | `pytest -m integration` |
| `slow` | Slow-running tests (benchmarks, large files) | `pytest -m slow` |
| `contract` | API contract tests | `pytest -m contract` |
| `io` | I/O statement tests | `pytest -m io` |

Note: `regression/` and `performance/` have no dedicated markers — run by directory path.

## Shared Fixtures (`tests/conftest.py`)

| Fixture | Returns | Description |
|---------|---------|-------------|
| `parser()` | `CobolParser` | Fresh parser instance with default config |
| `samples_dir()` | `pathlib.Path` | Absolute path to `tests/samples/` |

## Coverage Configuration

- **Tool:** `pytest-cov` with `--cov=cobolparser --cov-branch`
- **Floor:** `--cov-fail-under=81` (81% line coverage)
- **Report:** `--cov-report=html` generates `htmlcov/` directory
- Running a subset of tests (by marker, path, or name) will fail the coverage check — that is expected and normal.

## How to Run

```bash
# All tests
python -m pytest tests/ -v

# Single file
python -m pytest tests/unit/test_lexer.py -v

# Single test
python -m pytest tests/integration/test_call_comprehensive.py::TestCallComprehensive::test_call_with_periods -xvs

# By marker
python -m pytest -m integration
python -m pytest -m "io and not slow"

# By directory (no marker needed)
python -m pytest tests/regression/ -v
python -m pytest tests/performance/ -v

# With coverage
python -m pytest tests/ --cov=cobolparser --cov-report=html

# Stop on first failure, verbose
python -m pytest tests/ -x -v
```

## CI Matrix

GitHub Actions runs on Python 3.11, 3.12, and 3.13 for each of:
1. `ruff check .` + `black --check .`
2. `mypy cobolparser/`
3. `pytest tests/ -v` (with coverage)

## Gotchas / Invariants

- `test_shamrice_examples.py` uses `ErrorRecoveryMode.FAIL_FAST` — any parse error on those 24 programs is a CI failure.
- `test_all_samples.py` parametrizes over every `.cbl` / `.cob` file in `tests/samples/` via a glob fixture.
- The `performance/` directory contains benchmark programs, not correctness tests. They may be slow and are not in CI by default.

## Refresh Checklist

- [ ] Verify test count approximation (~5,969) by running `pytest --collect-only -q | tail -1`
- [ ] Check `conftest.py` for new fixtures
- [ ] Verify coverage floor (`--cov-fail-under`) in `pytest.ini` or `pyproject.toml`
- [ ] Check for new test markers in `pyproject.toml` `[tool.pytest.ini_options]`
- [ ] Verify `examples/cobol/shamrice/` still has 24 `.cbl` files
```

- [ ] **Step 2: Verify**

```bash
grep -c "shamrice" docs/okf/tests.md
grep -c "cov-fail-under" docs/okf/tests.md
grep -c "conftest" docs/okf/tests.md
```

Expected: each returns at least `1`.

- [ ] **Step 3: Commit**

```bash
git add docs/okf/tests.md
git commit -m "docs(okf): add tests subsystem file"
```

---

### Task 9: Create `docs/okf/batch.md`

**Files:**
- Create: `docs/okf/batch.md`
- Reference (read only): `cobolparser/batch.py`, `cobolparser/profiling.py`

**Interfaces:**
- Produces: batch and profiling reference

- [ ] **Step 1: Write `docs/okf/batch.md`**

```markdown
# Batch & Profiling
> Parallel multi-file parsing and performance profiling utilities.

## Files

| File | Purpose |
|------|---------|
| `cobolparser/batch.py` | `parse_files()` and `parse_files_with_copybooks()` using `ProcessPoolExecutor` |
| `cobolparser/profiling.py` | `ProfilerContext` wraps any parse call with cProfile, tracemalloc, and optional psutil |

## Key Classes / Functions

| Name | Location | Description |
|------|----------|-------------|
| `parse_files()` | `batch.py` | `parse_files(paths: list[str \| Path]) -> list[BatchResult]` — parallel parsing |
| `parse_files_with_copybooks()` | `batch.py` | `parse_files_with_copybooks(paths, copybook_paths=[]) -> list[BatchResult]` |
| `BatchResult` | `batch.py` | Dataclass: `path: str`, `result: ParseResult \| None`, `read_error: str \| None`, `profiling: ProfilingResult \| None` |
| `ProfilerContext` | `profiling.py` | Context manager: wraps a parse call; `.result` is `ProfilingResult` after exit |
| `ProfilingResult` | `profiling.py` | Dataclass: `wall_clock_s`, `cpu_user_s`, `cpu_system_s`, `memory_peak_mb`, `top_functions: list[FunctionProfile]` |
| `FunctionProfile` | `profiling.py` | Dataclass: `function_name`, `filename`, `call_count`, `total_time_s`, `per_call_s` |

## Data Flow / Lifecycle

**Batch parsing:**
1. `parse_files(paths)` distributes file paths across a `ProcessPoolExecutor` (default: `os.cpu_count() - 1` workers)
2. Each worker calls `parse_cobol(source, filename)` on its assigned file
3. Results collected into `list[BatchResult]`; files that fail to read get `read_error` populated instead of `result`
4. Executor can be reused across repeated calls (pass an existing executor as `executor=`) to avoid startup overhead

**With copybooks:**
- `parse_files_with_copybooks(paths, copybook_paths=["/path/to/copybooks"])` runs `parse_cobol_with_expansion()` per file instead of plain `parse_cobol()`

**Profiling:**
```python
from cobolparser.profiling import ProfilerContext

with ProfilerContext() as prof:
    parse_cobol(source)

result = prof.result   # ProfilingResult
print(result.wall_clock_s, result.memory_peak_mb)
for fn in result.top_functions[:10]:
    print(fn.function_name, fn.total_time_s)
```

## Public API (exported symbols)

```python
from cobolparser import parse_files
from cobolparser.batch import parse_files_with_copybooks, BatchResult
from cobolparser.profiling import ProfilerContext, ProfilingResult, FunctionProfile
```

## Gotchas / Invariants

- On Windows, code that calls `parse_files()` must be inside `if __name__ == "__main__":` (or a function called from there) because `ProcessPoolExecutor` spawns new Python processes.
- `BatchResult.result` is `None` when `read_error` is set; always check `read_error` first.
- `ProfilingResult.cpu_user_s` requires the `profiling` extra (`pip install -e ".[profiling]"`) which installs `psutil`. Without it, CPU time fields are `0.0`.
- File content is cached across batch calls (LRU cache in `batch.py`); this speeds up repeated parses of the same files but means stale content may be used if files change between calls.

## Refresh Checklist

- [ ] Verify `BatchResult` fields against `batch.py`
- [ ] Check `ProfilingResult` fields — new metrics may have been added
- [ ] Verify `parse_files_with_copybooks` signature in `batch.py`
- [ ] Check if `psutil` requirement changed (still in `[profiling]` extra only)
```

- [ ] **Step 2: Verify**

```bash
grep -c "ProcessPoolExecutor" docs/okf/batch.md
grep -c "ProfilingResult" docs/okf/batch.md
grep -c "BatchResult" docs/okf/batch.md
```

Expected: each returns at least `1`.

- [ ] **Step 3: Commit**

```bash
git add docs/okf/batch.md
git commit -m "docs(okf): add batch and profiling subsystem file"
```

---

### Task 10: Create `docs/okf/dialects.md`

**Files:**
- Create: `docs/okf/dialects.md`
- Reference (read only): `cobolparser/dialects/ibm_enterprise.py`, `cobolparser/plugins/core.py`

**Interfaces:**
- Produces: dialect reference

- [ ] **Step 1: Write `docs/okf/dialects.md`**

```markdown
# Dialects & Configuration
> Dialect and plugin configuration that controls parser behavior.

## Files

| File | Purpose |
|------|---------|
| `cobolparser/dialects/ibm_enterprise.py` | `IBMEnterpriseCobol` class; `IBMDataType` enum |
| `cobolparser/dialects/__init__.py` | Exports `IBMEnterpriseCobol` |
| `cobolparser/plugins/core.py` | `ErrorRecoveryMode`, `DialectType`, `MemoryConfiguration`, `SerializationConfig`, `ParseStatistics`, `PluginManager`, exception types |
| `cobolparser/plugins/__init__.py` | Exports all plugin configuration classes |

## Key Classes / Functions

| Name | Location | Description |
|------|----------|-------------|
| `IBMEnterpriseCobol` | `dialects/ibm_enterprise.py` | Dialect handler enabling IBM extensions |
| `IBMDataType` | `dialects/ibm_enterprise.py` | Enum of IBM-specific data types |
| `DialectType` | `plugins/core.py` | Enum: `IBM_ENTERPRISE`, `ANSI_COBOL`, `MICRO_FOCUS` |
| `ErrorRecoveryMode` | `plugins/core.py` | Enum: `FAIL_FAST` (stop at first error), `COLLECT_ALL` (accumulate all errors) |
| `MemoryConfiguration` | `plugins/core.py` | Dataclass: `max_memory_mb`, `enable_streaming`, `chunk_size_kb`, `max_error_count` |
| `SerializationConfig` | `plugins/core.py` | Dataclass: `include_metadata`, `include_source_locations`, `compact_format` |
| `ParseStatistics` | `plugins/core.py` | Dataclass: `lines_processed`, `tokens_processed`, `memory_peak_mb`, `parse_time_seconds` |
| `PluginManager` | `plugins/core.py` | Plugin registration and lifecycle management |
| `LexerError` | `plugins/core.py` | Lexer-level error (extends `ParseError`) |
| `UnterminatedStringError` | `plugins/core.py` | Unterminated string literal |
| `MemoryLimitExceededError` | `plugins/core.py` | Memory limit from `MemoryConfiguration.max_memory_mb` exceeded |

## IBM Enterprise COBOL Extensions

Enabled by passing `dialect=DialectType.IBM_ENTERPRISE` to `CobolParser` or by using `--dialect ibm-enterprise` on the CLI.

| Extension | Description |
|-----------|-------------|
| `COMP-3` / `PACKED-DECIMAL` | Binary-coded decimal storage |
| `COMP-1` | Single-precision floating point (4 bytes) |
| `COMP-2` | Double-precision floating point (8 bytes) |
| `COMP-4` / `BINARY` | Binary integer |
| `COMP-5` | Native binary (machine-dependent) |
| `POINTER` | Memory address type |
| `EXEC SQL … END-EXEC` | Embedded SQL blocks (parsed via `ExecSqlStatementParser`) |
| `EXEC CICS … END-EXEC` | CICS command blocks (parsed via `ExecCicsStatementParser`) |
| `EXEC IMS … END-EXEC` | IMS DLI call blocks (parsed via `ExecImsStatementParser`) |
| IBM intrinsic functions | `FUNCTION CURRENT-DATE`, `FUNCTION INTEGER-OF-DATE`, etc. |

## Configuring the Parser

```python
from cobolparser import CobolParser, ErrorRecoveryMode, MemoryConfiguration
from cobolparser.plugins import DialectType, SerializationConfig

# IBM dialect with error collection and memory limit
config = MemoryConfiguration(max_memory_mb=256)
parser = CobolParser(
    memory_config=config,
    error_recovery=ErrorRecoveryMode.COLLECT_ALL,
    dialect=DialectType.IBM_ENTERPRISE,
)
result = parser.parse(source)
```

## Public API (exported symbols)

```python
from cobolparser import ErrorRecoveryMode, MemoryConfiguration, DialectType, SerializationConfig
from cobolparser import IBMEnterpriseCobol
from cobolparser.plugins import PluginManager, ParseStatistics, LexerError, MemoryLimitExceededError
```

## Gotchas / Invariants

- `ErrorRecoveryMode.FAIL_FAST` raises immediately on the first error; `COLLECT_ALL` continues parsing and returns all errors in `ParseResult.errors`.
- Without `DialectType.IBM_ENTERPRISE`, `EXEC SQL` / `EXEC CICS` / `EXEC IMS` blocks will cause `UnknownStatementError`.
- `MemoryConfiguration.max_memory_mb` is checked during parsing; exceeding it raises `MemoryLimitExceededError`.
- `PluginManager` is for advanced extension; standard users only need `ErrorRecoveryMode` and `DialectType`.

## Refresh Checklist

- [ ] Verify `DialectType` enum values in `plugins/core.py`
- [ ] Check `IBMDataType` enum values in `dialects/ibm_enterprise.py`
- [ ] Verify `MemoryConfiguration` and `SerializationConfig` field names
- [ ] Check for new exception types in `plugins/core.py`
```

- [ ] **Step 2: Verify**

```bash
grep -c "IBMEnterpriseCobol" docs/okf/dialects.md
grep -c "ErrorRecoveryMode" docs/okf/dialects.md
grep -c "EXEC SQL" docs/okf/dialects.md
```

Expected: each returns at least `1`.

- [ ] **Step 3: Commit**

```bash
git add docs/okf/dialects.md
git commit -m "docs(okf): add dialects and configuration subsystem file"
```

---

### Task 11: Create `docs/okf/conventions.md`

**Files:**
- Create: `docs/okf/conventions.md`
- Reference (read only): `setup.py`, `pyproject.toml` or `setup.cfg`, `.pre-commit-config.yaml`

**Interfaces:**
- Produces: conventions reference

- [ ] **Step 1: Write `docs/okf/conventions.md`**

```markdown
# Conventions
> Code style, error hierarchy, Cython fast-path pattern, import rules, and vendoring.

## Code Style

| Tool | Config | Rules |
|------|--------|-------|
| **Black** | `pyproject.toml` | Line length 88, target `py311` |
| **Ruff** | `pyproject.toml` | pycodestyle (E/W), pyflakes (F), isort (I), bugbear (B), comprehensions (C4), pyupgrade (UP); **E501 ignored** |
| **mypy** | `pyproject.toml` | Strict: `disallow_untyped_defs`, `strict_equality`, `warn_return_any`; tests are **exempted** from typed def requirements |

Run locally:
```bash
python -m ruff check . --fix
python -m black .
python -m mypy cobolparser/
```

## Python Version

- Minimum: Python 3.11
- Tested: 3.11, 3.12, 3.13 (CI matrix)
- Modern syntax throughout: `list[T]` (not `List[T]`), `dict[K, V]`, `X | None` (not `Optional[X]`)

## Zero Runtime Dependencies

The core library (`cobolparser/`) has **no external dependencies**. This is a hard invariant.

- `[dev]` extra: pytest, pytest-cov, ruff, black, mypy, etc.
- `[fast]` extra: Cython, setuptools (for building `.pyx` extensions)
- `[profiling]` extra: `psutil` (imported lazily; library works without it)
- `[docs]` extra: documentation generation tools

Never add an `install_requires` entry to the package.

## Import Conventions

- `__init__.py` files may have unused imports (F401 ignored in ruff per-file config) — they re-export the public API
- Circular import guard: `ParseError` is defined in `cobolparser/_errors.py` (zero imports) rather than `core/exceptions.py` to break the cycle between `plugins/core.py` and `core/exceptions.py`
- Never import `ParseError` from `core/exceptions.py` inside `plugins/core.py` — always use `_errors.py`

## Error Hierarchy

```
ParseError  (cobolparser/_errors.py — zero internal imports)
  │
  ├── [core/exceptions.py]
  │     ├── TokenMismatch
  │     ├── UnexpectedEndOfInput
  │     ├── DivisionNotFoundError
  │     ├── UnknownStatementError
  │     └── ValidationError
  │
  ├── [plugins/core.py]
  │     ├── LexerError
  │     ├── UnterminatedStringError
  │     └── MemoryLimitExceededError
  │
  ├── [core/ast_factory.py]
  │     ├── NodeTypeError
  │     └── FieldValidationError
  │
  └── [preprocess/__init__.py]
        ├── PreprocessingError
        │     ├── CircularReferenceError
        │     ├── CopybookNotFoundError
        │     ├── PathTraversalError
        │     ├── EncodingError
        │     ├── NestingDepthError
        │     ├── CopybookSizeExceededError
        │     └── CopybookSyntaxError
```

## Cython Fast-Path Pattern

Three optional Cython modules accelerate hot paths:

| Module | File | Accelerates |
|--------|------|-------------|
| `cobolparser._lexer_fast` | `cobolparser/_lexer_fast.pyx` | `CobolLexer` inner loops |
| `cobolparser._preprocess_fast` | `cobolparser/_preprocess_fast.pyx` | `normalize_fixed_format()` |
| `cobolparser._data_fast` | `cobolparser/_data_fast.pyx` | DATA DIVISION PICTURE/clause loops |

**Rules:**
- `.pyx` source AND pre-generated `.c` files are **both checked into the repo** — builds do not require Cython to be installed
- Build in-place: `python setup.py build_ext --inplace`
- Skip entirely: `COBOLPARSER_SKIP_EXT=1 pip install -e ".[dev]"`
- Each Cython module subclasses or overrides the pure-Python counterpart — the pure-Python path is always the fallback
- Never import `_lexer_fast`, `_preprocess_fast`, or `_data_fast` directly; they are loaded transparently

## Vendoring

`cobolparser` is vendored into `backend/_vendor/cobol-parser/` — it is **never installed from PyPI** by the backend:

```bash
# After making changes to cobolparser/, sync to the backend vendor dir:
cp -r cobolparser/ ../backend/_vendor/cobol-parser/cobolparser/
```

This is a **manual step** — there is no auto-sync. Never edit the vendor copy directly.

## Pre-Commit Hooks (`.pre-commit-config.yaml`)

| Hook | Action |
|------|--------|
| `ruff` | `ruff check . --fix` |
| `ruff-format` | Ruff's built-in formatter |
| `black` | `black .` |
| `mypy` | `mypy cobolparser/ --ignore-missing-imports` |

Run all hooks: `pre-commit run --all-files`

## Adding a New Statement Parser

1. Create `cobolparser/parsers/statements/foo_parser.py` implementing `IStatementParser` (`parse()` + `matches()`)
2. Register it in `ProcedureDivisionParser` via `StatementParserRegistry`
3. Add `TokenType` entry in `lexer.py` if the verb is not already a keyword
4. Add AST node(s) in `cobolparser/models/statements/<category>.py` with `to_dict()`; use `create_node()` from `core/ast_factory.py`
5. Export the parser from `cobolparser/parsers/statements/__init__.py`
6. Export the AST node from `cobolparser/models/statements/__init__.py` and `cobolparser/models/__init__.py`

## Refresh Checklist

- [ ] Verify Black line length and target Python version in `pyproject.toml`
- [ ] Check ruff rule set for additions/removals
- [ ] Verify the error hierarchy — check `_errors.py`, `core/exceptions.py`, `plugins/core.py`, `preprocess/__init__.py`, `core/ast_factory.py` for new exception classes
- [ ] Confirm zero entries in `install_requires`
- [ ] Verify Cython module names are unchanged (`_lexer_fast`, `_preprocess_fast`, `_data_fast`)
- [ ] Check `.pre-commit-config.yaml` for hook changes
```

- [ ] **Step 2: Verify**

```bash
grep -c "ParseError" docs/okf/conventions.md
grep -c "COBOLPARSER_SKIP_EXT" docs/okf/conventions.md
grep -c "_vendor" docs/okf/conventions.md
```

Expected: each returns at least `1`.

- [ ] **Step 3: Commit**

```bash
git add docs/okf/conventions.md
git commit -m "docs(okf): add conventions subsystem file"
```

---

### Task 12: Final verification and single aggregate commit

**Files:**
- Verify: all 11 OKF files exist and cross-links work

**Interfaces:**
- Consumes: all 10 Tasks above (all files must exist)
- Produces: completed OKF

- [ ] **Step 1: Verify all files exist**

```bash
ls docs/OKF.md docs/okf/lexer.md docs/okf/preprocessing.md docs/okf/parser.md docs/okf/ast-models.md docs/okf/analysis.md docs/okf/cli.md docs/okf/tests.md docs/okf/batch.md docs/okf/dialects.md docs/okf/conventions.md
```

Expected: all 11 files listed, no errors.

- [ ] **Step 2: Verify cross-links in OKF.md**

```bash
grep -c "okf/lexer.md" docs/OKF.md
grep -c "okf/conventions.md" docs/OKF.md
```

Expected: each returns `1`.

- [ ] **Step 3: Verify each subsystem file has all required sections**

```bash
for f in docs/okf/*.md; do
  echo "=== $f ==="
  grep "^## " "$f"
done
```

Expected: each file contains `## Files`, `## Key Classes`, `## Data Flow`, `## Public API`, `## Gotchas`, `## Refresh Checklist` (or equivalent sections).

- [ ] **Step 4: Done**

All 11 OKF files are committed individually (Tasks 1–11). No aggregate commit needed.
Print confirmation:

```
OKF complete:
  docs/OKF.md           ← master index
  docs/okf/lexer.md
  docs/okf/preprocessing.md
  docs/okf/parser.md
  docs/okf/ast-models.md
  docs/okf/analysis.md
  docs/okf/cli.md
  docs/okf/tests.md
  docs/okf/batch.md
  docs/okf/dialects.md
  docs/okf/conventions.md
```
