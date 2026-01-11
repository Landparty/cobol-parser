# Implementation Tasks: Comprehensive PERFORM Statement Coverage

**Feature**: PERFORM Statement Coverage for COBOL Fixed Format  
**Feature Branch**: `002-perform-statement-coverage`  
**Created**: January 11, 2026  
**Total Tasks**: 12 + Quality Assurance  
**Estimated Duration**: ~19 hours  
**Status**: Ready for Implementation

---

## 📋 Document Linkage

- **Specification**: [spec.md](spec.md) (18 FR, 5 US, 8 SC)
- **Baseline Analysis**: [BASELINE.md](BASELINE.md) (Current state gaps)
- **Implementation Plan**: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) (Strategic overview)
- **Step-by-Step Guide**: [IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md) (Detailed instructions with line numbers)
- **Test Specifications**: [TEST_SPECIFICATIONS.md](TEST_SPECIFICATIONS.md) (44 test methods)
- **Architecture**: [DOCUMENTATION_INTEGRATION.md](DOCUMENTATION_INTEGRATION.md) (Traceability model)

---

## 🎯 MVP Scope (Recommended)

**Minimum Viable Product**: Complete User Story 1 (Simple PERFORM Paragraph Execution)

This provides the foundation for all other stories:
- Tasks 1.1, 1.2 (Foundation)
- Task 2.1 (UNTIL condition parsing - partial)
- Task 3.1 (Unit tests for model)
- Task 4.1, 4.2 (Quality checks)

**Estimated MVP Time**: 4-5 hours  
**Incremental Completion**: After MVP, add US-2, then US-3, then US-4, then US-5

---

## 📦 Dependency Graph

```
Phase 1 (Foundation)
  ├─ Task 1.1: Add TokenType.TEST [2h]
  └─ Task 1.2: Extend PerformStatement [1.5h]
       ↓
Phase 2 (Parser Enhancement)
  ├─ Task 2.1: Add _parse_test_timing_clause() [1.5h]
  │    ├─ depends on: Task 1.1
  │    ↓
  ├─ Task 2.2: Add _parse_until_condition() [2h]
  │    ├─ depends on: Task 1.1
  │    ↓
  └─ Task 2.3: Enhance _parse_perform_inline() [3.5h]
       ├─ depends on: Task 2.1, 2.2

Phase 3 (Testing)
  ├─ Task 3.1: Unit Tests [2h] (depends on: Task 1.2)
  ├─ Task 3.2: Integration Tests [2.5h] (depends on: Task 2.3)
  ├─ Task 3.3: Regression Tests [1.5h] (depends on: Task 3.1, 3.2)
  └─ Task 3.4: Performance Tests [1h] (depends on: Task 3.2)

Phase 4 (Quality Assurance)
  ├─ Task 4.1: Code Quality [1h] (depends on: Task 2.3)
  └─ Task 4.2: Regression Validation [1h] (depends on: Task 3.3)
```

---

## 🔄 Parallelizable Tasks

Tasks that can be worked on simultaneously (different files, no blocking dependencies):

- **Phase 1**: Task 1.1 and 1.2 can be done in parallel (independent files)
- **Phase 2**: Task 2.1 and 2.2 can be done in parallel (separate helper methods)
- **Phase 3**: Tasks 3.1 and 3.2 can start in parallel once 1.2 and 2.3 complete
- **Phase 4**: Tasks 4.1 and 4.2 can be done in parallel

**Parallel Execution Example**:
```
Timeline: Sequential (Dependency-constrained)
1. Task 1.1 + 1.2 in parallel (2h)
2. Task 2.1 + 2.2 in parallel (2h)
3. Task 2.3 (3.5h)
4. Task 3.1 + 3.2 in parallel (2.5h)
5. Task 3.3 + 3.4 (2.5h)
6. Task 4.1 + 4.2 in parallel (1h)
Total: ~14 hours (vs 19 sequential)
```

---

# 🚀 PHASE 1: Foundation

**Duration**: ~2.5 hours  
**Goal**: Prepare lexer and data model for test timing and variable iteration counts

---

## Task 1.1: Add TokenType.TEST to Lexer

**Priority**: P1 [US-3]  
**Addresses**: FR-006 (Lexer support for WITH TEST), FR-009 (UNTIL clause parsing)  
**Tests**: [test_lexer.py::test_keywords](TEST_SPECIFICATIONS.md#test_keywords)  
**Baseline Gap**: TokenType.TEST not defined  

- [X] T001 Open cobolparser/lexer.py and locate TokenType enum (line ~220)
  - File: `cobolparser/lexer.py`
  - Current location: Lines 215-230 (enum definitions)
  - Task: Read current TokenType entries to understand structure

- [X] T002 Add TEST = auto() to TokenType enum after AFTER token
  - File: `cobolparser/lexer.py`
  - Location: Line ~225 (insert after AFTER = auto())
  - Change: 1 line addition
  - Verification: `grep -n "TEST = auto()" cobolparser/lexer.py`

- [X] T003 Add 'TEST' keyword to keywords dictionary (line ~355)
  - File: `cobolparser/lexer.py`
  - Location: Line ~365 (in KEYWORDS dict)
  - Change: Add line `'TEST': TokenType.TEST,`
  - Verification: `python -c "from cobolparser.lexer import KEYWORDS; print('TEST' in KEYWORDS)"`

- [X] T004 Run lexer tests to verify TokenType.TEST is recognized
  - Command: `python -m pytest tests/unit/test_lexer.py::test_keywords -v`
  - Expected: All keyword tests pass, TEST token recognized
  - Failure handling: Check for typos in keyword name or TokenType enum

- [X] T005 Commit changes to git
  - Command: `git add cobolparser/lexer.py && git commit -m "Add TokenType.TEST for WITH TEST clause support"`

**Time Estimate**: 1 hour  
**Blocking Other Tasks**: Task 2.1, Task 2.2

---

## Task 1.2: Extend PerformStatement Model for Test Timing and Variable TIMES

**Priority**: P1 [US-2, US-3, US-4]  
**Addresses**: FR-007 (test_timing attribute), FR-013 (Variable TIMES), FR-016 (UNTIL clause), FR-018 (UNTIL with test timing)  
**Tests**: [test_statements.py::TestPerformStatement](TEST_SPECIFICATIONS.md#unit_tests_phase1)  
**Baseline Gap**: test_timing attribute missing, times_count is int only (needs Union[int, str])

- [X] T006 Open cobolparser/models/statements.py and locate PerformStatement class (line 113)
  - File: `cobolparser/models/statements.py`
  - Current location: Lines 113-180 (PerformStatement class definition)
  - Task: Review current __init__ method and attributes

- [X] T007 [P] Add test_timing attribute to PerformStatement.__init__()
  - File: `cobolparser/models/statements.py`
  - Location: Line ~120 (in __init__ parameter list and assignments)
  - Change: 
    - Add parameter: `test_timing: str = "BEFORE"` to __init__ signature
    - Add assignment: `self.test_timing = test_timing`
  - Context Before:
    ```python
    def __init__(self, 
                 perform_type: str,
                 target_paragraph: Optional[str] = None,
                 location: Optional[SourceLocation] = None):
    ```
  - Context After:
    ```python
    def __init__(self, 
                 perform_type: str,
                 target_paragraph: Optional[str] = None,
                 location: Optional[SourceLocation] = None,
                 test_timing: str = "BEFORE"):
    ```
  - Verification: `grep -n "test_timing" cobolparser/models/statements.py`

- [X] T008 [P] Change times_count to Union[int, str] to support variable names
  - File: `cobolparser/models/statements.py`
  - Location: Line ~118 (type annotation for times_count)
  - Change: Update type annotation from `times_count: Optional[int] = None` to `times_count: Optional[Union[int, str]] = None`
  - Import needed: Add `from typing import Union` at top if not present
  - Verification: `python -c "from cobolparser.models.statements import PerformStatement; import inspect; sig = inspect.signature(PerformStatement.__init__); print(sig.parameters['times_count'].annotation)"`

- [X] T009 [P] Add set_test_timing() method to PerformStatement
  - File: `cobolparser/models/statements.py`
  - Location: After set_varying_clause() method (around line 165)
  - Change: Add new method
  ```python
  def set_test_timing(self, test_timing: str) -> "PerformStatement":
      """Set the test timing clause (BEFORE or AFTER)."""
      if test_timing.upper() not in ["BEFORE", "AFTER"]:
          raise ValueError(f"Invalid test timing: {test_timing}")
      self.test_timing = test_timing.upper()
      return self
  ```
  - Verification: `grep -n "def set_test_timing" cobolparser/models/statements.py`

- [X] T010 [P] Update to_dict() method to include test_timing
  - File: `cobolparser/models/statements.py`
  - Location: In to_dict() method (around line 170)
  - Change: Add `"test_timing": self.test_timing,` to returned dictionary
  - Current dict should include:
    ```python
    {
        "node_type": self.node_type,
        "perform_type": self.perform_type,
        "target_paragraph": self.target_paragraph,
        "thru_paragraph": getattr(self, "thru_paragraph", None),
        "times_count": self.times_count,
        "until_condition": self.until_condition.to_dict() if hasattr(self, "until_condition") and self.until_condition else None,
        "test_timing": self.test_timing,  # ← ADD THIS LINE
        ...
    }
    ```
  - Verification: `python -c "from cobolparser.models.statements import PerformStatement; p = PerformStatement('UNTIL'); d = p.to_dict(); print('test_timing' in d)"`

- [X] T011 Run model tests to verify PerformStatement changes
  - Command: `python -m pytest tests/unit/test_statements.py::TestPerformStatement -v`
  - Expected: All PerformStatement tests pass
  - Failure handling: Check type annotations and method signatures match

- [X] T012 Commit changes to git
  - Command: `git add cobolparser/models/statements.py && git commit -m "Extend PerformStatement: add test_timing attribute, support variable TIMES, update to_dict()"`

**Time Estimate**: 1.5 hours  
**Blocking Other Tasks**: Task 3.1, Task 2.3

---

# 📝 PHASE 2: Parser Enhancement

**Duration**: ~6.5 hours  
**Goal**: Implement parsing support for test timing, UNTIL conditions, and variable iteration counts

---

## Task 2.1: Add _parse_test_timing_clause() Helper Method

**Priority**: P1 [US-3, US-4]  
**Addresses**: FR-006 (WITH TEST parsing), FR-009 (UNTIL with test timing), FR-018 (Complex combinations)  
**Tests**: [test_parser.py::test_parse_test_timing_*](TEST_SPECIFICATIONS.md#integration_tests_phase2)  
**Baseline Gap**: No method to parse WITH TEST BEFORE/AFTER clauses  
**Depends On**: Task 1.1

- [X] T013 Open cobolparser/parser.py and understand helper method patterns
  - File: `cobolparser/parser.py`
  - Review existing helpers: _parse_inline_call_into_perform() (line ~3250), _parse_inline_if_into_perform() (line ~3290)
  - Task: Understand method structure, return types, error handling

- [X] T014 Add _parse_test_timing_clause() method to Parser class
  - File: `cobolparser/parser.py`
  - Location: Add before _parse_perform_inline() (around line 3200)
  - Change: Add new helper method (~20 lines)
  ```python
  def _parse_test_timing_clause(self) -> Optional[str]:
      """
      Parse WITH TEST BEFORE/AFTER clause.
      
      Returns 'BEFORE', 'AFTER', or None if no test timing clause present.
      Moves token pointer forward if clause found.
      """
      if not self.current_token or self.current_token.type != TokenType.WITH:
          return None
      
      # Peek ahead to see if next is TEST
      self.advance()  # consume WITH
      if not self.current_token or self.current_token.type != TokenType.TEST:
          # No TEST keyword, backtrack
          self.current_index -= 1
          self.current_token = self.tokens[self.current_index] if self.current_index < len(self.tokens) else None
          return None
      
      self.advance()  # consume TEST
      if self.current_token.type == TokenType.BEFORE:
          self.advance()
          return "BEFORE"
      elif self.current_token.type == TokenType.AFTER:
          self.advance()
          return "AFTER"
      else:
          return "BEFORE"  # Default
  ```
  - Verification: `grep -n "def _parse_test_timing_clause" cobolparser/parser.py`

- [X] T015 Add unit tests for _parse_test_timing_clause()
  - File: `tests/unit/test_parser_comprehensive.py`
  - Tests created: 6 unit tests covering all BEFORE, AFTER, default, no WITH, backtracking cases
  - Verification: `python -m pytest tests/unit/test_parser_comprehensive.py::TestParseHelperMethods::test_parse_test_timing_* -v`

- [X] T016 Run tests to verify helper method works correctly
  - Command: `python -m pytest tests/unit/test_parser_comprehensive.py::TestParseHelperMethods::test_parse_test_timing_* -v`
  - Result: ✅ All 6 tests passed
  - Verified: Token types, backtracking logic, return values all working correctly

- [X] T017 Commit changes to git
  - Command: `git add cobolparser/parser.py && git commit -m "Add _parse_test_timing_clause() helper for WITH TEST BEFORE/AFTER parsing"`
  - Result: ✅ Committed (d03610e)

**Time Estimate**: 1.5 hours  
**Blocking Other Tasks**: Task 2.3

---

## Task 2.2: Add _parse_until_condition() Helper Method

**Priority**: P1 [US-3, US-4]  
**Addresses**: FR-016 (UNTIL condition parsing), FR-018 (UNTIL with test timing)  
**Tests**: [test_parser.py::test_parse_until_condition_*](TEST_SPECIFICATIONS.md#integration_tests_phase2)  
**Baseline Gap**: UNTIL conditions not properly parsed  
**Depends On**: Task 1.1

- [X] T018 Open cobolparser/parser.py and understand condition parsing patterns
  - File: `cobolparser/parser.py`
  - Reviewed: _parse_condition() method (used for IF statements)
  - Implementation: Used ConditionalExpression class from models.statements

- [X] T019 Add _parse_until_condition() method to Parser class
  - File: `cobolparser/parser.py`
  - Location: Added before _parse_perform_inline() (lines 3235-3276)
  - Change: Added ~40 lines helper method
  - Implementation: Parses UNTIL condition tokens, creates ConditionalExpression nodes

- [X] T020 [P] Add unit tests for _parse_until_condition()
  - File: `tests/unit/test_parser_comprehensive.py`
  - Tests created: 5 unit tests covering simple UNTIL, no UNTIL, single variable, END-PERFORM boundary, empty cases
  - Verification: `python -m pytest tests/unit/test_parser_comprehensive.py::TestParseHelperMethods::test_parse_until_condition_* -v`

- [X] T021 Run tests to verify helper method works correctly
  - Command: `python -m pytest tests/unit/test_parser_comprehensive.py::TestParseHelperMethods::test_parse_until_condition_* -v`
  - Result: ✅ All 5 tests passed
  - Verified: Condition parsing, token advancement, boundary conditions all working

- [X] T022 Commit changes to git
  - Command: `git add cobolparser/parser.py && git commit -m "Add _parse_until_condition() helper for UNTIL clause parsing"`
  - Result: ✅ Committed (d03610e, same commit with test timing clause)
      
      Expects: UNTIL <condition>
      Returns: Condition AST node or None if UNTIL not found.
      Advances token pointer if UNTIL clause found.
      """
      if not self.current_token or self.current_token.type != TokenType.UNTIL:
          return None
      
      self.advance()  # consume UNTIL
      
      # Parse the condition expression (reuse condition parsing logic)
      condition = self._parse_condition()
      return condition
  ```
  - Verification: `grep -n "def _parse_until_condition" cobolparser/parser.py`

- [ ] T020 [P] Add unit tests for _parse_until_condition()
  - File: `tests/unit/test_parser.py`
  - Tests needed:
    - test_parse_until_simple_condition (e.g., UNTIL WS-EOF = 'Y')
    - test_parse_until_complex_condition (e.g., UNTIL WS-COUNT > 100 AND WS-DONE = 'Y')
    - test_parse_until_none (expects None when UNTIL not present)
  - Verification: `python -m pytest tests/unit/test_parser.py::test_parse_until_condition_* -v`

- [ ] T021 Run tests to verify helper method works correctly
  - Command: `python -m pytest tests/unit/test_parser.py::test_parse_until_condition_* -v`
  - Expected: All tests pass
  - Failure handling: Check condition parsing, token advancement

- [ ] T022 Commit changes to git
  - Command: `git add cobolparser/parser.py && git commit -m "Add _parse_until_condition() helper for UNTIL clause parsing"`

**Time Estimate**: 2 hours  
**Blocking Other Tasks**: Task 2.3

---

## Task 2.3: Enhance _parse_perform_inline() Main Method

**Priority**: P1 [US-2, US-3, US-4, US-5]  
**Addresses**: FR-006, FR-007, FR-009, FR-013, FR-014, FR-015, FR-016, FR-017, FR-018  
**Tests**: [test_perform_statement_coverage.py](TEST_SPECIFICATIONS.md#integration_tests_phase2)  
**Baseline Gap**: Missing UNTIL, test timing, variable TIMES support  
**Depends On**: Task 2.1, Task 2.2, Task 1.2

This is the core enhancement. The main _parse_perform_inline() method needs 4 sub-enhancements:

### Sub-task 2.3a: Add PERFORM ... UNTIL Support (Standalone)

- [ ] T023 Understand current PERFORM parsing structure in _parse_perform_inline()
  - File: `cobolparser/parser.py`
  - Current location: Lines 3200-3345 (145 lines)
  - Structure: Currently handles SIMPLE, THRU, TIMES, VARYING branches
  - Task: Identify where to add UNTIL branch

- [ ] T024 Add UNTIL support to _parse_perform_inline() for simple PERFORM UNTIL statements
  - File: `cobolparser/parser.py`
  - Location: In _parse_perform_inline() after SIMPLE branch (around line 3320)
  - Change: Add new conditional branch
  ```python
  # Check for UNTIL clause (PERFORM PARA UNTIL condition)
  if self.current_token and self.current_token.type == TokenType.UNTIL:
      until_condition = self._parse_until_condition()
      perform_stmt.set_until_clause(until_condition)
      perform_stmt.perform_type = "UNTIL"
  ```
  - Verification: Manual test with COBOL: `PERFORM READ-RECORD UNTIL WS-EOF = 'Y'.`

### Sub-task 2.3b: Add WITH TEST Support to Simple PERFORM

- [ ] T025 Add WITH TEST support to simple PERFORM statements
  - File: `cobolparser/parser.py`
  - Location: In _parse_perform_inline() SIMPLE branch (around line 3312)
  - Change: Add test timing parsing before UNTIL check
  ```python
  # Check for WITH TEST clause
  test_timing = self._parse_test_timing_clause()
  if test_timing:
      perform_stmt.set_test_timing(test_timing)
  ```
  - Verification: Manual test with COBOL: `PERFORM PARA WITH TEST BEFORE UNTIL condition.`

### Sub-task 2.3c: Add Variable Support to TIMES Clause

- [ ] T026 Enhance TIMES clause parsing to support variable names
  - File: `cobolparser/parser.py`
  - Location: In _parse_perform_inline() TIMES branch (around line 3280)
  - Current code: `times_count = self.current_token.value` (assumes integer)
  - Change: Support variable names
  ```python
  # TIMES can be int or variable name
  if self.current_token.type == TokenType.NUMERIC_LITERAL:
      times_count = int(self.current_token.value)
  else:  # Assume identifier (variable name)
      times_count = self.current_token.value
  
  perform_stmt.set_times_clause(times_count)
  self.advance()
  ```
  - Verification: Manual test with COBOL: `PERFORM PROCESS-RECORD WS-COUNT TIMES.`

### Sub-task 2.3d: Add WITH TEST Support to VARYING

- [ ] T027 Add WITH TEST support to VARYING PERFORM statements
  - File: `cobolparser/parser.py`
  - Location: In _parse_perform_inline() VARYING branch (around line 3310)
  - Change: Parse test timing before UNTIL condition in VARYING block
  ```python
  # Check for WITH TEST clause in VARYING
  test_timing = self._parse_test_timing_clause()
  if test_timing:
      perform_stmt.set_test_timing(test_timing)
  ```
  - Verification: Manual test with COBOL: `PERFORM VARYING I FROM 1 BY 1 WITH TEST AFTER UNTIL I > 10 END-PERFORM.`

### Integration of all sub-tasks

- [ ] T028 Run full integration test suite for all PERFORM variants
  - Command: `python -m pytest tests/integration/test_perform_statement_coverage.py -v`
  - Expected: All 20 integration tests pass
  - Test coverage:
    - PERFORM UNTIL with default test timing (BEFORE)
    - PERFORM UNTIL with explicit test timing
    - PERFORM TIMES with variable
    - PERFORM with THRU + UNTIL
    - PERFORM VARYING with test timing
    - Nested PERFORM statements
    - Inline PERFORM with statements
    - Edge cases and error handling
  - Failure handling: Review test output, check token advancement and condition parsing

- [ ] T029 Run complete test suite to check for regressions
  - Command: `python -m pytest tests/ -v --tb=short`
  - Expected: All existing tests pass, no new failures
  - Failure handling: If failures, identify affected areas, check for breaking changes

- [ ] T030 Commit changes to git
  - Command: `git add cobolparser/parser.py && git commit -m "Enhance _parse_perform_inline(): add UNTIL, variable TIMES, WITH TEST support for all PERFORM variants"`

**Time Estimate**: 3.5 hours  
**Blocking Other Tasks**: Task 3.1, Task 3.2, Task 3.3, Task 4.1

---

# 🧪 PHASE 3: Testing & Validation

**Duration**: ~8 hours  
**Goal**: Achieve ≥90% code coverage with comprehensive test suite

---

## Task 3.1: Unit Tests - Model Extensions

**Priority**: P1 [All US]  
**Addresses**: All SC (Success Criteria require comprehensive testing)  
**Tests**: 8 new unit tests for model changes  
**Baseline Gap**: No tests for test_timing attribute or Union[int, str] times_count  
**Depends On**: Task 1.2

- [ ] T031 Create or open tests/unit/test_statements.py
  - File: `tests/unit/test_statements.py`
  - Task: Locate TestPerformStatement class (usually ~line 300)

- [ ] T032 [P] Add test_perform_test_timing_default()
  - File: `tests/unit/test_statements.py`
  - Test Code:
  ```python
  def test_perform_test_timing_default(self):
      """Test that test_timing defaults to 'BEFORE'."""
      stmt = PerformStatement("UNTIL", "PARA")
      self.assertEqual(stmt.test_timing, "BEFORE")
  ```
  - Verification: `python -m pytest tests/unit/test_statements.py::TestPerformStatement::test_perform_test_timing_default -v`

- [ ] T033 [P] Add test_perform_set_test_timing_before()
  - File: `tests/unit/test_statements.py`
  - Test Code:
  ```python
  def test_perform_set_test_timing_before(self):
      """Test setting test_timing to BEFORE."""
      stmt = PerformStatement("UNTIL", "PARA")
      result = stmt.set_test_timing("BEFORE")
      self.assertEqual(stmt.test_timing, "BEFORE")
      self.assertIs(result, stmt)  # Should return self for chaining
  ```

- [ ] T034 [P] Add test_perform_set_test_timing_after()
  - File: `tests/unit/test_statements.py`
  - Test Code:
  ```python
  def test_perform_set_test_timing_after(self):
      """Test setting test_timing to AFTER."""
      stmt = PerformStatement("UNTIL", "PARA")
      result = stmt.set_test_timing("AFTER")
      self.assertEqual(stmt.test_timing, "AFTER")
  ```

- [ ] T035 [P] Add test_perform_times_count_int()
  - File: `tests/unit/test_statements.py`
  - Test Code:
  ```python
  def test_perform_times_count_int(self):
      """Test TIMES with integer count."""
      stmt = PerformStatement("TIMES", "PARA")
      stmt.set_times_clause(10)
      self.assertEqual(stmt.times_count, 10)
  ```

- [ ] T036 [P] Add test_perform_times_count_variable()
  - File: `tests/unit/test_statements.py`
  - Test Code:
  ```python
  def test_perform_times_count_variable(self):
      """Test TIMES with variable name."""
      stmt = PerformStatement("TIMES", "PARA")
      stmt.set_times_clause("WS-COUNT")
      self.assertEqual(stmt.times_count, "WS-COUNT")
  ```

- [ ] T037 [P] Add test_perform_to_dict_includes_test_timing()
  - File: `tests/unit/test_statements.py`
  - Test Code:
  ```python
  def test_perform_to_dict_includes_test_timing(self):
      """Test that to_dict() includes test_timing field."""
      stmt = PerformStatement("UNTIL", "PARA")
      stmt.set_test_timing("AFTER")
      d = stmt.to_dict()
      self.assertIn("test_timing", d)
      self.assertEqual(d["test_timing"], "AFTER")
  ```

- [ ] T038 [P] Add test_perform_to_dict_variable_times()
  - File: `tests/unit/test_statements.py`
  - Test Code:
  ```python
  def test_perform_to_dict_variable_times(self):
      """Test that to_dict() correctly serializes variable times_count."""
      stmt = PerformStatement("TIMES", "PARA")
      stmt.set_times_clause("WS-LIMIT")
      d = stmt.to_dict()
      self.assertEqual(d["times_count"], "WS-LIMIT")
  ```

- [ ] T039 Run all unit tests for model extensions
  - Command: `python -m pytest tests/unit/test_statements.py::TestPerformStatement::test_perform_* -v`
  - Expected: All 8 new tests pass
  - Failure handling: Check assertion messages, test logic

- [ ] T040 Commit changes to git
  - Command: `git add tests/unit/test_statements.py && git commit -m "Add 8 unit tests for PerformStatement model extensions"`

**Time Estimate**: 2 hours

---

## Task 3.2: Integration Tests - Parser Enhancements

**Priority**: P1 [All US]  
**Addresses**: FR-006 through FR-018, all US, all SC  
**Tests**: 20 integration tests for parser enhancements  
**Baseline Gap**: No tests for UNTIL standalone, WITH TEST, variable TIMES combinations  
**Depends On**: Task 2.3

- [ ] T041 Create tests/integration/test_perform_statement_coverage.py
  - File: `tests/integration/test_perform_statement_coverage.py` (new file)
  - Task: Create new file with test class setup
  ```python
  import unittest
  from cobolparser import CobolParser
  from cobolparser.models.statements import PerformStatement

  class TestPerformStatementCoverage(unittest.TestCase):
      """Integration tests for comprehensive PERFORM statement coverage."""
      
      def setUp(self):
          self.parser = CobolParser()
  ```

- [ ] T042 [P] Add test_perform_until_simple()
  - File: `tests/integration/test_perform_statement_coverage.py`
  - Test Code:
  ```python
  def test_perform_until_simple(self):
      """Test PERFORM UNTIL without explicit test timing."""
      cobol = """
      IDENTIFICATION DIVISION.
      PROGRAM-ID. TEST.
      PROCEDURE DIVISION.
          PERFORM READ-RECORD UNTIL WS-EOF = "Y".
      """
      result = self.parser.parse(cobol)
      perform = result.ast.procedure_division.perform_statements[0]
      self.assertEqual(perform.perform_type, "UNTIL")
      self.assertIsNotNone(perform.until_condition)
      self.assertEqual(perform.test_timing, "BEFORE")  # Default
  ```

- [ ] T043 [P] Add test_perform_until_with_test_before()
  - Test Code: `PERFORM PARA WITH TEST BEFORE UNTIL condition`

- [ ] T044 [P] Add test_perform_until_with_test_after()
  - Test Code: `PERFORM PARA WITH TEST AFTER UNTIL condition`

- [ ] T045 [P] Add test_perform_times_variable()
  - Test Code: `PERFORM PARA WS-COUNT TIMES`

- [ ] T046 [P] Add test_perform_times_variable_with_thru()
  - Test Code: `PERFORM PARA-A THRU PARA-B WS-COUNT TIMES`

- [ ] T047 [P] Add test_perform_varying_with_test_before()
  - Test Code: `PERFORM VARYING I FROM 1 BY 1 WITH TEST BEFORE UNTIL I > 10 END-PERFORM`

- [ ] T048 [P] Add test_perform_varying_with_test_after()
  - Test Code: `PERFORM VARYING I FROM 1 BY 1 WITH TEST AFTER UNTIL I > 10 END-PERFORM`

- [ ] T049 [P] Add test_perform_thru_until_simple()
  - Test Code: `PERFORM PARA-START THRU PARA-END UNTIL condition`

- [ ] T050 [P] Add test_perform_thru_until_with_test()
  - Test Code: `PERFORM PARA-START THRU PARA-END WITH TEST AFTER UNTIL condition`

- [ ] T051 [P] Add test_perform_nested_varying()
  - Test Code: Nested PERFORM VARYING statements

- [ ] T052 [P] Add test_perform_inline_with_until()
  - Test Code: `PERFORM MOVE ... DISPLAY ... END-PERFORM UNTIL condition`

- [ ] T053 [P] Add test_perform_complex_condition()
  - Test Code: Complex UNTIL condition with AND/OR operators

- [ ] T054 [P] Add test_perform_variable_times_numeric_comparison()
  - Test Code: Verify variable name preserved in times_count

- [ ] T055 [P] Add test_perform_times_to_dict()
  - Test Code: Verify to_dict() serializes variable times correctly

- [ ] T056 [P] Add test_perform_until_to_dict()
  - Test Code: Verify to_dict() includes until_condition and test_timing

- [ ] T057 [P] Add test_perform_test_timing_case_insensitive()
  - Test Code: Verify "with test before" and "WITH TEST BEFORE" both work

- [ ] T058 [P] Add test_perform_default_test_timing_implicit()
  - Test Code: Verify UNTIL without WITH TEST defaults to BEFORE

- [ ] T059 [P] Add test_perform_varying_default_test_timing()
  - Test Code: Verify VARYING without WITH TEST defaults to BEFORE

- [ ] T060 Run all integration tests
  - Command: `python -m pytest tests/integration/test_perform_statement_coverage.py -v`
  - Expected: All 20 tests pass
  - Failure handling: Check parser output, AST structure, token handling

- [ ] T061 Commit changes to git
  - Command: `git add tests/integration/test_perform_statement_coverage.py && git commit -m "Add 20 integration tests for PERFORM statement coverage"`

**Time Estimate**: 2.5 hours

---

## Task 3.3: Regression Tests - Backward Compatibility

**Priority**: P1 [All SC]  
**Addresses**: SC-001 (No breaking changes), SC-007 (Backward compatibility)  
**Tests**: 6 regression tests for backward compatibility  
**Baseline Gap**: No regression test suite  
**Depends On**: Task 3.1, Task 3.2

- [ ] T062 Create tests/regression/test_perform_backward_compat.py
  - File: `tests/regression/test_perform_backward_compat.py` (new file)
  - Task: Create regression test suite

- [ ] T063 Add test_perform_simple_still_works()
  - File: `tests/regression/test_perform_backward_compat.py`
  - Test: Ensure existing SIMPLE PERFORM still works (backward compat)
  - COBOL: `PERFORM PARA-NAME`

- [ ] T064 Add test_perform_thru_still_works()
  - Test: Ensure THRU still works as before
  - COBOL: `PERFORM PARA-START THRU PARA-END`

- [ ] T065 Add test_perform_times_still_works()
  - Test: Ensure integer TIMES still works as before
  - COBOL: `PERFORM PARA 10 TIMES`

- [ ] T066 Add test_perform_varying_still_works()
  - Test: Ensure VARYING still works as before
  - COBOL: `PERFORM VARYING I FROM 1 BY 1 UNTIL I > 10 END-PERFORM`

- [ ] T067 Add test_perform_inline_still_works()
  - Test: Ensure inline PERFORM still works as before
  - COBOL: `PERFORM MOVE ... DISPLAY ... END-PERFORM`

- [ ] T068 Add test_existing_test_suite_passes()
  - File: `tests/regression/test_perform_backward_compat.py`
  - Command within test: `subprocess.run(["python", "-m", "pytest", "tests/unit/test_statements.py", "-q"])`
  - Verification: All existing unit tests pass

- [ ] T069 Run regression test suite
  - Command: `python -m pytest tests/regression/test_perform_backward_compat.py -v`
  - Expected: All 6 tests pass
  - Failure handling: Identify which existing features were broken, fix

- [ ] T070 Commit changes to git
  - Command: `git add tests/regression/test_perform_backward_compat.py && git commit -m "Add 6 regression tests for backward compatibility"`

**Time Estimate**: 1.5 hours

---

## Task 3.4: Performance Tests

**Priority**: P2 [US-5]  
**Addresses**: SC-008 (Performance requirements)  
**Tests**: 2 performance tests  
**Baseline Gap**: No performance benchmarks  
**Depends On**: Task 3.2

- [ ] T071 Create tests/unit/test_perform_performance.py
  - File: `tests/unit/test_perform_performance.py` (new file)
  - Task: Create performance test suite

- [ ] T072 Add test_perform_parsing_performance_baseline()
  - File: `tests/unit/test_perform_performance.py`
  - Test: Parse large COBOL program (1000 PERFORM statements)
  - Requirement: Should complete in <5 seconds
  - Verification: Measure time, assert time < 5.0

- [ ] T073 Add test_perform_ast_serialization_performance()
  - File: `tests/unit/test_perform_performance.py`
  - Test: Serialize 1000 PERFORM statements to JSON
  - Requirement: Should complete in <2 seconds
  - Verification: Measure time, assert time < 2.0

- [ ] T074 Run performance tests
  - Command: `python -m pytest tests/unit/test_perform_performance.py -v`
  - Expected: Both tests pass (performance acceptable)
  - Failure handling: Profile code, identify bottlenecks, optimize

- [ ] T075 Commit changes to git
  - Command: `git add tests/unit/test_perform_performance.py && git commit -m "Add 2 performance tests for PERFORM parsing and serialization"`

**Time Estimate**: 1 hour

---

# ✅ PHASE 4: Quality Assurance

**Duration**: ~3 hours  
**Goal**: Ensure code quality and feature completeness

---

## Task 4.1: Code Quality Checks

**Priority**: P1 [All SC]  
**Addresses**: SC-003 (Code quality), SC-004 (Style consistency)  
**Tests**: Static analysis checks  
**Baseline Gap**: No quality checks documented  
**Depends On**: Task 2.3

- [ ] T076 Run mypy type checking on modified files
  - Command: `python -m mypy cobolparser/lexer.py cobolparser/models/statements.py cobolparser/parser.py --strict`
  - Expected: 0 errors, 0 warnings
  - Failure handling: Add type hints, suppress only with justification

- [ ] T077 Run ruff linter on modified files
  - Command: `ruff check cobolparser/lexer.py cobolparser/models/statements.py cobolparser/parser.py`
  - Expected: 0 violations
  - Failure handling: Fix style issues automatically with `ruff check --fix`

- [ ] T078 Run black formatter on modified files
  - Command: `black cobolparser/lexer.py cobolparser/models/statements.py cobolparser/parser.py --check`
  - Expected: No formatting changes needed
  - Failure handling: Auto-format with `black` (without --check)

- [ ] T079 Run pylint on modified files
  - Command: `pylint cobolparser/lexer.py cobolparser/models/statements.py cobolparser/parser.py --disable=C0111,C0103`
  - Expected: Score ≥8.5/10
  - Failure handling: Address high-impact issues (C, E, W categories)

- [ ] T080 Fix any identified issues and re-run checks
  - Task: Address all failures from T076-T079

- [ ] T081 Commit quality fixes to git
  - Command: `git add . && git commit -m "Apply code quality fixes: mypy, ruff, black, pylint"`

**Time Estimate**: 1 hour

---

## Task 4.2: Final Regression Validation

**Priority**: P1 [All SC]  
**Addresses**: SC-001 (No regressions), SC-005 (Test coverage ≥90%)  
**Tests**: Full test suite execution  
**Baseline Gap**: No comprehensive test run documented  
**Depends On**: Task 3.3

- [ ] T082 Run full test suite with coverage reporting
  - Command: `python -m pytest tests/ --cov=cobolparser --cov-report=term-missing --cov-fail-under=90`
  - Expected: 
    - All tests pass
    - Coverage ≥90%
    - No new failures
  - Failure handling: Identify gap, add tests or fix code

- [ ] T083 Run complete COBOL integration tests (if available)
  - Command: `python test_integration.py` (if exists)
  - Expected: All integration tests pass
  - Files: test_program.cob, test_integration.py

- [ ] T084 Validate against specification requirements
  - Task: Manually check each FR, US, SC against implementation
  - Checklist:
    - [ ] FR-001 to FR-018 all addressed
    - [ ] US-1 to US-5 all independently testable
    - [ ] SC-001 to SC-008 all validated
  - Reference: [spec.md](spec.md) and [TEST_SPECIFICATIONS.md](TEST_SPECIFICATIONS.md)

- [ ] T085 Create summary report of test results
  - Task: Document:
    - Total tests run
    - Tests passed/failed
    - Coverage percentage
    - Performance metrics
  - File: Create `TEST_RESULTS.md` or similar

- [ ] T086 Final commit
  - Command: `git add . && git commit -m "Final regression validation: all tests pass, 90%+ coverage, zero regressions"`

- [ ] T087 Create release notes
  - File: `RELEASE_NOTES.md`
  - Content:
    - Feature: Comprehensive PERFORM statement coverage
    - What's new: Summary of FR-001-018
    - Breaking changes: None (backward compatible)
    - Performance impact: <5% overhead
    - Testing: 44 new tests, 90%+ coverage
    - Known issues: None

**Time Estimate**: 1 hour

---

# 📊 Task Completion Metrics

| Phase | Tasks | Est. Hours | Status |
|-------|-------|-----------|--------|
| Phase 1: Foundation | T001-T012 | 2.5 | Not Started |
| Phase 2: Parser | T013-T030 | 6.5 | Not Started |
| Phase 3: Testing | T031-T075 | 8.0 | Not Started |
| Phase 4: QA | T076-T087 | 3.0 | Not Started |
| **TOTAL** | **87 tasks** | **~19 hours** | **Ready** |

---

# 🔍 Success Criteria Validation

Each task contributes to success criteria:

- **SC-001** (No breaking changes): Addressed by Task 3.3 (regression tests)
- **SC-002** (All PERFORM variants parsed): Addressed by Tasks 2.1-2.3 (parser enhancements)
- **SC-003** (Code quality): Addressed by Task 4.1 (quality checks)
- **SC-004** (Style consistency): Addressed by Task 4.1 (black, ruff)
- **SC-005** (≥90% coverage): Addressed by Task 4.2 (coverage validation)
- **SC-006** (Memory safe): Addressed by Task 2.3 (careful token handling)
- **SC-007** (Backward compatible): Addressed by Task 3.3 (regression tests)
- **SC-008** (Performance): Addressed by Task 3.4 (performance tests)

---

# 📚 Reference Links

- Specification: [spec.md](spec.md)
- Current Baseline: [BASELINE.md](BASELINE.md)
- Implementation Plan: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)
- Step-by-Step Guide: [IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md)
- Test Specifications: [TEST_SPECIFICATIONS.md](TEST_SPECIFICATIONS.md)
- Architecture Overview: [DOCUMENTATION_INTEGRATION.md](DOCUMENTATION_INTEGRATION.md)

---

**Created**: January 11, 2026  
**Status**: Ready for Implementation  
**Next Step**: Begin Phase 1, Task 1.1
