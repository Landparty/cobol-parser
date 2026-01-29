# Implementation Plan: Comprehensive PERFORM Statement Coverage

**Feature Branch**: `002-perform-statement-coverage`  
**Created**: January 11, 2026  
**Baseline Reference**: [BASELINE.md](BASELINE.md)

---

## Executive Summary

This plan implements comprehensive PERFORM statement parsing for COBOL fixed format, extending the existing parser to support:
- ✅ Current: SIMPLE, TIMES, THRU, VARYING (partial)
- ➕ New: WITH TEST clauses, UNTIL (standalone), semantic type support for numeric parameters

**Scope**: 18 functional requirements, 8 success criteria, 5 user stories (P1-P3)  
**Impact**: ~200-300 lines of code changes + ~500 lines of new tests  
**Risk Level**: Low (backward-compatible changes only, all new features additive)

---

## Architecture Overview

### Current Framework (from BASELINE.md)

```
┌─────────────────────────────────────────────────────────────┐
│ COBOL Parser Architecture                                   │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Lexer (lexer.py)                                           │
│  ├─ TokenType enum (with, before, after available)         │
│  ├─ TokenType.TEST (MISSING - must add)                    │
│  └─ Keywords mapping                                        │
│                                                              │
│  Parser (parser.py)                                         │
│  ├─ _parse_perform_inline() [lines 3200-3345]             │
│  │  ├─ PERFORM VARYING path (lines 3213-3310)            │
│  │  └─ Simple PERFORM path (lines 3312-3344)             │
│  ├─ _parse_inline_call_into_perform()                     │
│  ├─ _parse_inline_if_into_perform()                       │
│  └─ _parse_inline_call_into_if()                          │
│                                                              │
│  AST Models (models/statements.py)                         │
│  ├─ PerformStatement [lines 113-180]                      │
│  │  ├─ Attributes (needs: test_timing, Union types)       │
│  │  ├─ Methods (all present)                              │
│  │  └─ to_dict() (needs: test_timing, Union serialization)│
│  └─ CobolExpression (for conditions)                      │
│                                                              │
│  Tests                                                      │
│  ├─ unit/test_statements.py (PerformStatement tests)      │
│  ├─ unit/test_perform_thru.py (PERFORM THRU tests)       │
│  ├─ unit/test_perform_until_nested.py (UNTIL integration) │
│  └─ integration/test_perform_until_nested.py              │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Changes Required (Additive Only - No Breaking Changes)

```
LEXER CHANGES:
  ├─ Add TokenType.TEST enum value (1 line)
  └─ Add 'TEST': TokenType.TEST to keywords (1 line)

PARSER CHANGES:
  ├─ Enhance _parse_perform_inline() to handle:
  │  ├─ WITH TEST BEFORE/AFTER parsing (30 lines)
  │  ├─ PERFORM ... UNTIL condition (standalone) (40 lines)
  │  ├─ Variable names in TIMES clause (20 lines)
  │  └─ Union type value handling (15 lines)
  ├─ New helper: _parse_test_timing_clause() (15 lines)
  ├─ New helper: _parse_until_condition() (20 lines)
  └─ Update _parse_perform_inline signature (minimal)

MODEL CHANGES:
  ├─ Add test_timing: Optional[str] attribute (1 line)
  ├─ Change times_count type to Union[int, str, None] (1 line)
  ├─ Update set_times_clause() to accept Union[int, str] (5 lines)
  ├─ Add set_test_timing() method (5 lines)
  ├─ Update varying_clause structure for Union types (5 lines)
  └─ Update to_dict() for new fields (5 lines)

TEST CHANGES:
  ├─ Unit tests for test_timing attribute (50 lines)
  ├─ Unit tests for Union type handling (50 lines)
  ├─ Integration tests for WITH TEST clauses (100 lines)
  ├─ Integration tests for PERFORM UNTIL (100 lines)
  └─ Regression test suite (100 lines)

Total Impact: ~400-500 lines of code + tests
```

---

## Phase 1: Foundation (Low Risk)

### 1.1 Add TokenType.TEST to Lexer

**File**: `cobolparser/lexer.py`

**Changes**:
```python
# Around line 220-221 (after BEFORE, AFTER)
TEST = auto()  # Add this line

# Around line 355 in keywords
'TEST': TokenType.TEST,  # Add this line
```

**Rationale**: WITH TEST clause requires TEST keyword tokenization  
**Risk**: None - additive only, no existing code affected  
**Testing**: `pytest -k lexer` to ensure tokenization works

### 1.2 Extend PerformStatement Model

**File**: `cobolparser/models/statements.py`

**Changes**:

a) Add test_timing attribute to `__init__()`:
```python
self.test_timing: Optional[str] = None  # BEFORE, AFTER, or None for default
```

b) Change times_count type signature:
```python
# FROM:
self.times_count: Optional[int] = None

# TO:
self.times_count: Optional[Union[int, str]] = None
```

c) Add methods:
```python
def set_test_timing(self, timing: str) -> None:
    """Set WITH TEST timing (BEFORE or AFTER)."""
    if timing.upper() in ("BEFORE", "AFTER"):
        self.test_timing = timing.upper()

def set_times_clause(self, count: Union[int, str]) -> None:
    """Set TIMES clause for the PERFORM.
    
    Args:
        count: int for literal (e.g., 10) or str for variable (e.g., "WS-COUNT")
    """
    self.perform_type = "TIMES"
    self.times_count = count
```

d) Update to_dict():
```python
def to_dict(self) -> Dict[str, Any]:
    """Convert PERFORM statement to dictionary representation."""
    result = super().to_dict()
    result.update({
        # ... existing fields ...
        "test_timing": self.test_timing,  # Add this
        "times_count": self.times_count,  # Already exists, now Union type
    })
    return result
```

**Rationale**: 
- Backward compatible (test_timing defaults to None)
- Union type accepts both existing int values and new str values
- Matches spec clarifications

**Risk**: Low - purely additive, no breaking changes  
**Testing**: `pytest tests/unit/test_statements.py::TestPerformStatement`

---

## Phase 2: Parser Enhancement (Medium Risk)

### 2.1 Add WITH TEST Parsing Helper

**File**: `cobolparser/parser.py` (new method, ~20 lines)

**Location**: After `_parse_perform_inline()`, around line 3350

```python
def _parse_test_timing_clause(self, tokens, i):
    """Parse optional WITH TEST [BEFORE | AFTER] clause.
    
    Returns: (timing_str, next_index)
        timing_str: "BEFORE", "AFTER", or None if not present
        next_index: position after clause (or same as input if not found)
    """
    # Check for WITH TEST
    if i >= len(tokens):
        return None, i
    
    # Skip newlines
    while i < len(tokens) and tokens[i].type == TokenType.NEWLINE:
        i += 1
    
    if i >= len(tokens) or tokens[i].value.upper() != "WITH":
        return None, i
    
    # Found WITH
    i += 1  # Skip WITH
    
    # Skip newlines
    while i < len(tokens) and tokens[i].type == TokenType.NEWLINE:
        i += 1
    
    if i >= len(tokens) or tokens[i].value.upper() != "TEST":
        # WITH without TEST - malformed, recover
        return None, i - 1  # Back up to WITH
    
    i += 1  # Skip TEST
    
    # Skip newlines
    while i < len(tokens) and tokens[i].type == TokenType.NEWLINE:
        i += 1
    
    # Get BEFORE or AFTER
    if i >= len(tokens):
        return "BEFORE", i  # Default
    
    timing_value = tokens[i].value.upper() if tokens[i].value else ""
    if timing_value in ("BEFORE", "AFTER"):
        return timing_value, i + 1
    
    return "BEFORE", i  # Default
```

**Rationale**: 
- Encapsulates WITH TEST parsing logic
- Reusable for multiple PERFORM variants
- Follows existing parser patterns (returns tuple of value + index)

**Risk**: Low - isolated helper method  
**Testing**: Unit test for helper in new test file

### 2.2 Add Condition Parsing Helper

**File**: `cobolparser/parser.py` (new method, ~25 lines)

**Location**: After `_parse_test_timing_clause()`, around line 3375

```python
def _parse_until_condition(self, tokens, i, stop_keywords=None):
    """Parse UNTIL condition expression.
    
    Collects tokens until newline, END-PERFORM, or stop keyword.
    Returns: (condition_expression, next_index)
    """
    if stop_keywords is None:
        stop_keywords = ["END-PERFORM", "ELSE", "END-IF", "NEWLINE"]
    
    cond_tokens = []
    while i < len(tokens):
        token = tokens[i]
        
        # Check for stop conditions
        if token.type == TokenType.NEWLINE:
            break
        if token.value and token.value.upper() in stop_keywords:
            break
        
        # Collect token
        cond_tokens.append(token.value)
        i += 1
    
    # Build condition expression
    condition_text = " ".join(cond_tokens).strip()
    
    if condition_text:
        condition_expr = ConditionalExpression("COMPARISON", tokens[i-1].location if i > 0 else tokens[0].location)
        condition_expr._metadata["value"] = condition_text
        return condition_expr, i
    
    return None, i
```

**Rationale**: 
- Extracts condition parsing logic
- Handles multi-line conditions (with newline skipping)
- Returns proper ConditionalExpression object

**Risk**: Low - similar to existing condition parsing in IF statements  
**Testing**: Integration test for various condition expressions

### 2.3 Enhance _parse_perform_inline() Main Method

**File**: `cobolparser/parser.py` (update existing method, ~80 lines)

**Location**: Lines 3200-3345 (replace existing implementation)

**Key Changes**:

a) Add standalone UNTIL support (before line 3312):
```python
# After PERFORM keyword, check for standalone UNTIL
if tokens[i].value and tokens[i].value.upper() == 'UNTIL':
    # PERFORM [THRU] UNTIL condition
    i += 1  # Skip UNTIL
    condition, i = self._parse_until_condition(tokens, i)
    pf.set_until_clause(condition)
    return i
```

b) In Simple PERFORM path, add WITH TEST support (after THRU check):
```python
# Check for WITH TEST clause (before checking for TIMES)
timing, i = self._parse_test_timing_clause(tokens, i)
if timing:
    pf.set_test_timing(timing)
    # Skip newlines after WITH TEST clause
    while i < len(tokens) and tokens[i].type == TokenType.NEWLINE:
        i += 1
```

c) Update TIMES clause to support variable names (around line 3334):
```python
# Change from:
if i < len(tokens) and tokens[i].type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER):
    try:
        times_count = int(tokens[i].value)
        i += 1
        # ...
        pf.set_times_clause(times_count)

# To:
if i < len(tokens) and tokens[i].type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER, TokenType.IDENTIFIER):
    times_value = tokens[i].value
    i += 1
    
    # Skip newlines
    while i < len(tokens) and tokens[i].type in (TokenType.NEWLINE, TokenType.COMMENT):
        i += 1
    
    # Check for TIMES keyword
    if i < len(tokens) and tokens[i].value and tokens[i].value.upper() in ("TIMES", "TIME"):
        i += 1
        
        # Convert to int if numeric literal, otherwise keep as string (variable name)
        try:
            times_count = int(times_value)
        except ValueError:
            times_count = times_value  # It's a variable name
        
        pf.set_times_clause(times_count)
```

d) In VARYING path, update to handle WITH TEST:
```python
# After setting VARYING clause (after line 3269):
# Check for optional WITH TEST AFTER
timing, i = self._parse_test_timing_clause(tokens, i)
if timing:
    pf.set_test_timing(timing)
```

**Rationale**: 
- Minimal changes to existing code structure
- All enhancements additive (no deletions)
- Backward compatible (new code only executed for new patterns)

**Risk**: Medium - modifies core parsing logic, but in contained sections  
**Testing**: Comprehensive integration tests for all new patterns

---

## Phase 3: Testing & Validation (Low Risk)

### 3.1 Unit Tests - Model Extensions

**File**: `tests/unit/test_statements.py` (add ~60 lines)

**New Tests**:

```python
def test_perform_statement_test_timing(self):
    """Test WITH TEST timing attribute."""
    location = SourceLocation(1, 1)
    perform_stmt = PerformStatement(location)
    
    perform_stmt.set_test_timing("BEFORE")
    assert perform_stmt.test_timing == "BEFORE"
    
    perform_stmt.set_test_timing("AFTER")
    assert perform_stmt.test_timing == "AFTER"

def test_perform_times_with_variable_reference(self):
    """Test TIMES clause with variable name (Union type)."""
    location = SourceLocation(1, 1)
    perform_stmt = PerformStatement(location)
    
    # Test with int (existing behavior)
    perform_stmt.set_times_clause(10)
    assert perform_stmt.times_count == 10
    assert isinstance(perform_stmt.times_count, int)
    
    # Test with variable name (new behavior)
    perform_stmt_var = PerformStatement(location)
    perform_stmt_var.set_times_clause("WS-COUNT")
    assert perform_stmt_var.times_count == "WS-COUNT"
    assert isinstance(perform_stmt_var.times_count, str)

def test_perform_to_dict_with_test_timing(self):
    """Test to_dict() includes test_timing."""
    location = SourceLocation(1, 1)
    perform_stmt = PerformStatement(location)
    perform_stmt.set_target_paragraph("TEST-PARA")
    perform_stmt.set_test_timing("AFTER")
    
    result = perform_stmt.to_dict()
    assert result["test_timing"] == "AFTER"

def test_varying_clause_union_types(self):
    """Test VARYING clause with Union types for from/by values."""
    # Test with literal values
    varying_clause_lit = {
        "variable": "I",
        "from_value": 1,  # int
        "by_value": 1     # int
    }
    
    # Test with variable references
    varying_clause_var = {
        "variable": "J",
        "from_value": "WS-START",  # str
        "by_value": "WS-INCREMENT"  # str
    }
    
    # Both should be acceptable
    assert isinstance(varying_clause_lit["from_value"], int)
    assert isinstance(varying_clause_var["from_value"], str)
```

**Risk**: None - unit tests only  
**Pass Criteria**: All assertions pass, to_dict() output valid JSON

### 3.2 Integration Tests - Parser Enhancements

**File**: `tests/integration/test_perform_statement_coverage.py` (new file, ~300 lines)

**Test Categories**:

a) PERFORM UNTIL (standalone):
```python
def test_perform_until_simple():
    """PERFORM paragraph-name UNTIL condition"""
    
def test_perform_until_thru():
    """PERFORM paragraph THRU paragraph UNTIL condition"""
    
def test_perform_until_with_test_before():
    """PERFORM PARA WITH TEST BEFORE UNTIL condition"""
    
def test_perform_until_with_test_after():
    """PERFORM PARA WITH TEST AFTER UNTIL condition"""
```

b) Times with variable reference:
```python
def test_perform_times_with_variable():
    """PERFORM PARA WS-COUNT TIMES"""
    
def test_perform_thru_times_with_variable():
    """PERFORM PARA THRU PARA WS-COUNT TIMES"""
```

c) VARYING with TEST:
```python
def test_perform_varying_with_test_after():
    """PERFORM VARYING ... WITH TEST AFTER UNTIL ... END-PERFORM"""
```

d) Complex combinations:
```python
def test_perform_thru_until_combination():
    """PERFORM PARA-A THRU PARA-B UNTIL condition"""
    
def test_perform_thru_test_until():
    """PERFORM PARA-A THRU PARA-B WITH TEST AFTER UNTIL condition"""
```

**Risk**: Low - new test file, no existing tests affected  
**Pass Criteria**: All assertions pass, AST correctly captures all attributes

### 3.3 Regression Test Suite

**File**: `tests/regression/test_perform_backward_compat.py` (new file, ~150 lines)

**Baseline Comparison Tests**:

```python
def test_backward_compat_simple_perform():
    """Verify simple PERFORM still works (from BASELINE)"""
    # Run existing test patterns, verify identical results

def test_backward_compat_perform_thru():
    """Verify PERFORM THRU still works (from BASELINE)"""

def test_backward_compat_perform_times():
    """Verify PERFORM TIMES still works (from BASELINE)"""

def test_backward_compat_perform_varying():
    """Verify PERFORM VARYING still works (from BASELINE)"""

def test_backward_compat_json_serialization():
    """Verify to_dict() output still valid (from BASELINE)"""

def test_backward_compat_times_as_int():
    """Verify times_count still accepts int (backward compatible)"""
```

**Risk**: None - validates no regression  
**Pass Criteria**: All tests pass, all existing behavior preserved

### 3.4 Performance Tests

**File**: `tests/unit/test_perform_performance.py` (new, ~80 lines)

```python
def test_parse_performance_with_many_perform_statements():
    """Verify parse time not affected by new PERFORM parsing"""
    # Generate program with 1000+ PERFORM statements
    # Measure parse time
    # Assert parse time within 10% of baseline
    
def test_memory_usage_with_complex_performs():
    """Verify memory usage not significantly increased"""
    # Parse large program with complex PERFORM statements
    # Assert memory usage within expected bounds
```

**Risk**: None - performance validation only  
**Pass Criteria**: Parse time/memory within acceptable bounds

---

## Phase 4: Integration & Quality Assurance (Low Risk)

### 4.1 Code Quality Checks

```bash
# Type checking
mypy cobolparser/parser.py cobolparser/models/statements.py

# Linting
ruff check cobolparser/

# Code formatting
black cobolparser/

# Full test suite
pytest tests/ --cov=cobolparser --cov-fail-under=90
```

### 4.2 Regression Validation

**Run baseline comparison**:
```bash
# All existing tests (should pass)
pytest tests/unit/test_statements.py::TestPerformStatement -v
pytest tests/unit/test_perform_thru.py -v
pytest tests/integration/test_perform_until_nested.py -v

# New regression suite
pytest tests/regression/test_perform_backward_compat.py -v

# Comparison: Before → After should be identical
```

### 4.3 Feature Validation Against Spec

| Spec Item | Implementation | Test Coverage |
|-----------|----------------|----------------|
| FR-006: WITH TEST support | _parse_test_timing_clause() | integration + unit |
| FR-007: VARYING components | Enhanced set_varying_clause() | integration |
| FR-013: Literal vs variable in TIMES | Union type in times_count | unit + integration |
| FR-016: THRU + UNTIL combinations | _parse_perform_inline() enhancement | integration |
| FR-018: THRU + WITH TEST + UNTIL | Parser logic | integration |
| SC-001: All COBOL variations | Integration test suite | comprehensive |
| SC-002: 100% test case pass | Full test suite | pytest report |

---

## Implementation Sequence

### Week 1: Foundation
1. Add TokenType.TEST to lexer (30 min)
2. Update PerformStatement model (1 hour)
3. Create baseline tests (1 hour)

### Week 2: Parser Enhancement
4. Add helper methods _parse_test_timing_clause(), _parse_until_condition() (2 hours)
5. Update _parse_perform_inline() for WITH TEST (2 hours)
6. Update _parse_perform_inline() for PERFORM UNTIL (1.5 hours)
7. Update _parse_perform_inline() for variable TIMES (1 hour)

### Week 3: Testing
8. Create unit tests (2 hours)
9. Create integration tests (3 hours)
10. Create regression tests (2 hours)
11. Performance validation (1 hour)

### Week 4: QA & Documentation
12. Code quality checks (1 hour)
13. Regression validation (1 hour)
14. Documentation updates (1 hour)

**Total Estimate**: 19 hours (~2.4 days of focused development)

---

## Risk Analysis & Mitigation

| Risk | Level | Mitigation |
|------|-------|-----------|
| Breaking existing PERFORM parsing | Medium | Comprehensive regression tests, backward compat tests |
| Union type serialization issues | Low | Unit tests for to_dict() output validation |
| Performance degradation | Low | Performance tests, parse time benchmarks |
| Token conflicts (TEST keyword) | Low | Check keyword precedence, existing keyword mapping |
| Condition parsing complexity | Medium | Isolate in _parse_until_condition() helper, reuse existing logic |
| Multi-line PERFORM statements | Medium | Test with various formatting, newline skipping validated |

---

## Success Criteria

### Code Quality
- ✅ All 30+ existing PERFORM tests pass (100%)
- ✅ New test coverage: ≥50 tests for new functionality
- ✅ Code coverage: ≥90% for modified code
- ✅ No linting errors or type checking failures
- ✅ All to_dict() outputs valid JSON

### Functional
- ✅ All 18 FR requirements implemented
- ✅ All 5 user stories testable
- ✅ All 8 SC success criteria met
- ✅ Backward compatibility verified (regression tests pass)

### Performance
- ✅ Parse time <5 seconds for 50,000 line programs
- ✅ Memory usage within baseline ±10%
- ✅ No infinite loops or stack overflows

### Documentation
- ✅ Spec file up-to-date with clarifications
- ✅ Baseline document complete
- ✅ Implementation plan documented
- ✅ Test patterns documented for future maintenance

---

## Appendix: Code Examples

### Example 1: PERFORM WITH TEST AFTER
```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-WITH-TEST.
       PROCEDURE DIVISION.
       MAIN.
           PERFORM PROCESS-RECORD WITH TEST AFTER UNTIL WS-EOF = 'Y'.
           STOP RUN.
       PROCESS-RECORD.
           DISPLAY 'Processing'.
           MOVE 'Y' TO WS-EOF.
```

**Expected AST**:
```json
{
  "node_type": "Statement",
  "statement_type": "PERFORM",
  "perform_type": "UNTIL",
  "target_paragraph": "PROCESS-RECORD",
  "test_timing": "AFTER",
  "until_condition": {...},
  "thru_paragraph": null,
  "times_count": null
}
```

### Example 2: PERFORM with Variable TIMES
```cobol
       PERFORM READ-FILE WS-RECORD-COUNT TIMES.
```

**Expected AST**:
```json
{
  "perform_type": "TIMES",
  "target_paragraph": "READ-FILE",
  "times_count": "WS-RECORD-COUNT"  // Note: string, not int
}
```

### Example 3: PERFORM VARYING with TEST
```cobol
       PERFORM VARYING I FROM 1 BY 1 
           WITH TEST AFTER 
           UNTIL I > 100
           MOVE I TO WS-INDEX
           CALL 'PROCESS' USING WS-INDEX
       END-PERFORM.
```

**Expected AST**:
```json
{
  "perform_type": "VARYING",
  "test_timing": "AFTER",
  "varying_clause": {
    "variable": "I",
    "from_value": 1,
    "by_value": 1
  },
  "until_condition": {...}
}
```

---

**Status**: Plan Complete - Ready for Implementation  
**Next Step**: Execute Phase 1 (Foundation) beginning with lexer changes
