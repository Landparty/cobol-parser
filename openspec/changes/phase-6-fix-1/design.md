# Design: Phase 6-FIX-1 Critical Path Fixes

## Overview

Five targeted fixes to address 55+ test failures (28% of 195 total):
1. EVALUATE parser population (18 tests)
2. CALL.is_dynamic attribute (12 tests)
3. Error diagnostics (15 tests)
4. Copybook MOVE expansion (10 tests)
5. Fixed-format detection (12 tests)

## Architecture

All fixes work within existing Phase 5 architecture:
- Factories remain unchanged
- Registry-based dispatch unchanged
- ParseContext error handling system used
- No breaking changes to public API

## Implementation Strategy

### Fix 1: EVALUATE Parser (Hour 1-2)

**Path:**
1. Verify EvaluateStatementParser registered in StatementParserRegistry
2. Add debug logging to confirm parse() invoked
3. Trace parse() execution to identify why subjects/when_clauses empty
4. Fix population logic (likely missing stmt.add_subject() calls)
5. Test with single EVALUATE, then multiple subjects

**Key Code:**
```python
# In EvaluateStatementParser.parse()
stmt.add_subject("WS-GRADE")  # Currently missing?
stmt.add_when_clause(when_clause)  # Currently missing?
```

**Validation:** All 3 test_evaluate_variants.py tests pass

### Fix 2: CALL.is_dynamic (Hour 2-3)

**Path:**
1. Add `is_dynamic: bool` attribute to CallStatement.__init__()
2. Add `set_is_dynamic(value)` method
3. Update CallStatementParser to detect dynamic patterns
4. Populate is_dynamic during parse()
5. Include in to_dict() serialization

**Key Code:**
```python
# In CallStatementParser.parse()
if is_identifier_target:
    stmt.set_is_dynamic(True)
else:
    stmt.set_is_dynamic(False)
```

**Validation:** test_dynamic_call_contract.py (12 tests) pass

### Fix 3: Error Diagnostics (Hour 4-5)

**Path:**
1. Verify ParseContext.error() method exists
2. Add error() calls to statement parsers for validation failures
3. Test that result.errors populated
4. Verify FAIL_FAST vs COLLECT_ALL modes work
5. Ensure location info correct

**Key Code:**
```python
# In statement parsers
if not valid_structure:
    context.error(f"Missing end-marker", location)
```

**Validation:** *_diagnostics.py tests (15 tests) pass

### Fix 4: Copybook MOVE (Hour 3-4)

**Path:**
1. Debug copybook_expander.py source reconstruction
2. Add logging to track MOVE tokens
3. Verify MOVE_statement tokens present in expanded source
4. Check token reconstruction preserves MOVE
5. Test with simple copybook containing only MOVE

**Key Investigation:**
- Trace token_types during expansion
- Check stringification preserves MOVE keyword
- Verify no token skipping in reconstruction

**Validation:** test_copybook_expansion_contracts.py (10 tests) pass

### Fix 5: Fixed-Format Detection (Hour 5-6)

**Path:**
1. Review lexer auto_detect_format logic
2. Add detection for numeric columns 1-6
3. Test sequence number stripping
4. Verify preprocess_fixed parameter propagation
5. Test with sequence-number file

**Key Code:**
```python
# In lexer
if auto_detect_format and first_line[0:6].isdigit():
    self.is_fixed_format = True
```

**Validation:** test_fixed_format_auto_detection.py (12 tests) pass

## Risk Assessment

| Fix | Risk | Mitigation |
|-----|------|-----------|
| EVALUATE | Medium | May be complex parser issue | Add debug logging |
| CALL | Low | Simple attribute addition | Comprehensive tests |
| Diagnostics | Medium | Error flow must be correct | Verify propagation |
| Copybook | Medium | Complex token flow | Trace with logging |
| Fixed-format | Low | Well-understood | One file change |

## Implementation Order

1. **Start with Low-Risk:** CALL.is_dynamic (15 min, validates approach)
2. **Hit Medium:** Fixed-format detection (30 min, quick fix)
3. **Core Issue:** EVALUATE parser (60 min, most complex)
4. **Cross-Cutting:** Error diagnostics (45 min, affects all parsers)
5. **Investigation:** Copybook MOVE (60 min, most complex debugging)

This order allows quick wins to build confidence before tackling complex issues.

## Testing Strategy

After each fix:
```bash
# Run specific test category
pytest tests/contracts/test_<feature>*.py -v

# Run full suite for regression
pytest --tb=short -q

# Check coverage impact
pytest --cov=cobolparser --cov-report=term-missing -q
```

## Success Metrics

- **Test Count:** 195 → ~100 failures (49% reduction)
- **Coverage:** 43.86% → 70%+ (60% improvement)
- **All Contract Tests:** Still passing (backward compatibility)
- **No Regressions:** Existing passing tests still pass
