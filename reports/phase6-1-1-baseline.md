# Phase 6.1.1: Test Suite Baseline Report

**Date:** February 2, 2026  
**Session:** Phase 6 Implementation - Root Cause Analysis & Triage

---

## Environment Documentation

### System Information
- **Operating System:** Windows 11
- **Python Version:** 3.14.2
- **Pytest Version:** 9.0.2
- **Pluggy Version:** 1.6.0

### Key Dependencies
- pytest-cov: 7.0.0
- coverage: 7.13.1
- cobolparser: 1.0.0 (editable install from workspace)

### Workspace Location
`c:\Users\samdi\Documents\workspace\cobol-parser`

---

## Test Suite Status

### Test Summary
| Metric | Value |
|--------|-------|
| **Total Tests Collected** | 2,558 |
| **Tests Passed** | 2,350 |
| **Tests Failed** | 195 |
| **Tests Skipped** | 13 |
| **Pass Rate** | 91.87% |
| **Warnings** | 54 |

### Test Execution Time
- **Total Duration:** ~29-35 seconds
- **Average per test:** ~11ms

### Test Distribution
```
Unit Tests:        ~1,500 (includes all test_*.py in tests/unit/)
Integration Tests: ~600 (includes test_*_integration.py in tests/integration/)
Contract Tests:    ~300 (includes test_*_contract*.py in tests/contracts/)
Performance Tests: ~50 (includes test_*_performance.py)
Regression Tests:  ~50 (includes test_*_backward_compat.py)
```

---

## Coverage Baseline

### Overall Coverage Summary
- **Total Coverage:** 43.86%
- **Coverage Requirement:** 81% (--cov-fail-under=81)
- **Coverage Gap:** 37.14% (to reach 81%)
- **Status:** ❌ FAILED - Below required threshold

### Coverage by Module Category (estimated from test output)
| Category | Coverage | Status |
|----------|----------|--------|
| Core Parser | ~60% | Below target |
| Lexer | ~70% | Below target |
| Models | ~55% | Below target |
| Parsers (Statements) | ~45% | Well below target |
| Parsers (Divisions) | ~40% | Well below target |
| Dialects | ~30% | Critical gap |
| Plugins | ~25% | Critical gap |
| Analysis Tools | ~80% | Acceptable |

### Under-Covered Modules (Priority Order)
1. **cobolparser/dialects/** - IBM Enterprise COBOL dialect support (~30% coverage)
2. **cobolparser/parsers/** - Statement and division parsers (~40-45% coverage)
3. **cobolparser/plugins/** - Plugin infrastructure (~25% coverage)
4. **cobolparser/models/** - AST node models (~55% coverage)
5. **cobolparser/preprocess/** - Copybook expansion and preprocessing (~35% coverage)

---

## Current Failure Categories

### Category 1: Copybook Expansion (10 failures)
**Status:** ❌ Critical - Feature gap  
**Examples:**
- `test_procedure_copybook_statements_in_ast` - MOVE statements from copybooks missing from AST
- `test_procedure_copybook_preserves_order` - Expected MOVE statement from copybook not found
- `test_copybook_expansion_integration` - Multiple copybook-related failures

**Impact:** Real COBOL programs using copybooks can't be parsed correctly

### Category 2: CALL Statement Features (12 failures)
**Status:** ❌ High Priority - Missing attributes  
**Examples:**
- `test_dynamic_call_is_detected` - CALL.is_dynamic attribute not being set
- `test_tracks_initial_value_from_working_storage` - Call value tracking not implemented
- `test_analyzer_populates_possible_values` - Call parameter analysis missing

**Impact:** Dynamic call analysis (critical for COBOL modernization) not working

### Category 3: Error Diagnostics (15 failures)
**Status:** ❌ High Priority - Missing error reporting  
**Examples:**
- `test_diagnostic_has_message` - EVALUATE error messages not generated
- `test_missing_program_reports_error` - CALL to missing programs not reported
- `test_missing_when_reports_error` - EVALUATE WHEN errors not detected

**Impact:** Parser can't report errors to users effectively

### Category 4: EVALUATE Statement Parsing (18 failures)
**Status:** ⚠️ Medium Priority - Incomplete implementation  
**Examples:**
- `test_evaluate_variants_sample` - WHEN clause parsing issues
- `test_multiple_subjects_any_and_also` - ALSO clause handling incomplete
- `test_evaluate_true_with_conditions` - Complex conditions not handled

**Impact:** Complex EVALUATE statements fail to parse

### Category 5: Fixed-Format COBOL (12 failures)
**Status:** ⚠️ Medium Priority - Auto-detection issues  
**Examples:**
- `test_fixed_format_auto_detection` - Sequence number detection broken
- `test_implicit_section_created_for_top_level_code` - Section structure not created
- Multiple fixed-format continuation issues

**Impact:** Legacy fixed-format COBOL programs can't be parsed

### Category 6: Statement Parser Features (35 failures)
**Status:** ⚠️ Medium Priority - Incomplete statement variants  
**Examples:**
- `test_move_multiple_targets` - MOVE with multiple targets incomplete
- `test_move_corresponding` - MOVE CORRESPONDING not implemented
- `test_perform_thru` - PERFORM...THRU variant incomplete
- `test_call_with_using_clause` - CALL...USING complex variants incomplete

**Impact:** Many real-world COBOL statement variants not supported

### Category 7: Complex Data Definition (15 failures)
**Status:** ⚠️ Medium Priority - Data structure edge cases  
**Examples:**
- `test_complex_occurs_structures` - Nested OCCURS clauses incomplete
- `test_multiple_redefines_patterns` - REDEFINES chains not fully supported
- `test_signed_decimal_picture_clauses` - Complex PICTURE clauses incomplete

**Impact:** Complex data structures can't be represented in AST

### Category 8: Cross-Division Integration (8 failures)
**Status:** ⚠️ Low-Medium Priority - Integration issues  
**Examples:**
- `test_identification_division_parsing` - Old API test (post-refactoring)
- `test_environment_division_parsing` - Division integration issues
- `test_procedure_division_parsing` - Cross-division context not maintained

**Impact:** Multi-division COBOL programs may have integration issues

### Category 9: Other Features (70+ failures)
**Status:** ⚠️ Low Priority - Various edge cases  
**Examples:**
- SQL statement support incomplete
- Performance benchmarks failing on edge cases
- Sentence structure with multiple verbs incomplete
- Level 77 item handling

**Impact:** Advanced features and optimizations incomplete

---

## Root Cause Summary

### Architecture Assessment
✅ **Strengths:**
- Factory-based architecture implemented correctly (Phase 5)
- Token streaming and lookahead working
- ParseContext propagation now correct
- Contract tests mostly passing (backward compatibility maintained)

⚠️ **Weaknesses:**
- Statement parser implementations incomplete (edge cases, attributes)
- Error reporting infrastructure missing
- Copybook expansion pipeline broken at MOVE statement level
- Fixed-format auto-detection needs enhancement

### Key Issues to Address

| Issue | Severity | Component | Est. Fix Time |
|-------|----------|-----------|---------------|
| Copybook MOVE statements missing from AST | **CRITICAL** | Copybook Expander | 2 hours |
| CALL.is_dynamic attribute not set | **HIGH** | CallStatementParser | 1 hour |
| Error diagnostics not reported | **HIGH** | Parser error handling | 3 hours |
| EVALUATE WHEN clause parsing | **HIGH** | EvaluateStatementParser | 2 hours |
| Fixed-format detection broken | **MEDIUM** | Lexer | 1 hour |
| MOVE advanced variants | **MEDIUM** | MoveStatementParser | 2 hours |
| PERFORM THRU variant | **MEDIUM** | PerformStatementParser | 1 hour |

---

## Next Steps

### Phase 1.2-1.5: Detailed Analysis
The following tests require isolated investigation to determine precise root causes:
1. **test_evaluate_variants_sample** - Trace WHEN parsing flow
2. **test_fixed_format_auto_detection** - Verify auto-detection logic
3. **test_doubled_quote_across_continuation** - Trace lexer state
4. **test_error_recovery_mechanisms** - Verify error mode propagation

### Phase 2: Priority Fixes
Based on this baseline, recommended fix order:
1. **Fix copybook MOVE statement expansion** → +2 tests fixed
2. **Implement CALL.is_dynamic** → +10 tests fixed
3. **Add error diagnostics** → +15 tests fixed
4. **Fix EVALUATE WHEN parsing** → +8 tests fixed
5. **Fix fixed-format detection** → +5 tests fixed

**Estimated Phase 2 Impact:** 195 → ~165 failures remaining

### Phase 3: Coverage Expansion
After fixes, focus on coverage expansion:
- Create comprehensive test suites for statement parsers (70+ tests)
- Create comprehensive test suites for division parsers (40+ tests)
- Expand integration tests for cross-division scenarios (20+ tests)
- Add performance and edge case tests

**Estimated Phase 3 Impact:** Coverage 43.86% → 80%+ overall

---

## Validation Checkpoints

- [x] Test environment documented
- [x] Full test suite executed
- [x] Coverage baseline measured (43.86%)
- [x] Failures categorized and analyzed
- [x] Root causes identified
- [ ] Isolated analysis of critical tests (Phase 1.2-1.5)
- [ ] Fix implementation (Phase 2)
- [ ] Coverage improvement (Phase 3)

---

**Report Generated:** 2026-02-02  
**Next Review:** After Phase 1.2-1.5 analysis completion
