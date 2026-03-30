# Documentation Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update all live user-facing documentation to reflect the current codebase: 2,975 tests, 81%+ coverage enforced, removed BC aliases, batch parsing API, and 3+ months of unlogged changes.

**Architecture:** Four independent parallel tasks — one per doc cluster. Each task reads the relevant source files to verify accuracy, then edits the docs in place. No production code changes. Tasks can be dispatched simultaneously.

**Tech Stack:** Python (cobolparser source), Markdown, git

---

## Known Stale Content (pre-audit baseline)

| File | Issue |
|------|-------|
| `README.md` line 4 | Badge: `tests-618%20passing` → `tests-2975%20passing` |
| `README.md` line 5 | Badge: `coverage-57%2B%25%20parser-yellow` → `coverage-81%25%2B%20enforced-green` |
| `README.md` lines 9, 23, 49, 429, 948, 1078 | All say "618 tests" or "618 comprehensive tests" → 2,975 |
| `README.md` lines 460, 948 | "57%+ parser coverage" → "81%+ coverage enforced" |
| `README.md` line 396 | `get_division_by_name()` removed (BC-3); correct method is `get_division()` |
| `README.md` line 928 | `--cov-fail-under=90` → `--cov-fail-under=81` |
| `docs/README.md` line 33 | "618 tests with 90%+ coverage (target: 1,455 tests)" → "2,975 tests, 81%+ enforced" |
| `docs/README.md` lines 29–30 | Stats dated 2026-01-11: "27% of COBOL statements fully implemented (11/41)" |
| `docs/README.md` lines 63–68 | "Most Critical Gaps" lists arithmetic/IO/EVALUATE — all now implemented |
| `docs/README.md` lines 97, 119 | References deleted `.specify/memory/constitution.md` |
| `docs/README.md` line 120 | "618+ comprehensive tests" → "2,975+" |
| `docs/PARSER_INVOCATION_GUIDE.md` line 312 | `ParseState` enum — removed (BC-3) |
| `CHANGELOG.md` | Last entry v1.1.0 (2026-01-29); 3+ months of changes undocumented |

---

## File Map

**Modified only (no new files):**
- `README.md` — metric fixes, API fix, badge updates
- `CHANGELOG.md` — new version entries
- `docs/README.md` — metric fixes, remove dead links, update gaps section
- `docs/PARSER_INVOCATION_GUIDE.md` — remove `ParseState`, verify all API examples
- `docs/cookbook.md` — verify all import paths and API calls
- `docs/call-statements.md` — verify import paths and AST field names
- `docs/perform-statements.md` — verify import paths and AST field names
- `docs/sql-statements.md` — verify import paths and AST field names
- `docs/cics-ims-statements.md` — verify import paths and AST field names
- `docs/copy-statements.md` — verify import paths and AST field names
- `docs/complete-program.md` — verify end-to-end example still runs
- `docs/data-items.md` — verify data item AST field names
- `docs/file-control.md` — verify file control AST field names
- `docs/ibm-enterprise.md` — verify IBM dialect API
- `docs/copybook-expansion.md` — verify copybook API
- `docs/factory-api.md` — verify `ASTNodeFactory` / `get_factory()` / `create_node()` API
- `docs/factory-performance.md` — verify factory performance guidance
- `docs/factory-extension-guide.md` — verify extension API
- `docs/ibm-dialect-registration.md` — verify dialect registration API

---

## Task 1: README.md and CHANGELOG.md (Stream A)

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Read (source of truth): `cobolparser/models/program.py`, `cobolparser/__init__.py`

- [ ] **Step 1: Verify current `get_division` API signature**

  Run:
  ```bash
  grep -n "def get_division" cobolparser/models/program.py
  ```
  Expected: `def get_division(self, name: str)` at some line — confirms `get_division_by_name` is gone.

- [ ] **Step 2: Verify what `parse_files` / `BatchResult` exports exist**

  Run:
  ```bash
  grep -n "parse_files\|BatchResult" cobolparser/__init__.py
  ```
  Note the exact names for use in the CHANGELOG.

- [ ] **Step 3: Fix README.md badges (lines 4–5)**

  In `README.md`, replace:
  ```
  [![Tests](https://img.shields.io/badge/tests-618%20passing-green.svg)](#testing)
  [![Coverage](https://img.shields.io/badge/coverage-57%2B%25%20parser-yellow.svg)](#testing)
  ```
  With:
  ```
  [![Tests](https://img.shields.io/badge/tests-2975%20passing-green.svg)](#testing)
  [![Coverage](https://img.shields.io/badge/coverage-81%25%2B%20enforced-green.svg)](#testing)
  ```

- [ ] **Step 4: Fix README.md description line (line 9)**

  Replace:
  ```
  Built following Test-Driven Development (TDD) principles with comprehensive test coverage (618 tests, 57%+ parser coverage).
  ```
  With:
  ```
  Built following Test-Driven Development (TDD) principles with comprehensive test coverage (2,975 tests, 81%+ coverage enforced).
  ```

- [ ] **Step 5: Fix README.md feature bullets (lines 23 and 49)**

  Replace both occurrences of:
  ```
  - ✅ **TDD Compliant** - 618 comprehensive tests ensuring reliability
  ```
  With:
  ```
  - ✅ **TDD Compliant** - 2,975 comprehensive tests ensuring reliability
  ```

- [ ] **Step 6: Fix README.md API Reference — remove `get_division_by_name` (line 396)**

  Replace:
  ```python
  class CobolProgram(ASTNode):
      program_name: str
      author: str
      divisions: Dict[str, CobolDivision]
      source_location: SourceLocation

      def get_division_by_name(self, name: str) -> Optional[CobolDivision]
      def to_json(self, config: SerializationConfig) -> Dict[str, Any]
  ```
  With:
  ```python
  class CobolProgram(ASTNode):
      program_name: str
      author: str
      divisions: Dict[str, CobolDivision]
      source_location: SourceLocation

      def get_division(self, name: str) -> Optional[CobolDivision]
      def to_json(self, config: SerializationConfig) -> Dict[str, Any]
  ```

- [ ] **Step 7: Fix README.md Testing section (lines ~429–460)**

  Replace:
  ```
  The parser includes a comprehensive test suite with 618 tests organized by category:
  ```
  With:
  ```
  The parser includes a comprehensive test suite with 2,975 tests organized by category:
  ```

  Replace:
  ```
  - **Unit Tests (500+)**: Component-specific functionality testing including comprehensive parser coverage
  ```
  With:
  ```
  - **Unit Tests (2,000+)**: Component-specific functionality testing including comprehensive parser coverage
  ```

  Replace (line ~460):
  ```
  - **Parser**: 57%+ statement coverage with detailed AST generation testing (417/636 statements covered)
  ```
  With:
  ```
  - **Parser**: 81%+ coverage enforced across all modules
  ```

- [ ] **Step 8: Fix README.md coverage threshold in contributing example (line ~928)**

  Replace:
  ```bash
  python -m pytest tests/ --cov=cobolparser --cov-fail-under=90
  ```
  With:
  ```bash
  python -m pytest tests/ --cov=cobolparser --cov-fail-under=81
  ```

- [ ] **Step 9: Fix remaining "618 tests" occurrences in README.md**

  Search for any remaining occurrences:
  ```bash
  grep -n "618" README.md
  ```
  Replace each with 2,975 (or "2,900+" where rounded prose is used). Also replace "57%+ parser coverage" with "81%+ coverage enforced" wherever it appears.

- [ ] **Step 10: Add batch parsing to README.md API Reference**

  After the `tokenize_cobol()` section, add:
  ```markdown
  #### parse_files()
  Parallel multi-file batch parsing.

  ```python
  from cobolparser import parse_files, BatchResult

  results = parse_files(["a.cbl", "b.cbl", "c.cbl"])
  for r in results:
      print(r.filename, r.result.success)
  ```
  ```

- [ ] **Step 11: Write CHANGELOG entries**

  Prepend the following to `CHANGELOG.md` after the header (before `## [1.1.0]`):

  ```markdown
  ## [2.0.0] - 2026-03-30

  ### Breaking Changes

  - **BC-1**: Removed 9 IO statement backward-compatibility class aliases (use classes in `cobolparser.models.statements.io` directly)
  - **BC-2**: Removed legacy `file_name`/`record_name` field pairs from `IOReadStatement` and `IOWriteStatement` (use `file_identifier` and `record_identifier`)
  - **BC-3**: Removed `ParseState` export, `CobolAST` alias, `IOErrorCode`/`IODiagnosticHelper` re-exports, and `get_division_by_name()` compat alias (use `get_division()`)
  - **BC-4 – BC-6**: Same commit as BC-3 (see above)
  - **BC-7**: Removed `ProcedureParagraph` and `ProcedureSection` compatibility aliases (use `CobolParagraph` and `CobolSection`)
  - **BC-8**: Removed legacy `TokenStream.advance()` and `TokenStream.is_at_end`; fixed `skip_whitespace_and_comments`

  ### Removed

  - `StatementRegistry` dead code; benchmark migrated to `StatementParserRegistry` (DUP-6)
  - Root-level statement parsers replaced by `parsers/statements/` subpackage

  ### Refactored

  - Deduplicated `_skip_whitespace`, `_collect_clause_stmts`, `_get_context`, `_report_error`, `_try_parse_nested_statement` into shared `parsers/statements/_utils` (DUP-1–4)
  - Deduplicated `STATEMENT_TOKEN_TYPES`/`KEYWORDS` into `_utils` (DUP-5)
  - Extracted `_collect_until_condition_tokens`; merged `_parse_until_clause`/`_parse_until_conditional` (DUP-7)
  - Updated metadata handling to use lazy initialization

  ### Fixed

  - Resolved 6 critical parser edge cases causing silent data loss or crashes
  - Fixed fixed-format comment lines being incorrectly parsed as code

  ### Changed

  - License changed to MIT (copyright Samuel Dion)

  ## [1.3.0] - 2026-03-20

  ### Added

  - **Batch parsing**: `parse_files(paths)` for parallel multi-file parsing using multiprocessing; returns `List[BatchResult]`
  - `BatchResult` and `parse_files` exported from top-level `cobolparser` package
  - IO statement parsers: `OPEN`, `CLOSE`, `READ`, `WRITE`, `REWRITE`, `DELETE`, `START`
  - Advanced configuration options for ignored memory patterns and language server settings
  - Performance benchmark suite

  ### Fixed

  - `parse_cobol` exceptions now caught in worker to prevent batch abort
  - Level number matching uses pre-compiled regex pattern

  ```

- [ ] **Step 12: Commit Stream A changes**

  ```bash
  git add README.md CHANGELOG.md
  git commit -m "docs: update README badges/counts and add CHANGELOG entries for v1.3.0 and v2.0.0"
  ```

---

## Task 2: Docs Hub — docs/README.md, PARSER_INVOCATION_GUIDE.md, cookbook.md (Stream B)

**Files:**
- Modify: `docs/README.md`
- Modify: `docs/PARSER_INVOCATION_GUIDE.md`
- Modify: `docs/cookbook.md`
- Read (source of truth): `cobolparser/__init__.py`, `cobolparser/models/program.py`, `cobolparser/parsers/statements/`

- [ ] **Step 1: Check which statement parsers now exist**

  Run:
  ```bash
  ls cobolparser/parsers/statements/
  ```
  Note what's there (arithmetic, call, control, data, io, etc.) — used to update the "Most Critical Gaps" section.

- [ ] **Step 2: Fix docs/README.md — coverage stats section (lines 29–34)**

  Replace:
  ```markdown
  ### Current Coverage Status (2026-01-11)

  - **27%** of COBOL statements fully implemented (11/41)
  - **43%** of HIGH priority statements complete (11/24)
  - **618 tests** with 90%+ coverage (target: 1,455 tests)
  ```
  With:
  ```markdown
  ### Current Coverage Status (2026-03-30)

  - **2,975 tests** with 81%+ coverage enforced
  ```

- [ ] **Step 3: Fix docs/README.md — IO coverage section**

  The IO coverage numbers (64 IO variations, 40+ tests) may now be outdated. Check:
  ```bash
  python -m pytest tests/ -m io --co -q 2>/dev/null | tail -3
  ```
  Update the IO test count in the IO Coverage Status section accordingly.

- [ ] **Step 4: Remove docs/README.md "Most Critical Gaps" section (lines ~63–68)**

  Delete the entire "Most Critical Gaps" section:
  ```markdown
  ### Most Critical Gaps

  **HIGH Priority Missing**:
  1. Arithmetic: ADD, SUBTRACT, MULTIPLY, DIVIDE (75-65% program frequency)
  2. File I/O: OPEN, CLOSE, READ, WRITE, REWRITE, DELETE (60-85% frequency)
  3. Control Flow: EVALUATE, ACCEPT, INITIALIZE (60-70% frequency)

  **Next Steps**: See project tracking system for current implementation roadmap.
  ```
  These features are now implemented.

- [ ] **Step 5: Fix docs/README.md — remove Constitutional Principles section (lines ~95–107)**

  Delete the entire "Constitutional Principles" section:
  ```markdown
  ### Constitutional Principles

  All parser development follows principles defined in [`.specify/memory/constitution.md`](../.specify/memory/constitution.md):

  1. **Test-First Development (TDD)** - All features developed using red-green-refactor cycle
  2. **Code Quality Standards** - 90%+ test coverage, type hints, comprehensive documentation
  3. **Performance Requirements** - 10,000+ lines/sec parsing speed, configurable memory limits
  4. **User Experience Consistency** - Predictable APIs, clear error messages
  5. **IBM Enterprise COBOL Priority** - Dialect-specific features prioritized
  ```
  The file `.specify/memory/constitution.md` has been deleted.

- [ ] **Step 6: Fix docs/README.md — Related Resources section (lines ~119–120)**

  Remove the constitution line:
  ```markdown
  - **Constitution**: [../.specify/memory/constitution.md](../.specify/memory/constitution.md) - Project governance
  ```

  Replace:
  ```markdown
  - **Test Suite**: `../tests/` - 618+ comprehensive tests (unit, integration, contract)
  ```
  With:
  ```markdown
  - **Test Suite**: `../tests/` - 2,975+ comprehensive tests (unit, integration, contract)
  ```

- [ ] **Step 7: Fix docs/PARSER_INVOCATION_GUIDE.md — remove ParseState**

  Run:
  ```bash
  grep -n "ParseState" docs/PARSER_INVOCATION_GUIDE.md
  ```
  Find the `ParseState` enum definition/usage (around line 312) and remove it entirely. `ParseState` was removed in BC-3.

- [ ] **Step 8: Verify docs/PARSER_INVOCATION_GUIDE.md imports and API**

  Check all code blocks in the file for these removed symbols:
  ```bash
  grep -n "get_division_by_name\|CobolAST\|IOErrorCode\|IODiagnosticHelper\|StatementRegistry\|\.advance()\|\.is_at_end" docs/PARSER_INVOCATION_GUIDE.md
  ```
  Fix any occurrences found:
  - `get_division_by_name(name)` → `get_division(name)`
  - `CobolAST` → `CobolProgram`
  - Remove any `ParseState` usage

- [ ] **Step 9: Add batch parsing to docs/PARSER_INVOCATION_GUIDE.md**

  Find the "Advanced Features" section and add:
  ```markdown
  ### Batch / Multi-File Parsing

  ```python
  from cobolparser import parse_files, BatchResult

  paths = ["program1.cbl", "program2.cbl", "program3.cbl"]
  results = parse_files(paths)   # parallel, uses multiprocessing

  for r in results:
      if r.result.success:
          print(f"{r.filename}: {r.result.ast.program_name}")
      else:
          print(f"{r.filename}: FAILED — {r.result.errors[0].message}")
  ```
  ```

- [ ] **Step 10: Verify docs/cookbook.md imports and API calls**

  Run:
  ```bash
  grep -n "get_division_by_name\|CobolAST\|IOErrorCode\|ParseState\|StatementRegistry\|618\|57%" docs/cookbook.md
  ```
  Fix any stale references found using the same replacements as above.

- [ ] **Step 11: Commit Stream B changes**

  ```bash
  git add docs/README.md docs/PARSER_INVOCATION_GUIDE.md docs/cookbook.md
  git commit -m "docs: update docs hub — fix metrics, remove dead links, add batch parsing"
  ```

---

## Task 3: Statement Guides (Stream C)

**Files:**
- Modify: `docs/call-statements.md`, `docs/perform-statements.md`, `docs/sql-statements.md`, `docs/cics-ims-statements.md`, `docs/copy-statements.md`, `docs/complete-program.md`
- Read (source of truth): `cobolparser/models/statements/call.py`, `cobolparser/models/statements/control.py`, `cobolparser/models/statements/misc.py`, `cobolparser/models/statements/io.py`

- [ ] **Step 1: Audit all statement guides for removed symbols**

  Run:
  ```bash
  grep -rn "get_division_by_name\|CobolAST\|IOErrorCode\|IODiagnosticHelper\|ParseState\|StatementRegistry\|ProcedureParagraph\|ProcedureSection\|618\|57%" \
    docs/call-statements.md docs/perform-statements.md docs/sql-statements.md \
    docs/cics-ims-statements.md docs/copy-statements.md docs/complete-program.md
  ```
  Note every hit — each is a stale reference to fix.

- [ ] **Step 2: Verify CALL statement AST field names**

  Run:
  ```bash
  grep -n "class CallStatement\|called_program\|call_target\|parameters\|on_exception\|not_on_exception" cobolparser/models/statements/call.py | head -20
  ```
  Compare against examples in `docs/call-statements.md` and fix any field name mismatches.

- [ ] **Step 3: Verify PERFORM statement AST field names**

  Run:
  ```bash
  grep -n "class PerformStatement\|target\|times_count\|test_timing\|until_condition\|varying" cobolparser/models/statements/control.py | head -20
  ```
  Compare against examples in `docs/perform-statements.md` and fix any mismatches.

- [ ] **Step 4: Verify SQL/CICS/IMS statement AST field names**

  Run:
  ```bash
  grep -n "class.*Exec\|sql_text\|cics_command\|ims_command\|host_variables" cobolparser/models/statements/misc.py cobolparser/dialects/ibm_enterprise.py | head -20
  ```
  Compare against `docs/sql-statements.md` and `docs/cics-ims-statements.md`, fix mismatches.

- [ ] **Step 5: Verify COPY statement AST field names**

  Run:
  ```bash
  grep -n "class CopyStatement\|copybook_name\|replacing" cobolparser/models/statements/misc.py | head -10
  ```
  Compare against `docs/copy-statements.md`, fix mismatches.

- [ ] **Step 6: Verify complete-program.md end-to-end example**

  The complete program example is likely still valid structurally, but check for removed API references:
  ```bash
  grep -n "get_division_by_name\|CobolAST\|ParseState" docs/complete-program.md
  ```
  Replace `get_division_by_name(name)` with `get_division(name)` wherever found.

- [ ] **Step 7: Fix any stale import paths in statement guides**

  All statement model classes now live in `cobolparser.models.statements.*`. Check:
  ```bash
  grep -n "^from cobolparser\|^import cobolparser" docs/call-statements.md docs/perform-statements.md docs/sql-statements.md docs/cics-ims-statements.md docs/copy-statements.md docs/complete-program.md
  ```
  If any import from `cobolparser.models.statements` (the old single-file) rather than the subpackage, update accordingly. Verify the correct import path:
  ```bash
  grep -rn "class CallStatement" cobolparser/models/statements/
  ```

- [ ] **Step 8: Commit Stream C changes**

  ```bash
  git add docs/call-statements.md docs/perform-statements.md docs/sql-statements.md \
    docs/cics-ims-statements.md docs/copy-statements.md docs/complete-program.md
  git commit -m "docs: update statement guides — fix AST field names and removed API references"
  ```

---

## Task 4: Data & Factory Guides (Stream D)

**Files:**
- Modify: `docs/data-items.md`, `docs/file-control.md`, `docs/ibm-enterprise.md`, `docs/copybook-expansion.md`, `docs/factory-api.md`, `docs/factory-performance.md`, `docs/factory-extension-guide.md`, `docs/ibm-dialect-registration.md`
- Read (source of truth): `cobolparser/models/data_items.py`, `cobolparser/core/ast_factory.py`, `cobolparser/dialects/ibm_enterprise.py`, `cobolparser/preprocess/__init__.py`

- [ ] **Step 1: Audit all data & factory guides for removed symbols**

  Run:
  ```bash
  grep -rn "get_division_by_name\|CobolAST\|IOErrorCode\|ParseState\|StatementRegistry\|618\|57%" \
    docs/data-items.md docs/file-control.md docs/ibm-enterprise.md \
    docs/copybook-expansion.md docs/factory-api.md docs/factory-performance.md \
    docs/factory-extension-guide.md docs/ibm-dialect-registration.md
  ```
  Fix every stale reference found.

- [ ] **Step 2: Verify data item AST field names**

  Run:
  ```bash
  grep -n "class CobolDataItem\|level_number\|name\|picture\|value\|occurs\|redefines\|comp_type" cobolparser/models/data_items.py | head -20
  ```
  Compare against `docs/data-items.md` code examples and fix any field name mismatches.

- [ ] **Step 3: Verify ASTNodeFactory API**

  Run:
  ```bash
  grep -n "def get_factory\|def create_node\|class ASTNodeFactory" cobolparser/core/ast_factory.py | head -10
  ```
  Compare against `docs/factory-api.md`. The canonical usage is `get_factory()` / `create_node()` — fix any examples that instantiate AST nodes directly.

- [ ] **Step 4: Verify factory extension guide**

  Run:
  ```bash
  grep -n "IStatementParser\|IDivisionParser\|ITokenStream" cobolparser/core/interfaces.py | head -20
  ```
  Compare against `docs/factory-extension-guide.md` and fix any interface name mismatches.

- [ ] **Step 5: Verify IBM dialect registration API**

  Run:
  ```bash
  grep -n "class.*Dialect\|def register\|DialectType" cobolparser/dialects/ibm_enterprise.py cobolparser/plugins/core.py | head -20
  ```
  Compare against `docs/ibm-dialect-registration.md` and fix any discrepancies.

- [ ] **Step 6: Verify copybook expansion API**

  Run:
  ```bash
  grep -n "def expand_copybooks\|def normalize_fixed_format" cobolparser/preprocess/__init__.py | head -10
  ```
  Compare against `docs/copybook-expansion.md`. Fix any incorrect function names or signatures.

- [ ] **Step 7: Verify IBM enterprise docs**

  Run:
  ```bash
  grep -n "class.*IBM\|COMP.3\|EXEC SQL\|EXEC CICS\|intrinsic" cobolparser/dialects/ibm_enterprise.py | head -20
  ```
  Compare against `docs/ibm-enterprise.md`. Fix any class or feature names that don't match.

- [ ] **Step 8: Commit Stream D changes**

  ```bash
  git add docs/data-items.md docs/file-control.md docs/ibm-enterprise.md \
    docs/copybook-expansion.md docs/factory-api.md docs/factory-performance.md \
    docs/factory-extension-guide.md docs/ibm-dialect-registration.md
  git commit -m "docs: update data and factory guides — verify AST fields, factory API, dialect registration"
  ```

---

## Final Verification

After all four tasks complete:

- [ ] **Check for any remaining stale numbers**

  ```bash
  grep -rn "618\|57%" README.md docs/README.md docs/PARSER_INVOCATION_GUIDE.md docs/cookbook.md
  ```
  Expected: zero matches.

- [ ] **Check for any remaining dead links**

  ```bash
  grep -rn "constitution\.md\|get_division_by_name\|CobolAST\b\|ParseState\b\|StatementRegistry\b\|ProcedureParagraph\b\|ProcedureSection\b\|IOErrorCode\b\|IODiagnosticHelper\b" docs/ README.md CHANGELOG.md
  ```
  Expected: zero matches.
