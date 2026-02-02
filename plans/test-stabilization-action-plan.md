# Phase 6: Test Stabilization & Coverage Improvement Action Plan

**Status:** Draft - Pending Review  
**Phase:** 6 (Post-Refactoring Stabilization)  
**Objective:** Systematically identify root causes, prioritize, and resolve all failing unit tests while improving test coverage and establishing prevention protocols.

---

## Executive Summary

Following the completion of Phase 5 (Factory Optimization and Validation), this action plan addresses the remaining test failures and coverage gaps to achieve production-ready stability.

### Current State
| Metric | Current | Target | Status |
|--------|---------|--------|--------|
| Tests Passing | 2,631 | 2,635 | 4 failures |
| Overall Coverage | 72.36% | 90%+ | Gap: 17.64% |
| Core Module Coverage | 91.68% | 95%+ | Near target |
| Factory Coverage | 85.09% | 85%+ | Exceeded |

### Known Failures
1. `test_evaluate_variants_sample` - EVALUATE statement parsing
2. `test_fixed_format_auto_detection` - Fixed-format detection
3. `test_doubled_quote_across_continuation` - Lexer continuation handling
4. `test_error_recovery_mechanisms` - Error recovery mode functionality

---

## Phase 1: Root Cause Analysis & Triage

### 1.1 Execute Full Test Suite Baseline
**Objective:** Confirm current failure state and capture detailed error output.

**Actions:**
- Run `pytest --tb=short -v` to get full failure details
- Capture stdout/stderr for each failing test
- Document test execution environment (Python version, OS)
- Generate initial coverage report

**Deliverable:** `reports/phase6-baseline-test-results.md`

### 1.2 Analyze test_evaluate_variants_sample
**Component:** `tests/unit/test_evaluate_variants.py`  
**Likely Area:** `cobolparser/parsers/statements/evaluate_parser.py`

**Investigation Steps:**
- [ ] Run test in isolation: `pytest tests/unit/test_evaluate_variants.py::test_evaluate_variants_sample -v`
- [ ] Examine EVALUATE statement parsing logic
- [ ] Check for missing WHEN clause handling
- [ ] Verify AST node creation via factory
- [ ] Compare expected vs actual AST structure

**Root Cause Hypotheses:**
- Factory integration may have changed node structure
- WHEN clause selector parsing may be incomplete
- Multiple subject handling (ALSO) may be broken

### 1.3 Analyze test_fixed_format_auto_detection
**Component:** `tests/integration/test_fixed_format_parsing.py`  
**Likely Area:** `cobolparser/lexer.py` or `cobolparser/parser.py`

**Investigation Steps:**
- [ ] Run test in isolation
- [ ] Check IX103A.CBL file availability
- [ ] Verify fixed-format detection heuristics
- [ ] Examine sequence number handling (columns 1-6)
- [ ] Test with and without preprocessing

**Root Cause Hypotheses:**
- IX103A.CBL file may not exist in test environment
- Auto-detection logic may be failing on specific patterns
- Preprocessing integration may have changed

### 1.4 Analyze test_doubled_quote_across_continuation
**Component:** `tests/unit/test_continuation_cases.py`  
**Likely Area:** `cobolparser/lexer.py`

**Investigation Steps:**
- [ ] Run test in isolation
- [ ] Examine multi-line string literal handling
- [ ] Check continuation indicator (-) processing
- [ ] Verify doubled quote escape handling across lines
- [ ] Review lexer state management during continuation

**Root Cause Hypotheses:**
- Doubled quote handling may not persist across continuation lines
- String literal reconstruction may be incomplete
- COBOL quote escaping rules may be misapplied

### 1.5 Analyze test_error_recovery_mechanisms
**Component:** `tests/unit/test_parser.py`  
**Likely Area:** `cobolparser/parser.py` or `cobolparser/core/exceptions.py`

**Investigation Steps:**
- [ ] Run test in isolation
- [ ] Verify ErrorRecoveryMode enum values
- [ ] Test COLLECT_ALL mode behavior
- [ ] Test FAIL_FAST mode behavior
- [ ] Check error aggregation logic

**Root Cause Hypotheses:**
- Error recovery mode may not be properly passed to division parsers
- Error collection may not be working with factory integration
- Mode switching may be ignored during parsing

### 1.6 Categorize Failures by Component

| Test | Component | Severity | Complexity |
|------|-----------|----------|------------|
| test_error_recovery_mechanisms | Core Parser | High | Medium |
| test_fixed_format_auto_detection | Lexer/Integration | High | Low |
| test_doubled_quote_across_continuation | Lexer | Medium | Medium |
| test_evaluate_variants_sample | Statement Parser | Medium | High |

### 1.7 Document Root Cause Findings
**Deliverable:** `reports/phase6-failure-analysis.md`

Contents:
- Detailed failure analysis for each test
- Root cause identification
- Proposed fix approach
- Risk assessment

---

## Phase 2: Critical Test Fixes

### Priority Order Rationale
1. **test_error_recovery_mechanisms** - Core functionality affects all parsing
2. **test_fixed_format_auto_detection** - Integration stability, likely quick fix
3. **test_doubled_quote_across_continuation** - Edge case but affects data integrity
4. **test_evaluate_variants_sample** - Complex statement parsing, lower impact

### 2.1 Fix test_error_recovery_mechanisms
**Owner:** TBD  
**Dependencies:** 1.5 complete

**Implementation Steps:**
- [ ] Verify ErrorRecoveryMode is properly imported and used
- [ ] Ensure CobolParser passes error_recovery to DivisionParserFactory
- [ ] Update ProcedureDivisionParser to respect error recovery mode
- [ ] Add error collection in COLLECT_ALL mode
- [ ] Implement early termination in FAIL_FAST mode
- [ ] Add unit tests for both modes

**Validation:**
- [ ] test_error_recovery_mechanisms passes
- [ ] New unit tests for error recovery pass
- [ ] No regressions in existing tests

### 2.2 Fix test_fixed_format_auto_detection
**Owner:** TBD  
**Dependencies:** 1.3 complete

**Implementation Steps:**
- [ ] Verify IX103A.CBL exists or create minimal test file
- [ ] Review auto-detection heuristics in lexer
- [ ] Fix sequence number detection (columns 1-6)
- [ ] Ensure preprocess_fixed parameter is respected
- [ ] Add fallback for missing test files

**Validation:**
- [ ] test_fixed_format_auto_detection passes
- [ ] test_ix103a_with_explicit_preprocessing passes
- [ ] test_ix103a_without_preprocessing_succeeds passes

### 2.3 Fix test_doubled_quote_across_continuation
**Owner:** TBD  
**Dependencies:** 1.4 complete

**Implementation Steps:**
- [ ] Trace lexer state during multi-line string parsing
- [ ] Fix doubled quote escape persistence across continuation
- [ ] Ensure proper string reconstruction
- [ ] Handle COBOL convention: doubled quotes = escaped quote

**Validation:**
- [ ] test_doubled_quote_across_continuation passes
- [ ] test_multi_line_continuation_proper still passes
- [ ] No regressions in other continuation tests

### 2.4 Fix test_evaluate_variants_sample
**Owner:** TBD  
**Dependencies:** 1.2 complete

**Implementation Steps:**
- [ ] Review EvaluateStatementParser factory integration
- [ ] Fix WHEN clause selector parsing
- [ ] Ensure ALSO (multiple subjects) works correctly
- [ ] Verify ANY, TRUE, FALSE condition handling
- [ ] Check range parsing (THRU)

**Validation:**
- [ ] test_evaluate_variants_sample passes
- [ ] All EVALUATE-related tests pass
- [ ] No regressions in statement parsing

### 2.5 Verify All Previously Failing Tests Pass
**Command:** `pytest tests/unit/test_evaluate_variants.py tests/integration/test_fixed_format_parsing.py tests/unit/test_continuation_cases.py tests/unit/test_parser.py::TestParserEdgeCases::test_error_recovery_mechanisms -v`

### 2.6 Run Full Regression Suite
**Command:** `pytest --cov=cobolparser --cov-report=term-missing`

**Acceptance Criteria:**
- All 2,635 tests pass
- No new failures introduced
- Coverage maintained or improved

---

## Phase 3: Coverage Improvement Sprint

### 3.1 Generate Detailed Coverage Report
**Command:** `pytest --cov=cobolparser --cov-report=html --cov-report=term-missing`

**Deliverable:** `reports/phase6-coverage-baseline.html`

### 3.2 Identify Top 10 Under-Covered Modules

Target modules for improvement (based on Phase 5 gaps):

| Module | Current Coverage | Target |
|--------|-----------------|--------|
| parsers/statements/display_parser.py | ~60% | 90% |
| parsers/statements/move_parser.py | ~65% | 90% |
| parsers/statements/if_parser.py | ~70% | 90% |
| parsers/statements/perform_parser.py | ~60% | 90% |
| parsers/statements/evaluate_parser.py | ~55% | 90% |
| parsers/statements/call_parser.py | ~60% | 90% |
| parsers/divisions/procedure.py | ~70% | 90% |
| parsers/divisions/data.py | ~75% | 90% |
| preprocess/copybook_expander.py | ~50% | 80% |
| dialects/ibm_enterprise.py | ~40% | 80% |

### 3.3 Create Unit Tests for Statement Parsers

For each parser in `cobolparser/parsers/statements/`:

**Required Test Categories:**
- [ ] Happy path parsing
- [ ] Edge cases (empty, minimal, maximal)
- [ ] Error handling (malformed input)
- [ ] Factory integration verification
- [ ] Metadata tracking

**Deliverables:**
- `tests/unit/test_display_parser_comprehensive.py`
- `tests/unit/test_move_parser_comprehensive.py`
- `tests/unit/test_if_parser_comprehensive.py`
- `tests/unit/test_perform_parser_comprehensive.py`
- `tests/unit/test_evaluate_parser_comprehensive.py`
- `tests/unit/test_call_parser_comprehensive.py`

### 3.4 Create Unit Tests for Division Parsers

For each parser in `cobolparser/parsers/divisions/`:

**Required Test Categories:**
- [ ] Division identification and parsing
- [ ] Section parsing within divisions
- [ ] Cross-division references
- [ ] Error recovery within divisions
- [ ] Factory integration

**Deliverables:**
- `tests/unit/test_identification_division_comprehensive.py`
- `tests/unit/test_environment_division_comprehensive.py`
- `tests/unit/test_data_division_comprehensive.py`
- `tests/unit/test_procedure_division_comprehensive.py`

### 3.5 Create Integration Tests for Cross-Division Parsing

**Test Scenarios:**
- [ ] Full program parsing (all divisions)
- [ ] Data division to procedure division linking
- [ ] File control to data division linkage
- [ ] Multiple programs in single parse
- [ ] Error propagation across divisions

**Deliverable:** `tests/integration/test_cross_division_parsing.py`

### 3.6 Add Tests for Error Handling and Edge Cases

**Test Categories:**
- [ ] Malformed COBOL (syntax errors)
- [ ] Incomplete statements
- [ ] Unexpected tokens
- [ ] Recovery after errors
- [ ] Empty/missing divisions
- [ ] Very large programs
- [ ] Unicode/encoding edge cases

**Deliverable:** `tests/integration/test_error_handling_comprehensive.py`

### 3.7 Achieve 90%+ Overall Coverage
**Target:** 90% overall coverage  
**Measurement:** `pytest --cov=cobolparser --cov-fail-under=90`

### 3.8 Achieve 95%+ Core Module Coverage
**Core Modules:**
- `cobolparser/core/` - 95%+
- `cobolparser/models/` - 90%+
- `cobolparser/parsers/divisions/` - 90%+

---

## Phase 4: Prevention & Process Improvement

### 4.1 Define Definition of Done Criteria

**For New Features:**
- [ ] Unit tests with >80% coverage for new code
- [ ] Integration tests for public API changes
- [ ] Contract tests for backward compatibility
- [ ] Documentation updated
- [ ] CHANGELOG.md updated
- [ ] Code review approved
- [ ] No regressions in existing tests

**For Bug Fixes:**
- [ ] Regression test added
- [ ] Root cause documented
- [ ] Fix verified with minimal reproduction
- [ ] No regressions in existing tests

### 4.2 Create Pre-Commit Test Execution Checklist

**Pre-Commit Checklist Template:**
```markdown
## Pre-Commit Checklist

- [ ] All unit tests pass: `pytest tests/unit/ -q`
- [ ] All integration tests pass: `pytest tests/integration/ -q`
- [ ] Coverage check: `pytest --cov=cobolparser --cov-fail-under=81 -q`
- [ ] Code formatted with Black: `black cobolparser/ tests/`
- [ ] Linting passes: `ruff check cobolparser/`
- [ ] Type checking passes: `mypy cobolparser/`
- [ ] Contract tests pass: `pytest tests/contracts/ -q`
```

### 4.3 Establish Code Review Protocol with Coverage Gates

**Review Requirements:**
- [ ] Coverage gate: New code must have >80% coverage
- [ ] No decrease in overall coverage
- [ ] All tests must pass
- [ ] Architecture review for parser changes
- [ ] API compatibility review for public interface changes

**Review Template:**
```markdown
## Code Review Checklist

### Functionality
- [ ] Code implements requirements correctly
- [ ] Edge cases handled
- [ ] Error handling appropriate

### Testing
- [ ] Unit tests cover new code (>80%)
- [ ] Integration tests for API changes
- [ ] Regression tests for bug fixes
- [ ] All tests pass

### Quality
- [ ] Code follows project style (Black, Ruff)
- [ ] Type hints present
- [ ] Docstrings complete
- [ ] No code smells (complexity, duplication)

### Coverage
- [ ] New code coverage >80%
- [ ] Overall coverage not decreased
- [ ] Core module coverage maintained
```

### 4.4 Document Test Writing Guidelines

**Deliverable:** `docs/TESTING_GUIDELINES.md`

**Contents:**
- Test file organization
- Naming conventions
- Test structure (Arrange-Act-Assert)
- Fixture usage
- Mocking guidelines
- Coverage expectations
- Performance test guidelines

### 4.5 Create Test Coverage Monitoring

**Coverage Monitoring Script:** `scripts/monitor_coverage.py`

**Features:**
- Generate coverage reports
- Track coverage trends
- Alert on coverage drops
- Generate module-level reports

**CI Integration:**
- Coverage report on every PR
- Coverage gate enforcement
- Trend analysis

### 4.6 Define Regression Test Criteria

**For Future Refactoring:**
- [ ] All existing tests must pass before refactoring
- [ ] Baseline performance metrics captured
- [ ] Contract tests must pass after refactoring
- [ ] Coverage must not decrease
- [ ] Integration tests with real COBOL programs

**Regression Test Suite:**
- Full unit test suite
- Full integration test suite
- Contract tests
- Performance benchmarks
- Large file parsing tests (100+ KB)

### 4.7 Update CHANGELOG

**Deliverable:** Update `CHANGELOG.md` with Phase 6 completion

**Entries:**
- Test stabilization complete (all tests passing)
- Coverage improved to 90%+
- Error recovery mechanisms fixed
- Fixed-format detection improved
- Lexer continuation handling fixed
- EVALUATE statement parsing fixed

### 4.8 Archive Phase 6 Documentation

**Deliverables:**
- Move `plans/test-stabilization-action-plan.md` to `docs/archived_docs/`
- Create `PHASE6_COMPLETE.md` summary
- Update `openspec/changes/refactor-parser-architecture/tasks.md`

---

## Phase 5: Validation & Sign-off

### 5.1 Execute Full Test Suite
**Command:** `pytest -v --tb=short`

**Acceptance Criteria:**
- 2,635 tests passing (100% pass rate)
- 0 failures
- 0 errors

### 5.2 Verify Coverage Targets
**Command:** `pytest --cov=cobolparser --cov-report=term-missing`

**Acceptance Criteria:**
- Overall coverage >= 90%
- Core module coverage >= 95%
- Factory coverage >= 85%

### 5.3 Run Performance Benchmarks
**Command:** `pytest tests/performance/ -v`

**Acceptance Criteria:**
- No performance regression vs Phase 5
- Factory creation: >= 1.4M nodes/sec
- Parse throughput: >= 100k lines/sec

### 5.4 Validate Backward Compatibility
**Command:** `pytest tests/contracts/ -v`

**Acceptance Criteria:**
- All contract tests pass
- Public API unchanged
- Existing integrations work

### 5.5 Complete Cross-Phase Validation

From `openspec/changes/refactor-parser-architecture/tasks.md`:

- [x] V.1 Run full test suite after each phase
- [x] V.2 Verify backward compatibility
- [ ] V.3 Maintain CHANGELOG entries
- [ ] V.4 Validate no performance regression
- [ ] V.5 Code review checklist for SOLID principles
- [ ] V.6 Final integration test with large COBOL programs
- [ ] V.7 IBM Enterprise COBOL dialect validation
- [x] V.8 Error recovery mode validation
- [ ] V.9 Documentation complete
- [ ] V.10 Archive change and update main specs

### 5.6 Final Review and Sign-off

**Review Participants:**
- Technical Lead
- QA Engineer
- Architecture Review Board

**Sign-off Criteria:**
- All tests passing
- Coverage targets met
- Performance benchmarks met
- Documentation complete
- CHANGELOG updated

---

## Timeline Summary

| Phase | Duration | Key Deliverables |
|-------|----------|------------------|
| Phase 1: Root Cause Analysis | Days 1-2 | Failure analysis report |
| Phase 2: Critical Test Fixes | Days 3-5 | All tests passing |
| Phase 3: Coverage Improvement | Days 6-10 | 90%+ coverage achieved |
| Phase 4: Prevention & Process | Days 11-12 | Guidelines and protocols |
| Phase 5: Validation | Day 13 | Sign-off and completion |

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Test fixes introduce regressions | Medium | High | Comprehensive regression testing |
| Coverage improvement takes longer | Medium | Medium | Prioritize critical modules |
| Performance degradation | Low | High | Benchmark after each change |
| Complex EVALUATE fix required | Medium | Medium | Allocate extra time |

---

## Success Criteria

1. **All tests passing:** 2,635 tests with 0 failures
2. **Coverage targets met:** 90% overall, 95% core
3. **No performance regression:** Maintain Phase 5 benchmarks
4. **Process improvements:** Guidelines and protocols documented
5. **Backward compatibility:** All contract tests pass

---

## Appendix A: Test Execution Commands

```bash
# Full test suite with coverage
pytest --cov=cobolparser --cov-report=term-missing --cov-report=html

# Run specific failing tests
pytest tests/unit/test_evaluate_variants.py -v
pytest tests/integration/test_fixed_format_parsing.py -v
pytest tests/unit/test_continuation_cases.py::test_doubled_quote_across_continuation -v
pytest tests/unit/test_parser.py::TestParserEdgeCases::test_error_recovery_mechanisms -v

# Coverage for specific module
pytest --cov=cobolparser.parsers.statements.display_parser --cov-report=term-missing

# Performance tests
pytest tests/performance/ -v

# Contract tests
pytest tests/contracts/ -v
```

## Appendix B: Module Coverage Targets

| Module | Current | Target | Priority |
|--------|---------|--------|----------|
| cobolparser/core/ | 91.68% | 95% | High |
| cobolparser/models/ | ~85% | 90% | High |
| cobolparser/parsers/statements/ | ~60% | 90% | High |
| cobolparser/parsers/divisions/ | ~70% | 90% | High |
| cobolparser/lexer.py | ~80% | 90% | Medium |
| cobolparser/parser.py | ~85% | 90% | Medium |
| cobolparser/preprocess/ | ~50% | 80% | Low |
| cobolparser/dialects/ | ~40% | 80% | Low |

---

*Document Version: 1.0*  
*Last Updated: 2026-02-02*  
*Status: Draft - Pending Review*
