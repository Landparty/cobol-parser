# Quickstart Guide: CALL Statement Examples

**Phase**: 1 - Design & API Contracts  
**Date**: January 11, 2026  
**Coverage**: 6 examples for 6 user stories

---

## Overview

This quickstart guide provides one example for each user story, showing COBOL source code and the resulting AST JSON output.

Each example is independent and can be used as a reference for understanding the feature.

---

## Example 1: Basic Static CALL (US-1, FR-001)

**User Story**: As a COBOL parser user, I need to parse basic CALL statements with program names so I can analyze program dependencies.

### COBOL Source
```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLER.
       
       PROCEDURE DIVISION.
           CALL "SUBPROGRAM".
           STOP RUN.
```

### Parser Invocation
```python
from cobolparser import CobolParser

parser = CobolParser()
ast = parser.parse("""
    IDENTIFICATION DIVISION.
    PROGRAM-ID. CALLER.
    PROCEDURE DIVISION.
        CALL "SUBPROGRAM".
        STOP RUN.
""")

# Access the CALL statement
call_stmt = ast.program.procedure_division.statements[0]
print(call_stmt.to_dict())
```

### Expected AST (to_dict output)
```json
{
  "node_type": "CALL_STATEMENT",
  "called_program": "SUBPROGRAM",
  "is_dynamic": false,
  "location": {
    "line": 5,
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

### Key Points
- ✅ Static call: program name is string literal
- ✅ No parameters
- ✅ `is_dynamic` is false
- ✅ All optional fields are null or empty

### Related Spec
- **User Story**: [US-1](../spec.md#us-1-basic-call)
- **Requirements**: FR-001, FR-002
- **Test File**: tests/unit/test_call_basic_parsing.py

---

## Example 2: Parameters with Passing Modes (US-2, FR-003, FR-004)

**User Story**: As a developer analyzing COBOL code, I need the parser to capture parameter passing modes so I can understand data flow.

### COBOL Source
```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLER.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-INPUT PIC X(100).
       01 WS-COUNTER PIC 9(4) VALUE 0.
       01 WS-TEMP PIC X(50).
       
       PROCEDURE DIVISION.
           CALL "PROCESS" USING BY REFERENCE WS-INPUT
                                BY CONTENT WS-TEMP
                                BY VALUE WS-COUNTER.
           STOP RUN.
```

### Parser Invocation
```python
parser = CobolParser()
ast = parser.parse(cobol_source)
call_stmt = ast.program.procedure_division.statements[0]

# Check each parameter's passing mode
for i, param in enumerate(call_stmt.using_parameters):
    print(f"Param {i}: {param.name} -> {param.passing_mode}")
```

### Expected AST (to_dict output)
```json
{
  "node_type": "CALL_STATEMENT",
  "called_program": "PROCESS",
  "is_dynamic": false,
  "using_parameters": [
    {
      "name": "WS-INPUT",
      "passing_mode": "REFERENCE"
    },
    {
      "name": "WS-TEMP",
      "passing_mode": "CONTENT"
    },
    {
      "name": "WS-COUNTER",
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

### Key Points
- ✅ Three parameters with different passing modes
- ✅ BY REFERENCE: parameter can be modified
- ✅ BY CONTENT: parameter protected from modification
- ✅ BY VALUE: numeric value only
- ✅ Modes preserved independently

### Related Spec
- **User Story**: [US-2](../spec.md#us-2-parameter-passing)
- **Requirements**: FR-003, FR-004
- **Test File**: tests/unit/test_call_parameter_modes.py

---

## Example 3: RETURNING Clause (US-3, FR-005, FR-006, FR-006a)

**User Story**: As a code analyst, I need to identify which CALL statements return values to understand function-like patterns.

### COBOL Source
```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALCULATOR.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-NUM1 PIC 9(5).
       01 WS-NUM2 PIC 9(5).
       01 WS-RESULT PIC 9(5).
       
       PROCEDURE DIVISION.
           MOVE 10 TO WS-NUM1.
           MOVE 20 TO WS-NUM2.
           
           CALL "ADD" USING BY REFERENCE WS-NUM1
                            BY REFERENCE WS-NUM2
                      RETURNING WS-RESULT.
           
           DISPLAY "Result: " WS-RESULT.
           STOP RUN.
```

### Parser Invocation
```python
parser = CobolParser()
ast = parser.parse(cobol_source)
call_stmt = ast.program.procedure_division.statements[2]  # Third statement

print(f"Program: {call_stmt.called_program}")
print(f"Return variable: {call_stmt.returning_parameter}")
print(f"Has GIVING: {call_stmt.giving_parameter is not None}")
```

### Expected AST (to_dict output)
```json
{
  "node_type": "CALL_STATEMENT",
  "called_program": "ADD",
  "is_dynamic": false,
  "using_parameters": [
    {
      "name": "WS-NUM1",
      "passing_mode": "REFERENCE"
    },
    {
      "name": "WS-NUM2",
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

### Key Points
- ✅ RETURNING captures return value
- ✅ Both USING parameters and RETURNING present
- ✅ GIVING is null (RETURNING and GIVING are mutually exclusive)
- ✅ Return value stored in WS-RESULT

### Related Spec
- **User Story**: [US-3](../spec.md#us-3-returning-clause)
- **Requirements**: FR-005, FR-006, FR-006a
- **Test File**: tests/unit/test_call_returning_giving.py

---

## Example 4: Exception Handling (US-4, FR-007 through FR-010)

**User Story**: As a developer reviewing error handling logic, I need exception clauses parsed so I can verify error recovery completeness.

### COBOL Source
```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ERROR-HANDLER.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-STATUS PIC X(5).
       
       PROCEDURE DIVISION.
           CALL "SERVICE"
               ON EXCEPTION
                   DISPLAY "Service unavailable"
                   MOVE "ERR01" TO WS-STATUS
               NOT ON EXCEPTION
                   DISPLAY "Service called successfully"
                   MOVE "OK" TO WS-STATUS
               ON OVERFLOW
                   DISPLAY "Parameter stack overflow"
                   MOVE "ERR99" TO WS-STATUS
               END-CALL.
           
           DISPLAY "Status: " WS-STATUS.
           STOP RUN.
```

### Parser Invocation
```python
parser = CobolParser()
ast = parser.parse(cobol_source)
call_stmt = ast.program.procedure_division.statements[0]

print(f"Exception handlers: {len(call_stmt.on_exception)}")
print(f"Success handlers: {len(call_stmt.not_on_exception)}")
print(f"Overflow handlers: {len(call_stmt.on_overflow)}")

# Examine first exception handler statement
if call_stmt.on_exception:
    handler = call_stmt.on_exception[0]
    print(f"First handler type: {handler.node_type}")
```

### Expected AST (to_dict output)
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
      "text": "Service unavailable"
    },
    {
      "node_type": "MOVE_STATEMENT",
      "source": "ERR01",
      "target": "WS-STATUS"
    }
  ],
  "not_on_exception": [
    {
      "node_type": "DISPLAY_STATEMENT",
      "text": "Service called successfully"
    },
    {
      "node_type": "MOVE_STATEMENT",
      "source": "OK",
      "target": "WS-STATUS"
    }
  ],
  "on_overflow": [
    {
      "node_type": "DISPLAY_STATEMENT",
      "text": "Parameter stack overflow"
    },
    {
      "node_type": "MOVE_STATEMENT",
      "source": "ERR99",
      "target": "WS-STATUS"
    }
  ]
}
```

### Key Points
- ✅ Three exception handler types captured
- ✅ Multiple statements in each handler
- ✅ Statements execute in order (DISPLAY, MOVE)
- ✅ END-CALL properly terminates all handlers
- ✅ Handlers are independent (one executes at runtime)

### Related Spec
- **User Story**: [US-4](../spec.md#us-4-exception-handling)
- **Requirements**: FR-007, FR-008, FR-009, FR-010
- **Test File**: tests/unit/test_call_exception_handling.py

---

## Example 5: Multi-Line CALL (US-5, FR-011, FR-012)

**User Story**: As a user parsing legacy COBOL, I need multi-line CALL statements with continuation to work correctly.

### COBOL Source (Fixed Format)
```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MULTILINE.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-PROG PIC X(30).
       01 WS-INPUT PIC X(100).
       01 WS-OUTPUT PIC X(100).
       01 WS-RESULT PIC X(50).
       
       PROCEDURE DIVISION.
           CALL "PARSER" USING BY REFERENCE WS-INPUT
     -                         BY CONTENT WS-PROG
     -                   RETURNING WS-RESULT
     -               ON EXCEPTION
     -                   DISPLAY "Parse failed"
     -               END-CALL.
           STOP RUN.
```

### Parser Invocation
```python
parser = CobolParser()
ast = parser.parse(cobol_source)
call_stmt = ast.program.procedure_division.statements[0]

# Despite multi-line, parsed as single CALL statement
print(f"Program: {call_stmt.called_program}")
print(f"Params: {len(call_stmt.using_parameters)}")
print(f"Return: {call_stmt.returning_parameter}")
print(f"Exceptions: {len(call_stmt.on_exception)}")
```

### Expected AST (to_dict output - Same as single-line version)
```json
{
  "node_type": "CALL_STATEMENT",
  "called_program": "PARSER",
  "is_dynamic": false,
  "using_parameters": [
    {
      "name": "WS-INPUT",
      "passing_mode": "REFERENCE"
    },
    {
      "name": "WS-PROG",
      "passing_mode": "CONTENT"
    }
  ],
  "returning_parameter": "WS-RESULT",
  "giving_parameter": null,
  "on_exception": [
    {
      "node_type": "DISPLAY_STATEMENT",
      "text": "Parse failed"
    }
  ],
  "not_on_exception": [],
  "on_overflow": []
}
```

### Key Points
- ✅ Column 7 hyphen `-` marks continuation
- ✅ Multi-line statement parsed as single CALL
- ✅ All clauses from separate lines combined
- ✅ AST structure identical to single-line version
- ✅ Fixed format (columns 8-72) preserved

### Related Spec
- **User Story**: [US-5](../spec.md#us-5-cobol-fixed-format)
- **Requirements**: FR-011, FR-012
- **Test File**: tests/unit/test_call_fixed_format.py

---

## Example 6: Dynamic CALL Analysis (US-6, FR-015, FR-016)

**User Story**: As a program analyst, I need to track MOVE statements to variables used in CALL so I can understand which programs might be called.

### COBOL Source
```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DYNAMIC-CALLER.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-PROGRAM-VAR PIC X(30).
       01 WS-CHOICE PIC 9.
       
       PROCEDURE DIVISION.
           IF WS-CHOICE = 1
               MOVE "PROGRAM-A" TO WS-PROGRAM-VAR
           ELSE IF WS-CHOICE = 2
               MOVE "PROGRAM-B" TO WS-PROGRAM-VAR
           ELSE
               MOVE "PROGRAM-C" TO WS-PROGRAM-VAR
           END-IF.
           
           CALL WS-PROGRAM-VAR USING BY REFERENCE WS-CHOICE.
           STOP RUN.
```

### Parser Invocation
```python
parser = CobolParser()
ast = parser.parse(cobol_source)
call_stmt = ast.program.procedure_division.statements[1]  # Second statement

print(f"Dynamic call: {call_stmt.is_dynamic}")
print(f"Program variable: {call_stmt.called_program}")
print(f"Possible values: {call_stmt.possible_values}")

# Access tracked values
if "WS-PROGRAM-VAR" in call_stmt.possible_values:
    progs = call_stmt.possible_values["WS-PROGRAM-VAR"]
    print(f"Possible programs: {progs}")
```

### Expected AST (to_dict output)
```json
{
  "node_type": "CALL_STATEMENT",
  "called_program": "WS-PROGRAM-VAR",
  "is_dynamic": true,
  "using_parameters": [
    {
      "name": "WS-CHOICE",
      "passing_mode": "REFERENCE"
    }
  ],
  "returning_parameter": null,
  "giving_parameter": null,
  "on_exception": [],
  "not_on_exception": [],
  "on_overflow": [],
  "possible_values": {
    "WS-PROGRAM-VAR": ["PROGRAM-A", "PROGRAM-B", "PROGRAM-C"]
  }
}
```

### Key Points
- ✅ Dynamic call: program name is variable
- ✅ `is_dynamic` is true
- ✅ `possible_values` tracks MOVE statements to called program variable
- ✅ Three possible programs identified: A, B, C
- ✅ MVP scope: Only direct MOVE statements (not assignments from other sources)

### Related Spec
- **User Story**: [US-6](../spec.md#us-6-dynamic-call-analysis)
- **Requirements**: FR-015, FR-016
- **Test File**: tests/unit/test_call_dynamic_analysis.py
- **Scope Limitation**: MOVE statements only (see research.md Section 4)

---

## Quick Reference: Parser API

### Basic Usage
```python
from cobolparser import CobolParser

# Create parser
parser = CobolParser()

# Parse COBOL source
ast = parser.parse(cobol_source_code)

# Access CALL statements in procedure division
for statement in ast.program.procedure_division.statements:
    if statement.node_type == "CALL_STATEMENT":
        print(f"Found CALL: {statement.called_program}")
        print(f"Dynamic: {statement.is_dynamic}")
        print(f"Parameters: {len(statement.using_parameters)}")
```

### Accessing CALL Statement Properties
```python
call = statement  # Assume this is a CallStatement

# Program name
print(call.called_program)      # String: "PROG" or "WS-VAR"

# Dynamic indicator
print(call.is_dynamic)          # Boolean: True/False

# Parameters
for param in call.using_parameters:
    print(f"  {param.name}: {param.passing_mode}")

# Return value
print(call.returning_parameter) # String or None

# Exception handlers
if call.on_exception:
    print("Has exception handler")
    for stmt in call.on_exception:
        print(f"  Handler: {stmt.node_type}")

# Possible values (dynamic analysis)
print(call.possible_values)     # Dict[str, List[str]]
```

### JSON Export
```python
# Convert to JSON-compatible dictionary
call_dict = call_statement.to_dict()

# Pretty-print
import json
print(json.dumps(call_dict, indent=2))
```

---

## Running the Examples

```bash
# Create a COBOL file with example 1
cat > example1.cob << 'EOF'
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLER.
       PROCEDURE DIVISION.
           CALL "SUBPROGRAM".
           STOP RUN.
EOF

# Parse with Python
python << 'EOF'
from cobolparser import CobolParser
import json

parser = CobolParser()
ast = parser.parse(open('example1.cob').read())
call = ast.program.procedure_division.statements[0]
print(json.dumps(call.to_dict(), indent=2))
EOF
```

---

## References

- **Feature Specification**: [spec.md](../spec.md)
- **Data Model**: [data-model.md](../data-model.md)
- **API Contracts**: contracts/ directory
- **Test Files**: tests/unit/test_call_*.py
- **Parser Code**: cobolparser/parser.py (line 4444+)

---

**Quickstart Status**: ✅ COMPLETE  
**Examples**: 6 (one per user story)  
**Ready for Phase 2 Testing**: YES

