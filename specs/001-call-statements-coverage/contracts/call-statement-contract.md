# API Contract: CALL Statement Structure

**Phase**: 1 - Design & API Contracts  
**Date**: January 11, 2026  
**Coverage**: 6 CALL statement variation categories from spec.md User Stories

---

## Contract Overview

This contract defines the expected AST structure (to_dict output) for all 6 variations of CALL statements tested in Phase 2.

Each contract includes:
1. **COBOL Source**: Input program text
2. **AST Contract**: Expected to_dict() JSON structure
3. **Validation Rules**: Success criteria for parser

---

## Contract 1: Basic Static CALL (US-1, FR-001, FR-002)

### COBOL Source
```cobol
CALL "SUBPROGRAM"
```

### AST Contract (Expected to_dict() output)
```json
{
  "node_type": "CALL_STATEMENT",
  "called_program": "SUBPROGRAM",
  "is_dynamic": false,
  "location": {
    "line": 10,
    "column": 8,
    "length": 1
  },
  "using_parameters": [],
  "returning_parameter": null,
  "giving_parameter": null,
  "on_exception": [],
  "not_on_exception": [],
  "on_overflow": [],
  "possible_values": {}
}
```

### Validation Rules
- ✅ `node_type` must be "CALL_STATEMENT"
- ✅ `called_program` must be "SUBPROGRAM" (string literal)
- ✅ `is_dynamic` must be false (literal program name)
- ✅ `using_parameters` must be empty array
- ✅ All optional fields must be null or empty
- ✅ `location` must include line, column, length

### Test Case
**File**: `tests/unit/test_call_basic_parsing.py`  
**Method**: `test_call_with_literal_program_name`  
**Assertion**: `assert ast.to_dict() == expected_contract`

---

## Contract 2: Dynamic CALL with Variable (US-1, FR-002)

### COBOL Source
```cobol
CALL WS-PROGRAM-VAR
```

### AST Contract
```json
{
  "node_type": "CALL_STATEMENT",
  "called_program": "WS-PROGRAM-VAR",
  "is_dynamic": true,
  "location": {
    "line": 11,
    "column": 8,
    "length": 1
  },
  "using_parameters": [],
  "returning_parameter": null,
  "giving_parameter": null,
  "on_exception": [],
  "not_on_exception": [],
  "on_overflow": [],
  "possible_values": {}
}
```

### Validation Rules
- ✅ `is_dynamic` must be true (identifier program name)
- ✅ `called_program` must be "WS-PROGRAM-VAR" (variable name)
- ✅ No parameters

### Test Case
**File**: `tests/unit/test_call_basic_parsing.py`  
**Method**: `test_call_with_variable_program_name`  
**Assertion**: `assert ast.is_dynamic == True`

---

## Contract 3: CALL with Single Parameter (US-2, FR-003)

### COBOL Source
```cobol
CALL "PROCESS" USING BY REFERENCE WS-INPUT
```

### AST Contract
```json
{
  "node_type": "CALL_STATEMENT",
  "called_program": "PROCESS",
  "is_dynamic": false,
  "using_parameters": [
    {
      "name": "WS-INPUT",
      "passing_mode": "REFERENCE"
    }
  ],
  "returning_parameter": null,
  "giving_parameter": null,
  "on_exception": [],
  "not_on_exception": [],
  "on_overflow": [],
  "possible_values": {}
}
```

### Validation Rules
- ✅ `using_parameters` is array with 1 element
- ✅ First parameter has `name` = "WS-INPUT"
- ✅ First parameter has `passing_mode` = "REFERENCE"

### Test Case
**File**: `tests/unit/test_call_parameter_modes.py`  
**Method**: `test_by_reference_mode`  
**Assertion**: `assert ast.using_parameters[0].passing_mode == "REFERENCE"`

---

## Contract 4: CALL with Mixed Parameter Modes (US-2, FR-004)

### COBOL Source
```cobol
CALL "MIXED" USING BY REFERENCE P1
                  BY CONTENT P2
                  BY VALUE P3
```

### AST Contract
```json
{
  "node_type": "CALL_STATEMENT",
  "called_program": "MIXED",
  "is_dynamic": false,
  "using_parameters": [
    {
      "name": "P1",
      "passing_mode": "REFERENCE"
    },
    {
      "name": "P2",
      "passing_mode": "CONTENT"
    },
    {
      "name": "P3",
      "passing_mode": "VALUE"
    }
  ],
  "returning_parameter": null,
  "giving_parameter": null,
  "on_exception": [],
  "not_on_exception": [],
  "on_overflow": [],
  "possible_values": {}
}
```

### Validation Rules
- ✅ `using_parameters` length = 3
- ✅ Each parameter has correct `passing_mode` preserved
- ✅ Parameter order maintained: REFERENCE → CONTENT → VALUE

### Test Case
**File**: `tests/unit/test_call_parameter_modes.py`  
**Method**: `test_mixed_modes`  
**Assertion**: `assert len(ast.using_parameters) == 3; assert ast.using_parameters[1].passing_mode == "CONTENT"`

---

## Contract 5: CALL with RETURNING Clause (US-3, FR-005, FR-006)

### COBOL Source
```cobol
CALL "CALCULATOR" USING BY REFERENCE WS-INPUT
                   RETURNING WS-RESULT
```

### AST Contract
```json
{
  "node_type": "CALL_STATEMENT",
  "called_program": "CALCULATOR",
  "is_dynamic": false,
  "using_parameters": [
    {
      "name": "WS-INPUT",
      "passing_mode": "REFERENCE"
    }
  ],
  "returning_parameter": "WS-RESULT",
  "giving_parameter": null,
  "on_exception": [],
  "not_on_exception": [],
  "on_overflow": [],
  "possible_values": {}
}
```

### Validation Rules
- ✅ `returning_parameter` is "WS-RESULT"
- ✅ `giving_parameter` is null
- ✅ USING clause and RETURNING clause both present

### Test Case
**File**: `tests/unit/test_call_returning_giving.py`  
**Method**: `test_returning_only`  
**Assertion**: `assert ast.returning_parameter == "WS-RESULT"; assert ast.giving_parameter is None`

---

## Contract 6: CALL with Exception Handling (US-4, FR-007, FR-008, FR-009, FR-010)

### COBOL Source
```cobol
CALL "SERVICE"
    ON EXCEPTION
        DISPLAY "Error occurred"
    NOT ON EXCEPTION
        DISPLAY "Success"
    END-CALL
```

### AST Contract
```json
{
  "node_type": "CALL_STATEMENT",
  "called_program": "SERVICE",
  "is_dynamic": false,
  "using_parameters": [],
  "returning_parameter": null,
  "giving_parameter": null,
  "on_exception": [
    {
      "node_type": "DISPLAY_STATEMENT",
      "text": "Error occurred"
    }
  ],
  "not_on_exception": [
    {
      "node_type": "DISPLAY_STATEMENT",
      "text": "Success"
    }
  ],
  "on_overflow": [],
  "possible_values": {}
}
```

### Validation Rules
- ✅ `on_exception` is array with 1 DisplayStatement
- ✅ `not_on_exception` is array with 1 DisplayStatement
- ✅ Both handler arrays contain Statement objects (not empty)
- ✅ Statements have correct `node_type`

### Test Case
**File**: `tests/unit/test_call_exception_handling.py`  
**Method**: `test_on_exception_clause`  
**Assertion**: `assert len(ast.on_exception) == 1; assert ast.on_exception[0].node_type == "DISPLAY_STATEMENT"`

---

## Contract 7: CALL Across Multiple Lines (US-5, FR-011, FR-012)

### COBOL Source
```cobol
           CALL "MULTILINE" USING BY REFERENCE P1
     -                              BY CONTENT P2
     -                       RETURNING WS-RESULT
```

### AST Contract (Same as Contract 5)
```json
{
  "node_type": "CALL_STATEMENT",
  "called_program": "MULTILINE",
  "is_dynamic": false,
  "using_parameters": [
    {
      "name": "P1",
      "passing_mode": "REFERENCE"
    },
    {
      "name": "P2",
      "passing_mode": "CONTENT"
    }
  ],
  "returning_parameter": "WS-RESULT",
  "giving_parameter": null,
  "on_exception": [],
  "not_on_exception": [],
  "on_overflow": [],
  "possible_values": {}
}
```

### Validation Rules
- ✅ Multi-line statement parsed as single CALL
- ✅ Column 7 hyphen `-` correctly handles continuation
- ✅ All clauses from separate lines merged correctly
- ✅ AST structure identical to single-line version

### Test Case
**File**: `tests/unit/test_call_fixed_format.py`  
**Method**: `test_multiline_with_hyphen_continuation`  
**Assertion**: `assert ast.to_dict() == single_line_version.to_dict()`

---

## Contract 8: Dynamic CALL with Value Tracking (US-6, FR-015, FR-016)

### COBOL Source
```cobol
MOVE "PROG-A" TO WS-PROGRAM
MOVE "PROG-B" TO WS-PROGRAM
CALL WS-PROGRAM
```

### AST Contract for CALL Statement
```json
{
  "node_type": "CALL_STATEMENT",
  "called_program": "WS-PROGRAM",
  "is_dynamic": true,
  "using_parameters": [],
  "returning_parameter": null,
  "giving_parameter": null,
  "on_exception": [],
  "not_on_exception": [],
  "on_overflow": [],
  "possible_values": {
    "WS-PROGRAM": ["PROG-A", "PROG-B"]
  }
}
```

### Validation Rules
- ✅ `possible_values` contains dictionary
- ✅ Key is "WS-PROGRAM" (called program variable)
- ✅ Value is array of strings from MOVE statements
- ✅ Order preserved: ["PROG-A", "PROG-B"] (chronological)
- ✅ Only MOVE statements tracked (MVP scope)

### Test Case
**File**: `tests/unit/test_call_dynamic_analysis.py`  
**Method**: `test_multiple_moves_to_call`  
**Assertion**: `assert "WS-PROGRAM" in ast.possible_values; assert len(ast.possible_values["WS-PROGRAM"]) == 2`

---

## Mutual Exclusivity Contract (FR-006a)

### Invalid COBOL Source (Should Fail)
```cobol
CALL "FUNC" RETURNING RESULT-VAR GIVING OUTPUT-VAR
```

### Expected Parser Behavior
- **Status**: ParsingError raised
- **Error Message**: "RETURNING and GIVING clauses are mutually exclusive"
- **Location**: Line number and column of conflicting clause

### Test Case
**File**: `tests/unit/test_call_returning_giving.py`  
**Method**: `test_mutually_exclusive`  
**Assertion**: `with pytest.raises(ParsingError, match="mutually exclusive"): parser.parse(source)`

---

## Serialization Contract

### General Rules for All CALL Statement Variants

1. **Node Type**:
   - Must include `"node_type": "CALL_STATEMENT"`

2. **Location Information**:
   - Must include `location` dict with `line`, `column`, `length`
   - Used for error reporting

3. **Empty Collections**:
   - Empty arrays: `[]`
   - Null values: `null` (not omitted)

4. **JSON Compatibility**:
   - All values must be JSON-serializable
   - No Python objects in output
   - Strings, numbers, booleans, null, arrays, objects only

5. **Nested Statements**:
   - Exception handlers contain Statement objects
   - Each Statement has its own `to_dict()` method
   - Exception handler arrays recursive (to_dict on each element)

---

## Test Execution Commands

```bash
# Run all CALL statement contract tests
pytest tests/contracts/test_call_statement_contract.py -v

# Run specific contract
pytest tests/contracts/test_call_statement_contract.py::test_basic_static_call -v

# Verify JSON serialization
pytest tests/contracts/test_call_statement_contract.py -v -k "serialization"
```

---

## References

- **Data Model**: [data-model.md](../data-model.md)
- **Feature Specification**: [../spec.md](../spec.md)
- **Parser Implementation**: [../../../cobolparser/parser.py](../../../cobolparser/parser.py) line 4444+
- **CallStatement Model**: [../../../cobolparser/models/statements.py](../../../cobolparser/models/statements.py) line 268-350

---

**Contract Status**: ✅ COMPLETE  
**Contracts Included**: 8 variations + 1 mutual exclusivity rule  
**Ready for Phase 2 Testing**: YES

