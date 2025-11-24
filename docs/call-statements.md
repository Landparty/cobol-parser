# CALL Statement Parsing Examples

This document shows examples of how CALL statements are parsed into AST nodes, including support for dynamic CALL statements that use variables instead of literal program names.

## Table of Contents
- [Static CALL Statements](#static-call-statements)
  - [Basic CALL Statement](#basic-call-statement)
  - [CALL with GIVING Clause](#call-with-giving-clause)
  - [CALL with Exception Handling](#call-with-exception-handling)
  - [CALL with Literal Program Name](#call-with-literal-program-name)
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
  "is_dynamic": false,
  "possible_values": [],
  "using_parameters": ["WS-PARAM1", "WS-PARAM2"],
  "giving_parameter": null,
  "on_exception": null,
  "not_on_exception": null,
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
- `is_dynamic`: False for static calls (literal program name)
- `possible_values`: Empty array for static calls
- `using_parameters`: Array of parameter names passed to the called program
- `giving_parameter`: Optional parameter that receives the return value
- `on_exception`/`not_on_exception`: Exception handling clauses

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
  "using_parameters": ["WS-NUM1", "WS-NUM2"],
  "giving_parameter": "WS-RESULT",
  "on_exception": null,
  "not_on_exception": null,
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