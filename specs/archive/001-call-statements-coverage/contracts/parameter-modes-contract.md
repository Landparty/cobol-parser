# API Contract: Parameter Passing Modes

**Phase**: 1 - Design & API Contracts  
**Date**: January 11, 2026  
**Coverage**: Parameter passing modes in CALL statements (US-2, FR-003, FR-004)

---

## Contract Overview

This contract defines the expected behavior and AST structure for all parameter passing modes in CALL statements:
- BY REFERENCE: Default, parameter passed by address
- BY CONTENT: Parameter passed by value (copy)
- BY VALUE: IBM extension, numeric value only

---

## Contract 1: BY REFERENCE Parameter (Default)

### COBOL Source - Explicit
```cobol
CALL "PROCESS" USING BY REFERENCE WS-DATA
```

### COBOL Source - Implicit (Default)
```cobol
CALL "PROCESS" USING WS-DATA
```

### Expected AST Structure
```json
{
  "node_type": "CALL_STATEMENT",
  "called_program": "PROCESS",
  "is_dynamic": false,
  "using_parameters": [
    {
      "name": "WS-DATA",
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

### Semantics
- **Pass Method**: By address (reference)
- **Original Variable**: CAN be modified by called program
- **Visibility**: Changes visible to calling program after CALL
- **Performance**: Most efficient (no copy overhead)
- **Use Case**: When called program needs to modify data
- **Example**: Updating records, accumulating values

### Validation Rules
- ✅ `passing_mode` must be "REFERENCE"
- ✅ Both explicit `BY REFERENCE` and implicit (no keyword) map to "REFERENCE"
- ✅ Default mode when no mode specified
- ✅ Can be mixed with other modes

### Test Cases
**File**: `tests/unit/test_call_parameter_modes.py`

1. **test_by_reference_mode** (explicit):
   ```python
   assert ast.using_parameters[0].passing_mode == "REFERENCE"
   ```

2. **test_default_mode** (implicit):
   ```python
   assert ast.using_parameters[0].passing_mode == "REFERENCE"
   ```

---

## Contract 2: BY CONTENT Parameter

### COBOL Source
```cobol
CALL "PROCESS" USING BY CONTENT WS-DATA
```

### Expected AST Structure
```json
{
  "node_type": "CALL_STATEMENT",
  "called_program": "PROCESS",
  "is_dynamic": false,
  "using_parameters": [
    {
      "name": "WS-DATA",
      "passing_mode": "CONTENT"
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

### Semantics
- **Pass Method**: By value (copy of data)
- **Original Variable**: CANNOT be modified by called program
- **Visibility**: Original variable unchanged after CALL
- **Performance**: Less efficient (data copy overhead)
- **Use Case**: When called program should not modify input data
- **Example**: Read-only parameters, computed values

### Validation Rules
- ✅ `passing_mode` must be "CONTENT"
- ✅ Can be mixed with BY REFERENCE and BY VALUE
- ✅ Original variable protected from modification

### Test Case
**File**: `tests/unit/test_call_parameter_modes.py`  
**Method**: `test_by_content_mode`  
```python
assert ast.using_parameters[0].passing_mode == "CONTENT"
```

---

## Contract 3: BY VALUE Parameter

### COBOL Source
```cobol
CALL "CALCULATE" USING BY VALUE WS-COUNT
```

### Expected AST Structure
```json
{
  "node_type": "CALL_STATEMENT",
  "called_program": "CALCULATE",
  "is_dynamic": false,
  "using_parameters": [
    {
      "name": "WS-COUNT",
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

### Semantics
- **Pass Method**: Numeric value only (IBM extension)
- **Data Type**: Typically numeric (PIC 9, COMP, etc.)
- **Conversion**: Non-numeric data converted to number
- **Original Variable**: CANNOT be modified
- **Performance**: Efficient for numeric values
- **Use Case**: Numeric calculations, counters, flags
- **Example**: Passing iteration counts, amounts

### Validation Rules
- ✅ `passing_mode` must be "VALUE"
- ✅ Commonly used with numeric parameters
- ✅ Can be mixed with BY REFERENCE and BY CONTENT
- ✅ IBM Enterprise COBOL extension (not ANSI COBOL)

### Test Case
**File**: `tests/unit/test_call_parameter_modes.py`  
**Method**: `test_by_value_mode`  
```python
assert ast.using_parameters[0].passing_mode == "VALUE"
```

---

## Contract 4: Mixed Parameter Modes

### COBOL Source
```cobol
CALL "MIXED" USING BY REFERENCE P1
                  BY CONTENT P2
                  BY VALUE P3
                  USING P4
```

### Expected AST Structure
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
    },
    {
      "name": "P4",
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

### Semantics
- **Mode per Parameter**: Each parameter can have different mode
- **Independence**: Modes don't affect each other
- **Order Preserved**: Parameters maintain parsing order
- **Mixed Usage**: Real programs commonly use all three modes

### Validation Rules
- ✅ `using_parameters` array has 4 elements
- ✅ Each parameter has correct `passing_mode` independently
- ✅ Order preserved: P1, P2, P3, P4
- ✅ Modes can appear in any order

### Test Case
**File**: `tests/unit/test_call_parameter_modes.py`  
**Method**: `test_mixed_modes`  
```python
assert len(ast.using_parameters) == 4
assert ast.using_parameters[0].passing_mode == "REFERENCE"
assert ast.using_parameters[1].passing_mode == "CONTENT"
assert ast.using_parameters[2].passing_mode == "VALUE"
assert ast.using_parameters[3].passing_mode == "REFERENCE"
```

---

## Contract 5: No Parameters

### COBOL Source
```cobol
CALL "NOPARM"
```

### Expected AST Structure
```json
{
  "node_type": "CALL_STATEMENT",
  "called_program": "NOPARM",
  "is_dynamic": false,
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
- ✅ `using_parameters` is empty array
- ✅ CALL valid without any parameters
- ✅ Called program receives no data

### Test Case
**File**: `tests/unit/test_call_basic_parsing.py`  
**Method**: `test_call_with_no_parameters`  
```python
assert ast.using_parameters == []
```

---

## Contract 6: RETURNING with Parameter Modes

### COBOL Source
```cobol
CALL "FUNC" USING BY REFERENCE INPUT
                  BY CONTENT DATA
                  RETURNING RESULT
```

### Expected AST Structure
```json
{
  "node_type": "CALL_STATEMENT",
  "called_program": "FUNC",
  "is_dynamic": false,
  "using_parameters": [
    {
      "name": "INPUT",
      "passing_mode": "REFERENCE"
    },
    {
      "name": "DATA",
      "passing_mode": "CONTENT"
    }
  ],
  "returning_parameter": "RESULT",
  "giving_parameter": null,
  "on_exception": [],
  "not_on_exception": [],
  "on_overflow": [],
  "possible_values": {}
}
```

### Validation Rules
- ✅ Parameter modes work independently of RETURNING
- ✅ USING and RETURNING can coexist
- ✅ Each parameter has its mode, RETURNING is separate

### Test Case
**File**: `tests/unit/test_call_parameter_modes.py`  
**Method**: `test_modes_with_returning`  
```python
assert len(ast.using_parameters) == 2
assert ast.returning_parameter == "RESULT"
assert ast.using_parameters[0].passing_mode == "REFERENCE"
assert ast.using_parameters[1].passing_mode == "CONTENT"
```

---

## Contract 7: Exception Handlers with Parameter Modes

### COBOL Source
```cobol
CALL "SERVICE" USING BY VALUE REQUEST
    ON EXCEPTION
        DISPLAY "Service failed"
    NOT ON EXCEPTION
        MOVE "OK" TO STATUS
    END-CALL
```

### Expected AST Structure
```json
{
  "node_type": "CALL_STATEMENT",
  "called_program": "SERVICE",
  "is_dynamic": false,
  "using_parameters": [
    {
      "name": "REQUEST",
      "passing_mode": "VALUE"
    }
  ],
  "on_exception": [
    { "node_type": "DISPLAY_STATEMENT", "text": "Service failed" }
  ],
  "not_on_exception": [
    { "node_type": "MOVE_STATEMENT", "source": "OK", "target": "STATUS" }
  ],
  "on_overflow": [],
  "returning_parameter": null,
  "giving_parameter": null,
  "possible_values": {}
}
```

### Validation Rules
- ✅ Parameter modes independent of exception handlers
- ✅ USING, RETURNING, and exception handlers all coexist
- ✅ Each feature orthogonal to others

### Test Case
**File**: `tests/unit/test_call_parameter_modes.py`  
**Method**: `test_modes_with_exceptions`  
```python
assert ast.using_parameters[0].passing_mode == "VALUE"
assert len(ast.on_exception) == 1
assert len(ast.not_on_exception) == 1
```

---

## Parameter Mode Decision Table

| Scenario | Mode | When to Use | Example |
|----------|------|-----------|---------|
| Data needs modification | REFERENCE | Output parameters, updates | `USING BY REFERENCE RECORD` |
| Data is read-only | CONTENT | Input parameters, checks | `USING BY CONTENT INPUT` |
| Numeric value | VALUE | Counters, amounts, flags | `USING BY VALUE COUNT` |
| Default/unspecified | REFERENCE | Most common case | `USING PARAMETER` |

---

## Edge Cases & Validation

### Valid Combinations
- ✅ Mix all three modes in single CALL: `USING BY REF P1 BY CONTENT P2 BY VALUE P3`
- ✅ Repeat modes: `USING BY REF P1 BY REF P2`
- ✅ Modes with RETURNING: `USING BY VALUE X RETURNING RESULT`
- ✅ Modes with exception handlers: `USING BY CONTENT DATA ON EXCEPTION ...`

### Invalid Combinations (Should Fail)
- ❌ Invalid mode name: `USING BY REFERENCE? P1` (syntax error)
- ❌ Mode without parameter: `USING BY REFERENCE` (missing parameter)
- ❌ Duplicate RETURNING: `RETURNING A RETURNING B` (mutual exclusivity)

---

## Test Execution Commands

```bash
# Run all parameter mode tests
pytest tests/unit/test_call_parameter_modes.py -v

# Run specific mode test
pytest tests/unit/test_call_parameter_modes.py::test_by_reference_mode -v

# Run mixed mode tests
pytest tests/unit/test_call_parameter_modes.py::test_mixed_modes -v

# Verify default mode behavior
pytest tests/unit/test_call_parameter_modes.py::test_default_mode -v
```

---

## References

- **ANSI COBOL-85**: CALL statement parameter modes
- **IBM Enterprise COBOL**: BY VALUE extension
- **Specification**: [../spec.md](../spec.md) US-2 (Parameter Passing), FR-003, FR-004
- **Data Model**: [../data-model.md](../data-model.md) Entity: CallParameter
- **Related Contracts**: [call-statement-contract.md](call-statement-contract.md)

---

**Parameter Mode Contract Status**: ✅ COMPLETE  
**Modes Covered**: 3 (REFERENCE, CONTENT, VALUE)  
**Ready for Phase 2 Testing**: YES

