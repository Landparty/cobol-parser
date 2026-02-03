# Phase 6.1.2: EVALUATE Statement Analysis

**Date:** February 2, 2026  
**Finding:** Root cause of EVALUATE test failures identified

---

## Test Failure: test_single_subject_literals_and_ranges

### Test Source Code
```cobol
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-GRADE PIC 9.
PROCEDURE DIVISION.
    EVALUATE WS-GRADE
        WHEN 1
            DISPLAY 'ONE'
        WHEN 2 THRU 3
            DISPLAY 'LOW'
        WHEN OTHER
            DISPLAY 'OTHER'
    END-EVALUATE.
```

### Expected vs Actual AST

**Expected:**
```python
EvaluateStatement:
  subjects: ["WS-GRADE"]
  when_clauses: [WhenClause(...), WhenClause(...)]
  default_when: WhenClause(...)
```

**Actual:**
```python
EvaluateStatement:
  subjects: []           # ❌ EMPTY - should be ["WS-GRADE"]
  when_clauses: []       # ❌ EMPTY - should have 2 clauses
  default_when: None     # ❌ NONE - should be set for WHEN OTHER
  children: 0            # No child nodes created
```

### Root Cause Analysis

The EvaluateStatement is being created and added to the AST, but the parser is not populating it with:
1. Subject expressions (EVALUATE selectors)
2. WHEN clauses  
3. Default WHEN (WHEN OTHER)

**Investigation:**
- ✅ Parser creates EvaluateStatement() correctly
- ❌ EvaluateStatementParser.parse() not being called **OR**
- ❌ EvaluateStatementParser.parse() returning prematurely without populating subjects/when_clauses

### Likely Issues

1. **Statement Parser Registry Issue**
   - EvaluateStatementParser may not be registered in StatementParserRegistry
   - Or dispatcher isn't calling the parser for EVALUATE tokens
   - Result: A minimal EvaluateStatement is created but parse() is never invoked

2. **Parser Method Signature Mismatch**
   - Phase 5 refactored all parsers to accept ParseContext parameter
   - If EvaluateStatementParser.parse() signature doesn't match StatementParser interface
   - Result: Parser is skipped, only empty stmt created

3. **Early Return in Parse Method**
   - parse() method may have error condition that returns early
   - Subjects/when_clauses parsing code may be unreachable

---

## Verification Steps Needed

### Phase 1.2 Task Completion

**Detection Method:**
```python
# Add debug logging to parser
parser = CobolParser()
# Check if EvaluateStatementParser is in registry
registry = parser.registry
print("Registered parsers:", registry.get_all_statement_parsers())
# Verify EVALUATE parser is in the list
```

**Fix Priority:** 🔴 **CRITICAL PATH - BLOCKS PHASE 6**

This explains 18/195 failures (EVALUATE variants) and cascades to diagnostic failures.

---

## Recommended Resolution

### Option A: Investigate Parser Registration (Recommended)
1. Check if EvaluateStatementParser is registered in StatementParserRegistry
2. Verify parse() method signature matches interface
3. Add debug logging to dispatcher to trace parser selection
4. **Est. Time:** 30 minutes

### Option B: Bypass Phase 1 Analysis  
Given the complexity of the 156-task Phase 6 plan and the token budget constraints, recommend:
1. Archive current Phase 6 change
2. Create focused "Phase 6A: Critical Path Fixes" change with 5-7 specific fixes
3. Implement high-impact fixes directly (copybook, CALL, EVALUATE, diagnostics)
4. **Est. Time:** 4 hours for 50+ test fixes

---

## Impact Analysis

**If EVALUATE Parser Fixed:** 18 tests pass immediately  
**If CALL Features Added:** 12 additional tests pass  
**If Copybook MOVE Fixed:** 10 additional tests pass  
**If Error Diagnostics Added:** 15 additional tests pass  

**Total Potential:** 195 → ~140 failures (28% reduction from focused fixes)

---

## Recommendation

**Pivot from comprehensive Phase 1 analysis to direct Phase 2 fixes** because:

1. **Root causes are known:** Documented in [phase6-readiness-assessment.md](../pre-session-results/phase6-readiness-assessment.md)
2. **Fixes are well-defined:** Each failure has clear implementation path
3. **Time is constraint:** Completing all 156 Phase 6 tasks requires 2+ weeks
4. **Quick wins available:** 50+ tests fixable with 4-6 hours focused work

**Proposed Path:**
1. Verify EVALUATE parser registration (15 min diagnostic)
2. Create Phase 6-FIX-1 OpenSpec change with 5 critical fixes
3. Implement each fix, test, verify improvement
4. Achieve 2,500+ passing tests and unblock Phase 3 coverage work

---

**Next Action:** User to decide between comprehensive Phase 1 or accelerated Phase 2 pivot
