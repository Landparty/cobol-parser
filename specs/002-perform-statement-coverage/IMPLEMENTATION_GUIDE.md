# Implementation Guide: Comprehensive PERFORM Statement Coverage

**Feature Branch**: `002-perform-statement-coverage`  
**Created**: January 11, 2026  
**Purpose**: Detailed step-by-step walkthrough with full traceability to specs, code locations, and tests  
**Integration**: Combines IMPLEMENTATION_PLAN.md, BASELINE.md, spec.md, and IMPLEMENTATION_AUDIT.md findings

---

## 📊 Quick Reference: Spec-to-Task Traceability Matrix

This matrix shows which task addresses which specification requirement. Use this to verify coverage.

| Spec Item | Type | Task | File | Lines | Tests | Status |
|-----------|------|------|------|-------|-------|--------|
| FR-006 | Lexer | 1.1, 2.1 | lexer.py, parser.py | 220-221, 355 | test_with_test_before, test_with_test_after | New |
| FR-007 | Model | 1.2 | statements.py | 113-180 | test_varying_union_types | Enhancement |
| FR-013 | Parser | 2.3c | parser.py | 3320-3340 | test_perform_times_variable | New |
| FR-016 | Parser | 2.3 | parser.py | 3200-3345 | test_perform_thru_until | New |
| FR-018 | Parser | 2.3 | parser.py | 3200-3345 | test_perform_thru_test_until | New |
| US-1 | Spec | - | spec.md | 30-60 | test_simple_perform | Existing |
| US-2 | Spec | - | spec.md | 65-95 | test_perform_times | Existing |
| US-3 | Spec | 2.1, 2.2, 2.3 | parser.py | 3200-3345 | test_perform_until_* | New |
| US-4 | Spec | 2.2, 2.3d | parser.py | 3200-3345 | test_perform_varying_* | Enhancement |
| SC-001 | Metric | 3.1, 3.2, 3.3 | tests/ | N/A | All tests | N/A |
| SC-002 | Metric | 3.1, 3.2, 3.3 | tests/ | N/A | All tests | N/A |

**Legend**: FR=Functional Requirement, US=User Story, SC=Success Criteria, New=New code, Enhancement=Modified existing

---

## 🎯 Implementation Checklist

Use this checklist to track progress through implementation. Mark items as you complete them.

### Phase 1: Foundation ⏱️ Estimated: 2.5 hours

- [ ] **Task 1.1**: Add TokenType.TEST to Lexer
  - [ ] Step 1.1.1: Open cobolparser/lexer.py
  - [ ] Step 1.1.2: Add TEST = auto() after AFTER
  - [ ] Step 1.1.3: Add 'TEST': TokenType.TEST to keywords
  - [ ] Step 1.1.4: Verify with test command
  - [ ] Step 1.1.5: Commit changes
  - **Addresses**: FR-006, US-3
  - **Tests**: test_lexer.py::test_keywords
  - **Baseline Gap Closed**: TokenType.TEST missing

- [ ] **Task 1.2**: Extend PerformStatement Model
  - [ ] Step 1.2.1: Add test_timing attribute to __init__()
  - [ ] Step 1.2.2: Change times_count to Union[int, str]
  - [ ] Step 1.2.3: Add set_test_timing() method
  - [ ] Step 1.2.4: Update set_times_clause() signature
  - [ ] Step 1.2.5: Update to_dict() method
  - [ ] Step 1.2.6: Verify with test command
  - [ ] Step 1.2.7: Commit changes
  - **Addresses**: FR-007, FR-013
  - **Tests**: test_statements.py::TestPerformStatement::*
  - **Baseline Gaps Closed**: test_timing, Union types

### Phase 2: Parser Enhancement ⏱️ Estimated: 6.5 hours

- [ ] **Task 2.1**: Add _parse_test_timing_clause() Helper
  - [ ] Step 2.1.1: Understand method pattern
  - [ ] Step 2.1.2: Add helper method to parser.py
  - [ ] Step 2.1.3: Write unit tests for helper
  - [ ] Step 2.1.4: Verify with test command
  - [ ] Step 2.1.5: Commit changes
  - **Addresses**: FR-006, US-3
  - **Tests**: test_parser.py::test_parse_test_timing_*
  - **Depends On**: Task 1.1

- [ ] **Task 2.2**: Add _parse_until_condition() Helper
  - [ ] Step 2.2.1: Add helper method to parser.py
  - [ ] Step 2.2.2: Write unit tests for helper
  - [ ] Step 2.2.3: Verify with test command
  - [ ] Step 2.2.4: Commit changes
  - **Addresses**: FR-016, US-3
  - **Tests**: test_parser.py::test_parse_until_condition_*
  - **Depends On**: Task 1.1

- [ ] **Task 2.3**: Enhance _parse_perform_inline() Main Method
  - [ ] Step 2.3a: Add standalone UNTIL support
  - [ ] Step 2.3b: Add WITH TEST support to Simple PERFORM
  - [ ] Step 2.3c: Add variable support to TIMES clause
  - [ ] Step 2.3d: Add WITH TEST support to VARYING
  - [ ] Step 2.3.5: Integration test all variants
  - [ ] Step 2.3.6: Verify with test command
  - [ ] Step 2.3.7: Commit changes
  - **Addresses**: FR-006, FR-013, FR-016, FR-018, US-3, US-4
  - **Tests**: test_perform_statement_coverage.py (integration)
  - **Depends On**: Task 2.1, Task 2.2

### Phase 3: Testing & Validation ⏱️ Estimated: 8 hours

- [ ] **Task 3.1**: Unit Tests - Model Extensions
  - [ ] Step 3.1.1: Add test_timing tests
  - [ ] Step 3.1.2: Add Union type tests
  - [ ] Step 3.1.3: Verify all pass
  - [ ] Step 3.1.4: Commit changes
  - **Files**: tests/unit/test_statements.py (60 lines added)
  - **Tests**: ~8 new test methods
  - **Depends On**: Task 1.2

- [ ] **Task 3.2**: Integration Tests - Parser Enhancements
  - [ ] Step 3.2.1: Create new integration test file
  - [ ] Step 3.2.2: Add PERFORM UNTIL tests
  - [ ] Step 3.2.3: Add TIMES with variable tests
  - [ ] Step 3.2.4: Add WITH TEST tests
  - [ ] Step 3.2.5: Add complex combination tests
  - [ ] Step 3.2.6: Verify all pass
  - [ ] Step 3.2.7: Commit changes
  - **Files**: tests/integration/test_perform_statement_coverage.py (new, ~300 lines)
  - **Tests**: ~20 new integration test methods
  - **Depends On**: Task 2.3

- [ ] **Task 3.3**: Regression Test Suite
  - [ ] Step 3.3.1: Create regression test file
  - [ ] Step 3.3.2: Add backward compatibility tests
  - [ ] Step 3.3.3: Verify all existing tests still pass
  - [ ] Step 3.3.4: Commit changes
  - **Files**: tests/regression/test_perform_backward_compat.py (new, ~150 lines)
  - **Tests**: ~6 regression test methods
  - **Depends On**: Task 3.1, Task 3.2

- [ ] **Task 3.4**: Performance Tests
  - [ ] Step 3.4.1: Create performance test file
  - [ ] Step 3.4.2: Add performance baseline tests
  - [ ] Step 3.4.3: Verify performance acceptable
  - [ ] Step 3.4.4: Commit changes
  - **Files**: tests/unit/test_perform_performance.py (new, ~80 lines)
  - **Tests**: ~2 performance test methods
  - **Depends On**: Task 3.2

### Phase 4: Quality Assurance ⏱️ Estimated: 3 hours

- [ ] **Task 4.1**: Code Quality Checks
  - [ ] Step 4.1.1: Run mypy on modified files
  - [ ] Step 4.1.2: Run ruff check on modified files
  - [ ] Step 4.1.3: Run black on modified files
  - [ ] Step 4.1.4: Verify all pass
  - **Commands**: See QA section below
  - **Pass Criteria**: 0 errors, 0 warnings

- [ ] **Task 4.2**: Regression Validation
  - [ ] Step 4.2.1: Run all existing PERFORM tests
  - [ ] Step 4.2.2: Run new regression suite
  - [ ] Step 4.2.3: Run full test suite
  - [ ] Step 4.2.4: Verify coverage ≥90%
  - **Commands**: See QA section below
  - **Pass Criteria**: All tests pass

- [ ] **Task 4.3**: Feature Validation
  - [ ] Step 4.3.1: Verify all FR addressed
  - [ ] Step 4.3.2: Verify all SC met
  - [ ] Step 4.3.3: Verify all US testable
  - **Commands**: Use traceability matrix above
  - **Pass Criteria**: 100% coverage

---

## 📍 Detailed Task Instructions with Code Locations

### Phase 1: Foundation

---

#### Task 1.1: Add TokenType.TEST to Lexer

**Spec Coverage**: FR-006 (WITH TEST support), US-3 (PERFORM UNTIL with test timing)  
**Baseline Gap Closed**: TokenType.TEST missing (prevents WITH TEST parsing)  
**Prerequisite**: None (foundational)

##### Step 1.1.1: Locate TokenType Enum in Lexer

**File**: `cobolparser/lexer.py`  
**Current State**: TokenType enum at line 22 with TokenType values  
**Baseline Reference**: [BASELINE.md - Current Test Coverage](BASELINE.md#current-lexer-implementation)

Open the file and find the TokenType enum:
```bash
# Verify lexer.py exists
test -f cobolparser/lexer.py && echo "✓ File found" || echo "✗ File not found"

# Find line number of BEFORE token
grep -n "BEFORE = auto()" cobolparser/lexer.py
# Expected output: 220:BEFORE = auto()
```

##### Step 1.1.2: Add TEST = auto() After AFTER

**File**: `cobolparser/lexer.py`  
**Location**: After line 220 (which contains `BEFORE = auto()`)

**Current Code Context** (lines 218-223):
```python
AFTER = auto()
BEFORE = auto()
DELETE = auto()
```

**Required Change**: Add one line after BEFORE:
```python
AFTER = auto()
BEFORE = auto()
TEST = auto()          # <-- ADD THIS LINE
DELETE = auto()
```

**Verification Command**:
```bash
grep -n "TEST = auto()" cobolparser/lexer.py
# Expected: 221:TEST = auto()
# If not found: Check line numbers, may have shifted
```

##### Step 1.1.3: Add 'TEST' to Keywords Dictionary

**File**: `cobolparser/lexer.py`  
**Location**: In the `keywords` dictionary (around line 355)

**Current Code Context** (lines 353-358):
```python
'WITH': TokenType.WITH,
'BEFORE': TokenType.BEFORE,
'AFTER': TokenType.AFTER,
'DELETE': TokenType.DELETE,
```

**Required Change**: Add one line in alphabetical order:
```python
'WITH': TokenType.WITH,
'BEFORE': TokenType.BEFORE,
'AFTER': TokenType.AFTER,
'TEST': TokenType.TEST,         # <-- ADD THIS LINE
'DELETE': TokenType.DELETE,
```

**Verification Command**:
```bash
grep -n "'TEST':" cobolparser/lexer.py
# Expected: 356:'TEST': TokenType.TEST,
```

##### Step 1.1.4: Test Token Recognition

**Test File**: `tests/unit/test_lexer.py`  
**Test to Run**:
```bash
cd C:\Users\sam94\workspace\cobol-parser
python -m pytest tests/unit/test_lexer.py::TestTokenizer::test_keywords -v
# Or if that method name differs:
python -m pytest tests/unit/ -k "test_token" -v | head -20
```

**Expected Result**: Tests pass, TEST token recognized

##### Step 1.1.5: Commit This Task

```bash
git add cobolparser/lexer.py
git commit -m "feat(lexer): add TokenType.TEST for WITH TEST clause support

- Add TEST to TokenType enum (line 221)
- Add 'TEST': TokenType.TEST to keywords dict (line 356)
- Enables parsing of PERFORM ... WITH TEST BEFORE/AFTER
- Addresses FR-006, supports US-3 PERFORM UNTIL with test timing"
```

---

#### Task 1.2: Extend PerformStatement Model

**Spec Coverage**: FR-007 (condition handling), FR-013 (variable TIMES), US-3, US-4  
**Baseline Gaps Closed**: test_timing attribute missing, times_count should be Union[int, str]  
**Prerequisite**: Task 1.1 (for testing WITH TEST attribute)

##### Step 1.2.1: Add test_timing Attribute to __init__()

**File**: `cobolparser/models/statements.py`  
**Class**: PerformStatement  
**Location**: Lines 113-130 (in __init__ method)

**Baseline Reference**: [BASELINE.md - PerformStatement Model](BASELINE.md#current-performstatement-model)

**Current Code** (lines 116-126):
```python
def __init__(self, location: SourceLocation):
    super().__init__("PerformStatement", location)
    self.perform_type: str = "SIMPLE"
    self.target_paragraph: Optional[str] = None
    self.thru_paragraph: Optional[str] = None
    self.times_count: Optional[int] = None
    self.until_condition: Optional[CobolExpression] = None
    self.varying_clause: Optional[Dict[str, Any]] = None
    self.inline_statements: List[CobolStatement] = []
```

**Required Changes**:

a) Change line 121 (`times_count` type):
```python
# FROM:
self.times_count: Optional[int] = None

# TO:
self.times_count: Optional[Union[int, str]] = None
```

b) Add new attribute after line 124:
```python
self.inline_statements: List[CobolStatement] = []
self.test_timing: Optional[str] = None  # <-- ADD THIS LINE
```

**Expected Code After Change** (lines 116-127):
```python
def __init__(self, location: SourceLocation):
    super().__init__("PerformStatement", location)
    self.perform_type: str = "SIMPLE"
    self.target_paragraph: Optional[str] = None
    self.thru_paragraph: Optional[str] = None
    self.times_count: Optional[Union[int, str]] = None  # CHANGED: Added str
    self.until_condition: Optional[CobolExpression] = None
    self.varying_clause: Optional[Dict[str, Any]] = None
    self.inline_statements: List[CobolStatement] = []
    self.test_timing: Optional[str] = None  # ADDED: New attribute
```

**Verification**:
```bash
python -c "
from cobolparser.models.statements import PerformStatement
from cobolparser.models.ast_base import SourceLocation
ps = PerformStatement(SourceLocation(1,1))
assert hasattr(ps, 'test_timing'), 'test_timing not found'
assert ps.test_timing is None, 'test_timing should default to None'
assert ps.times_count is None, 'times_count should default to None'
print('✓ Both attributes present and initialized correctly')
"
```

##### Step 1.2.2: Add set_test_timing() Method

**File**: `cobolparser/models/statements.py`  
**Class**: PerformStatement  
**Location**: After existing set_* methods (around line 155)

**Baseline Reference**: [BASELINE.md - Methods Currently Implemented](BASELINE.md#methods-currently-implemented)

**Add this method** (after `set_until_clause()`, before `set_varying_clause()`):
```python
def set_test_timing(self, timing: str) -> None:
    """Set WITH TEST timing qualifier (BEFORE or AFTER).
    
    Args:
        timing: "BEFORE" or "AFTER" for WITH TEST timing
        
    Raises:
        ValueError: If timing not in ("BEFORE", "AFTER")
        
    Maps to Spec: FR-006 (WITH TEST support)
    """
    timing_upper = timing.upper() if timing else ""
    if timing_upper not in ("BEFORE", "AFTER"):
        raise ValueError(f"Invalid timing '{timing}': must be BEFORE or AFTER")
    self.test_timing = timing_upper
```

**Verification**:
```bash
python -c "
from cobolparser.models.statements import PerformStatement
from cobolparser.models.ast_base import SourceLocation
ps = PerformStatement(SourceLocation(1,1))
ps.set_test_timing('BEFORE')
assert ps.test_timing == 'BEFORE'
ps.set_test_timing('AFTER')
assert ps.test_timing == 'AFTER'
print('✓ set_test_timing() works correctly')
"
```

##### Step 1.2.3: Update set_times_clause() for Union Type

**File**: `cobolparser/models/statements.py`  
**Class**: PerformStatement  
**Location**: Around line 145 (existing method)

**Current Code**:
```python
def set_times_clause(self, count: int) -> None:
    """Set TIMES clause for the PERFORM."""
    self.perform_type = "TIMES"
    self.times_count = count
```

**Required Change**: Update to accept Union[int, str]:
```python
def set_times_clause(self, count: Union[int, str]) -> None:
    """Set TIMES clause for the PERFORM.
    
    Args:
        count: int for literal (e.g., 10) or str for variable (e.g., "WS-COUNT")
        
    Maps to Spec: FR-013 (literal vs variable TIMES)
    """
    self.perform_type = "TIMES"
    self.times_count = count
```

**Verification**:
```bash
python -c "
from cobolparser.models.statements import PerformStatement
from cobolparser.models.ast_base import SourceLocation
ps = PerformStatement(SourceLocation(1,1))
# Test with int
ps.set_times_clause(10)
assert ps.times_count == 10 and isinstance(ps.times_count, int)
# Test with str
ps.set_times_clause('WS-COUNT')
assert ps.times_count == 'WS-COUNT' and isinstance(ps.times_count, str)
print('✓ set_times_clause() accepts both int and str')
"
```

##### Step 1.2.4: Update to_dict() Method

**File**: `cobolparser/models/statements.py`  
**Class**: PerformStatement  
**Location**: Around line 170 (existing method)

**Current Code** (lines 170-180, example):
```python
def to_dict(self) -> Dict[str, Any]:
    """Convert to dictionary representation."""
    result = super().to_dict()
    result.update({
        "perform_type": self.perform_type,
        "target_paragraph": self.target_paragraph,
        "thru_paragraph": self.thru_paragraph,
        "times_count": self.times_count,
        "until_condition": self.until_condition.to_dict() if self.until_condition else None,
        "varying_clause": self.varying_clause,
        "inline_statements": [s.to_dict() for s in self.inline_statements],
    })
    return result
```

**Required Change**: Add test_timing to the dict:
```python
def to_dict(self) -> Dict[str, Any]:
    """Convert to dictionary representation."""
    result = super().to_dict()
    result.update({
        "perform_type": self.perform_type,
        "target_paragraph": self.target_paragraph,
        "thru_paragraph": self.thru_paragraph,
        "times_count": self.times_count,
        "test_timing": self.test_timing,  # <-- ADD THIS LINE
        "until_condition": self.until_condition.to_dict() if self.until_condition else None,
        "varying_clause": self.varying_clause,
        "inline_statements": [s.to_dict() for s in self.inline_statements],
    })
    return result
```

**Verification**:
```bash
python -c "
from cobolparser.models.statements import PerformStatement
from cobolparser.models.ast_base import SourceLocation
ps = PerformStatement(SourceLocation(1,1))
ps.set_test_timing('AFTER')
ps.set_times_clause('WS-COUNT')
d = ps.to_dict()
assert 'test_timing' in d, 'test_timing not in dict'
assert d['test_timing'] == 'AFTER', f'Expected AFTER, got {d[\"test_timing\"]}'
assert d['times_count'] == 'WS-COUNT', f'Expected WS-COUNT, got {d[\"times_count\"]}'
print('✓ to_dict() includes new attributes')
import json
json.dumps(d)  # Verify JSON serializable
print('✓ to_dict() output is JSON serializable')
"
```

##### Step 1.2.5: Verify Type Hints (Add Union Import if Needed)

**File**: `cobolparser/models/statements.py`  
**Location**: Top of file (imports section)

Check if Union is imported:
```bash
grep "from typing import" cobolparser/models/statements.py | head -3
# Should see line with Union
```

If not present, add to imports:
```python
from typing import Dict, List, Optional, Union, Any
#                                    ^^^^^ <- Add Union here
```

##### Step 1.2.6: Run Tests for Model Changes

```bash
cd C:\Users\sam94\workspace\cobol-parser

# Run PerformStatement tests
python -m pytest tests/unit/test_statements.py::TestPerformStatement -v

# If tests don't exist yet, run general model tests
python -m pytest tests/unit/test_statements.py -v -k perform
```

**Expected**: All tests pass (or show what new tests are needed)

##### Step 1.2.7: Commit Task 1.2

```bash
git add cobolparser/models/statements.py
git commit -m "feat(model): enhance PerformStatement for test timing and Union types

Changes:
- Add test_timing: Optional[str] attribute (supports BEFORE/AFTER)
- Change times_count to Union[int, str] (supports variable names)
- Add set_test_timing() method with validation
- Update set_times_clause() to accept Union types
- Update to_dict() to include test_timing in serialization

Addresses: FR-007, FR-013
Closes BASELINE gaps: test_timing attribute, Union types"
```

---

### Phase 2: Parser Enhancement

---

#### Task 2.1: Add _parse_test_timing_clause() Helper

**Spec Coverage**: FR-006 (WITH TEST support), US-3 (PERFORM UNTIL)  
**Implementation Location**: `cobolparser/parser.py`, new helper method  
**Prerequisite**: Task 1.1 (TokenType.TEST added)  
**Enables**: Task 2.3 (main PERFORM parsing uses this helper)

##### Step 2.1.1: Understand Parser Pattern

**File**: `cobolparser/parser.py`  
**Reference**: Existing helper methods around line 3350+

Look at existing helper patterns:
```bash
grep -n "def _parse_inline_call_into_perform" cobolparser/parser.py
# Should find around line 3352
```

Helper methods in the parser:
- Return tuples: `(parsed_value, next_token_index)`
- Accept `(tokens, current_index)` as parameters
- Handle newlines with `while tokens[i].type == TokenType.NEWLINE`
- Are placed after main parsing method

##### Step 2.1.2: Add _parse_test_timing_clause() Helper

**File**: `cobolparser/parser.py`  
**Location**: After `_parse_perform_inline()` method ends (around line 3345)

**Add this method**:
```python
def _parse_test_timing_clause(self, tokens: List[Token], i: int) -> Tuple[Optional[str], int]:
    """Parse optional WITH TEST [BEFORE | AFTER] clause.
    
    Parses: WITH TEST BEFORE | WITH TEST AFTER
    
    Args:
        tokens: Token list from lexer
        i: Current position in token stream
        
    Returns:
        Tuple of (timing_str, next_index) where:
        - timing_str: "BEFORE", "AFTER", or None if not present
        - next_index: Position after clause
        
    Maps to Spec: FR-006 (WITH TEST support)
    Links to: Task 2.3 (used by _parse_perform_inline)
    """
    if i >= len(tokens):
        return None, i
    
    # Skip newlines
    while i < len(tokens) and tokens[i].type == TokenType.NEWLINE:
        i += 1
    
    if i >= len(tokens) or not tokens[i].value or tokens[i].value.upper() != "WITH":
        return None, i
    
    # Found WITH, skip it
    i += 1
    
    # Skip newlines after WITH
    while i < len(tokens) and tokens[i].type == TokenType.NEWLINE:
        i += 1
    
    if i >= len(tokens) or not tokens[i].value or tokens[i].value.upper() != "TEST":
        # WITH without TEST - malformed, back up
        return None, i - 1
    
    # Found TEST, skip it
    i += 1
    
    # Skip newlines after TEST
    while i < len(tokens) and tokens[i].type == TokenType.NEWLINE:
        i += 1
    
    # Get BEFORE or AFTER (or default to BEFORE)
    if i >= len(tokens) or not tokens[i].value:
        return "BEFORE", i
    
    timing_value = tokens[i].value.upper()
    if timing_value in ("BEFORE", "AFTER"):
        return timing_value, i + 1
    
    # Default to BEFORE if not specified
    return "BEFORE", i
```

**Verification - Method Exists**:
```bash
grep -n "def _parse_test_timing_clause" cobolparser/parser.py
# Should find the method
```

##### Step 2.1.3: Test the Helper Method

Create a simple unit test to verify the helper works:

```bash
python -c "
from cobolparser.lexer import CobolLexer, TokenType
from cobolparser.parser import CobolParser

# Test parsing 'WITH TEST BEFORE'
lexer = CobolLexer()
tokens = lexer.tokenize('WITH TEST BEFORE')
parser = CobolParser()

# The helper method should exist
assert hasattr(parser, '_parse_test_timing_clause'), 'Method not found'

# Test with mock tokens
result = parser._parse_test_timing_clause(tokens, 0)
assert result[0] is not None, 'Should parse WITH TEST clause'
print('✓ _parse_test_timing_clause() helper works')
"
```

##### Step 2.1.4: Commit Task 2.1

```bash
git add cobolparser/parser.py
git commit -m "feat(parser): add _parse_test_timing_clause() helper method

- New helper to parse WITH TEST BEFORE/AFTER clause
- Returns tuple: (timing_str, next_index)
- Handles newlines and error recovery
- Used by _parse_perform_inline() in subsequent tasks

Addresses: FR-006
Links to: Task 2.3 (main PERFORM parsing enhancement)"
```

---

#### Task 2.2: Add _parse_until_condition() Helper

**Spec Coverage**: FR-016 (THRU + UNTIL), US-3 (PERFORM UNTIL)  
**Implementation Location**: `cobolparser/parser.py`, new helper method  
**Prerequisite**: Task 1.1 (lexer changes)  
**Enables**: Task 2.3 (main PERFORM parsing uses this helper)

##### Step 2.2.1: Add _parse_until_condition() Helper

**File**: `cobolparser/parser.py`  
**Location**: After `_parse_test_timing_clause()` (around line 3390)

**Add this method**:
```python
def _parse_until_condition(self, tokens: List[Token], i: int, 
                          stop_keywords: Optional[List[str]] = None) -> Tuple[Optional['ConditionalExpression'], int]:
    """Parse UNTIL condition expression.
    
    Parses condition between UNTIL and newline/END-PERFORM/stop keyword.
    
    Args:
        tokens: Token list from lexer
        i: Current position (should be after UNTIL keyword)
        stop_keywords: Keywords that end the condition
        
    Returns:
        Tuple of (condition_expr, next_index)
        
    Maps to Spec: FR-016 (UNTIL support in various contexts)
    Links to: Task 2.3 (used by _parse_perform_inline)
    """
    if stop_keywords is None:
        stop_keywords = ["END-PERFORM", "ELSE", "END-IF"]
    
    cond_tokens = []
    while i < len(tokens):
        token = tokens[i]
        
        # Stop at newline
        if token.type == TokenType.NEWLINE:
            break
        
        # Stop at stop keywords
        if token.value and token.value.upper() in stop_keywords:
            break
        
        # Collect token value
        if token.value:
            cond_tokens.append(token.value)
        
        i += 1
    
    # Build condition expression from collected tokens
    condition_text = " ".join(cond_tokens).strip()
    
    if condition_text:
        # Use existing condition creation pattern from IF statement parsing
        from cobolparser.models.expressions import ConditionalExpression
        condition_expr = ConditionalExpression(
            "COMPARISON",
            tokens[i-1].location if i > 0 else tokens[0].location
        )
        condition_expr._metadata["value"] = condition_text
        return condition_expr, i
    
    return None, i
```

**Verification - Method Exists**:
```bash
grep -n "def _parse_until_condition" cobolparser/parser.py
# Should find the method
```

##### Step 2.2.2: Test the Helper Method

```bash
python -c "
from cobolparser.lexer import CobolLexer
from cobolparser.parser import CobolParser

lexer = CobolLexer()
tokens = lexer.tokenize('WS-EOF = \"Y\"')
parser = CobolParser()

assert hasattr(parser, '_parse_until_condition'), 'Method not found'
print('✓ _parse_until_condition() helper added')
"
```

##### Step 2.2.3: Commit Task 2.2

```bash
git add cobolparser/parser.py
git commit -m "feat(parser): add _parse_until_condition() helper method

- New helper to parse UNTIL condition expressions
- Collects tokens until newline or stop keyword
- Returns ConditionalExpression object
- Handles multi-line condition scenarios

Addresses: FR-016
Links to: Task 2.3 (main PERFORM parsing enhancement)"
```

---

#### Task 2.3: Enhance _parse_perform_inline() Main Method

**Spec Coverage**: FR-006, FR-013, FR-016, FR-018, US-3, US-4  
**Implementation Location**: `cobolparser/parser.py`, lines 3200-3345  
**Prerequisite**: Task 2.1, Task 2.2 (helpers created)  
**Depends On**: Task 1.1, Task 1.2 (lexer and model changes)

##### Step 2.3a: Add Standalone UNTIL Support

**File**: `cobolparser/parser.py`  
**Method**: `_parse_perform_inline()`  
**Current Location**: Lines 3312-3344 (Simple PERFORM branch)

**Context**: After checking for VARYING keyword, add check for standalone UNTIL

**Find Location**: Search for the simple PERFORM section:
```bash
grep -n "# Simple PERFORM" cobolparser/parser.py | head -1
# Should find around line 3312
```

**Code to Add** (insert after VARYING check, before THRU/TIMES parsing):
```python
        # Check for standalone UNTIL (not in VARYING context)
        # Addresses: FR-016 (PERFORM UNTIL support)
        if not found_varying and i < len(tokens):
            # Skip newlines
            saved_i = i
            while i < len(tokens) and tokens[i].type == TokenType.NEWLINE:
                i += 1
            
            if i < len(tokens) and tokens[i].value and tokens[i].value.upper() == 'UNTIL':
                # Found PERFORM ... UNTIL (no THRU, no TIMES)
                i += 1  # Skip UNTIL
                condition, i = self._parse_until_condition(tokens, i)
                pf.set_until_clause(condition)
                
                # Check for optional WITH TEST clause
                timing, i = self._parse_test_timing_clause(tokens, i)
                if timing:
                    pf.set_test_timing(timing)
                
                return i
            else:
                # Not UNTIL, restore position
                i = saved_i
```

**Verification**: This enables parsing `PERFORM PARA UNTIL condition`

##### Step 2.3b: Add WITH TEST Support to Simple PERFORM

**File**: `cobolparser/parser.py`  
**Method**: `_parse_perform_inline()`  
**Location**: After THRU paragraph parsing, before TIMES check

**Context**: In the Simple PERFORM path, after extracting thru_paragraph

**Code to Add** (after THRU check, before TIMES section):
```python
        # Check for WITH TEST clause (BEFORE or AFTER)
        # Addresses: FR-006 (WITH TEST support)
        timing, i = self._parse_test_timing_clause(tokens, i)
        if timing:
            pf.set_test_timing(timing)
            # Skip newlines after WITH TEST clause
            while i < len(tokens) and tokens[i].type == TokenType.NEWLINE:
                i += 1
```

**Verification**: This enables parsing `PERFORM PARA WITH TEST BEFORE UNTIL condition`

##### Step 2.3c: Add Variable Support to TIMES Clause

**File**: `cobolparser/parser.py`  
**Method**: `_parse_perform_inline()`  
**Current Location**: Around line 3334 (TIMES count parsing)

**Current Code** (lines 3332-3340, approximate):
```python
        if i < len(tokens) and tokens[i].type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER):
            try:
                times_count = int(tokens[i].value)
                i += 1
                pf.set_times_clause(times_count)
            except ValueError:
                # Handle error
                pass
```

**Required Change** - Replace with version that accepts variables:
```python
        # Parse TIMES count (can be literal or variable name)
        # Addresses: FR-013 (literal vs variable TIMES)
        if i < len(tokens) and tokens[i].type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER, TokenType.IDENTIFIER):
            times_value = tokens[i].value
            i += 1
            
            # Skip newlines before TIMES keyword
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

**Verification**: This enables parsing:
- `PERFORM PARA 10 TIMES` (existing, still works)
- `PERFORM PARA WS-COUNT TIMES` (new, variable reference)

##### Step 2.3d: Add WITH TEST Support to VARYING

**File**: `cobolparser/parser.py`  
**Method**: `_parse_perform_inline()`  
**Current Location**: VARYING branch (around line 3310)

**Context**: After extracting all VARYING components, check for optional WITH TEST

**Code to Add** (after VARYING clause fully parsed, before returning):
```python
        # Check for optional WITH TEST AFTER in VARYING clause
        # Addresses: FR-018 (VARYING with WITH TEST support)
        timing, i = self._parse_test_timing_clause(tokens, i)
        if timing:
            pf.set_test_timing(timing)
```

**Verification**: This enables parsing:
- `PERFORM VARYING I FROM 1 BY 1 UNTIL I > 10 END-PERFORM` (existing)
- `PERFORM VARYING I FROM 1 BY 1 WITH TEST AFTER UNTIL I > 10 END-PERFORM` (new)

##### Step 2.3.5: Run Integration Tests

```bash
cd C:\Users\sam94\workspace\cobol-parser
python -m pytest tests/integration/ -v -k perform
# Should see existing tests still pass
```

##### Step 2.3.6: Commit Task 2.3

```bash
git add cobolparser/parser.py
git commit -m "feat(parser): enhance _parse_perform_inline() for comprehensive PERFORM support

Enhancements:
- 2.3a: Add standalone UNTIL support (FR-016)
- 2.3b: Add WITH TEST to Simple PERFORM (FR-006)
- 2.3c: Accept variable names in TIMES clause (FR-013)
- 2.3d: Add WITH TEST to VARYING clause (FR-018)

Enables parsing of:
- PERFORM PARA UNTIL condition
- PERFORM PARA WITH TEST BEFORE/AFTER UNTIL condition
- PERFORM PARA WS-COUNT TIMES (variable reference)
- PERFORM VARYING ... WITH TEST AFTER UNTIL ... END-PERFORM

Addresses: FR-006, FR-013, FR-016, FR-018
Depends on: Task 2.1, Task 2.2 (helpers)"
```

---

### Phase 3: Testing & Validation

Complete test specifications will be provided in a separate comprehensive test file document. See: [TEST_SPECIFICATIONS.md](TEST_SPECIFICATIONS.md) (to be created)

For now, quick reference:

#### Task 3.1: Unit Tests (Model Extensions)

**File**: `tests/unit/test_statements.py`  
**Add to**: Class `TestPerformStatement` (existing class, lines 349+)  
**Tests to Add**: ~8 new test methods covering:
- `test_perform_statement_test_timing()` - test_timing attribute
- `test_perform_times_with_int()` - backward compat
- `test_perform_times_with_variable()` - Union[int, str]
- `test_perform_to_dict_with_test_timing()` - serialization

#### Task 3.2: Integration Tests (Parser Enhancements)

**File**: `tests/integration/test_perform_statement_coverage.py` (new file)  
**Size**: ~300 lines  
**Tests to Add**: ~20 integration test methods covering:
- PERFORM UNTIL variants
- TIMES with variable references
- WITH TEST clause parsing
- Complex combinations (THRU + UNTIL + TEST)

#### Task 3.3: Regression Tests

**File**: `tests/regression/test_perform_backward_compat.py` (new file)  
**Size**: ~150 lines  
**Tests to Add**: ~6 regression test methods verifying:
- All existing PERFORM patterns still work
- No breaking changes to API
- Backward compatibility with int-only times_count

#### Task 3.4: Performance Tests

**File**: `tests/unit/test_perform_performance.py` (new file)  
**Size**: ~80 lines  
**Tests to Add**: ~2 performance test methods:
- Parse time for large programs with many PERFORMs
- Memory usage validation

---

### Phase 4: Quality Assurance

#### Task 4.1: Code Quality Checks

```bash
cd C:\Users\sam94\workspace\cobol-parser

# Type checking
echo "=== Running mypy ==="
mypy cobolparser/parser.py cobolparser/models/statements.py

# Linting
echo "=== Running ruff ==="
ruff check cobolparser/parser.py cobolparser/models/statements.py cobolparser/lexer.py

# Code formatting
echo "=== Running black ==="
black cobolparser/parser.py cobolparser/models/statements.py cobolparser/lexer.py

# Full test suite
echo "=== Running pytest ==="
pytest tests/ --cov=cobolparser --cov-fail-under=90 -v
```

#### Task 4.2: Regression Validation

```bash
cd C:\Users\sam94\workspace\cobol-parser

# Run all existing PERFORM tests (should all pass)
echo "=== Existing PERFORM Tests ==="
pytest tests/unit/test_statements.py::TestPerformStatement -v
pytest tests/unit/test_perform_thru.py -v
pytest tests/integration/test_perform_until_nested.py -v

# Run new regression suite
echo "=== Regression Tests ==="
pytest tests/regression/test_perform_backward_compat.py -v

# Full test coverage report
echo "=== Coverage Report ==="
pytest tests/ --cov=cobolparser --cov-report=term-missing | grep -E "(TOTAL|cobolparser)"
```

#### Task 4.3: Feature Validation

Use the traceability matrix at the top of this guide to verify:
1. ✅ All FR (FR-001 through FR-018) addressed
2. ✅ All SC (SC-001 through SC-008) met
3. ✅ All US (US-1 through US-5) testable
4. ✅ All spec gaps from BASELINE.md closed

---

## 🔗 Cross-Reference Guide

### Finding Information by Need

**"I need to understand what FR-006 means"**
→ See [spec.md](spec.md) lines 120-140 (Functional Requirements section)

**"Where does FR-006 get implemented?"**
→ See traceability matrix above: Task 1.1, 2.1, 2.3b

**"What's the current baseline for test_timing?"**
→ See [BASELINE.md](BASELINE.md#missing-attributes-per-spec-clarifications)

**"How do I add test_timing to PerformStatement?"**
→ See this guide, Section "Task 1.2: Extend PerformStatement Model"

**"What tests validate test_timing?"**
→ See Task 3.1 (Unit Tests), test method `test_perform_statement_test_timing()`

**"What COBOL example uses WITH TEST BEFORE?"**
→ See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md#example-1-perform-with-test-after) lines 680+

**"What's the risk of this change?"**
→ See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md#risk-analysis--mitigation) Risk Analysis section

**"Are we done implementing FR-006?"**
→ Check traceability matrix: Task 1.1 ✓, Task 2.1 ✓, Task 2.3b ✓ = Done

---

## 🚨 Troubleshooting Guide

### Common Mistakes During Implementation

#### Problem 1: Union Type Import Missing
**Symptom**: `NameError: name 'Union' is not defined`  
**Cause**: Forgot to import Union from typing  
**Solution**: 
```bash
# Check imports in statements.py
grep "from typing import" cobolparser/models/statements.py

# Should see Union in the list. If not, add it:
# FROM: from typing import Dict, List, Optional, Any
# TO:   from typing import Dict, List, Optional, Union, Any
```

#### Problem 2: TokenType.TEST Not Recognized
**Symptom**: Parser doesn't recognize "WITH TEST" in COBOL programs  
**Cause**: TokenType.TEST added to enum but not to keywords dictionary  
**Solution**:
```bash
# Verify both changes exist
grep "TEST = auto()" cobolparser/lexer.py
grep "'TEST':" cobolparser/lexer.py

# Both should return results. If one is missing, add it.
```

#### Problem 3: _parse_test_timing_clause() Not Called
**Symptom**: WITH TEST clause in COBOL but test_timing not set in AST  
**Cause**: Helper method exists but never called from _parse_perform_inline()  
**Solution**:
```bash
# Check if helper is called (should see at least 2 calls)
grep "_parse_test_timing_clause" cobolparser/parser.py | grep -v "def _parse_test_timing"

# If only shows def, add calls in _parse_perform_inline():
# For Simple PERFORM: after THRU check
# For VARYING: after varying clause parsed
```

#### Problem 4: times_count as Union Type But Still Only Accepts Int
**Symptom**: `PERFORM PARA WS-COUNT TIMES` fails with error  
**Cause**: Type changed but parser code not updated to pass string  
**Solution**:
```bash
# Verify parser code at line ~3334 checks for IDENTIFIER token:
grep -A 10 "NUMERIC_LITERAL, TokenType.LEVEL_NUMBER" cobolparser/parser.py | head -15

# Should see: TokenType.IDENTIFIER in the type check
# If not, add it to support variable names
```

#### Problem 5: Tests Still Failing After Changes
**Symptom**: Regression tests pass but new tests fail  
**Cause**: Implementation incomplete or test expectations wrong  
**Solution**:
```bash
# Run specific failing test with verbose output
pytest tests/unit/test_statements.py::TestPerformStatement::test_perform_statement_test_timing -vv

# Compare expected vs actual
# Check if test needs updating based on new behavior
```

#### Problem 6: Performance Degraded
**Symptom**: Parse time significantly slower after changes  
**Cause**: Inefficient token scanning in new helper methods  
**Solution**:
```bash
# Run performance test with baseline
pytest tests/unit/test_perform_performance.py -v

# Compare parse times with baseline (should be <5% slower)
# If significantly slower, check for:
# - Unnecessary while loops
# - Repeated token scanning
# - Inefficient string operations
```

---

## ✅ Completion Checklist - Final Validation

Before declaring the feature complete:

- [ ] All 4 phases completed (Foundation, Parser, Testing, QA)
- [ ] All 12 tasks marked as done in todo list
- [ ] Traceability matrix shows 100% spec coverage
- [ ] All 30+ existing PERFORM tests still pass
- [ ] All new tests pass (unit + integration + regression)
- [ ] Code coverage ≥90% for modified files
- [ ] No type checking errors (`mypy` passes)
- [ ] No linting errors (`ruff check` passes)
- [ ] Code formatted correctly (`black` passes)
- [ ] Performance within acceptable bounds (<5% slower)
- [ ] No breaking changes to public API
- [ ] Feature branch has clean git history with meaningful commits
- [ ] Documentation updated (spec.md, BASELINE.md, this guide)

**Final Validation Command**:
```bash
cd C:\Users\sam94\workspace\cobol-parser

# All-in-one validation
echo "=== TYPE CHECK ===" && \
mypy cobolparser/parser.py cobolparser/models/statements.py && \
echo "✓ Type check passed" && \

echo "=== LINT CHECK ===" && \
ruff check cobolparser/parser.py cobolparser/models/statements.py cobolparser/lexer.py && \
echo "✓ Lint check passed" && \

echo "=== FORMAT CHECK ===" && \
black --check cobolparser/parser.py cobolparser/models/statements.py cobolparser/lexer.py && \
echo "✓ Format check passed" && \

echo "=== TESTS ===" && \
pytest tests/ --cov=cobolparser --cov-fail-under=90 -q && \
echo "✓ All tests passed" && \

echo "" && \
echo "✅ FEATURE IMPLEMENTATION COMPLETE"
```

---

**Integration Complete**: This guide combines IMPLEMENTATION_PLAN.md, BASELINE.md, spec.md, and audit findings into a single executable roadmap with full traceability between specifications, tasks, code locations, and tests.

**Next Step**: Begin with Task 1.1 (Add TokenType.TEST to Lexer) using the detailed instructions above.
