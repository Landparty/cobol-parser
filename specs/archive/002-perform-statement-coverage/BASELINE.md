# BASELINE: Current PERFORM Statement Implementation

**Date**: January 11, 2026  
**Purpose**: Document existing code state for regression testing after feature implementation

## Current PerformStatement Model (`cobolparser/models/statements.py:113-180`)

### Attributes Currently Supported
```python
- perform_type: str = "SIMPLE"           # SIMPLE, TIMES, UNTIL, VARYING
- target_paragraph: Optional[str]        # Target paragraph name
- thru_paragraph: Optional[str]          # Ending paragraph for THRU
- times_count: Optional[int]             # TIMES count (int only, not Union)
- until_condition: Optional[CobolExpression]
- varying_clause: Optional[Dict[str, Any]]
- inline_statements: List[CobolStatement]
```

### Methods Currently Implemented
- `set_target_paragraph(paragraph: str)` - sets target_paragraph
- `set_thru_paragraph(paragraph: str)` - sets thru_paragraph
- `set_times_clause(count: int)` - sets perform_type="TIMES" and times_count
- `set_until_clause(condition)` - sets perform_type="UNTIL" and until_condition
- `set_varying_clause(variable, from_value, by_value, until_condition)` - sets perform_type="VARYING" and varying_clause
- `add_inline_statement(statement)` - adds to inline_statements
- `to_dict()` - serializes to dictionary

### Missing Attributes (Per Spec Clarifications)
- ❌ `test_timing`: No support for WITH TEST BEFORE/AFTER timing qualifier
- ❌ Union type for `times_count`: Currently `Optional[int]`, should be `Optional[Union[int, str]]`
- ❌ Union types for `from_value` and `by_value` in varying_clause: Currently str, should be `Union[int, str]`

## Current Parser Implementation (`cobolparser/parser.py:3200-3345`)

### `_parse_perform_inline()` Method

**Supported Patterns**:
1. ✅ `PERFORM paragraph-name`
2. ✅ `PERFORM paragraph-name THRU paragraph-name`
3. ✅ `PERFORM paragraph-name n TIMES`
4. ✅ `PERFORM paragraph-name THRU paragraph-name n TIMES`
5. ✅ `PERFORM VARYING variable FROM value BY value UNTIL condition ... END-PERFORM`
6. ✅ Inline PERFORM with CALL statements (lines 3276-3297)
7. ✅ Inline PERFORM with IF statements (lines 3297+)

**Unsupported Patterns**:
- ❌ `PERFORM paragraph-name UNTIL condition`
- ❌ `PERFORM paragraph-name WITH TEST BEFORE UNTIL condition`
- ❌ `PERFORM paragraph-name WITH TEST AFTER UNTIL condition`
- ❌ `PERFORM ... THRU ... UNTIL condition`
- ❌ `PERFORM ... WITH TEST ... UNTIL condition`
- ❌ `PERFORM VARYING ... WITH TEST AFTER ...`
- ❌ Support for variable names in TIMES clause (currently only accepts int)
- ❌ Support for Union types in VARYING from_value/by_value

### Parser Code Structure
- Lines 3213-3310: PERFORM VARYING handling
- Lines 3312-3344: Simple PERFORM handling (paragraph + optional THRU/TIMES)
- Helper methods:
  - `_parse_inline_call_into_perform()` (lines 3352-3393)
  - `_parse_inline_if_into_perform()` (lines 3397-3454)
  - `_parse_inline_call_into_if()` (lines 3456-3500)

### Limitations
- Condition parsing in VARYING assumes simple string concatenation (line 3255-3256)
- No explicit WITH TEST handling or test_timing tracking
- Variable names in TIMES clause not supported (would fail int() conversion at line 3334)

## Current Test Coverage

### Unit Tests

**Test Files**:
- `tests/unit/test_statements.py:349-500` - PerformStatement model tests
- `tests/unit/test_perform_thru.py` - PERFORM THRU parsing (210 lines)
- `tests/unit/test_perform_until_numeric_period.py` - UNTIL with numeric literals
- `tests/unit/test_sample_features.py:477` - Sample PERFORM test
- `tests/unit/test_models.py:321` - Model-level PERFORM tests

**Test Coverage Gaps**:
- ❌ No tests for `PERFORM UNTIL condition` (simple, without THRU/TIMES)
- ❌ No tests for `PERFORM ... WITH TEST BEFORE UNTIL`
- ❌ No tests for `PERFORM ... WITH TEST AFTER UNTIL`
- ❌ No tests for variable name in TIMES clause (e.g., `PERFORM PARA WS-COUNT TIMES`)
- ❌ No tests for `PERFORM ... THRU ... UNTIL condition` combinations
- ❌ No tests for `test_timing` attribute (doesn't exist)
- ❌ No tests for Union types in varying_clause from_value/by_value

### Integration Tests

**Test Files**:
- `tests/integration/test_perform_until_nested.py` - PERFORM UNTIL with nested statements (175+ lines)
  - Tests UNTIL with simple calls, multiple calls, nested IF
  - Tests VARYING clause
  - Tests JSON serialization

**Coverage Summary**:
- ✅ SIMPLE PERFORM - Covered
- ✅ PERFORM THRU - Covered
- ✅ PERFORM TIMES - Covered
- ✅ PERFORM TIMES THRU - Covered
- ✅ PERFORM VARYING - Covered
- ✅ Inline PERFORM with statements - Covered
- ❌ PERFORM UNTIL (without VARYING) - NOT Covered
- ❌ WITH TEST clauses - NOT Covered
- ❌ Variable references in TIMES - NOT Covered

## Existing Test Patterns

### Unit Test Pattern (from test_statements.py)
```python
def test_perform_statement_creation(self):
    location = SourceLocation(30, 4)
    perform_stmt = PerformStatement(location)
    
    # Assert initialization
    assert perform_stmt.statement_type == "PERFORM"
    assert perform_stmt.perform_type == "SIMPLE"
```

### Integration Test Pattern (from test_perform_thru.py)
```python
parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
result = parser.parse(source)
perform_stmt = [c for c in proc_div.sections[0].children if hasattr(c, 'target_paragraph')][0]
assert perform_stmt.target_paragraph == "PARA-START"
assert perform_stmt.thru_paragraph == "PARA-END"
```

## Parser Infrastructure Dependencies

### Token Types (from lexer)
- ✅ TokenType.PERFORM
- ✅ TokenType.TIMES, TokenType.TIME
- ✅ TokenType.IDENTIFIER
- ✅ TokenType.NUMERIC_LITERAL
- ✅ TokenType.NEWLINE
- ✅ TokenType.COMMENT
- ✅ TokenType.CALL, TokenType.IF
- ✅ TokenType.WITH (line 354)
- ✅ TokenType.BEFORE (line 220)
- ✅ TokenType.AFTER (line 219)
- ❌ TokenType.TEST - NOT DEFINED, must be added to lexer TokenType enum

### AST Infrastructure
- ✅ SourceLocation - for tracking source positions
- ✅ ASTNode - base class with children tracking
- ✅ CobolExpression - for condition expressions
- ✅ ConditionalExpression - for conditions with operators

### Parser Architecture
- Current section tracking: `self.current_section`
- Statement addition pattern: `self.current_section.add_child(pf)`
- Expression creation pattern: Inline CobolExpression/ConditionalExpression creation

## Code Quality Metrics

### Existing Code Statistics
- PerformStatement model: ~67 lines (lines 113-180 in statements.py)
- PERFORM parsing: ~145 lines (lines 3200-3345 in parser.py)
- Existing tests: ~400+ lines across multiple files
- Test count: 30+ test methods found via grep

### Code Style Observations
- Uses logging for debug output
- Extensive whitespace/newline skipping
- Token type and value checks together (`tokens[i].type == X` and `tokens[i].value.upper() == "Y"`)
- Dictionary for varying_clause instead of dedicated class

## Regression Testing Plan

### What to Test After Implementation

1. **Backward Compatibility**
   - All existing PERFORM SIMPLE tests still pass
   - All existing PERFORM THRU tests still pass
   - All existing PERFORM TIMES tests still pass
   - All existing PERFORM VARYING tests still pass
   - Inline PERFORM with nested statements still works

2. **Model Changes**
   - times_count Union[int, str, None] accepts both int and str
   - Existing int values still work (backward compatible)
   - New test_timing attribute defaults to None (backward compatible)
   - Varying clause from_value/by_value support Union types

3. **Parser Changes**
   - New WITH TEST parsing doesn't break existing patterns
   - PERFORM UNTIL (without THRU) parsing works correctly
   - PERFORM ... THRU ... UNTIL combinations parse correctly
   - Variable references in TIMES clause work

4. **JSON Serialization**
   - to_dict() includes new test_timing field
   - Union types serialize properly (int as-is, str as-is)
   - No missing fields in output

5. **Performance**
   - No regression in parse time for large programs
   - Memory usage within expected bounds
   - No infinite loops in new parsing logic

## Baseline Regression Test Commands

```bash
# Run all existing PERFORM tests (should all pass)
python -m pytest tests/unit/test_statements.py::TestPerformStatement -v
python -m pytest tests/unit/test_perform_thru.py -v
python -m pytest tests/integration/test_perform_until_nested.py -v

# Measure baseline test coverage
python -m pytest --cov=cobolparser --cov-fail-under=90 tests/unit/test_statements.py::TestPerformStatement

# Measure parse performance baseline
python -m pytest tests/unit/test_performance_and_edge_cases.py::TestParsingPerformance -v
```

## Success Criteria for Regression

- ✅ All 30+ existing PERFORM tests still pass
- ✅ No new test failures introduced
- ✅ Code coverage maintained at 90%+
- ✅ Parse time performance within 10% of baseline
- ✅ All to_dict() output still valid JSON
- ✅ No breaking changes to public API

---

**Status**: Baseline documented on 2026-01-11  
**Next Step**: Execute implementation plan, then re-run regression tests to verify no breakage
