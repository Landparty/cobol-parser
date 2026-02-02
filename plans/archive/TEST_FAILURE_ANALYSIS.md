# Test Failure Analysis - Session Summary

## Current Test Status
- **Total Failures**: 128
- **Total Passing**: 2221
- **Skipped**: 13

## Baseline Comparison
- **Pre-existing failures** (from known_failures.txt): 32 failures
- **New failures introduced**: 96 failures (128 - 32)
- **Tests fixed by refactoring**: +25 tests (2196 → 2221 passing)

## Failure Categorization

### 1. Pre-existing Failures (32) - NOT caused by refactoring
These failures exist in the baseline and should be investigated separately:

**EVALUATE Diagnostics (4 failures)**
- `test_missing_end_evaluate_reports_error`
- `test_missing_end_evaluate_message_contains_term`
- `test_consecutive_also_reports_error`
- `test_syntax_errors_are_errors`

**IO Coverage Reporter (18 failures)**
- Various `io_coverage_reporter.py` tests related to test analysis functionality
- These are unrelated to parser functionality

**Other Pre-existing (10 failures)**
- Fixed format parsing: 2 failures
- Value clause contract: 1 failure
- Continuation cases: 1 failure
- Preprocess tests: 2 failures
- Evaluate statement diagnostics: 1 failure
- Parser error handling: 1 failure
- Copybook expansion: 1 failure

### 2. NEW Failures Introduced (96) - ROOT CAUSE ANALYSIS

#### IF Statement Failures (13 failures)
**Files affected:**
- `test_if_complete.py` - 12 failures
- `test_control_flow_basic.py` - 4 failures (overlap)

**Root Cause:** 
The inline delegation method `_parse_if_inline()` was changed to simply skip tokens:
```python
def _parse_if_inline(self, tokens, i):
    """Legacy inline parser - fallback to skip for now."""
    # IF statements are handled elsewhere, this is emergency fallback
    while i < len(tokens) and tokens[i].type not in (TokenType.PERIOD, TokenType.NEWLINE):
        i += 1
    return i
```

This **removes all IF statement parsing** from the sentence parsing path, breaking IF statement functionality completely.

**Impact:**
- IF statements are no longer parsed when encountered in PROCEDURE DIVISION
- Nested IF statements (IF within PERFORM, etc.) are skipped entirely
- JSON serialization tests fail because IF statements aren't created

#### PERFORM Statement Failures (20+ failures)
**Files affected:**
- `test_perform_statement_coverage.py` - 11 failures
- `test_perform_until_nested.py` - 7 failures  
- `test_perform_backward_compat.py` - 8 failures
- `test_sample_programs.py` - 1 failure (arithmetic_operations.cbl)

**Root Cause:**
Similar to IF, `_parse_perform_inline()` was changed to skip tokens:
```python
def _parse_perform_inline(self, tokens, i):
    """Legacy inline parser - delegate to registry."""
    return self._parse_with_registry(tokens, i)
```

Actually, PERFORM delegates to registry which should work... but the issue is that PERFORM is complex and requires special inline handling for the UNTIL/TIMES/VARYING clauses that the registry parsers don't handle.

**Impact:**
- PERFORM statements with UNTIL, TIMES, VARYING clauses fail
- Backward compatibility tests fail due to changed behavior
- Nested statements inside PERFORM blocks aren't properly parsed

#### EVALUATE Diagnostic Failures (14 failures)  
**Files affected:**
- `test_evaluate_diagnostics.py` - 13 failures
- `test_evaluate_serialization.py` - 1 failure

**Root Cause:**
The new EvaluateStatementParser doesn't implement comprehensive error checking/diagnostics that the old inline implementation had. Specifically:
- Missing error detection for malformed EVALUATE statements
- No validation of WHEN clause syntax
- Missing THROUGH range validation
- Missing WHEN OTHER placement validation

**Impact:**
- Error reporting tests fail because expected errors aren't generated
- Diagnostic test cases can't validate error handling

#### Other New Failures (49 failures)
- **Entry statements** (4): `_parse_entry_inline()` now just skips
- **GO TO statements** (1): `_parse_goto_inline()` now just skips  
- **Arithmetic migration** (2): Likely side effects
- **Fixed format parsing** (1): Side effect
- **Copybook expansion** (1): Pre-existing actually, but in failure list

## Root Cause Summary

The refactoring introduced **two architectural problems**:

### Problem 1: Over-aggressive Token Skipping
When creating fallback implementations for `_parse_*_inline()` methods, I used a simple token-skipping approach:
```python
while i < len(tokens) and tokens[i].type not in (TokenType.PERIOD, TokenType.NEWLINE):
    i += 1
return i
```

This **completely removes** the statements from the parse tree instead of actually parsing them.

### Problem 2: Incomplete Parser Implementations
The extracted parsers (EVALUATE, CALL) don't fully replicate the error checking and diagnostic functionality of the original inline implementations. The tests expect these diagnostics.

## Recommendations

### Short-term Fix (Revert to baseline)
The 96 new failures are caused by the token-skipping fallback implementations and incomplete extracted parsers. Options:

1. **Option A: Restore original inline implementations**
   - Keep DISPLAY, MOVE, arithmetic parsers using registry
   - Restore the original `_parse_if_inline()`, `_parse_perform_inline()` implementations
   - This prevents new failures while keeping the improvements from registry delegation
   - Time: ~30 minutes

2. **Option B: Complete the extracted parsers**
   - Implement full IF and PERFORM parsers with all error checking
   - Add diagnostic generation to EVALUATE parser
   - Add error validation to callable/entry statements
   - Time: ~3-4 hours

3. **Option C: Hybrid approach**
   - Use registry delegation ONLY for statements where full parsers exist (DISPLAY, MOVE, arithmetic)
   - Keep original inline for complex statements (IF, PERFORM, EVALUATE)
   - Gradually extract complex statements when ready
   - Time: ~1 hour + ongoing

### Medium-term Plan  
If proceeding with Option A or C, the next phase should be:
1. Extract IF statement parser (137 lines) - highest priority for control flow
2. Extract PERFORM statement parser (319 lines) - complex but frequently used
3. Add comprehensive error checking to extracted parsers
4. Create diagnostic test suite for error conditions

## Impact Assessment

**Positive Outcomes:**
- ✅ +25 tests fixed (primarily arithmetic and MOVE operations)
- ✅ Registry pattern proven to work for simple statements
- ✅ TokenStream synchronization framework in place
- ✅ Architecture foundation solid

**Negative Outcomes:**
- ❌ -96 tests lost (primarily IF, PERFORM, diagnostic tests)
- ❌ Core control flow statements (IF, PERFORM) broken
- ❌ Error diagnostic capabilities lost

**Net Impact**: -71 tests (96 new failures - 25 fixes)

## Conclusion

The refactoring strategy of delegating to registry via skipping fallbacks was too aggressive. The token-skipping approach prevents proper statement parsing rather than delegating to registry.

**Recommendation:** Implement Option A (Restore inline implementations) to re-baseline and prevent regression, then proceed with careful extraction of complex parsers in subsequent phases.
