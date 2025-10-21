# CALL Statement Parsing Examples

This document shows examples of how CALL statements are parsed into AST nodes.

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

## Usage in Code Analysis

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
#   {'program': 'SUBPROGRAM', 'parameters': ['WS-PARAM1', 'WS-PARAM2'], 'has_return': False, 'has_exception_handling': False, 'line': 3},
#   {'program': 'CALCULATOR', 'parameters': ['WS-NUM1', 'WS-NUM2'], 'has_return': True, 'has_exception_handling': False, 'line': 3},
#   {'program': 'VALIDATOR', 'parameters': ['WS-INPUT-DATA'], 'has_return': False, 'has_exception_handling': True, 'line': 3}
# ]
```