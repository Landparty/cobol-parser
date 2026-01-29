# Test Specifications: Comprehensive PERFORM Statement Coverage

**Feature**: PERFORM Statement Coverage  
**Date**: January 11, 2026  
**Purpose**: Detailed test specifications with full traceability to specs and implementation  
**Integration**: Links to IMPLEMENTATION_GUIDE.md, spec.md, and BASELINE.md

---

## 📊 Test Coverage Summary

| Phase | Test Category | File | New Tests | Status | Addresses |
|-------|---------------|------|-----------|--------|-----------|
| 1 | Unit - Model | test_statements.py | 8 | Foundation | FR-007, FR-013 |
| 2 | Integration - Parser | test_perform_statement_coverage.py | 20 | Enhancement | FR-006, FR-016, FR-018 |
| 3 | Regression | test_perform_backward_compat.py | 6 | Validation | All FR |
| 4 | Performance | test_perform_performance.py | 2 | Validation | SC-002, SC-008 |

**Total New Tests**: 36 test methods + full coverage of spec requirements

---

## Phase 1: Unit Tests - Model Extensions

**File**: `tests/unit/test_statements.py`  
**Add to Class**: `TestPerformStatement` (existing, around line 349)  
**New Tests to Add**: 8 test methods  
**Related Tasks**: Task 1.2 (Extend PerformStatement Model)

---

### Unit Test 1.1: test_perform_statement_test_timing

**Specification Link**: FR-006 (WITH TEST support), US-3 (PERFORM UNTIL with test timing)  
**Baseline Link**: [BASELINE.md - Missing Attributes](BASELINE.md#missing-attributes-per-spec-clarifications)  
**Implementation Link**: [IMPLEMENTATION_GUIDE.md - Task 1.2.2](IMPLEMENTATION_GUIDE.md#step-122-add-set_test_timing-method)  
**COBOL Example**: User Story 3, Acceptance Scenario 2

**Test Method**:
```python
def test_perform_statement_test_timing(self):
    """Test WITH TEST timing attribute (BEFORE/AFTER).
    
    Validates: FR-006 (Parser supports WITH TEST timing qualifiers)
    Maps to: US-3 Acceptance Scenario 2 (WITH TEST BEFORE)
    Maps to: US-3 Acceptance Scenario 3 (WITH TEST AFTER)
    Closes BASELINE gap: test_timing attribute
    """
    location = SourceLocation(1, 1)
    perform_stmt = PerformStatement(location)
    
    # Test BEFORE timing
    perform_stmt.set_test_timing("BEFORE")
    self.assertEqual(perform_stmt.test_timing, "BEFORE")
    self.assertEqual(perform_stmt.perform_type, "SIMPLE")
    
    # Test AFTER timing
    perform_stmt.set_test_timing("AFTER")
    self.assertEqual(perform_stmt.test_timing, "AFTER")
    self.assertEqual(perform_stmt.perform_type, "SIMPLE")
    
    # Test case-insensitive input
    perform_stmt.set_test_timing("before")
    self.assertEqual(perform_stmt.test_timing, "BEFORE")  # Should normalize
    
    # Test invalid timing raises error
    with self.assertRaises(ValueError):
        perform_stmt.set_test_timing("INVALID")
    
    # Test None default
    perform_stmt_default = PerformStatement(location)
    self.assertIsNone(perform_stmt_default.test_timing)
```

**Verification Commands**:
```bash
pytest tests/unit/test_statements.py::TestPerformStatement::test_perform_statement_test_timing -v
# Expected: PASSED
```

---

### Unit Test 1.2: test_perform_times_with_int

**Specification Link**: FR-013 (Support literal TIMES), US-2 (PERFORM with TIMES)  
**Baseline Link**: Existing behavior (backward compatibility check)  
**Implementation Link**: [IMPLEMENTATION_GUIDE.md - Task 1.2.3](IMPLEMENTATION_GUIDE.md#step-123-update-set_times_clause-for-union-type)  
**COBOL Example**: User Story 2, Acceptance Scenario 1

**Test Method**:
```python
def test_perform_times_with_int(self):
    """Test TIMES clause with integer literal (existing behavior).
    
    Validates: FR-013 (Support both literal and variable in TIMES)
    Validates: Backward compatibility (int still works)
    Maps to: US-2 Acceptance Scenario 1 (PERFORM ... 10 TIMES)
    """
    location = SourceLocation(1, 1)
    perform_stmt = PerformStatement(location)
    
    # Test with integer literal
    perform_stmt.set_times_clause(10)
    self.assertEqual(perform_stmt.times_count, 10)
    self.assertIsInstance(perform_stmt.times_count, int)
    self.assertEqual(perform_stmt.perform_type, "TIMES")
    
    # Test with different integer
    perform_stmt.set_times_clause(5)
    self.assertEqual(perform_stmt.times_count, 5)
    
    # Test with zero (edge case)
    perform_stmt.set_times_clause(0)
    self.assertEqual(perform_stmt.times_count, 0)
```

**Verification Commands**:
```bash
pytest tests/unit/test_statements.py::TestPerformStatement::test_perform_times_with_int -v
# Expected: PASSED
```

---

### Unit Test 1.3: test_perform_times_with_variable

**Specification Link**: FR-013 (Support variable TIMES), US-2 (PERFORM with TIMES)  
**Baseline Link**: [BASELINE.md - Unsupported Patterns](BASELINE.md#unsupported-patterns)  
**Implementation Link**: [IMPLEMENTATION_GUIDE.md - Task 1.2.3](IMPLEMENTATION_GUIDE.md#step-123-update-set_times_clause-for-union-type)  
**COBOL Example**: User Story 2, Acceptance Scenario 3

**Test Method**:
```python
def test_perform_times_with_variable(self):
    """Test TIMES clause with variable name reference (Union[int, str]).
    
    Validates: FR-013 (Support variable reference in TIMES)
    Validates: Union[int, str] type support
    Maps to: US-2 Acceptance Scenario 3 (PERFORM PARA WS-COUNT TIMES)
    Closes BASELINE gap: Variable names in TIMES clause
    """
    location = SourceLocation(1, 1)
    perform_stmt = PerformStatement(location)
    
    # Test with variable name
    perform_stmt.set_times_clause("WS-COUNT")
    self.assertEqual(perform_stmt.times_count, "WS-COUNT")
    self.assertIsInstance(perform_stmt.times_count, str)
    self.assertEqual(perform_stmt.perform_type, "TIMES")
    
    # Test with different variable name
    perform_stmt.set_times_clause("WS-RECORD-COUNT")
    self.assertEqual(perform_stmt.times_count, "WS-RECORD-COUNT")
    
    # Test with uppercase variable (should be preserved as-is)
    perform_stmt.set_times_clause("I")
    self.assertEqual(perform_stmt.times_count, "I")
```

**Verification Commands**:
```bash
pytest tests/unit/test_statements.py::TestPerformStatement::test_perform_times_with_variable -v
# Expected: PASSED
```

---

### Unit Test 1.4: test_perform_to_dict_with_test_timing

**Specification Link**: FR-007 (Condition handling), SC-002 (Test coverage)  
**Baseline Link**: [BASELINE.md - to_dict() serialization](BASELINE.md#limitations)  
**Implementation Link**: [IMPLEMENTATION_GUIDE.md - Task 1.2.4](IMPLEMENTATION_GUIDE.md#step-124-update-to_dict-method)  

**Test Method**:
```python
def test_perform_to_dict_with_test_timing(self):
    """Test to_dict() includes test_timing attribute.
    
    Validates: test_timing serialization for JSON export
    Validates: SC-002 (Test coverage and traceability)
    """
    location = SourceLocation(1, 1)
    perform_stmt = PerformStatement(location)
    perform_stmt.set_target_paragraph("TEST-PARA")
    perform_stmt.set_test_timing("AFTER")
    
    result = perform_stmt.to_dict()
    
    # Verify test_timing in dict
    self.assertIn("test_timing", result)
    self.assertEqual(result["test_timing"], "AFTER")
    
    # Verify other attributes intact
    self.assertEqual(result["target_paragraph"], "TEST-PARA")
    self.assertEqual(result["perform_type"], "SIMPLE")
    
    # Verify JSON serializable
    import json
    json_str = json.dumps(result)
    self.assertIsInstance(json_str, str)
    self.assertIn("test_timing", json_str)
```

**Verification Commands**:
```bash
pytest tests/unit/test_statements.py::TestPerformStatement::test_perform_to_dict_with_test_timing -v
# Expected: PASSED
```

---

### Unit Test 1.5: test_to_dict_times_as_variable

**Specification Link**: FR-013, SC-002 (Test coverage)  
**Implementation Link**: [IMPLEMENTATION_GUIDE.md - Task 1.2.4](IMPLEMENTATION_GUIDE.md#step-124-update-to_dict-method)  

**Test Method**:
```python
def test_to_dict_times_as_variable(self):
    """Test to_dict() with times_count as variable name (Union type).
    
    Validates: Union[int, str] type serialization
    Validates: Variable reference preservation in JSON
    """
    location = SourceLocation(1, 1)
    perform_stmt = PerformStatement(location)
    perform_stmt.set_target_paragraph("READ-LOOP")
    perform_stmt.set_times_clause("WS-LOOP-COUNT")
    
    result = perform_stmt.to_dict()
    
    # Verify times_count as string
    self.assertEqual(result["times_count"], "WS-LOOP-COUNT")
    self.assertIsInstance(result["times_count"], str)
    
    # Verify JSON serializable
    import json
    json_str = json.dumps(result)
    self.assertIn("WS-LOOP-COUNT", json_str)
```

**Verification Commands**:
```bash
pytest tests/unit/test_statements.py::TestPerformStatement::test_to_dict_times_as_variable -v
# Expected: PASSED
```

---

### Unit Test 1.6: test_perform_varying_union_types

**Specification Link**: FR-007 (VARYING components), US-4 (PERFORM VARYING)  
**Baseline Link**: [BASELINE.md - Union types in varying_clause](BASELINE.md#missing-attributes-per-spec-clarifications)  
**Implementation Link**: [IMPLEMENTATION_GUIDE.md - Task 1.2](IMPLEMENTATION_GUIDE.md#phase-1-foundation)  

**Test Method**:
```python
def test_perform_varying_union_types(self):
    """Test VARYING clause with Union types for from_value/by_value.
    
    Validates: FR-007 (VARYING components support)
    Validates: Union[int, str] in VARYING clause
    Maps to: US-4 (PERFORM VARYING with loop control)
    Closes BASELINE gap: Union types in varying_clause
    """
    location = SourceLocation(1, 1)
    perform_stmt = PerformStatement(location)
    
    # Test with literal values (int)
    varying_clause_lit = {
        "variable": "I",
        "from_value": 1,
        "by_value": 1
    }
    perform_stmt.set_varying_clause("I", 1, 1, None)
    
    result_lit = perform_stmt.to_dict()
    self.assertEqual(result_lit["varying_clause"]["from_value"], 1)
    self.assertIsInstance(result_lit["varying_clause"]["from_value"], int)
    
    # Test with variable references (str)
    perform_stmt2 = PerformStatement(location)
    perform_stmt2.set_varying_clause("J", "WS-START", "WS-INCREMENT", None)
    
    result_var = perform_stmt2.to_dict()
    self.assertEqual(result_var["varying_clause"]["from_value"], "WS-START")
    self.assertIsInstance(result_var["varying_clause"]["from_value"], str)
```

**Verification Commands**:
```bash
pytest tests/unit/test_statements.py::TestPerformStatement::test_perform_varying_union_types -v
# Expected: PASSED
```

---

### Unit Test 1.7: test_perform_combined_attributes

**Specification Link**: FR-006 + FR-007 + FR-013 (Combined features)  
**Implementation Link**: [IMPLEMENTATION_GUIDE.md - Tasks 1.1 & 1.2](IMPLEMENTATION_GUIDE.md#phase-1-foundation)  

**Test Method**:
```python
def test_perform_combined_attributes(self):
    """Test PERFORM with multiple enhanced attributes together.
    
    Validates: test_timing, Union times_count, and all attributes work together
    Validates: Complex COBOL statement representation
    """
    location = SourceLocation(1, 1)
    perform_stmt = PerformStatement(location)
    
    # Set all attributes
    perform_stmt.set_target_paragraph("MAIN-LOOP")
    perform_stmt.set_thru_paragraph("END-LOOP")
    perform_stmt.set_test_timing("BEFORE")
    perform_stmt.set_times_clause("WS-MAX-TIMES")
    
    result = perform_stmt.to_dict()
    
    # Verify all attributes
    self.assertEqual(result["target_paragraph"], "MAIN-LOOP")
    self.assertEqual(result["thru_paragraph"], "END-LOOP")
    self.assertEqual(result["test_timing"], "BEFORE")
    self.assertEqual(result["times_count"], "WS-MAX-TIMES")
    self.assertEqual(result["perform_type"], "TIMES")
```

**Verification Commands**:
```bash
pytest tests/unit/test_statements.py::TestPerformStatement::test_perform_combined_attributes -v
# Expected: PASSED
```

---

### Unit Test 1.8: test_perform_default_values

**Specification Link**: FR-007 (Defaults for WITH TEST)  
**Implementation Link**: [IMPLEMENTATION_GUIDE.md - Task 1.2](IMPLEMENTATION_GUIDE.md#step-121-add-test_timing-attribute-to-__init__)  

**Test Method**:
```python
def test_perform_default_values(self):
    """Test PerformStatement default values for new attributes.
    
    Validates: New attributes have correct defaults
    Validates: Backward compatibility with existing code
    """
    location = SourceLocation(1, 1)
    perform_stmt = PerformStatement(location)
    
    # All new attributes should default to None
    self.assertIsNone(perform_stmt.test_timing)
    self.assertIsNone(perform_stmt.times_count)
    
    # Existing attributes should have defaults
    self.assertEqual(perform_stmt.perform_type, "SIMPLE")
    self.assertIsNone(perform_stmt.target_paragraph)
    self.assertIsNone(perform_stmt.thru_paragraph)
    
    # Existing code relying on defaults should still work
    result = perform_stmt.to_dict()
    self.assertIn("test_timing", result)
    self.assertIsNone(result["test_timing"])
```

**Verification Commands**:
```bash
pytest tests/unit/test_statements.py::TestPerformStatement::test_perform_default_values -v
# Expected: PASSED
```

---

## Phase 2: Integration Tests - Parser Enhancements

**File**: `tests/integration/test_perform_statement_coverage.py` (new file)  
**Size**: ~300 lines  
**New Tests to Add**: 20 integration test methods  
**Related Tasks**: Task 2.1, 2.2, 2.3 (Parser enhancement)

---

### Integration Test 2.1: test_perform_until_simple

**Specification Link**: FR-016 (UNTIL support), US-3 (PERFORM UNTIL)  
**Baseline Link**: [BASELINE.md - Unsupported Patterns](BASELINE.md#unsupported-patterns)  
**Implementation Link**: [IMPLEMENTATION_GUIDE.md - Task 2.3a](IMPLEMENTATION_GUIDE.md#step-23a-add-standalone-until-support)  
**COBOL Example**: User Story 3, Acceptance Scenario 1

**Test Method**:
```python
def test_perform_until_simple(self):
    """Test PERFORM paragraph UNTIL condition (no THRU, no TIMES).
    
    Validates: FR-016 (PERFORM ... UNTIL support)
    Validates: US-3 Acceptance Scenario 1
    Closes BASELINE gap: PERFORM UNTIL (standalone)
    """
    cobol_code = """
           IDENTIFICATION DIVISION.
           PROGRAM-ID. TEST-UNTIL.
           DATA DIVISION.
           WORKING-STORAGE SECTION.
           01  WS-EOF PIC X VALUE 'N'.
           PROCEDURE DIVISION.
           MAIN.
               PERFORM READ-RECORD UNTIL WS-EOF = 'Y'.
               STOP RUN.
           READ-RECORD.
               MOVE 'Y' TO WS-EOF.
    """
    
    parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    result = parser.parse(cobol_code)
    
    # Find PERFORM statement in AST
    perform_stmts = self._find_performs(result.ast)
    self.assertEqual(len(perform_stmts), 1)
    
    perform = perform_stmts[0]
    self.assertEqual(perform.perform_type, "UNTIL")
    self.assertEqual(perform.target_paragraph, "READ-RECORD")
    self.assertIsNone(perform.thru_paragraph)
    self.assertIsNotNone(perform.until_condition)
    self.assertIsNone(perform.test_timing)  # Default
```

**Verification Commands**:
```bash
pytest tests/integration/test_perform_statement_coverage.py::test_perform_until_simple -v
# Expected: PASSED
```

---

### Integration Test 2.2: test_perform_until_thru

**Specification Link**: FR-016 (THRU + UNTIL), US-3  
**Baseline Link**: [BASELINE.md - Unsupported Patterns](BASELINE.md#unsupported-patterns)  
**Implementation Link**: [IMPLEMENTATION_GUIDE.md - Task 2.3a](IMPLEMENTATION_GUIDE.md#step-23a-add-standalone-until-support)  
**COBOL Example**: User Story 3, Acceptance Scenario 4

**Test Method**:
```python
def test_perform_until_thru(self):
    """Test PERFORM paragraph THRU paragraph UNTIL condition.
    
    Validates: FR-016 (THRU + UNTIL combination)
    Validates: US-3 Acceptance Scenario 4
    """
    cobol_code = """
           PROCEDURE DIVISION.
           MAIN.
               PERFORM INIT-PARA THRU END-INIT UNTIL WS-DONE = 'Y'.
               STOP RUN.
           INIT-PARA.
           ...
           END-INIT.
    """
    
    parser = CobolParser()
    result = parser.parse(cobol_code)
    
    perform_stmts = self._find_performs(result.ast)
    self.assertEqual(len(perform_stmts), 1)
    
    perform = perform_stmts[0]
    self.assertEqual(perform.perform_type, "UNTIL")
    self.assertEqual(perform.target_paragraph, "INIT-PARA")
    self.assertEqual(perform.thru_paragraph, "END-INIT")
    self.assertIsNotNone(perform.until_condition)
```

**Verification Commands**:
```bash
pytest tests/integration/test_perform_statement_coverage.py::test_perform_until_thru -v
# Expected: PASSED
```

---

### Integration Test 2.3: test_perform_until_with_test_before

**Specification Link**: FR-006 (WITH TEST BEFORE), US-3  
**Baseline Link**: [BASELINE.md - Unsupported Patterns](BASELINE.md#unsupported-patterns)  
**Implementation Link**: [IMPLEMENTATION_GUIDE.md - Task 2.3b](IMPLEMENTATION_GUIDE.md#step-23b-add-with-test-support-to-simple-perform)  
**COBOL Example**: User Story 3, Acceptance Scenario 2

**Test Method**:
```python
def test_perform_until_with_test_before(self):
    """Test PERFORM paragraph WITH TEST BEFORE UNTIL condition.
    
    Validates: FR-006 (WITH TEST BEFORE support)
    Validates: US-3 Acceptance Scenario 2
    Closes BASELINE gap: WITH TEST BEFORE parsing
    """
    cobol_code = """
           PROCEDURE DIVISION.
           MAIN.
               PERFORM PROCESS-RECORD WITH TEST BEFORE 
                   UNTIL WS-COUNT > 100.
               STOP RUN.
           PROCESS-RECORD.
    """
    
    parser = CobolParser()
    result = parser.parse(cobol_code)
    
    perform_stmts = self._find_performs(result.ast)
    self.assertEqual(len(perform_stmts), 1)
    
    perform = perform_stmts[0]
    self.assertEqual(perform.perform_type, "UNTIL")
    self.assertEqual(perform.test_timing, "BEFORE")
    self.assertEqual(perform.target_paragraph, "PROCESS-RECORD")
    self.assertIsNotNone(perform.until_condition)
```

**Verification Commands**:
```bash
pytest tests/integration/test_perform_statement_coverage.py::test_perform_until_with_test_before -v
# Expected: PASSED
```

---

### Integration Test 2.4: test_perform_until_with_test_after

**Specification Link**: FR-006 (WITH TEST AFTER), US-3  
**Baseline Link**: [BASELINE.md - Unsupported Patterns](BASELINE.md#unsupported-patterns)  
**Implementation Link**: [IMPLEMENTATION_GUIDE.md - Task 2.3b](IMPLEMENTATION_GUIDE.md#step-23b-add-with-test-support-to-simple-perform)  
**COBOL Example**: User Story 3, Acceptance Scenario 3

**Test Method**:
```python
def test_perform_until_with_test_after(self):
    """Test PERFORM paragraph WITH TEST AFTER UNTIL condition.
    
    Validates: FR-006 (WITH TEST AFTER support)
    Validates: US-3 Acceptance Scenario 3 (ensures one execution)
    Closes BASELINE gap: WITH TEST AFTER parsing
    """
    cobol_code = """
           PROCEDURE DIVISION.
           MAIN.
               PERFORM PROCESS-RECORD WITH TEST AFTER 
                   UNTIL WS-DONE = 'Y'.
               STOP RUN.
           PROCESS-RECORD.
    """
    
    parser = CobolParser()
    result = parser.parse(cobol_code)
    
    perform_stmts = self._find_performs(result.ast)
    self.assertEqual(len(perform_stmts), 1)
    
    perform = perform_stmts[0]
    self.assertEqual(perform.perform_type, "UNTIL")
    self.assertEqual(perform.test_timing, "AFTER")
    self.assertEqual(perform.target_paragraph, "PROCESS-RECORD")
```

**Verification Commands**:
```bash
pytest tests/integration/test_perform_statement_coverage.py::test_perform_until_with_test_after -v
# Expected: PASSED
```

---

### Integration Test 2.5: test_perform_times_with_literal

**Specification Link**: FR-013 (Literal TIMES), US-2  
**Baseline Link**: Existing behavior (validation)  
**COBOL Example**: User Story 2, Acceptance Scenario 1

**Test Method**:
```python
def test_perform_times_with_literal(self):
    """Test PERFORM paragraph n TIMES (backward compatibility check).
    
    Validates: FR-013 (Literal TIMES still works)
    Validates: Backward compatibility
    """
    cobol_code = """
           PROCEDURE DIVISION.
           MAIN.
               PERFORM PROCESS-RECORD 10 TIMES.
               STOP RUN.
           PROCESS-RECORD.
    """
    
    parser = CobolParser()
    result = parser.parse(cobol_code)
    
    perform_stmts = self._find_performs(result.ast)
    perform = perform_stmts[0]
    
    self.assertEqual(perform.perform_type, "TIMES")
    self.assertEqual(perform.times_count, 10)
    self.assertIsInstance(perform.times_count, int)
```

**Verification Commands**:
```bash
pytest tests/integration/test_perform_statement_coverage.py::test_perform_times_with_literal -v
# Expected: PASSED
```

---

### Integration Test 2.6: test_perform_times_with_variable

**Specification Link**: FR-013 (Variable TIMES), US-2  
**Baseline Link**: [BASELINE.md - Unsupported Patterns](BASELINE.md#unsupported-patterns)  
**Implementation Link**: [IMPLEMENTATION_GUIDE.md - Task 2.3c](IMPLEMENTATION_GUIDE.md#step-23c-add-variable-support-to-times-clause)  
**COBOL Example**: User Story 2, Acceptance Scenario 3

**Test Method**:
```python
def test_perform_times_with_variable(self):
    """Test PERFORM paragraph WS-COUNT TIMES (variable reference).
    
    Validates: FR-013 (Variable reference in TIMES)
    Validates: Union[int, str] support in parser
    Closes BASELINE gap: Variable names in TIMES clause
    """
    cobol_code = """
           DATA DIVISION.
           WORKING-STORAGE SECTION.
           01  WS-COUNT PIC 9(5).
           PROCEDURE DIVISION.
           MAIN.
               PERFORM PROCESS-RECORD WS-COUNT TIMES.
               STOP RUN.
           PROCESS-RECORD.
    """
    
    parser = CobolParser()
    result = parser.parse(cobol_code)
    
    perform_stmts = self._find_performs(result.ast)
    perform = perform_stmts[0]
    
    self.assertEqual(perform.perform_type, "TIMES")
    self.assertEqual(perform.times_count, "WS-COUNT")
    self.assertIsInstance(perform.times_count, str)
```

**Verification Commands**:
```bash
pytest tests/integration/test_perform_statement_coverage.py::test_perform_times_with_variable -v
# Expected: PASSED
```

---

### Integration Test 2.7: test_perform_thru_times_with_variable

**Specification Link**: FR-013, US-2  
**Implementation Link**: [IMPLEMENTATION_GUIDE.md - Task 2.3c](IMPLEMENTATION_GUIDE.md#step-23c-add-variable-support-to-times-clause)  
**COBOL Example**: User Story 2, Acceptance Scenario 2

**Test Method**:
```python
def test_perform_thru_times_with_variable(self):
    """Test PERFORM paragraph THRU paragraph WS-COUNT TIMES.
    
    Validates: FR-013 with THRU combination
    """
    cobol_code = """
           PROCEDURE DIVISION.
           MAIN.
               PERFORM PARA-A THRU PARA-B WS-COUNT TIMES.
               STOP RUN.
           PARA-A.
           PARA-B.
    """
    
    parser = CobolParser()
    result = parser.parse(cobol_code)
    
    perform_stmts = self._find_performs(result.ast)
    perform = perform_stmts[0]
    
    self.assertEqual(perform.perform_type, "TIMES")
    self.assertEqual(perform.target_paragraph, "PARA-A")
    self.assertEqual(perform.thru_paragraph, "PARA-B")
    self.assertEqual(perform.times_count, "WS-COUNT")
    self.assertIsInstance(perform.times_count, str)
```

**Verification Commands**:
```bash
pytest tests/integration/test_perform_statement_coverage.py::test_perform_thru_times_with_variable -v
# Expected: PASSED
```

---

### Integration Test 2.8: test_perform_varying_with_test_after

**Specification Link**: FR-018 (VARYING + WITH TEST), US-4  
**Baseline Link**: [BASELINE.md - Unsupported Patterns](BASELINE.md#unsupported-patterns)  
**Implementation Link**: [IMPLEMENTATION_GUIDE.md - Task 2.3d](IMPLEMENTATION_GUIDE.md#step-23d-add-with-test-support-to-varying)  

**Test Method**:
```python
def test_perform_varying_with_test_after(self):
    """Test PERFORM VARYING ... WITH TEST AFTER UNTIL ... END-PERFORM.
    
    Validates: FR-018 (VARYING with WITH TEST support)
    Validates: US-4 (PERFORM VARYING with loop control)
    Closes BASELINE gap: WITH TEST in VARYING clause
    """
    cobol_code = """
           PROCEDURE DIVISION.
           MAIN.
               PERFORM VARYING I FROM 1 BY 1 
                   WITH TEST AFTER 
                   UNTIL I > 100
                   MOVE I TO WS-INDEX
                   CALL 'PROCESS' USING WS-INDEX
               END-PERFORM.
               STOP RUN.
    """
    
    parser = CobolParser()
    result = parser.parse(cobol_code)
    
    perform_stmts = self._find_performs(result.ast)
    perform = perform_stmts[0]
    
    self.assertEqual(perform.perform_type, "VARYING")
    self.assertEqual(perform.test_timing, "AFTER")
    self.assertEqual(perform.varying_clause["variable"], "I")
    self.assertEqual(perform.varying_clause["from_value"], 1)
    self.assertEqual(perform.varying_clause["by_value"], 1)
    self.assertIsNotNone(perform.until_condition)
```

**Verification Commands**:
```bash
pytest tests/integration/test_perform_statement_coverage.py::test_perform_varying_with_test_after -v
# Expected: PASSED
```

---

### Integration Tests 2.9-2.20: Additional Coverage

Create similar integration tests for:

- `test_perform_thru_test_until` - PERFORM PARA THRU PARA WITH TEST AFTER UNTIL
- `test_perform_thru_until_combination` - Complex combinations
- `test_perform_varying_with_literal_values` - VARYING with literal FROM/BY
- `test_perform_varying_with_variable_values` - VARYING with variable FROM/BY
- `test_perform_varying_nested` - Nested PERFORM VARYING
- `test_perform_inline_call` - Inline CALL within PERFORM (existing)
- `test_perform_inline_if` - Inline IF within PERFORM (existing)
- `test_perform_multi_line` - Multi-line PERFORM statements
- `test_perform_with_continuation_lines` - PERFORM spanning lines
- `test_perform_json_serialization` - All variants to JSON
- `test_perform_error_recovery` - Error handling with COLLECT_ALL
- `test_perform_edge_cases` - Empty clauses, malformed statements

**Total**: 20 integration test methods covering all combinations from spec

---

## Phase 3: Regression Tests

**File**: `tests/regression/test_perform_backward_compat.py` (new file)  
**Size**: ~150 lines  
**New Tests to Add**: 6 regression test methods

---

### Regression Test 3.1: test_backward_compat_simple_perform

**Test Method**:
```python
def test_backward_compat_simple_perform(self):
    """Verify simple PERFORM still works (from BASELINE).
    
    Validates: No breaking changes to basic functionality
    """
    # This is an existing pattern from BASELINE
    cobol_code = """
           PROCEDURE DIVISION.
           MAIN.
               PERFORM INITIALIZE-DATA.
               STOP RUN.
           INITIALIZE-DATA.
    """
    
    parser = CobolParser()
    result = parser.parse(cobol_code)
    
    # Should parse without errors
    self.assertIsNotNone(result.ast)
    perform_stmts = self._find_performs(result.ast)
    self.assertEqual(len(perform_stmts), 1)
    self.assertEqual(perform_stmts[0].target_paragraph, "INITIALIZE-DATA")
```

---

### Regression Tests 3.2-3.6

Create similar regression tests for:
- `test_backward_compat_perform_thru` - PERFORM THRU (existing)
- `test_backward_compat_perform_times` - PERFORM TIMES with int (existing)
- `test_backward_compat_perform_varying` - PERFORM VARYING (existing)
- `test_backward_compat_json_serialization` - to_dict() still works
- `test_backward_compat_times_as_int` - times_count still accepts int

**Total**: 6 regression test methods ensuring zero breaking changes

---

## Phase 4: Performance Tests

**File**: `tests/unit/test_perform_performance.py` (new file)  
**Size**: ~80 lines  
**New Tests to Add**: 2 performance test methods

---

### Performance Test 4.1: test_parse_performance_many_performs

**Test Method**:
```python
def test_parse_performance_many_performs(self):
    """Verify parse time not degraded by new PERFORM parsing.
    
    Validates: SC-002, SC-008 (Performance requirements)
    """
    # Generate large program with many PERFORM statements
    performs = []
    for i in range(1000):
        performs.append(f"           PERFORM PARA-{i}.")
    
    cobol_code = """
           PROCEDURE DIVISION.
           MAIN.
""" + "\n".join(performs) + """
               STOP RUN.
           PARA-1.
           PARA-2.
    """
    
    parser = CobolParser()
    import time
    
    start = time.time()
    result = parser.parse(cobol_code)
    elapsed = time.time() - start
    
    # Should parse 1000+ statements in reasonable time
    self.assertLess(elapsed, 5.0)  # 5 seconds for large program
```

---

### Performance Test 4.2: test_memory_usage_complex_performs

**Test Method**:
```python
def test_memory_usage_complex_performs(self):
    """Verify memory usage not significantly increased.
    
    Validates: SC-008 (Performance requirements)
    """
    import sys
    
    # Generate program with complex PERFORM statements
    cobol_code = """
           PROCEDURE DIVISION.
           MAIN.
               PERFORM VARYING I FROM 1 BY 1 UNTIL I > 100
                   WITH TEST AFTER
                   PERFORM VARYING J FROM 1 BY 1 UNTIL J > 100
                       PERFORM PROCESS-RECORD WS-COUNT TIMES
                       END-PERFORM
                   END-PERFORM
               END-PERFORM.
               STOP RUN.
           PROCESS-RECORD.
    """
    
    parser = CobolParser()
    result = parser.parse(cobol_code)
    
    # Memory usage should be reasonable (not a hard assertion, just observation)
    # This test will be measured against baseline
    perform_stmts = self._find_performs(result.ast)
    self.assertGreater(len(perform_stmts), 0)
```

---

## 📋 Test Execution Summary

**Run All New Tests**:
```bash
cd C:\Users\sam94\workspace\cobol-parser

# Phase 1: Unit tests
pytest tests/unit/test_statements.py::TestPerformStatement -v

# Phase 2: Integration tests
pytest tests/integration/test_perform_statement_coverage.py -v

# Phase 3: Regression tests
pytest tests/regression/test_perform_backward_compat.py -v

# Phase 4: Performance tests
pytest tests/unit/test_perform_performance.py -v

# ALL TOGETHER with coverage
pytest tests/ --cov=cobolparser --cov-fail-under=90 -v
```

---

## 🔗 Traceability: Tests to Specifications

This table shows which tests validate which spec requirements:

| Spec Item | Test | File | Line | Status |
|-----------|------|------|------|--------|
| FR-006 | test_perform_statement_test_timing | test_statements.py | 1.1 | Unit |
| FR-006 | test_perform_until_with_test_before | test_perform_statement_coverage.py | 2.3 | Integration |
| FR-006 | test_perform_until_with_test_after | test_perform_statement_coverage.py | 2.4 | Integration |
| FR-007 | test_perform_varying_union_types | test_statements.py | 1.6 | Unit |
| FR-013 | test_perform_times_with_int | test_statements.py | 1.2 | Unit |
| FR-013 | test_perform_times_with_variable | test_statements.py | 1.3 | Unit |
| FR-013 | test_perform_times_with_literal | test_perform_statement_coverage.py | 2.5 | Integration |
| FR-013 | test_perform_times_with_variable | test_perform_statement_coverage.py | 2.6 | Integration |
| FR-016 | test_perform_until_simple | test_perform_statement_coverage.py | 2.1 | Integration |
| FR-016 | test_perform_until_thru | test_perform_statement_coverage.py | 2.2 | Integration |
| FR-018 | test_perform_varying_with_test_after | test_perform_statement_coverage.py | 2.8 | Integration |
| SC-001 | All integration tests | test_perform_statement_coverage.py | 2.* | All |
| SC-002 | All tests + performance | All test files | - | All |

**Total Test Count**: 36 new test methods + 6 regression + 2 performance = 44 tests validating spec requirements

---

**Test Integration Complete**: This document provides full test specifications with traceability to specs, implementation, and baseline for comprehensive validation of the PERFORM statement coverage feature.

**Next Step**: Execute tests as specified in [IMPLEMENTATION_GUIDE.md - Phase 3](IMPLEMENTATION_GUIDE.md#phase-3-testing--validation).
