# CALL Statement Parsing Examples

This document shows examples of how CALL statements are parsed into AST nodes, including support for dynamic CALL statements that use variables instead of literal program names, parameter passing modes, exception handling, and fixed-format COBOL support.

## CLI Examples

```bash
# Find all CALL statements in a program
cobol-parser parse program.cbl --find-type CallStatement

# Analyze dynamic CALL targets (tracks possible values via MOVE analysis)
cobol-parser analyze program.cbl

# Analyze with copybook expansion
cobol-parser analyze program.cbl --copybook-path ./copybooks

# Navigate to a specific paragraph that contains CALLs
cobol-parser parse program.cbl procedure.CALL-SUBPROGRAM
```

## Table of Contents
- [Static CALL Statements](#static-call-statements)
  - [Basic CALL Statement](#basic-call-statement)
  - [CALL with GIVING Clause](#call-with-giving-clause)
  - [CALL with Exception Handling](#call-with-exception-handling)
  - [CALL with Literal Program Name](#call-with-literal-program-name)
- [CALL Statement in Fixed Format](#call-statement-in-fixed-format)
  - [Multi-line CALL with Continuation](#multi-line-call-with-continuation)
  - [Columns 8-72 Compliance](#columns-8-72-compliance)
- [Parameter Passing Modes Explained](#parameter-passing-modes-explained)
  - [BY REFERENCE Mode](#by-reference-mode)
  - [BY CONTENT Mode](#by-content-mode)
  - [BY VALUE Mode](#by-value-mode)
  - [Mixed Modes in Single CALL](#mixed-modes-in-single-call)
- [Exception Handling Best Practices](#exception-handling-best-practices)
  - [ON EXCEPTION Handler](#on-exception-handler)
  - [NOT ON EXCEPTION Handler](#not-on-exception-handler)
  - [ON OVERFLOW Handler](#on-overflow-handler)
  - [END-CALL Terminator](#end-call-terminator)
- [Dynamic CALL Statements](#dynamic-call-statements)
  - [Basic Dynamic CALL](#basic-dynamic-call)
  - [Dynamic CALL with Value Tracking](#dynamic-call-with-value-tracking)
  - [Dynamic CALL Analysis](#dynamic-call-analysis)
- [Usage in Code Analysis](#usage-in-code-analysis)

## Static CALL Statements

Static CALL statements use literal string values for the program name.

## Basic CALL Statement

### COBOL Source
```cobol
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           CALL "SUBPROGRAM" USING WS-PARAM1 WS-PARAM2.
           STOP RUN.
```

### Parsed AST Output
```json
{
  "node_type": "CallStatement",
  "called_program": "SUBPROGRAM",
  "using_parameters": [
    {"name": "WS-PARAM1", "mode": "REFERENCE"},
    {"name": "WS-PARAM2", "mode": "REFERENCE"}
  ],
  "giving_parameter": null,
  "returning_parameter": null,
  "is_dynamic": false,
  "possible_values": [],
  "on_overflow": null,
  "on_exception": null,
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {}
}
```

### Key Properties
- `called_program`: The name of the program being called (string)
- `using_parameters`: Array of parameter objects with `name` and `mode` (REFERENCE, CONTENT, or VALUE)
- `giving_parameter`: Optional parameter that receives the return value (legacy)
- `returning_parameter`: Optional parameter for RETURNING clause
- `is_dynamic`: False for static calls (literal program name), True for variable-based calls
- `possible_values`: Array of possible values for dynamic calls
- `on_overflow`/`on_exception`/`not_on_exception`: Exception handling clauses

## CALL with GIVING Clause

### COBOL Source
```cobol
       PROCEDURE DIVISION.
       CALCULATE-RESULT.
           CALL "CALCULATOR" USING WS-NUM1 WS-NUM2
                             GIVING WS-RESULT.
```

### Parsed AST Output
```json
{
  "node_type": "CallStatement",
  "called_program": "CALCULATOR",
  "using_parameters": [
    {"name": "WS-NUM1", "mode": "REFERENCE"},
    {"name": "WS-NUM2", "mode": "REFERENCE"}
  ],
  "giving_parameter": "WS-RESULT",
  "returning_parameter": null,
  "is_dynamic": false,
  "possible_values": [],
  "on_overflow": null,
  "on_exception": null,
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {}
}
```

## CALL with Exception Handling

### COBOL Source
```cobol
       PROCEDURE DIVISION.
       CALL-SUBPROGRAM.
           CALL "VALIDATOR" USING WS-INPUT-DATA
                          ON EXCEPTION
                             MOVE "ERROR" TO WS-STATUS
                          NOT ON EXCEPTION
                             MOVE "SUCCESS" TO WS-STATUS.
```

### Parsed AST Output
```json
{
  "node_type": "CallStatement",
  "called_program": "VALIDATOR",
  "using_parameters": ["WS-INPUT-DATA"],
  "giving_parameter": null,
  "on_exception": [
    {
      "node_type": "MoveStatement",
      "source": "ERROR",
      "targets": ["WS-STATUS"],
      "location": {
        "file": "example.cob",
        "line": 5,
        "column": 30
      }
    }
  ],
  "not_on_exception": [
    {
      "node_type": "MoveStatement",
      "source": "SUCCESS",
      "targets": ["WS-STATUS"],
      "location": {
        "file": "example.cob",
        "line": 7,
        "column": 30
      }
    }
  ],
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {}
}
```

## CALL with Literal Program Name

### COBOL Source
```cobol
       PROCEDURE DIVISION.
           CALL "CBL_OC_DUMP" USING WS-DUMP-DATA.
```

### Parsed AST Output
```json
{
  "node_type": "CallStatement",
  "called_program": "CBL_OC_DUMP",
  "using_parameters": ["WS-DUMP-DATA"],
  "giving_parameter": null,
  "on_exception": null,
  "not_on_exception": null,
  "location": {
    "file": "example.cob",
    "line": 2,
    "column": 12
  },
  "metadata": {}
}
```

## CALL Statement in Fixed Format

Fixed-format COBOL has strict column requirements (7-72 for statements, with column 7 reserved for continuation indicators). CALL statements spanning multiple lines use the hyphen continuation character.

### Multi-line CALL with Continuation

### COBOL Source
```cobol
1234567890123456789012345678901234567890123456789012345678901234567890
       CALL "CALCULATE-INVOICE"
           USING BY REFERENCE WS-INVOICE-REC
                             WS-RATE-TABLE
                 BY VALUE WS-TOLERANCE
           RETURNING WS-RESULT-CODE.
```

**Key Points**:
- Line 1: Statement starts in column 11 (standard)
- Line 2-4: Continuation lines must have hyphen in column 7
- All parameters within columns 8-72
- RETURNING clause on final line
- Parser recognizes continuation markers and assembles complete statement

### Parsed Structure
The parser treats all continuation lines as a single logical CALL statement:
```python
call_stmt.called_program = "CALCULATE-INVOICE"
call_stmt.using_parameters = [
    CallParameter("WS-INVOICE-REC", "REFERENCE"),
    CallParameter("WS-RATE-TABLE", "REFERENCE"),
    CallParameter("WS-TOLERANCE", "VALUE")
]
call_stmt.returning_parameter = "WS-RESULT-CODE"
```

### Columns 8-72 Compliance

Fixed-format COBOL requires statements to fit within columns 8-72 (positions 8-72). Anything in columns 1-7 is reserved for line numbering/continuation, and columns 73+ are ignored as comments.

**Valid CALL within column limits**:
```cobol
       CALL "PGM" USING P1 P2 P3 P4 P5.
1234567|        content must fit here        |72
```

**Invalid - exceeds column 72**:
```cobol
       CALL "PROGRAM-WITH-VERY-LONG-NAME" USING PARAMETER1 PARAMETER2.
       ^ col 7         ^ col 8                                           ^ col 73+
```

## Parameter Passing Modes Explained

COBOL supports three modes for passing parameters to CALL statements:

### BY REFERENCE Mode

**Default mode** - the called program receives access to the original variable and can modify it.

```cobol
       CALL "UPDATE-RECORD" USING BY REFERENCE WS-RECORD.
```

**Parser Output**:
```python
CallParameter("WS-RECORD", passing_mode="REFERENCE")
```

**Characteristics**:
- Original variable is modified if called program changes it
- Most memory efficient (no copy made)
- Used when called program needs to update data
- If mode not specified, defaults to REFERENCE

### BY CONTENT Mode

The called program receives a copy of the data and cannot modify the original.

```cobol
       CALL "VALIDATE-INPUT" USING BY CONTENT WS-INPUT.
```

**Parser Output**:
```python
CallParameter("WS-INPUT", passing_mode="CONTENT")
```

**Characteristics**:
- Original variable is protected from modification
- Copy made before calling program
- Used for read-only operations
- Slightly less efficient than REFERENCE

### BY VALUE Mode

The called program receives a copy that is also a new temporary variable (copy-in).

```cobol
       CALL "CALCULATE" USING BY VALUE WS-AMOUNT.
```

**Parser Output**:
```python
CallParameter("WS-AMOUNT", passing_mode="VALUE")
```

**Characteristics**:
- Copies the value but not the variable itself
- Original variable never modified
- Most isolated execution
- Used for pure functions and calculations

### Mixed Modes in Single CALL

A single CALL can use different modes for different parameters:

```cobol
       CALL "PROCESS"
           USING BY REFERENCE WS-DATA
                 BY CONTENT WS-CONFIG
                 BY VALUE WS-AMOUNT.
```

**Parser Output**:
```python
call_stmt.using_parameters = [
    CallParameter("WS-DATA", passing_mode="REFERENCE"),
    CallParameter("WS-CONFIG", passing_mode="CONTENT"),
    CallParameter("WS-AMOUNT", passing_mode="VALUE")
]
```

## Exception Handling Best Practices

CALL statements can include exception handlers to manage runtime errors and special conditions.

### ON EXCEPTION Handler

Executes when the called program terminates abnormally.

```cobol
       CALL "EXTERNAL-SERVICE"
           USING WS-REQUEST
           ON EXCEPTION
               MOVE "SERVICE-FAILED" TO WS-STATUS
               DISPLAY "Error calling external service".
```

**Parser Recognition**:
```python
call_stmt.on_exception = [MoveStatement(...), DisplayStatement(...)]
```

### NOT ON EXCEPTION Handler

Executes when the called program terminates normally (the opposite of ON EXCEPTION).

```cobol
       CALL "EXTERNAL-SERVICE"
           USING WS-REQUEST
           NOT ON EXCEPTION
               MOVE "SERVICE-OK" TO WS-STATUS.
```

**Mutual Exclusivity Note**: `RETURNING` and `GIVING` clauses are mutually exclusive - a single CALL statement cannot have both.

### ON OVERFLOW Handler

Handles special condition when called program stack overflows (rare but important for deep recursion or limited environments).

```cobol
       CALL "RECURSIVE-CALC"
           USING WS-VALUE
           ON OVERFLOW
               MOVE -1 TO WS-RESULT
               MOVE "STACK-OVERFLOW" TO WS-STATUS.
```

**Parser Recognition**:
```python
call_stmt.on_overflow = [MoveStatement(...), MoveStatement(...)]
```

### END-CALL Terminator

Explicit terminator for CALL statements with exception handlers. Optional but recommended for complex multi-line CALL statements.

```cobol
       CALL "PROCESS-FILE"
           USING WS-FILENAME
           ON EXCEPTION
               PERFORM ERROR-HANDLER
           NOT ON EXCEPTION
               PERFORM SUCCESS-HANDLER
           END-CALL.
       
       NEXT-STATEMENT.
```

**Parser Recognition**: END-CALL marks the end of exception handler scope, preventing ambiguity in complex programs.

## Dynamic CALL Statements

Dynamic CALL statements use variables instead of literal strings, allowing the program name to be determined at runtime. The parser can track possible values through data flow analysis.

### Basic Dynamic CALL

#### COBOL Source
```cobol
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PROGRAM-NAME     PIC X(20).
       
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           MOVE "SUBPROGRAM" TO WS-PROGRAM-NAME.
           CALL WS-PROGRAM-NAME USING WS-DATA.
```

#### Parsed AST Output (Before Analysis)
```json
{
  "node_type": "CallStatement",
  "called_program": "WS-PROGRAM-NAME",
  "is_dynamic": true,
  "possible_values": [],
  "using_parameters": ["WS-DATA"],
  "giving_parameter": null,
  "location": {
    "file": "example.cob",
    "line": 8,
    "column": 12
  },
  "metadata": {}
}
```

### Dynamic CALL with Value Tracking

#### COBOL Source
```cobol
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TXT              PIC X(10) VALUE "PROG-INIT".
       01  WS-COUNTER          PIC 9(5).
       
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           MOVE "PROG-A" TO WS-TXT.
           CALL WS-TXT USING WS-COUNTER.
           
           MOVE "PROG-B" TO WS-TXT.
           CALL WS-TXT USING WS-COUNTER.
           
           MOVE "PROG-C" TO WS-TXT.
           CALL WS-TXT.
           
           STOP RUN.
```

#### Analysis with DynamicCallAnalyzer
```python
from cobolparser import parse_cobol
from cobolparser.analysis import DynamicCallAnalyzer

# Parse the source
result = parse_cobol(cobol_source)

# Analyze dynamic calls
analyzer = DynamicCallAnalyzer()
analyzer.analyze(result.ast)

# Find CALL statements
calls = result.ast.find_statements("CALL")
for call in calls:
    if call.is_dynamic:
        print(f"Dynamic CALL to variable: {call.called_program}")
        print(f"Possible values: {call.possible_values}")
        # Output: Possible values: ['PROG-A', 'PROG-B', 'PROG-C', 'PROG-INIT']
```

#### Parsed AST Output (After Analysis)
```json
{
  "node_type": "CallStatement",
  "called_program": "WS-TXT",
  "is_dynamic": true,
  "possible_values": ["PROG-A", "PROG-B", "PROG-C", "PROG-INIT"],
  "using_parameters": ["WS-COUNTER"],
  "giving_parameter": null,
  "location": {
    "file": "example.cob",
    "line": 9,
    "column": 12
  },
  "metadata": {}
}
```

### Dynamic CALL Analysis

The `DynamicCallAnalyzer` tracks possible values for dynamic CALL statements by:

1. **Collecting Initial Values**: Scanning data definitions for VALUE clauses
2. **Tracking MOVE Statements**: Following all MOVE operations that assign to the variable
3. **Populating Possible Values**: Combining all tracked values into the `possible_values` array

#### Example: Multiple Conditional Paths
```cobol
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PROGRAM          PIC X(10).
       01  WS-TRANS-CODE       PIC X.
           88  INQUIRY         VALUE 'I'.
           88  UPDATE          VALUE 'U'.
           88  DELETE          VALUE 'D'.
       
       PROCEDURE DIVISION.
       SELECT-PROGRAM.
           IF INQUIRY
               MOVE "INQ-PROG" TO WS-PROGRAM
           ELSE
               IF UPDATE
                   MOVE "UPD-PROG" TO WS-PROGRAM
               ELSE
                   MOVE "DEL-PROG" TO WS-PROGRAM
               END-IF
           END-IF.
           
       EXECUTE-PROGRAM.
           CALL WS-PROGRAM.
```

After analysis, the CALL statement will have:
- `is_dynamic`: true
- `possible_values`: ["DEL-PROG", "INQ-PROG", "UPD-PROG"] (sorted alphabetically)

This allows you to:
- Generate call graphs with all possible targets
- Identify missing subprograms
- Document runtime behavior
- Perform impact analysis across dynamic calls

## Usage in Code Analysis

### Basic Call Analysis
```python
from cobolparser import parse_cobol
from cobolparser.models.statements import CallStatement

def analyze_call_statements(cobol_source):
    result = parse_cobol(cobol_source)

    call_info = []
    def find_calls(node):
        if isinstance(node, CallStatement):
            call_info.append({
                'program': node.called_program,
                'is_dynamic': node.is_dynamic,
                'possible_values': node.possible_values,
                'parameters': node.using_parameters,
                'has_return': node.giving_parameter is not None,
                'has_exception_handling': node.on_exception is not None,
                'line': node.location.line
            })

        if hasattr(node, 'children'):
            for child in node.children:
                find_calls(child)

    find_calls(result.ast)
    return call_info

# Example output:
# [
#   {'program': 'SUBPROGRAM', 'is_dynamic': False, 'possible_values': [], 
#    'parameters': ['WS-PARAM1', 'WS-PARAM2'], 'has_return': False, 
#    'has_exception_handling': False, 'line': 3},
#   {'program': 'WS-TXT', 'is_dynamic': True, 
#    'possible_values': ['PROG-A', 'PROG-B', 'PROG-C'], 
#    'parameters': ['WS-DATA'], 'has_return': False, 
#    'has_exception_handling': False, 'line': 8}
# ]
```

### Dynamic Call Analysis with Value Tracking
```python
from cobolparser import parse_cobol
from cobolparser.analysis import DynamicCallAnalyzer

def analyze_dynamic_calls(cobol_source):
    # Parse COBOL source
    result = parse_cobol(cobol_source)
    
    # Run dynamic call analysis
    analyzer = DynamicCallAnalyzer()
    analyzer.analyze(result.ast)
    
    # Extract dynamic call information
    dynamic_calls = []
    for call in result.ast.find_statements("CALL"):
        if call.is_dynamic:
            dynamic_calls.append({
                'variable': call.called_program,
                'possible_programs': call.possible_values,
                'line': call.location.line
            })
    
    return {
        'dynamic_calls': dynamic_calls,
        'tracked_variables': analyzer.get_all_tracked_variables()
    }

# Example output:
# {
#   'dynamic_calls': [
#     {'variable': 'WS-PROGRAM-NAME', 
#      'possible_programs': ['PROG-A', 'PROG-B', 'PROG-C'],
#      'line': 15}
#   ],
#   'tracked_variables': ['WS-PROGRAM-NAME', 'WS-OTHER-VAR']
# }
```

### Building a Call Graph with Dynamic Calls
```python
from cobolparser import parse_cobol
from cobolparser.analysis import DynamicCallAnalyzer

def build_call_graph(cobol_source):
    result = parse_cobol(cobol_source)
    analyzer = DynamicCallAnalyzer()
    analyzer.analyze(result.ast)
    
    call_graph = {
        'program': result.ast.program_name,
        'calls': []
    }
    
    for call in result.ast.find_statements("CALL"):
        if call.is_dynamic:
            # Add all possible targets for dynamic calls
            for target in call.possible_values:
                call_graph['calls'].append({
                    'target': target,
                    'type': 'dynamic',
                    'variable': call.called_program,
                    'line': call.location.line
                })
        else:
            # Single target for static calls
            call_graph['calls'].append({
                'target': call.called_program.strip('"'),
                'type': 'static',
                'line': call.location.line
            })
    
    return call_graph

# Example output:
# {
#   'program': 'MAIN-PROG',
#   'calls': [
#     {'target': 'STATIC-SUB', 'type': 'static', 'line': 5},
#     {'target': 'PROG-A', 'type': 'dynamic', 'variable': 'WS-PROG', 'line': 10},
#     {'target': 'PROG-B', 'type': 'dynamic', 'variable': 'WS-PROG', 'line': 10},
#     {'target': 'PROG-C', 'type': 'dynamic', 'variable': 'WS-PROG', 'line': 10}
#   ]
# }
```

## Summary

The COBOL parser provides comprehensive support for:
- **Static CALL statements** with literal program names (FR-001)
- **Dynamic CALL statements** with variable program names (FR-002)  
- **Parameter passing modes**: BY REFERENCE, BY CONTENT, BY VALUE (FR-003, FR-004)
- **RETURNING clause** for capturing return values (FR-005)
- **GIVING clause** for output capture (FR-005)
- **Mutual exclusivity** validation between RETURNING and GIVING (FR-006a)
- **Exception handlers**: ON EXCEPTION, NOT ON EXCEPTION, ON OVERFLOW (FR-007 through FR-010)
- **Fixed-format COBOL** with multi-line support (FR-011, FR-012)
- **Dynamic value tracking** via MOVE statement analysis (FR-015, FR-016)

For more information, see the [CALL Statement Specification](../specs/001-call-statements-coverage/spec.md).
````