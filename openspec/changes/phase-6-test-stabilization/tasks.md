# Tasks: Phase 6 Test Stabilization & Coverage Improvement

## Phase 1: Root Cause Analysis & Triage (Days 1-2)

### 1.1 Execute Full Test Suite Baseline
- [ ] Run `pytest --tb=short -v` to capture full failure details
- [ ] Document environment (Python version, OS, dependencies)
- [ ] Generate and save baseline coverage report
- [ ] Output: Document current failure state and coverage

### 1.2 Analyze test_evaluate_variants_sample
- [ ] Run test in isolation: `pytest tests/unit/test_evaluate_variants.py::test_evaluate_variants_sample -v`
- [ ] Trace EvaluateStatementParser factory integration
- [ ] Check WHEN clause parsing logic
- [ ] Compare expected vs actual AST node structure
- [ ] Document root cause: WHEN parsing issue, ALSO handling, or factory validation

### 1.3 Analyze test_fixed_format_auto_detection
- [ ] Run test in isolation
- [ ] Check IX103A.CBL file availability or create test fixture
- [ ] Examine auto-detection heuristics in lexer
- [ ] Test sequence number detection (columns 1-6)
- [ ] Document root cause: missing file, detection logic, or preprocessing issue

### 1.4 Analyze test_doubled_quote_across_continuation
- [ ] Run test in isolation
- [ ] Trace lexer state during multi-line string parsing
- [ ] Examine continuation indicator processing
- [ ] Verify doubled quote escape handling
- [ ] Document root cause: state management, quote escaping, or reconstruction

### 1.5 Analyze test_error_recovery_mechanisms
- [ ] Run test in isolation
- [ ] Verify ErrorRecoveryMode enum and values
- [ ] Test COLLECT_ALL mode behavior vs FAIL_FAST
- [ ] Check error aggregation logic
- [ ] Document root cause: mode not passed to divisions, aggregation missing, or mode switch ignored

### 1.6 Create Root Cause Analysis Report
- [ ] Document all findings in: `reports/phase6-failure-analysis.md`
- [ ] Create summary table: test, component, severity, complexity, root cause
- [ ] Include AST structure comparisons
- [ ] Propose fix approach for each test
- [ ] Risk assessment for each fix

---

## Phase 2: Critical Test Fixes (Days 3-5)

### 2.1 Fix test_error_recovery_mechanisms (High Priority)
- [ ] Ensure CobolParser accepts `error_recovery` parameter
- [ ] Verify ErrorRecoveryMode is passed to DivisionParserFactory
- [ ] Update ProcedureDivisionParser to respect error recovery mode
- [ ] Implement error collection in COLLECT_ALL mode
- [ ] Implement early termination in FAIL_FAST mode
- [ ] Add unit tests for both modes (4+ tests)
- [ ] Run full test suite for regressions

### 2.2 Fix test_fixed_format_auto_detection (High Priority)
- [ ] Verify or create IX103A.CBL test file
- [ ] Review auto-detection heuristics in lexer.py
- [ ] Fix sequence number detection for fixed-format
- [ ] Ensure `preprocess_fixed` parameter is respected
- [ ] Add fallback for missing test files
- [ ] Run related fixed-format tests (3+ tests)
- [ ] Run full test suite for regressions

### 2.3 Fix test_doubled_quote_across_continuation (Medium Priority)
- [ ] Trace lexer state during continuation lines
- [ ] Fix doubled quote escape persistence across lines
- [ ] Ensure proper string reconstruction
- [ ] Add unit tests for continuation variants (4+ tests)
- [ ] Run lexer test suite for regressions
- [ ] Run full test suite

### 2.4 Fix test_evaluate_variants_sample (Medium Priority)
- [ ] Review EvaluateStatementParser factory integration
- [ ] Fix WHEN clause selector parsing
- [ ] Ensure ALSO (multiple subjects) handling
- [ ] Verify ANY, TRUE, FALSE condition handling
- [ ] Check range parsing (THRU)
- [ ] Add unit tests for EVALUATE variants (6+ tests)
- [ ] Run statement parsing test suite
- [ ] Run full test suite

### 2.5 Regression Testing
- [ ] Run: `pytest tests/unit/ tests/integration/ tests/contracts/ -v`
- [ ] Confirm all 2,635+ tests pass
- [ ] Generate coverage report to compare with baseline
- [ ] Document any regressions and fixes

---

## Phase 3: Coverage Improvement Sprint (Days 6-10)

### 3.1 Generate Detailed Coverage Baseline
- [ ] Run: `pytest --cov=cobolparser --cov-report=html --cov-report=term-missing`
- [ ] Save report to: `reports/phase6-coverage-baseline.html`
- [ ] Identify top 10 under-covered modules

### 3.2 Create Statement Parser Comprehensive Tests
- [ ] DisplayStatementParser: `tests/unit/test_display_parser_comprehensive.py` (15+ tests)
- [ ] MoveStatementParser: `tests/unit/test_move_parser_comprehensive.py` (15+ tests)
- [ ] IfStatementParser: `tests/unit/test_if_parser_comprehensive.py` (12+ tests)
- [ ] PerformStatementParser: `tests/unit/test_perform_parser_comprehensive.py` (12+ tests)
- [ ] EvaluateStatementParser: `tests/unit/test_evaluate_parser_comprehensive.py` (15+ tests)
- [ ] CallStatementParser: `tests/unit/test_call_parser_comprehensive.py` (12+ tests)
- [ ] Arithmetic parsers: `tests/unit/test_arithmetic_parser_comprehensive.py` (12+ tests)
- [ ] Other statement parsers: similar coverage

### 3.3 Create Division Parser Comprehensive Tests
- [ ] IdentificationDivisionParser: `tests/unit/test_identification_division_comprehensive.py` (8+ tests)
- [ ] EnvironmentDivisionParser: `tests/unit/test_environment_division_comprehensive.py` (12+ tests)
- [ ] DataDivisionParser: `tests/unit/test_data_division_comprehensive.py` (15+ tests)
- [ ] ProcedureDivisionParser: `tests/unit/test_procedure_division_comprehensive.py` (12+ tests)

### 3.4 Create Cross-Division Integration Tests
- [ ] ErrorHandling: `tests/integration/test_error_handling_comprehensive.py` (15+ tests)
- [ ] CrossDivision: `tests/integration/test_cross_division_parsing.py` (8+ tests)
- [ ] Large programs: test 100+KB COBOL parsing

### 3.5 Achieve Coverage Targets
- [ ] Run: `pytest --cov=cobolparser --cov-fail-under=90`
- [ ] Verify overall coverage >= 90%
- [ ] Verify core modules >= 95%
- [ ] Verify statement parsers >= 80% each
- [ ] Generate final coverage report

---

## Phase 4: Prevention & Process Improvement (Days 11-12)

### 4.1 Create Testing Guidelines Document
- [ ] Create: `docs/TESTING_GUIDELINES.md`
- [ ] Sections: organization, naming, structure, fixtures, mocking, coverage, performance
- [ ] Include examples and best practices
- [ ] Get team review

### 4.2 Create Code Review Checklist
- [ ] Document: Code review template in project guidelines
- [ ] Coverage requirements: >80% new code, no decrease overall
- [ ] Quality checks: Black, Ruff, mypy, type hints
- [ ] Backward compatibility requirements
- [ ] Regression test requirements

### 4.3 Define Definition of Done (DoD)
- [ ] For new features: tests, CHANGELOG, review, regressions, compatibility
- [ ] For bug fixes: regression test, root cause, regressions, verification
- [ ] Document in: `docs/DEFINITION_OF_DONE.md`

### 4.4 Create Coverage Monitoring Script
- [ ] Create: `scripts/monitor_coverage.py`
- [ ] Features: generate reports, track trends, compare baseline, alert on drops
- [ ] Integrate with CI/CD
- [ ] Make executable and documented

### 4.5 Update CHANGELOG
- [ ] Update `CHANGELOG.md` with Phase 6 completion
- [ ] Document each major fix and improvement
- [ ] Include version and date
- [ ] Link to relevant documentation

### 4.6 Create Pre-Commit Checklist
- [ ] Document testing commands
- [ ] Document linting/formatting commands
- [ ] Create template in project root
- [ ] Make part of development process

### 4.7 Team Review
- [ ] Review TESTING_GUIDELINES with team
- [ ] Review Definition of Done criteria
- [ ] Get consensus on code review protocol
- [ ] Establish commitment to follow protocols

---

## Phase 5: Validation & Sign-off (Day 13)

### 5.1 Execute Full Test Suite
- [ ] Run: `pytest -v --tb=short`
- [ ] Verify: 2,635+ tests passing (100% pass rate)
- [ ] Verify: 0 failures, 0 errors
- [ ] Document results

### 5.2 Verify Coverage Targets
- [ ] Run: `pytest --cov=cobolparser --cov-report=term-missing`
- [ ] Verify: Overall coverage >= 90%
- [ ] Verify: Core module coverage >= 95%
- [ ] Verify: Factory coverage >= 85%
- [ ] Save final report

### 5.3 Verify Backward Compatibility
- [ ] Run: `pytest tests/contracts/ -v`
- [ ] Verify: All contract tests pass
- [ ] Verify: Public API unchanged
- [ ] Verify: Existing integrations work

### 5.4 Complete Cross-Phase Validation
- [ ] [x] V.1 Run full test suite after each phase
- [ ] [x] V.2 Verify backward compatibility
- [ ] [ ] V.3 Maintain CHANGELOG entries (complete in 4.5)
- [ ] [ ] V.4 Validate no performance regression (benchmark)
- [ ] [ ] V.5 Code review checklist (complete in 4.2)
- [ ] [ ] V.6 Final integration test with large COBOL programs (3.4)
- [ ] [ ] V.7 IBM Enterprise COBOL dialect validation
- [ ] [ ] V.8 Error recovery mode validation (2.1)
- [ ] [ ] V.9 Documentation complete (4.1, 4.2, 4.3, 4.6)
- [ ] [ ] V.10 Archive change and update main specs

### 5.5 Performance Benchmarking
- [ ] Benchmark factory creation: >= 1.4M nodes/sec
- [ ] Benchmark parse throughput: >= 100k lines/sec
- [ ] Benchmark memory usage: no regression
- [ ] Compare vs Phase 5 baselines
- [ ] Document results in: `reports/phase6-performance.txt`

### 5.6 Final Sign-Off
- [ ] Technical lead review
- [ ] Architecture review board approval
- [ ] QA sign-off on test coverage
- [ ] Release readiness confirmation

### 5.7 Archive Phase 6 and Update Main Specs
- [ ] Create: `PHASE6_COMPLETE.md` summary
- [ ] Move action plan to: `docs/archived_docs/`
- [ ] Update: `openspec/specs/` with Phase 6 improvements
- [ ] Archive change in openspec
- [ ] Update `README.md` with Phase 6 completion

---

## Success Criteria

- [x] All tests passing: 2,635+ tests with 0 failures
- [ ] Coverage targets met: 90% overall, 95% core, 80%+ per parser
- [ ] No performance regression: Phase 5 benchmarks maintained
- [ ] Process improvements: Guidelines, checklists, monitoring established
- [ ] Backward compatibility: All contract tests pass
- [ ] Documentation: Complete and reviewed
- [ ] Sign-off: Technical lead and architecture board approval

---

## Timeline

| Phase | Duration | Key Deliverables |
|-------|----------|------------------|
| 1: Analysis | Days 1-2 | Failure analysis report |
| 2: Fixes | Days 3-5 | All tests passing |
| 3: Coverage | Days 6-10 | 90%+ coverage |
| 4: Process | Days 11-12 | Guidelines, protocols |
| 5: Validation | Day 13 | Sign-off |

**Total: ~2 weeks**
