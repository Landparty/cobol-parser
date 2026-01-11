# Implementation Tasks: Comprehensive CALL Statement Coverage

**Feature**: Ensure all variations of CALL statements are covered and tested by the parser for COBOL fixed format  
**Branch**: `001-call-statements-coverage`  
**Date**: January 11, 2026  
**Total Tasks**: 19 | **Total Duration**: 13-19 hours

**Status**: Ready for execution | **Input**: spec.md, plan.md, framework-baseline.md

---

## Phase 0: Research & Technology Decisions (2-3 hours)

**Goal**: Establish technical foundation by researching existing implementations and clarifying integration points  
**Input**: spec.md, framework-baseline.md  
**Output**: research.md document with 5 sections  
**Independent Test**: Generated research.md contains all 5 sections with verified findings

---

### Setup Tasks

- [ ] T001 Research: Verify lexer continuation support in cobolparser/lexer.py for column 7 hyphen handling

**Details**:
- Examine cobolparser/lexer.py (680 lines total)
- Cross-reference: framework-baseline.md Section 8
- Spec requirement: spec.md FR-011, FR-012
- Question: Is continuation already fully implemented?
- Output: research.md section "Continuation Line Handling"
- Time: 0.5 hours

---

- [ ] T002 Research: Confirm parser recursion depth limits for nested exception handlers

**Details**:
- Examine parser.py for recursion tracking
- Cross-reference: framework-baseline.md Section 9
- Spec clarification: spec.md Clarifications "nested statements depth"
- Question: Use existing limits or define new ones?
- Output: research.md section "Exception Handler Recursion"
- Time: 0.5 hours
- Depends: T001

---

- [ ] T003 Research: Document parameter mode semantics (REFERENCE, CONTENT, VALUE)

**Details**:
- Examine statements.py CallParameter class (lines 286-298)
- Cross-reference: framework-baseline.md Section 2
- Spec requirement: spec.md FR-003, FR-004
- Question: What does "BY CONTENT" mean in this implementation?
- Output: research.md section "Parameter Mode Definitions"
- Time: 0.5 hours
- Depends: T001

---

- [ ] T004 Research: Define MOVE tracking scope for dynamic CALL analysis

**Details**:
- Examine analysis/value_tracker.py (if exists)
- Cross-reference: framework-baseline.md Section 13
- Spec requirement: spec.md FR-015, FR-016
- Spec clarification: spec.md Clarifications "MOVE statements only"
- Question: Which MOVE statements should be tracked?
- Output: research.md section "Dynamic Call Value Tracking"
- Time: 0.5 hours
- Depends: T003

---

- [ ] T005 Research: Identify validation point for RETURNING/GIVING mutual exclusivity

**Details**:
- Examine parser.py parse_call_statement() (line 4444+)
- Cross-reference: framework-baseline.md Section 3
- Spec requirement: spec.md FR-006a
- Question: Validate at parse time or model time?
- Output: research.md section "RETURNING/GIVING Mutual Exclusivity"
- Time: 0.5 hours
- Depends: T004

---

### Phase 0 Validation

- [ ] T006 Consolidate: Create research.md with findings from T001-T005

**Details**:
- File: specs/001-call-statements-coverage/research.md
- Content: 5 sections from tasks T001-T005
- Include: Code citations, decision rationale, implementation impact
- Verify: All cross-references link to framework-baseline.md sections
- Time: 0.5 hours
- Depends: T005

---

## Phase 1: Design & API Contracts (3-4 hours)

**Goal**: Document data models, create API contracts, produce quickstart guide  
**Input**: spec.md, framework-baseline.md, research.md (from Phase 0)  
**Output**: data-model.md, contracts/ directory, quickstart.md  
**Independent Test**: All 3 output files exist, contracts are machine-readable, quickstart has 6 examples

---

### Design Tasks

- [ ] T007 Design: Document CallStatement data model with constraints

**Details**:
- File: specs/001-call-statements-coverage/data-model.md (new section "Entity: CallStatement")
- Reference: framework-baseline.md Section 2
- Spec source: spec.md (CallStatement definition)
- Addition: RETURNING/GIVING mutual exclusivity constraint (spec.md FR-006a)
- Include: Fields, methods, validation rules, serialization
- Time: 1 hour
- Depends: T006

---

- [ ] T008 Design: Document CallParameter data model and passing modes

**Details**:
- File: specs/001-call-statements-coverage/data-model.md (new section "Entity: CallParameter")
- Reference: framework-baseline.md Section 2 (lines 286-298)
- Spec source: spec.md (CallParameter definition)
- Clarify: Valid values for passing_mode = ["REFERENCE", "CONTENT", "VALUE"]
- Include: Default behavior, serialization format
- Time: 0.5 hours
- Depends: T007

---

- [ ] T009 Contract: Create call-statement-contract.md for CALL statement structure

**Details**:
- File: specs/001-call-statements-coverage/contracts/call-statement-contract.md
- Coverage: 6 CALL categories from spec.md user stories
- Input format: COBOL source samples for each variation
- Output format: to_dict() JSON structure
- Include: Static calls, dynamic calls, parameters, RETURNING/GIVING, exceptions, multi-line
- Time: 1 hour
- Depends: T008

---

- [ ] T010 Contract: Create exception-handlers-contract.md for exception clause structures

**Details**:
- File: specs/001-call-statements-coverage/contracts/exception-handlers-contract.md
- Coverage: spec.md US-4 Exception Handling (FR-007 through FR-010)
- Input format: COBOL source with ON EXCEPTION, NOT ON EXCEPTION, ON OVERFLOW
- Output format: Exception handler AST structure with statement lists
- Include: Single handler, multiple handlers, nested statements, END-CALL
- Time: 0.5 hours
- Depends: T009

---

- [ ] T011 Contract: Create parameter-modes-contract.md for parameter passing variations

**Details**:
- File: specs/001-call-statements-coverage/contracts/parameter-modes-contract.md
- Coverage: spec.md US-2 Parameter Passing Modes (FR-003, FR-004)
- Input format: COBOL source with BY REFERENCE, BY CONTENT, BY VALUE, defaults
- Output format: CallParameter array with passing_mode field for each
- Include: Single mode, mixed modes, default modes, edge cases
- Time: 0.5 hours
- Depends: T010

---

- [ ] T012 Guide: Create quickstart.md with 6 CALL examples

**Details**:
- File: specs/001-call-statements-coverage/quickstart.md
- Coverage: One example per user story (6 total)
- Examples:
  1. Basic CALL: `CALL "SUBPROG"` (US-1, FR-001)
  2. Parameters: `CALL "SUB" USING BY REFERENCE P1 BY VALUE P2` (US-2, FR-003)
  3. RETURNING: `CALL "CALC" RETURNING RESULT` (US-3, FR-005)
  4. Exceptions: `CALL "SUB" ON EXCEPTION DISPLAY "ERROR"` (US-4, FR-007)
  5. Multi-line: Continuation with hyphen in column 7 (US-5, FR-011)
  6. Dynamic: `MOVE "PROG" TO VAR CALL VAR` (US-6, FR-015)
- Format: COBOL source + AST JSON output for each
- Time: 1 hour
- Depends: T011

---

### Phase 1 Validation

- [ ] T013 Consolidate: Verify all Phase 1 outputs exist and cross-reference correctly

**Details**:
- Check files exist:
  - specs/001-call-statements-coverage/data-model.md (2 entities documented)
  - specs/001-call-statements-coverage/contracts/call-statement-contract.md
  - specs/001-call-statements-coverage/contracts/exception-handlers-contract.md
  - specs/001-call-statements-coverage/contracts/parameter-modes-contract.md
  - specs/001-call-statements-coverage/quickstart.md (6 examples)
- Verify: All files reference spec.md FRs correctly
- Verify: All contracts are machine-readable YAML/JSON format
- Time: 0.5 hours
- Depends: T012

---

## Phase 2: Implementation & Testing (8-12 hours)

**Goal**: Implement 10 development tasks with full test coverage per user story  
**Input**: spec.md, framework-baseline.md, research.md, data-model.md, contracts/  
**Output**: Enhanced cobolparser code, 6 test suites, coverage ≥90%  
**Independent Test**: All 6 user stories independently testable; coverage ≥90% on core modules

---

### Implementation Task I1: Add Mutual Exclusivity Validation

- [x] T014 [P] [US3] Implement RETURNING/GIVING mutual exclusivity check in parser

**Details**:
- **Spec**: FR-006a (Mutual Exclusivity validation)
- **File**: cobolparser/parser.py
- **Location**: parse_call_statement() method, lines 4510-4530 (RETURNING/GIVING parsing section)
- **Task**: After parsing both RETURNING and GIVING clauses, add validation:
  - If both clauses present: raise ParsingError with message "RETURNING and GIVING clauses are mutually exclusive"
  - If only one or neither: allow normally
- **Code pattern**: Reference AUDIT-IMPLEMENTATION-PLAN.md Part 3 for example
- **Verify**: Type hints correct, error message clear
- **Test file**: tests/unit/test_call_returning_giving.py::test_mutually_exclusive (task T018)
- **Time**: 1 hour
- **Depends**: T013 (T006 Phase 0 research on validation point)

---

### Implementation Task I2: Basic CALL Test Suite

- [x] T015 [P] [US1] Create test suite for basic CALL statement parsing

**Details**:
- **Spec**: FR-001, FR-002 (Basic CALL with literal/variable program names)
- **File**: tests/unit/test_call_basic_parsing.py (new file)
- **Test cases** (minimum 3):
  1. test_call_with_literal_program_name: `CALL "PROGRAM"` → CallStatement.called_program="PROGRAM", is_dynamic=False
  2. test_call_with_variable_program_name: `CALL WS-VAR` → CallStatement.called_program="WS-VAR", is_dynamic=True
  3. test_call_with_no_parameters: Both cases above with no USING clause → using_parameters=[]
- **Framework reference**: framework-baseline.md Section 11 (Test Patterns)
- **Setup**: Use pytest fixtures from test_call_statement_parsing.py (existing 4 baseline tests)
- **Coverage target**: ≥90% for CallStatement basic properties
- **Time**: 1.5 hours
- **Depends**: T013

---

### Implementation Task I3: Parameter Modes Test Suite

- [x] T016 [P] [US2] Create test suite for parameter passing modes

**Details**:
- **Spec**: FR-003, FR-004 (BY REFERENCE, BY CONTENT, BY VALUE modes)
- **File**: tests/unit/test_call_parameter_modes.py (new file)
- **Test cases** (minimum 5):
  1. test_by_reference_mode: `USING BY REFERENCE P1` → CallParameter.passing_mode="REFERENCE"
  2. test_by_content_mode: `USING BY CONTENT P2` → CallParameter.passing_mode="CONTENT"
  3. test_by_value_mode: `USING BY VALUE P3` → CallParameter.passing_mode="VALUE"
  4. test_default_mode: `USING P1 P2` (no explicit mode) → both default to "REFERENCE"
  5. test_mixed_modes: `USING BY REFERENCE P1 BY CONTENT P2 BY VALUE P3` → each retains specified mode
- **Framework reference**: framework-baseline.md Section 2 (CallParameter implementation)
- **Contract reference**: contracts/parameter-modes-contract.md
- **Coverage target**: ≥90% for CallParameter.passing_mode handling
- **Time**: 1.5 hours
- **Depends**: T013

---

### Implementation Task I4: RETURNING/GIVING Test Suite

- [ ] T017 [P] [US3] Create test suite for RETURNING/GIVING clauses

**Details**:
- **Spec**: FR-005, FR-006, FR-006a (RETURNING/GIVING capture and mutual exclusivity)
- **File**: tests/unit/test_call_returning_giving.py (new file)
- **Test cases** (minimum 5):
  1. test_returning_only: `CALL "FUNC" RETURNING WS-RESULT` → returning_parameter="WS-RESULT", giving_parameter=null
  2. test_giving_only: `CALL "FUNC" GIVING WS-OUTPUT` → giving_parameter="WS-OUTPUT", returning_parameter=null
  3. test_neither_clause: CALL with no RETURNING/GIVING → both null
  4. test_with_using_clause: Both clauses work with USING parameters
  5. test_mutually_exclusive: CALL with both RETURNING and GIVING → parser raises error
- **Framework reference**: framework-baseline.md Section 3 (Parser Implementation)
- **Contract reference**: contracts/call-statement-contract.md
- **Validation**: Test T014 implementation is verified here
- **Coverage target**: ≥90% for RETURNING/GIVING handling
- **Time**: 1.5 hours
- **Depends**: T014 (mutual exclusivity implementation must be complete first)

---

### Implementation Task I5: Exception Handling Test Suite

- [x] T018 [P] [US4] Create test suite for exception handling clauses

**Details**:
- **Spec**: FR-007, FR-008, FR-009, FR-010 (ON EXCEPTION, NOT ON EXCEPTION, ON OVERFLOW, END-CALL)
- **File**: tests/unit/test_call_exception_handling.py (new file)
- **Test cases** (minimum 5):
  1. test_on_exception_clause: `CALL "SUB" ON EXCEPTION MOVE "ERROR" TO STATUS` → on_exception contains MoveStatement
  2. test_not_on_exception_clause: `CALL "SUB" NOT ON EXCEPTION MOVE "OK" TO STATUS` → not_on_exception contains MoveStatement
  3. test_both_exception_clauses: Both ON EXCEPTION and NOT ON EXCEPTION present → both populated
  4. test_on_overflow_clause: `CALL "SUB" ON OVERFLOW DISPLAY "OVERFLOW"` → on_overflow contains DisplayStatement
  5. test_end_call_terminator: CALL with END-CALL → exception clauses properly bounded
- **Framework reference**: framework-baseline.md Section 5 (Exception Handler Parsing)
- **Contract reference**: contracts/exception-handlers-contract.md
- **Coverage target**: ≥90% for exception handler parsing
- **Time**: 2 hours
- **Depends**: T013

---

### Implementation Task I6: Fixed Format Compliance Test Suite

- [x] T019 [P] [US5] Create test suite for COBOL fixed format compliance

**Details**:
- **Spec**: FR-011, FR-012 (Multi-line CALL with continuation, columns 7-72)
- **File**: tests/unit/test_call_fixed_format.py (new file)
- **Test cases** (minimum 4):
  1. test_multiline_with_hyphen_continuation: CALL spanning multiple lines with `-` in column 7 → all parameters captured
  2. test_columns_8_72: CALL statements confined to columns 8-72 → parsed correctly
  3. test_literals_spanning_lines: String literals broken across lines with continuation → reassembled correctly
  4. test_comment_handling: CALL statements with inline comments (column 73+) → comments ignored
- **Framework reference**: framework-baseline.md Section 8 (Fixed Format Support)
- **Input**: Create test programs with actual fixed format columns
- **Lexer reference**: cobolparser/lexer.py (680 lines, handles column 7 continuation)
- **Coverage target**: ≥90% for fixed format continuation handling
- **Time**: 2 hours
- **Depends**: T013

---

### Implementation Task I7: Dynamic Call Tracking Test Suite

- [x] T020 [P] [US6] Create test suite for dynamic CALL analysis

**Details**:
- **Spec**: FR-015, FR-016 (Dynamic CALL value tracking from MOVE statements)
- **File**: tests/unit/test_call_dynamic_analysis.py (new file)
- **Test cases** (minimum 4):
  1. test_single_move_to_call: Single MOVE then CALL with same variable → value tracked
  2. test_multiple_moves_to_call: Multiple MOVE statements, pick latest → tracked correctly
  3. test_conditional_move_to_call: MOVE inside IF/EVALUATE, then CALL → handled correctly
  4. test_non_move_statements_ignored: INITIALIZE, COMPUTE, etc. before CALL → not tracked
- **Framework reference**: framework-baseline.md Section 2 (CallStatement.possible_values tracking)
- **Analysis reference**: cobolparser/analysis/ (if value_tracker exists)
- **Research**: Uses Phase 0 research task T004 findings on MOVE scope
- **Coverage target**: ≥90% for dynamic value tracking
- **Time**: 1.5 hours
- **Depends**: T013

---

### Implementation Task I8: Contract Tests

- [x] T021 [P] Expand contract test suite for CallStatement serialization

**Details**:
- **Spec**: FR-014, FR-022 (Serialization contracts, test coverage)
- **File**: tests/contracts/test_call_statement_contract.py (expand or create)
- **Test cases** (minimum 3):
  1. test_call_to_dict_output: CallStatement.to_dict() → JSON structure matches contract
  2. test_backward_compatibility: AST from old test cases → new code maintains structure
  3. test_exception_structures: Exception handler nested statements → serialized correctly
- **Framework reference**: framework-baseline.md Section 3 (to_dict() implementation)
- **Contract reference**: contracts/call-statement-contract.md
- **Validation**: Run against all 6 contract files from Phase 1
- **Time**: 1 hour
- **Depends**: T015, T016, T017, T018, T019, T020 (all implementation tasks must complete first)

---

### Implementation Task I9: Regression Tests

- [x] T022 Run regression test suite to verify baseline functionality

**Details**:
- **Spec**: FR-017 through FR-022 (Test Coverage commitment)
- **Command**: `pytest tests/unit/test_call_*.py -v --tb=short`
- **Verify**:
  - 4 baseline tests (test_call_statement_parsing.py) still pass ✓
  - 6 new test suites pass ✓
  - No mypy type errors: `mypy cobolparser/ --strict`
  - No ruff linting errors: `ruff check cobolparser/`
  - Black formatting: `black --check cobolparser/`
- **Framework reference**: framework-baseline.md Section 11 (Test Execution)
- **Regression criteria**: Zero test failures, zero new warnings
- **Time**: 1 hour
- **Depends**: T021 (all implementation complete)

---

### Implementation Task I10: Coverage Measurement

- [x] T023 Measure code coverage and validate ≥90% targets

**Details**:
- **Spec**: SC-002 (95%+ coverage requirement)
- **Target files**:
  - statements.py CallStatement class (lines 268-350): ≥95%
  - parser.py parse_call_statement function (line 4444+): ≥95%
  - All test files created (I2-I7): Collectively ≥90%
- **Command**: 
  ```bash
  pytest tests/unit/test_call_*.py -v \
    --cov=cobolparser.models.statements \
    --cov=cobolparser.parser \
    --cov-report=html \
    --cov-fail-under=90
  ```
- **Output**: htmlcov/index.html with coverage breakdown
- **Report**: Coverage summary showing per-function percentages
- **Framework reference**: AUDIT-IMPLEMENTATION-PLAN.md Part 8 (Validation Checklist)
- **Validation**: Must achieve ≥90% before Phase 2 is complete
- **Time**: 1 hour
- **Depends**: T022 (regression tests pass first)

---

## Phase 3: Polish & Cross-Cutting Concerns (1-2 hours)

**Goal**: Documentation updates, integration testing, final validation  
**Input**: All phases 0-2 complete  
**Output**: Updated docs, passing integration tests  
**Independent Test**: Full parser still works, documentation updated, git history clean

---

### Final Tasks

- [x] T024 Update documentation with CALL statement patterns and examples

**Details**:
- **File**: docs/call-statements.md
- **Updates**:
  - Add section: "CALL Statement in Fixed Format" (2 examples with multi-line handling)
  - Add section: "Parameter Passing Modes Explained" (reference modes table)
  - Add section: "Exception Handling Best Practices" (handler patterns, END-CALL usage)
  - Add section: "Dynamic CALL Analysis" (MOVE tracking limitations, MVP scope)
  - Reference: All 6 user stories from spec.md
- **Validation**: All links to spec.md and code work correctly
- **Time**: 1 hour
- **Depends**: T023

---

- [x] T025 Run full integration test suite

**Details**:
- **Spec**: FR-017 through FR-022 (Full integration validation)
- **Command**: `pytest tests/integration/ -v --tb=short`
- **Verify**:
  - test_call_comprehensive.py passes (existing tests)
  - test_call_real_world_patterns.py passes (new acceptance tests if created)
  - Full COBOL programs parse without regression
- **Regression check**: Parse existing test programs (e.g., test_program.cob)
- **Framework reference**: framework-baseline.md Section 11 (Integration Testing)
- **Time**: 1 hour
- **Depends**: T024

---

- [x] T026 Final validation: Verify all success criteria met

**Details**:
- **Checklist** (all 8 must be ✓):
  - [ ] SC-001: 6 explicit CALL variations tested (US1-US6 from spec.md)
  - [ ] SC-002: ≥90% code coverage on CallStatement and parse_call_statement (from T023)
  - [ ] SC-003: Backward compatibility maintained (T022 regression tests)
  - [ ] SC-004: Fixed format handling verified (T019, T025)
  - [ ] SC-005: Exception handler parsing works (T018)
  - [ ] SC-006: Parameter modes captured correctly (T016)
  - [ ] SC-007: Dynamic CALL tracking functional (T020)
  - [ ] SC-008: RETURNING/GIVING mutual exclusivity enforced (T017)
- **Report**: success-criteria-validation.md with evidence for each
- **Time**: 0.5 hours
- **Depends**: T025

---

- [x] T027 Commit final changes to git with clean history

**Details**:
- **Commit structure**:
  1. `feat: add mutual exclusivity validation for RETURNING/GIVING (FR-006a)` (T014)
  2. `test: add basic CALL parsing test suite (FR-001, FR-002)` (T015)
  3. `test: add parameter modes test suite (FR-003, FR-004)` (T016)
  4. `test: add RETURNING/GIVING test suite (FR-005, FR-006)` (T017)
  5. `test: add exception handling test suite (FR-007 through FR-010)` (T018)
  6. `test: add fixed format compliance test suite (FR-011, FR-012)` (T019)
  7. `test: add dynamic call tracking test suite (FR-015, FR-016)` (T020)
  8. `test: expand contract test suite (FR-014, FR-022)` (T021)
  9. `docs: update call-statements.md with new patterns and examples` (T024)
  10. `docs: add success criteria validation and final checklist` (T026)
- **Verify**: Each commit passes its related tests
- **Branch**: 001-call-statements-coverage
- **Time**: 0.5 hours
- **Depends**: T026

---

## Task Dependency Graph

```
Phase 0 Research:
  T001 → T002 → T003 → T004 → T005 → T006 ✓

Phase 1 Design:
  T006 → T007 → T008 → T009 → T010 → T011 → T012 → T013 ✓

Phase 2 Implementation:
  T013 → ┬─ T014 (I1: Mutual Exclusivity) ──────────┐
         ├─ T015 (I2: Basic CALL) ────────┐         │
         ├─ T016 (I3: Parameters) ────────┤─ T017  │
         ├─ T018 (I4: Exceptions) ────────┤  [P]   │
         ├─ T019 (I5: Fixed Format) ──────┤  [P]   ├─ T021 ─→ T022 ─→ T023 ✓
         ├─ T020 (I6: Dynamic) ──────────┤  [P]   │
         └─────────────────────────────┬──┘        │
                                       └───────────┘

Phase 3 Polish:
  T023 → T024 → T025 → T026 → T027 ✓
```

**Key Notes**:
- [P] = Parallelizable tasks (T015-T020 can run in parallel after T013)
- T014 must complete before T017 (mutual exclusivity validation)
- T021 waits for all T015-T020 to complete (contract test expansion)
- Critical path: T001→T006→T013→T014→T021→T022→T023→T026→T027 (~18 hours)

## Timeline & Capacity Planning

| Phase | Duration | Start | End | Critical Path |
|-------|----------|-------|-----|---------|
| 0: Research (T001-T006) | 2-3 hrs | T+0h | T+3h | YES (blocks T007) |
| 1: Design (T007-T013) | 3-4 hrs | T+3h | T+7h | YES (blocks T014) |
| 2a: Setup (T014) | 1 hr | T+7h | T+8h | YES (blocks T017,T021) |
| 2b: Tests (T015-T020) | 9 hrs | T+8h | T+17h | YES but parallelizable |
| 2c: Contract (T021) | 1 hr | T+17h | T+18h | YES (blocks T022) |
| 2d: Regression (T022) | 1 hr | T+18h | T+19h | YES (blocks T023) |
| 2e: Coverage (T023) | 1 hr | T+19h | T+20h | YES (blocks T024) |
| 3: Polish (T024-T027) | 2-3 hrs | T+20h | T+23h | YES (final) |
| **TOTAL** | **18-23 hours** | | | |

## Parallel Execution Opportunities

**Phase 2 Parallelization** (After T014 mutual exclusivity is implemented):

**Batch 1** (T015-T020 can run in parallel, ~2 hours wall clock):
- T015: Basic CALL test suite
- T016: Parameter modes test suite
- T018: Exception handling test suite
- T019: Fixed format test suite
- T020: Dynamic CALL tracking test suite

**Batch 2** (T017 depends on T014):
- T017: RETURNING/GIVING test suite (after T014 mutual exclusivity implementation)

**Sequential** (After Batch 1+2):
- T021: Contract tests (needs all T015-T020 complete)
- T022: Regression tests
- T023: Coverage measurement
- T024-T027: Polish tasks

**Realistic Sequential Execution**: 18 hours  
**With Parallelization** (6 developers / CI jobs): 12-14 hours wall clock

---

## Validation Checklist

**Before Starting**:
- [ ] All references to spec.md, framework-baseline.md, research.md verified
- [ ] Git branch 001-call-statements-coverage created and active
- [ ] Python 3.13+ installed with pytest, mypy, black, ruff available

**During Execution**:
- [ ] Each task completed in order per dependency graph
- [ ] Regression tests run after implementation tasks (T022)
- [ ] Coverage verified after T023
- [ ] Documentation updated (T024)

**Post-Implementation**:
- [ ] All 8 success criteria verified (T026)
- [ ] All 22 functional requirements tested
- [ ] All commits have meaningful messages
- [ ] No TODO comments in code
- [ ] Full test suite passes: `pytest tests/unit/test_call_*.py -v`

---

## Quick Reference Commands

```bash
# Run all CALL statement tests
pytest tests/unit/test_call_*.py -v

# Check coverage
pytest tests/unit/test_call_*.py -v \
  --cov=cobolparser.models.statements \
  --cov=cobolparser.parser \
  --cov-fail-under=90

# Code quality checks
ruff check cobolparser/ && black --check cobolparser/ && mypy cobolparser/

# Integration tests
pytest tests/integration/test_call_*.py -v

# Full test suite
pytest tests/ -v

# Specific test
pytest tests/unit/test_call_basic_parsing.py::test_call_with_literal_program_name -v
```

---

## References

- **Specification**: [spec.md](spec.md) (6 User Stories, 22 FRs, 8 Success Criteria)
- **Implementation Plan**: [plan.md](plan.md) (3 phases with cross-references)
- **Framework Baseline**: [framework-baseline.md](framework-baseline.md) (758 lines, 15 sections with code locations)
- **Audit Report**: [AUDIT-IMPLEMENTATION-PLAN.md](AUDIT-IMPLEMENTATION-PLAN.md) (700 lines, detailed task mapping)
- **Constitution**: [.specify/memory/constitution.md](.specify/memory/constitution.md) (5 core principles)

---

**Status**: Ready for implementation  
**Last Updated**: January 11, 2026  
**Branch**: 001-call-statements-coverage
