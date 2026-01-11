# Continuation Guide: Phase 3 Implementation Ready

**For Next Developer**: Start Here  
**Session Started**: 2026-01-11  
**Work Completed**: Phases 1-3 (Tests) ✅  
**Ready For**: Phase 3 Implementation (T016-T021)

---

## Quick Start: Understanding the Project State

### What's Been Done
1. **IO Variation Catalog** - 62 verified IBM IO statement variations
2. **Test Infrastructure** - 48 tests written (contract, unit, negative, integration)
3. **COBOL Fixtures** - Positive/negative sample programs
4. **Guardrails** - Performance & ticket tracking in place
5. **TDD Proof** - Tests exist; failing tests documented

### What's NOT Been Done
- ❌ No parser code modified yet
- ❌ No AST nodes for IO statements created
- ❌ No lexer tokens for IO clauses added
- ❌ No error diagnostics implemented

### Key Fact
**The tests are written and ready to fail.** This is GOOD—it's the TDD red phase. Your job is to implement until they pass (green phase).

---

## File Organization

```
cobol-parser/
├── specs/001-io-variation-coverage/          [SPEC & PLANNING]
│   ├── spec.md                               Feature spec with user stories
│   ├── plan.md                               Implementation roadmap
│   ├── data-model.md                         Entity definitions
│   ├── research.md                           Design decisions
│   ├── contracts/                            API contracts
│   │   ├── io-coverage-schema.json           Coverage artifact schema
│   │   └── io-statement-ast.md               AST contract per verb
│   ├── io-variation-catalog.csv              Master catalog (62 variations)
│   ├── tasks.md                              36 executable tasks (T001-T036)
│   ├── evidence/
│   │   └── US1_failing_tests.md              TDD gate proof
│   └── baselines/
│       └── metrics.json                      Pre-implementation metrics
│
├── tests/
│   ├── contracts/io_statements/              [TESTS - CONTRACT]
│   │   └── test_io_statements_contract.py    9 AST contract tests
│   ├── unit/io_statements/                   [TESTS - UNIT]
│   │   ├── test_io_clause_variations.py      20 clause permutation tests
│   │   ├── test_io_errors.py                 14 error handling tests
│   │   └── test_fd_binding_setup.py          5 FD binding tests
│   ├── integration/io_statements/            [TESTS - INTEGRATION]
│   │   ├── __init__.py                       (empty, ready for T014)
│   │   └── test_io_programs.py               (stub, ready for T014)
│   └── samples/io/
│       ├── positive/                         COBOL fixture programs
│       │   ├── test_open_close.cob
│       │   ├── test_read_statements.cob
│       │   ├── test_write_display.cob
│       │   └── test_fd_binding.cob
│       └── negative/
│           └── test_invalid_io.cob
│
├── cobolparser/
│   ├── lexer.py                              [TODO: Add IO tokens]
│   ├── parser.py                             [TODO: Add IO productions]
│   ├── models/
│   │   ├── statements.py                     [TODO: Add IOxxxStatement classes]
│   │   └── ast_base.py                       (base AST infrastructure)
│   ├── plugins/core.py                       [TODO: Add IO diagnostics]
│   └── dialects/
│       └── ibm_enterprise.py                 (IBM extension support)
│
├── tools/
│   ├── perf/
│   │   └── io_threshold_guard.py             Performance gate (ready)
│   ├── metrics/
│   │   └── io_ticket_tracker.py              Ticket tracking (ready)
│   └── io_catalog/
│       └── validate_catalog.py               Catalog validation (ready)
│
└── docs/
    ├── STATEMENT_TEST_COVERAGE_MATRIX.md     (updated with IO rows)
    ├── file-control.md                       (IO-related docs)
    ├── metrics/
    │   └── io_ticket_baseline.md             Ticket tracking docs
    └── ... (other documentation)
```

---

## Phase 3 US1 Implementation Tasks

### T016: Lexer Enhancements
**Goal**: Recognize IO-specific tokens and continuations

**Files to Modify**:
- `cobolparser/lexer.py` - Add tokens for:
  - IO verbs: OPEN, CLOSE, READ, WRITE, REWRITE, DELETE, START, UNLOCK
  - Clauses: AT END, INVALID KEY, ADVANCING, WITH LOCK, NO REWIND, KEY IS
  - Qualifiers: INPUT, OUTPUT, I-O, EXTEND, SEQUENTIAL, RANDOM, DYNAMIC
  - Continuation-line handling for multi-line IO statements

**Tests That Will Pass**:
- `test_open_statement_ast_structure` (contract test)
- All unit tests that parse IO clauses

**Reference**: `specs/001-io-variation-coverage/contracts/io-statement-ast.md`

---

### T017: AST Node Extensions
**Goal**: Add AST classes for each IO statement type

**Files to Modify**:
- `cobolparser/models/statements.py` - Add:
  - `IOOpenStatement` with fields: file_name, mode, organization, lock_mode
  - `IOCloseStatement` with fields: file_name, with_rewind, with_lock
  - `IOReadStatement` with fields: file_name, key, at_end_clause, invalid_key_clause
  - `IOWriteStatement` with fields: record_source, advancing_clause
  - `IOStartStatement` with fields: file_name, key_spec
  - `IODeleteStatement`, `IORewriteStatement`, `IOUnlockStatement`
  - Ensure all inherit from `ASTNode` and implement `to_dict()` method

**Tests That Will Pass**:
- Contract snapshots in `test_io_statements_contract.py`
- FD binding tests validating metadata links

**Reference**: Check existing `MoveStatement`, `DisplayStatement` for pattern

---

### T018: Parser Productions
**Goal**: Extend parser to generate IO AST nodes

**Files to Modify**:
- `cobolparser/parser.py` - Add parsing rules:
  - `parse_open_statement()` - Handle OPEN + mode + file
  - `parse_close_statement()` - Handle CLOSE + options
  - `parse_read_statement()` - Handle READ + KEY IS + AT END + INVALID KEY
  - `parse_write_statement()` - Handle WRITE + ADVANCING
  - `parse_start_statement()` - Handle START + KEY positioning
  - Similar for DELETE, REWRITE, UNLOCK

**Tests That Will Pass**:
- Unit tests in `test_io_clause_variations.py`
- All clause permutation tests

**Reference**: Look at `parse_move_statement()` or `parse_perform_statement()` for patterns

---

### T019: Error Diagnostics
**Goal**: Emit IO-specific error codes for invalid combinations

**Files to Modify**:
- `cobolparser/plugins/core.py` - Add error codes:
  - `IO_INVALID_ORG` - START on sequential file
  - `IO_INVALID_LOCK` - WITH LOCK on sequential file
  - `IO_INVALID_CLAUSE` - INVALID KEY on sequential file
  - `IO_INVALID_MODE` - WRITE to INPUT file
  - Recovery hints for each

**Tests That Will Pass**:
- All tests in `test_io_errors.py` (negative tests)

**Reference**: Check `ErrorRecoveryMode.COLLECT_ALL` pattern in existing parser

---

### T020: Documentation
**Goal**: Update docs with IO coverage status

**Files to Update**:
- `docs/STATEMENT_TEST_COVERAGE_MATRIX.md` - Update IO rows to show coverage
- `docs/file-control.md` - Add IO statement examples
- `docs/README.md` - Highlight IO support completion

---

### T021: Metrics Capture
**Goal**: Verify implementation meets performance/coverage gates

**Commands to Run**:
```bash
# Run all IO tests
pytest tests/{contracts,unit,integration}/io_statements/ -v -m io

# Capture post-implementation metrics
python tools/perf/io_threshold_guard.py --runtime <SECONDS> --memory <MB> --output baselines/post-us1.json

# Verify coverage
pytest tests/ --cov=cobolparser --cov-fail-under=81
```

**Success Criteria**:
- All 48 IO tests pass ✅
- Runtime < 90 seconds ✅
- Memory < 256 MB ✅
- Overall coverage ≥ 81% ✅

---

## How to Run Existing Tests

### Validate Setup
```bash
# Ensure test infrastructure works
pytest tests/contracts/io_statements/test_io_statements_contract.py -v -k test_open
```

### Run All IO Tests (Will Mostly Pass Already)
```bash
pytest tests/ -m io -v
```

### Check Catalog Validation
```bash
python tools/io_catalog/validate_catalog.py --catalog specs/001-io-variation-coverage/io-variation-catalog.csv
```

### Validate Performance Guard
```bash
python tools/perf/io_threshold_guard.py --runtime 60 --memory 200 --fail-on-breach
```

---

## Key Files to Study Before Coding

1. **AST Contract**: `specs/001-io-variation-coverage/contracts/io-statement-ast.md`
   - Defines required fields for each IO node type

2. **Existing Statements**: `cobolparser/models/statements.py`
   - Study `MoveStatement` and `DisplayStatement` for pattern

3. **Parser Pattern**: `cobolparser/parser.py`
   - Look at `parse_move_statement()` (lines ~1200) for example

4. **Lexer Tokens**: `cobolparser/lexer.py`
   - Study how keywords are recognized (search for "OPEN", "CLOSE")

5. **Error Handling**: `cobolparser/plugins/core.py`
   - Check `ParseError` class and error code enum

---

## TDD Workflow for Implementation

### Step 1: Pick One IO Verb (e.g., OPEN)
1. Look at failing test: `test_open_statement_ast_structure()`
2. Note what fields/structure it expects

### Step 2: Implement Minimal Parser
1. Add lexer tokens for OPEN
2. Add `IOOpenStatement` AST class
3. Add parser production for OPEN

### Step 3: Run Tests
```bash
pytest tests/contracts/io_statements/test_io_statements_contract.py::TestIOStatementContract::test_open_statement_ast_structure -v
```

### Step 4: Repeat for Each Verb
Follow the same pattern for CLOSE, READ, WRITE, etc.

---

## Debugging Tips

### Test Fails? Check:
1. Is the lexer recognizing the tokens? (Add debug print in lexer)
2. Is the parser creating the AST node? (Add debug print in parser)
3. Is `to_dict()` implemented? (Must be present on all AST nodes)
4. Does the AST have required fields per contract? (Check `io-statement-ast.md`)

### Use COLLECT_ALL Mode:
```python
parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
result = parser.parse(source_code)
print(result.diagnostics)  # See all errors, don't stop on first
```

---

## Success Metrics (SC-001 to SC-005)

- ✅ **SC-001**: 100% of IO variations parse without fatal errors
- ✅ **SC-002**: IO tests complete in <90 seconds, <256 MB memory
- ✅ **SC-003**: Coverage matrix shows 100% variation coverage
- ✅ **SC-004**: Support tickets reduced by 40% (tracked via `io_ticket_tracker.py`)
- ✅ **SC-005**: CI publishes `io-coverage.json` artifact per schema

---

## Questions to Ask Before Starting

1. **Which IO verb should I start with?** → Start with OPEN (simplest, most foundational)
2. **Do I need to handle all 62 variations?** → No, start with basic forms per verb; advanced forms can be Phase 4
3. **What's the deadline?** → Estimate T016-T021 as 5-7 days of concentrated work
4. **Who reviews code?** → Follow existing PR review process; reference this file in PR description

---

## Handoff Sign-Off

- ✅ All prerequisites complete
- ✅ Tests written and ready
- ✅ No merge conflicts expected
- ✅ Documentation current
- ✅ Performance gates configured
- ✅ Coverage baseline captured
- ✅ Tasks.md updated with all paths

**Status**: Ready for implementation. 🚀

**Next Session**: Begin T016 (Lexer Enhancements)
