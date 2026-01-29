# Data Model: CALL Statement Components

**Phase**: 1 - Design & API Contracts  
**Date**: January 11, 2026  
**Input**: research.md (Phase 0 findings)  
**Status**: Complete

---

## Entity: CallStatement

### Definition

`CallStatement` is the primary AST node representing COBOL CALL statements. It captures all variations of program invocation including static calls, dynamic calls, parameter passing, return values, and exception handling.

### Location
- File: `cobolparser/models/statements.py`
- Lines: 268-350
- Base Class: `ASTNode`

### Core Properties

| Property | Type | Required | Default | Constraint |
|----------|------|----------|---------|-----------|
| `called_program` | str | YES | – | Program name (literal or identifier) |
| `is_dynamic` | bool | NO | False | True if program name is identifier (CALL VAR) |
| `using_parameters` | List[CallParameter] | NO | [] | Parameters passed to called program |
| `returning_parameter` | Optional[str] | NO | None | Variable to receive return value |
| `giving_parameter` | Optional[str] | NO | None | IBM extension: alternative return value capture |
| `on_exception` | List[Statement] | NO | [] | Statements to execute if CALL fails |
| `not_on_exception` | List[Statement] | NO | [] | Statements to execute if CALL succeeds |
| `on_overflow` | List[Statement] | NO | [] | Statements to execute on parameter stack overflow |
| `possible_values` | Dict[str, List[str]] | NO | {} | Tracked values for dynamic CALL analysis |

### Constraints & Validation

**Mutual Exclusivity** (FR-006a):
- ❌ RETURNING and GIVING **cannot both be present**
- ✅ Either RETURNING or GIVING is allowed
- ✅ Neither RETURNING nor GIVING is allowed
- **Implementation**: Validate at parse time in `cobolparser/parser.py` parse_call_statement()

**Parameter Validation** (FR-003, FR-004):
- Each parameter in `using_parameters` must have valid `passing_mode`:
  - `"REFERENCE"` (default): Parameter passed by reference (modifications visible to caller)
  - `"CONTENT"`: Parameter passed by value (copy of data)
  - `"VALUE"`: IBM extension, numeric value only
- Invalid passing modes should raise validation error

**Exception Handler Structure** (FR-007 through FR-010):
- Each handler list (`on_exception`, `not_on_exception`, `on_overflow`) is a list of Statement objects
- Handlers execute in order until END-CALL
- Each handler can contain nested statements
- Exception handlers can be empty lists (no action for that handler)

### Methods

| Method | Parameters | Returns | Purpose |
|--------|-----------|---------|---------|
| `set_called_program(name)` | name: str | None | Set program name |
| `add_using_parameter(param)` | param: CallParameter | None | Add parameter to USING clause |
| `set_returning_parameter(var_name)` | var_name: str | None | Set RETURNING clause variable |
| `set_giving_parameter(var_name)` | var_name: str | None | Set GIVING clause variable |
| `to_dict()` | None | Dict | Serialize to JSON-compatible dictionary |

### Serialization (to_dict)

```python
{
    "node_type": "CALL_STATEMENT",
    "called_program": "SUBPROGRAM",  # or identifier name
    "is_dynamic": false,
    "location": {
        "line": 42,
        "column": 8,
        "length": 1
    },
    "using_parameters": [
        {
            "name": "PARAM1",
            "passing_mode": "REFERENCE"
        }
    ],
    "returning_parameter": "RESULT-VAR",
    "giving_parameter": null,
    "on_exception": [
        {
            "node_type": "DISPLAY_STATEMENT",
            "text": "ERROR"
        }
    ],
    "not_on_exception": [],
    "on_overflow": [],
    "possible_values": {
        "WS-PROG-VAR": ["PROG-A", "PROG-B"]
    }
}
```

### Examples

#### Example 1: Basic Static CALL
```cobol
CALL "SUBPROGRAM"
```
```python
CallStatement(
    called_program="SUBPROGRAM",
    is_dynamic=False,
    using_parameters=[],
    returning_parameter=None,
    giving_parameter=None,
    on_exception=[],
    not_on_exception=[],
    on_overflow=[]
)
```

#### Example 2: Dynamic CALL with Parameters
```cobol
CALL WS-PROGRAM-VAR USING BY REFERENCE WS-INPUT
                           BY VALUE WS-COUNT
                     RETURNING WS-RESULT
```
```python
CallStatement(
    called_program="WS-PROGRAM-VAR",
    is_dynamic=True,
    using_parameters=[
        CallParameter("WS-INPUT", passing_mode="REFERENCE"),
        CallParameter("WS-COUNT", passing_mode="VALUE")
    ],
    returning_parameter="WS-RESULT",
    giving_parameter=None,
    on_exception=[],
    not_on_exception=[],
    on_overflow=[],
    possible_values={"WS-PROGRAM-VAR": ["PROG-A", "PROG-B"]}
)
```

#### Example 3: CALL with Exception Handling
```cobol
CALL "SERVICE"
    ON EXCEPTION
        DISPLAY "Service unavailable"
        MOVE 1 TO RETURN-CODE
    NOT ON EXCEPTION
        DISPLAY "Service called successfully"
    ON OVERFLOW
        DISPLAY "Parameter stack overflow"
    END-CALL
```
```python
CallStatement(
    called_program="SERVICE",
    is_dynamic=False,
    using_parameters=[],
    returning_parameter=None,
    giving_parameter=None,
    on_exception=[
        DisplayStatement("Service unavailable"),
        MoveStatement("1", "RETURN-CODE")
    ],
    not_on_exception=[
        DisplayStatement("Service called successfully")
    ],
    on_overflow=[
        DisplayStatement("Parameter stack overflow")
    ]
)
```

---

## Entity: CallParameter

### Definition

`CallParameter` represents a single parameter in a CALL statement's USING clause. It captures the parameter name and how the parameter is passed to the called program.

### Location
- File: `cobolparser/models/statements.py`
- Lines: 286-298
- Parent: Referenced by `CallStatement.using_parameters`

### Core Properties

| Property | Type | Required | Default | Constraint |
|----------|------|----------|---------|-----------|
| `name` | str | YES | – | Parameter identifier (COBOL variable name) |
| `passing_mode` | str | NO | "REFERENCE" | How parameter is passed: REFERENCE, CONTENT, or VALUE |
| `giving_parameter` | bool | NO | False | Internal flag for GIVING clause (rarely used) |
| `returning_parameter` | bool | NO | False | Internal flag for RETURNING clause (rarely used) |

### Passing Modes

**BY REFERENCE** (Default):
- Parameter passed by address
- Called program can modify original variable
- Changes visible to calling program after CALL
- Most common mode
- Example: `CALL "SUB" USING BY REFERENCE VAR`

**BY CONTENT**:
- Parameter passed by value (copy)
- Called program receives copy of data
- Original variable protected from modification
- Used when data should not be changed
- Example: `CALL "SUB" USING BY CONTENT VAR`

**BY VALUE** (IBM Enterprise COBOL):
- Numeric value only (IBM extension)
- Conversion may occur for non-numeric data
- Used for performance with simple values
- Limited to scalar types
- Example: `CALL "SUB" USING BY VALUE COUNTER`

### Validation Rules

1. **Valid passing_mode values**: `"REFERENCE"`, `"CONTENT"`, `"VALUE"`
2. **Default behavior**: If no passing mode specified, defaults to `"REFERENCE"`
3. **Type checking**: Parameter name must be valid COBOL identifier (alphanumeric, underscore)

### Serialization

```python
{
    "name": "PARAMETER-NAME",
    "passing_mode": "REFERENCE"  # or "CONTENT" or "VALUE"
}
```

### Examples

#### Example 1: BY REFERENCE (default)
```cobol
CALL "PROCESS" USING BY REFERENCE WS-DATA
```
```python
CallParameter("WS-DATA", passing_mode="REFERENCE")
```

#### Example 2: BY CONTENT
```cobol
CALL "CALC" USING BY CONTENT INPUT-VALUE
```
```python
CallParameter("INPUT-VALUE", passing_mode="CONTENT")
```

#### Example 3: BY VALUE
```cobol
CALL "INCREMENT" USING BY VALUE COUNTER
```
```python
CallParameter("COUNTER", passing_mode="VALUE")
```

#### Example 4: Default (no explicit mode)
```cobol
CALL "SUB" USING VAR1 VAR2 VAR3
```
```python
[
    CallParameter("VAR1", passing_mode="REFERENCE"),
    CallParameter("VAR2", passing_mode="REFERENCE"),
    CallParameter("VAR3", passing_mode="REFERENCE")
]
```

---

## Relationships

### CallStatement → CallParameter
- **Type**: One-to-Many
- **Cardinality**: 1 CallStatement → 0..N CallParameters
- **Relationship**: `CallStatement.using_parameters` is a list of `CallParameter` objects
- **Example**: A CALL with 3 parameters has 3 CallParameter objects

### CallStatement → Exception Handlers
- **Type**: One-to-Many
- **Cardinality**: 1 CallStatement → 0..3 exception handler lists
- **Exception Handler Types**:
  1. `on_exception`: Statements to execute if CALL fails
  2. `not_on_exception`: Statements to execute if CALL succeeds
  3. `on_overflow`: Statements to execute on parameter stack overflow

### CallStatement → Dynamic Value Tracking
- **Type**: One-to-Many
- **Property**: `possible_values` dictionary
- **Key**: Variable name (identifier for dynamic CALL)
- **Value**: List of possible string values (from MOVE tracking)
- **Scope**: MVP only tracks MOVE statements (see research.md Section 4)

---

## Constraints Summary

**Mandatory Constraints**:
- [x] Mutual exclusivity: RETURNING XOR GIVING (FR-006a)
- [x] Parameter validation: Valid passing modes only
- [x] Exception handler types: on_exception, not_on_exception, on_overflow

**Optional Constraints**:
- [ ] Recursion depth limit: Consider 50-level nesting limit (research.md Section 2)
- [ ] Dynamic value tracking: Currently unlimited, MVP scope only (research.md Section 4)

**Serialization Constraints**:
- [x] All AST nodes must implement `to_dict()` method
- [x] Serialization must include SourceLocation (line, column, length)
- [x] All values must be JSON-compatible types

---

## References

- **Framework Baseline**: [framework-baseline.md Section 2](framework-baseline.md)
- **Feature Specification**: [spec.md](spec.md) FR-001 through FR-022
- **Source Code**: [cobolparser/models/statements.py](../../../cobolparser/models/statements.py) lines 268-350
- **Research Findings**: [research.md](research.md)

---

**Data Model Status**: ✅ COMPLETE  
**Ready for Phase 1 Contracts**: YES - Proceed with T009-T011

