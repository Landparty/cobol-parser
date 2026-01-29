# API Contract: Exception Handlers

**Phase**: 1 - Design & API Contracts  
**Date**: January 11, 2026  
**Coverage**: Exception handling clauses in CALL statements (US-4, FR-007 through FR-010)

---

## Contract Overview

This contract defines the expected structure for exception handler clauses in CALL statements:
- ON EXCEPTION: Executed if CALL fails
- NOT ON EXCEPTION: Executed if CALL succeeds
- ON OVERFLOW: Executed on parameter stack overflow

---

## Contract 1: ON EXCEPTION Handler

### COBOL Source
```cobol
CALL "SERVICE"
    ON EXCEPTION
        DISPLAY "Error: Service failed"
        MOVE 1 TO RETURN-CODE
    END-CALL
```

### Expected AST Structure
```json
{
  "node_type": "CALL_STATEMENT",
  "called_program": "SERVICE",
  "is_dynamic": false,
  "on_exception": [
    {
      "node_type": "DISPLAY_STATEMENT",
      "text": "Error: Service failed",
      "location": { "line": 3, "column": 8, "length": 1 }
    },
    {
      "node_type": "MOVE_STATEMENT",
      "source": "1",
      "target": "RETURN-CODE",
      "location": { "line": 4, "column": 8, "length": 1 }
    }
  ],
  "not_on_exception": [],
  "on_overflow": []
}
```

### Validation Rules
- ✅ `on_exception` is array of Statement objects
- ✅ Each statement has `node_type` and `location`
- ✅ Multiple statements execute in order
- ✅ Statements can be different types (DISPLAY, MOVE, etc.)

### Test Case
**File**: `tests/unit/test_call_exception_handling.py`  
**Method**: `test_on_exception_clause`  
**Assertion**: `assert len(ast.on_exception) == 2; assert ast.on_exception[0].node_type == "DISPLAY_STATEMENT"`

---

## Contract 2: NOT ON EXCEPTION Handler

### COBOL Source
```cobol
CALL "OPERATION"
    NOT ON EXCEPTION
        DISPLAY "Operation successful"
    END-CALL
```

### Expected AST Structure
```json
{
  "node_type": "CALL_STATEMENT",
  "called_program": "OPERATION",
  "is_dynamic": false,
  "on_exception": [],
  "not_on_exception": [
    {
      "node_type": "DISPLAY_STATEMENT",
      "text": "Operation successful",
      "location": { "line": 3, "column": 8, "length": 1 }
    }
  ],
  "on_overflow": []
}
```

### Validation Rules
- ✅ `not_on_exception` is array of Statement objects
- ✅ Can be paired with ON EXCEPTION or standalone
- ✅ Executes when CALL succeeds (no exception)

### Test Case
**File**: `tests/unit/test_call_exception_handling.py`  
**Method**: `test_not_on_exception_clause`  
**Assertion**: `assert len(ast.not_on_exception) == 1; assert ast.on_exception == []`

---

## Contract 3: Both ON EXCEPTION and NOT ON EXCEPTION

### COBOL Source
```cobol
CALL "PROCESS"
    ON EXCEPTION
        DISPLAY "Failed"
    NOT ON EXCEPTION
        DISPLAY "Succeeded"
    END-CALL
```

### Expected AST Structure
```json
{
  "node_type": "CALL_STATEMENT",
  "called_program": "PROCESS",
  "is_dynamic": false,
  "on_exception": [
    {
      "node_type": "DISPLAY_STATEMENT",
      "text": "Failed"
    }
  ],
  "not_on_exception": [
    {
      "node_type": "DISPLAY_STATEMENT",
      "text": "Succeeded"
    }
  ],
  "on_overflow": []
}
```

### Validation Rules
- ✅ Both handler arrays populated
- ✅ Handlers execute conditionally (one or the other)
- ✅ Mutual exclusion: ON EXCEPTION XOR NOT ON EXCEPTION at runtime
- ✅ END-CALL properly terminates handler list

### Test Case
**File**: `tests/unit/test_call_exception_handling.py`  
**Method**: `test_both_exception_clauses`  
**Assertion**: `assert len(ast.on_exception) == 1; assert len(ast.not_on_exception) == 1`

---

## Contract 4: ON OVERFLOW Handler

### COBOL Source
```cobol
CALL "UTILITY" USING P1 P2 P3
    ON OVERFLOW
        DISPLAY "Too many parameters"
    END-CALL
```

### Expected AST Structure
```json
{
  "node_type": "CALL_STATEMENT",
  "called_program": "UTILITY",
  "is_dynamic": false,
  "using_parameters": [
    { "name": "P1", "passing_mode": "REFERENCE" },
    { "name": "P2", "passing_mode": "REFERENCE" },
    { "name": "P3", "passing_mode": "REFERENCE" }
  ],
  "on_exception": [],
  "not_on_exception": [],
  "on_overflow": [
    {
      "node_type": "DISPLAY_STATEMENT",
      "text": "Too many parameters"
    }
  ]
}
```

### Validation Rules
- ✅ `on_overflow` is array of Statement objects
- ✅ Triggered when parameter stack overflows (rare at runtime)
- ✅ Can be combined with ON EXCEPTION clauses
- ✅ Independent of ON EXCEPTION / NOT ON EXCEPTION

### Test Case
**File**: `tests/unit/test_call_exception_handling.py`  
**Method**: `test_on_overflow_clause`  
**Assertion**: `assert len(ast.on_overflow) == 1; assert ast.on_overflow[0].node_type == "DISPLAY_STATEMENT"`

---

## Contract 5: All Three Exception Handlers

### COBOL Source
```cobol
CALL "COMPLEX"
    ON EXCEPTION
        DISPLAY "Exception"
    NOT ON EXCEPTION
        DISPLAY "No exception"
    ON OVERFLOW
        DISPLAY "Overflow"
    END-CALL
```

### Expected AST Structure
```json
{
  "node_type": "CALL_STATEMENT",
  "called_program": "COMPLEX",
  "is_dynamic": false,
  "on_exception": [
    { "node_type": "DISPLAY_STATEMENT", "text": "Exception" }
  ],
  "not_on_exception": [
    { "node_type": "DISPLAY_STATEMENT", "text": "No exception" }
  ],
  "on_overflow": [
    { "node_type": "DISPLAY_STATEMENT", "text": "Overflow" }
  ]
}
```

### Validation Rules
- ✅ All three handler arrays populated
- ✅ Order doesn't matter (ON EXCEPTION, NOT ON EXCEPTION, ON OVERFLOW can appear in any order)
- ✅ Runtime: Only one branch executes (exception, success, or overflow)
- ✅ END-CALL terminates all handlers

### Test Case
**File**: `tests/unit/test_call_exception_handling.py`  
**Method**: `test_all_three_handlers`  
**Assertion**: `assert len(ast.on_exception) == 1; assert len(ast.not_on_exception) == 1; assert len(ast.on_overflow) == 1`

---

## Contract 6: END-CALL Terminator

### COBOL Source (With END-CALL)
```cobol
CALL "PROC1"
    ON EXCEPTION
        CALL "ERROR-HANDLER"
        DISPLAY "Error handled"
    END-CALL
CALL "PROC2"
```

### Expected Behavior
- ✅ First CALL ends at END-CALL (line 5)
- ✅ Exception handler contains both CALL and DISPLAY
- ✅ Second CALL (line 6) is separate CALL statement
- ✅ Handlers properly bounded by END-CALL

### Validation Rules
- ✅ END-CALL is mandatory when exception handlers present
- ✅ Marks end of all exception handler clauses
- ✅ Next statement after END-CALL is independent

### Test Case
**File**: `tests/unit/test_call_exception_handling.py`  
**Method**: `test_end_call_terminator`  
**Assertion**: AST contains 2 separate CallStatement objects

---

## Contract 7: Nested Statements in Handlers

### COBOL Source
```cobol
CALL "SERVICE"
    ON EXCEPTION
        IF ERROR-CODE = "001"
            DISPLAY "Database error"
            MOVE 1 TO RETRY-COUNT
        ELSE
            DISPLAY "Unknown error"
        END-IF
    END-CALL
```

### Expected AST Structure
```json
{
  "on_exception": [
    {
      "node_type": "IF_STATEMENT",
      "condition": { "left": "ERROR-CODE", "operator": "=", "right": "001" },
      "then_statements": [
        { "node_type": "DISPLAY_STATEMENT", "text": "Database error" },
        { "node_type": "MOVE_STATEMENT", "source": "1", "target": "RETRY-COUNT" }
      ],
      "else_statements": [
        { "node_type": "DISPLAY_STATEMENT", "text": "Unknown error" }
      ]
    }
  ]
}
```

### Validation Rules
- ✅ Exception handlers can contain complex nested statements
- ✅ IF/THEN/ELSE statements properly nested in handler
- ✅ Multiple statements in handler branches
- ✅ Recursion depth limits apply to nested statements

### Test Case
**File**: `tests/unit/test_call_exception_handling.py`  
**Method**: `test_nested_statements_in_handlers`  
**Assertion**: `assert ast.on_exception[0].node_type == "IF_STATEMENT"`

---

## Contract 8: Empty Exception Handlers

### COBOL Source
```cobol
CALL "NULLOP"
    ON EXCEPTION
    NOT ON EXCEPTION
    END-CALL
```

### Expected AST Structure
```json
{
  "node_type": "CALL_STATEMENT",
  "on_exception": [],
  "not_on_exception": [],
  "on_overflow": []
}
```

### Validation Rules
- ✅ Handler clauses present but no statements
- ✅ Empty arrays (not null)
- ✅ Parser handles empty handler gracefully
- ✅ No error when handler has no action

### Test Case
**File**: `tests/unit/test_call_exception_handling.py`  
**Method**: `test_empty_exception_handlers`  
**Assertion**: `assert ast.on_exception == []; assert ast.not_on_exception == []`

---

## Validation Rules Summary

### Handler Syntax Rules
1. ON EXCEPTION must include at least one statement (in practice)
2. NOT ON EXCEPTION and ON OVERFLOW can be empty
3. Handlers end at END-CALL or next major statement
4. Clause order not enforced: can appear in any order

### Handler Execution Rules (Runtime)
1. ON EXCEPTION: Executed if CALL raises exception (call failed)
2. NOT ON EXCEPTION: Executed if CALL succeeds (no exception)
3. ON OVERFLOW: Executed if parameter stack overflow occurs
4. Only one branch executes per CALL invocation

### Nesting Rules
1. Handlers can contain any valid COBOL statement
2. Statements can be nested arbitrarily (with recursion limit)
3. Handlers can contain other CALLs with their own handlers
4. Maximum nesting depth: 50 levels (research.md recommendation)

---

## Test Execution Commands

```bash
# Run all exception handler tests
pytest tests/unit/test_call_exception_handling.py -v

# Run specific handler test
pytest tests/unit/test_call_exception_handling.py::test_on_exception_clause -v

# Verify handler serialization
pytest tests/unit/test_call_exception_handling.py -v -k "serialization"
```

---

## References

- **Specification**: [../spec.md](../spec.md) US-4 (Exception Handling), FR-007 through FR-010
- **COBOL Standard**: ANSI COBOL-85 exception handling
- **IBM Enterprise**: COBOL exception handling extensions
- **Related Contracts**: [call-statement-contract.md](call-statement-contract.md)
- **Data Model**: [../data-model.md](../data-model.md)

---

**Exception Handler Contract Status**: ✅ COMPLETE  
**Handler Types Covered**: 3 (ON EXCEPTION, NOT ON EXCEPTION, ON OVERFLOW)  
**Ready for Phase 2 Testing**: YES

