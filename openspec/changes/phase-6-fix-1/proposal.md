# Phase 6-FIX-1: Critical Path Fixes

**Schema:** spec-driven  
**Scope:** High-impact test fixes targeting 195 failure reduction  
**Target:** 195 → ~100 failures, 43% → 70%+ coverage  
**Timeline:** 6-8 hours focused work

---

## Proposal

### Goal
Fix the highest-impact failures from Phase 6 baseline through targeted implementation of 5 critical parser features.

### Why This Matters
- Current: 195 failing tests (8.1% failure rate)
- Root causes identified in Phase 1 analysis
- 5 fixes address 55+ tests (28% of failures)
- Establishes momentum for Phase 3 coverage expansion

### What's Changing

#### Fix 1: EVALUATE Parser Registration & Subject Population (18 tests)
**Current Issue:** EvaluateStatement created but not populated with subjects/when_clauses  
**Fix:** Verify parser registration, ensure parse() method invoked, populate AST properly  
**Files:** cobolparser/parsers/statements/evaluate_parser.py, cobolparser/core/registry.py  
**Impact:** test_evaluate_variants*.py tests (3 tests), test_evaluate_*.py (15+ tests)

#### Fix 2: CALL.is_dynamic Attribute Implementation (12 tests)
**Current Issue:** CallStatement missing is_dynamic attribute for dynamic call detection  
**Fix:** Add is_dynamic tracking, populate based on CALL usage patterns  
**Files:** cobolparser/models/statements.py (CallStatement), cobolparser/parsers/statements/call_parser.py  
**Impact:** test_dynamic_call_contract.py tests (12 tests)

#### Fix 3: Copybook MOVE Statement Expansion (10 tests)
**Current Issue:** MOVE statements from expanded copybooks missing from AST  
**Fix:** Debug copybook expansion pipeline, ensure MOVE statements included in result  
**Files:** cobolparser/preprocess/copybook_expander.py  
**Impact:** test_copybook_expansion_contracts.py, test_copybook_expansion_integration.py (10 tests)

#### Fix 4: Error Diagnostic Reporting (15 tests)
**Current Issue:** Parser doesn't report errors for missing WHEN, missing END-EVALUATE, invalid structures  
**Fix:** Implement error reporting in statement parsers, propagate to result.errors  
**Files:** cobolparser/parser.py, statement parser files  
**Impact:** test_evaluate_diagnostics.py, test_call_diagnostics.py, test_move_diagnostics.py (15 tests)

#### Fix 5: Fixed-Format Auto-Detection (12 tests)
**Current Issue:** Sequence number detection broken for fixed-format COBOL  
**Fix:** Fix auto-detection heuristics in lexer, respect preprocess_fixed parameter  
**Files:** cobolparser/lexer.py  
**Impact:** test_fixed_format_auto_detection.py and related fixed-format tests (12 tests)

### Key Capabilities
- [x] Parser registration verification and debugging
- [x] AST population for complex statements
- [x] Attribute tracking (is_dynamic)
- [x] Error collection and reporting
- [x] Format auto-detection improvement

### Impact
- **Tests Fixed:** 55+ failing tests pass
- **Coverage Improved:** 43% → 70%+
- **Architecture:** No changes needed - fixes within existing Phase 5 design
- **Backward Compatibility:** All contract tests remain passing

### Success Criteria
- [ ] test_evaluate_variants.py: 3/3 tests passing
- [ ] test_dynamic_call_contract.py: 12/12 tests passing
- [ ] test_copybook_expansion*.py: 10/10 tests passing
- [ ] *_diagnostics.py: 15/15 tests passing
- [ ] Fixed-format tests: 12/12 passing
- [ ] Overall: 195 → ~100 failures
- [ ] Coverage: 43.86% → 70%+
- [ ] Contract tests: All passing (backward compatibility)

---

## Timeline
- **Hour 1-2:** EVALUATE parser fix + verification (18 tests)
- **Hour 2-3:** CALL.is_dynamic implementation (12 tests)
- **Hour 3-4:** Copybook MOVE debugging (10 tests)
- **Hour 4-5:** Error diagnostic implementation (15 tests)
- **Hour 5-6:** Fixed-format fix (12 tests)
- **Hour 6+:** Coverage expansion targeting highest ROI modules

---

## Related Documents
- Phase 6 readiness assessment
- Phase 6.1.1 baseline report
- Phase 6.1.2 EVALUATE analysis
- Phase 5 refactoring completion notes
