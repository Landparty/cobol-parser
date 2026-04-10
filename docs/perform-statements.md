# PERFORM Statement Parsing Examples

This document shows examples of how PERFORM statements are parsed into AST nodes.

## CLI Examples

```bash
# Find all PERFORM statements in a program
cobol-parser parse program.cbl --find-type PerformStatement

# View the PROCEDURE division to see all statements including PERFORMs
cobol-parser parse program.cbl procedure

# Navigate to a specific paragraph
cobol-parser parse program.cbl procedure.MAIN-PROCESS
```

## Simple PERFORM (Subroutine Call)

### COBOL Source
```cobol
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           PERFORM INITIALIZE-DATA.
           PERFORM PROCESS-RECORDS.
           STOP RUN.

       INITIALIZE-DATA.
           MOVE ZERO TO WS-COUNTER.

       PROCESS-RECORDS.
           ADD 1 TO WS-COUNTER.
```

### Parsed AST Output
```json
{
  "node_type": "PerformStatement",
  "perform_type": "SIMPLE",
  "target_paragraph": "INITIALIZE-DATA",
  "times_count": null,
  "until_condition": null,
  "varying_clause": null,
  "inline_statements": null,
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {}
}
```

### Key Properties
- `perform_type`: Type of PERFORM ("SIMPLE", "TIMES", "UNTIL", "VARYING")
- `target_paragraph`: Name of the paragraph/section being performed
- `times_count`: Number of times to execute (for TIMES performs)
- `until_condition`: Condition for UNTIL performs
- `varying_clause`: VARYING clause details
- `inline_statements`: Statements within PERFORM...END-PERFORM blocks

## PERFORM TIMES

### COBOL Source
```cobol
       PROCEDURE DIVISION.
       PROCESS-MULTIPLE.
           PERFORM PROCESS-ONE-RECORD 10 TIMES.
```

### Parsed AST Output
```json
{
  "node_type": "PerformStatement",
  "perform_type": "TIMES",
  "target_paragraph": "PROCESS-ONE-RECORD",
  "times_count": {
    "value": 10,
    "is_literal": true
  },
  "until_condition": null,
  "varying_clause": null,
  "inline_statements": null,
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {}
}
```

## PERFORM UNTIL

### COBOL Source
```cobol
       PROCEDURE DIVISION.
       READ-UNTIL-END.
           PERFORM READ-RECORD UNTIL WS-EOF = "Y".
```

### Parsed AST Output
```json
{
  "node_type": "PerformStatement",
  "perform_type": "UNTIL",
  "target_paragraph": "READ-RECORD",
  "times_count": null,
  "until_condition": {
    "left_operand": "WS-EOF",
    "operator": "=",
    "right_operand": "Y"
  },
  "varying_clause": null,
  "inline_statements": null,
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {}
}
```

## PERFORM VARYING

### COBOL Source
```cobol
       PROCEDURE DIVISION.
       LOOP-WITH-COUNTER.
           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 10
               COMPUTE WS-TOTAL = WS-TOTAL + WS-I
           END-PERFORM.
```

### Parsed AST Output
```json
{
  "node_type": "PerformStatement",
  "perform_type": "VARYING",
  "target_paragraph": null,
  "times_count": null,
  "until_condition": {
    "left_operand": "WS-I",
    "operator": ">",
    "right_operand": 10
  },
  "varying_clause": {
    "variable": "WS-I",
    "from_value": 1,
    "by_value": 1
  },
  "inline_statements": [
    {
      "node_type": "ComputeStatement",
      "expression": "WS-TOTAL + WS-I",
      "targets": ["WS-TOTAL"],
      "location": {
        "file": "example.cob",
        "line": 4,
        "column": 16
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

## Inline PERFORM (PERFORM...END-PERFORM)

### COBOL Source
```cobol
       PROCEDURE DIVISION.
       INLINE-PROCESS.
           PERFORM
               MOVE "START" TO WS-STATUS
               ADD 1 TO WS-COUNTER
               DISPLAY "Processing..."
           END-PERFORM.
```

### Parsed AST Output
```json
{
  "node_type": "PerformStatement",
  "perform_type": "INLINE",
  "target_paragraph": null,
  "times_count": null,
  "until_condition": null,
  "varying_clause": null,
  "inline_statements": [
    {
      "node_type": "MoveStatement",
      "source": "START",
      "targets": ["WS-STATUS"],
      "location": {
        "file": "example.cob",
        "line": 4,
        "column": 16
      }
    },
    {
      "node_type": "AddStatement",
      "value": 1,
      "target": "WS-COUNTER",
      "location": {
        "file": "example.cob",
        "line": 5,
        "column": 16
      }
    },
    {
      "node_type": "DisplayStatement",
      "display_items": ["Processing..."],
      "location": {
        "file": "example.cob",
        "line": 6,
        "column": 16
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

## Usage in Code Analysis

```python
from cobolparser import parse_cobol
from cobolparser.models.statements import PerformStatement

def analyze_perform_statements(cobol_source):
    result = parse_cobol(cobol_source)

    perform_info = []
    def find_performs(node):
        if isinstance(node, PerformStatement):
            info = {
                'type': node.perform_type,
                'target': node.target_paragraph,
                'line': node.location.line
            }

            if node.perform_type == 'TIMES':
                info['times'] = node.times_count.value if node.times_count else None
            elif node.perform_type == 'UNTIL':
                info['condition'] = str(node.until_condition) if node.until_condition else None
            elif node.perform_type == 'VARYING':
                info['varying_var'] = node.varying_clause.get('variable') if node.varying_clause else None
            elif node.perform_type == 'INLINE':
                info['statement_count'] = len(node.inline_statements) if node.inline_statements else 0

            perform_info.append(info)

        if hasattr(node, 'children'):
            for child in node.children:
                find_performs(child)

    find_performs(result.ast)
    return perform_info

# Example output:
# [
#   {'type': 'SIMPLE', 'target': 'INITIALIZE-DATA', 'line': 3},
#   {'type': 'TIMES', 'target': 'PROCESS-ONE-RECORD', 'times': 10, 'line': 3},
#   {'type': 'UNTIL', 'target': 'READ-RECORD', 'condition': 'WS-EOF = Y', 'line': 3},
#   {'type': 'VARYING', 'target': None, 'varying_var': 'WS-I', 'line': 3},
#   {'type': 'INLINE', 'target': None, 'statement_count': 3, 'line': 3}
# ]
```