# CICS and IMS Statement Parsing Examples

This document shows examples of how EXEC CICS statements and IMS interface calls are parsed into AST nodes.

## EXEC CICS RECEIVE Statement

### COBOL Source
```cobol
       PROCEDURE DIVISION.
       RECEIVE-COMMAREA.
           EXEC CICS RECEIVE
               INTO(WS-COMMAREA)
               LENGTH(WS-COMMAREA-LEN)
               NOHANDLE
           END-EXEC.
```

### Parsed AST Output
```json
{
  "node_type": "ExecCICSStatement",
  "statement_type": "EXEC-CICS",
  "cics_command": "RECEIVE",
  "cics_options": {
    "INTO": "WS-COMMAREA",
    "LENGTH": "WS-COMMAREA-LEN",
    "NOHANDLE": true
  },
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {
    "dialect": "IBM_ENTERPRISE",
    "has_options": true,
    "option_count": 3
  }
}
```

## EXEC CICS SEND Statement

### COBOL Source
```cobol
       PROCEDURE DIVISION.
       SEND-RESPONSE.
           EXEC CICS SEND
               FROM(WS-RESPONSE-DATA)
               LENGTH(WS-RESPONSE-LEN)
               END-EXEC.
```

### Parsed AST Output
```json
{
  "node_type": "ExecCICSStatement",
  "statement_type": "EXEC-CICS",
  "cics_command": "SEND",
  "cics_options": {
    "FROM": "WS-RESPONSE-DATA",
    "LENGTH": "WS-RESPONSE-LEN"
  },
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {
    "dialect": "IBM_ENTERPRISE",
    "has_options": true,
    "option_count": 2
  }
}
```

## EXEC CICS LINK Statement

### COBOL Source
```cobol
       PROCEDURE DIVISION.
       CALL-SUBPROGRAM.
           EXEC CICS LINK
               PROGRAM('SUBPROG1')
               COMMAREA(WS-COMMAREA)
               LENGTH(WS-COMMAREA-LEN)
           END-EXEC.
```

### Parsed AST Output
```json
{
  "node_type": "ExecCICSStatement",
  "statement_type": "EXEC-CICS",
  "cics_command": "LINK",
  "cics_options": {
    "PROGRAM": "'SUBPROG1'",
    "COMMAREA": "WS-COMMAREA",
    "LENGTH": "WS-COMMAREA-LEN"
  },
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {
    "dialect": "IBM_ENTERPRISE",
    "has_options": true,
    "option_count": 3
  }
}
```

## EXEC IMS GU (Get Unique) Statement

### COBOL Source
```cobol
       PROCEDURE DIVISION.
       GET-EMPLOYEE.
           EXEC IMS GU
               SEGMENT(EMPLOYEE)
               SSA(EMP-ID = '12345')
               INTO(IO-AREA)
           END-EXEC.
```

### Parsed AST Output
```json
{
  "node_type": "ExecIMSStatement",
  "statement_type": "EXEC-IMS",
  "ims_command": "GU",
  "ims_call_type": "GU",
  "ims_options": {
    "SEGMENT": "EMPLOYEE",
    "SSA": "EMP-ID = '12345'",
    "INTO": "IO-AREA"
  },
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {
    "dialect": "IBM_ENTERPRISE",
    "has_options": true,
    "option_count": 3
  }
}
```

## EXEC IMS ISRT (Insert) Statement

### COBOL Source
```cobol
       PROCEDURE DIVISION.
       INSERT-EMPLOYEE.
           EXEC IMS ISRT
               SEGMENT(EMPLOYEE)
               INTO(IO-AREA)
           END-EXEC.
```

### Parsed AST Output
```json
{
  "node_type": "ExecIMSStatement",
  "statement_type": "EXEC-IMS",
  "ims_command": "ISRT",
  "ims_call_type": "ISRT",
  "ims_options": {
    "SEGMENT": "EMPLOYEE",
    "INTO": "IO-AREA"
  },
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {
    "dialect": "IBM_ENTERPRISE",
    "has_options": true,
    "option_count": 2
  }
}
```

## IMS Interface CALL Statement (CBLTDLI)

### COBOL Source
```cobol
       PROCEDURE DIVISION.
       IMS-CALL-EXAMPLE.
           CALL 'CBLTDLI' USING
               DLI-FUNCTION
               IO-PCB-MASK
               IO-AREA.
```

### Parsed AST Output
```json
{
  "node_type": "CobolStatement",
  "statement_type": "CALL",
  "operands": [
    "'CBLTDLI'",
    "DLI-FUNCTION",
    "IO-PCB-MASK",
    "IO-AREA"
  ],
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {
    "dialect": "IBM_ENTERPRISE",
    "is_ims_interface_call": true,
    "ims_interface_type": "CBLTDLI"
  }
}
```

## IMS Interface CALL Statement (AIBTDLI)

### COBOL Source
```cobol
       PROCEDURE DIVISION.
       AIB-CALL-EXAMPLE.
           CALL 'AIBTDLI' USING
               AIB-MASK
               DLI-FUNCTION
               IO-PCB-MASK
               IO-AREA.
```

### Parsed AST Output
```json
{
  "node_type": "CobolStatement",
  "statement_type": "CALL",
  "operands": [
    "'AIBTDLI'",
    "AIB-MASK",
    "DLI-FUNCTION",
    "IO-PCB-MASK",
    "IO-AREA"
  ],
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {
    "dialect": "IBM_ENTERPRISE",
    "is_ims_interface_call": true,
    "ims_interface_type": "AIBTDLI"
  }
}
```

## Key Properties

### EXEC CICS Statements
- `cics_command`: The CICS command being executed (RECEIVE, SEND, LINK, etc.)
- `cics_options`: Dictionary of command options and their values
- `statement_type`: Always "EXEC-CICS"

### EXEC IMS Statements
- `ims_command`: The IMS command (GU, GN, ISRT, REPL, DLET, etc.)
- `ims_call_type`: Same as ims_command (for compatibility)
- `ims_options`: Dictionary of command options (SEGMENT, SSA, INTO, etc.)
- `statement_type`: Always "EXEC-IMS"

### IMS Interface CALL Statements
- `statement_type`: "CALL"
- `operands`: Array containing the interface name and parameters
- `is_ims_interface_call`: Boolean indicating IMS interface usage
- `ims_interface_type`: Type of IMS interface (CBLTDLI, AIBTDLI, CEETDLI)

## Usage in Code Analysis

```python
from cobolparser import parse_cobol
from cobolparser.dialects.ibm_enterprise import ExecCICSStatement, ExecIMSStatement

def analyze_cics_ims_statements(cobol_source):
    result = parse_cobol(cobol_source)

    middleware_info = {
        'cics_statements': [],
        'ims_statements': [],
        'ims_interface_calls': []
    }

    def find_middleware(node):
        if isinstance(node, ExecCICSStatement):
            middleware_info['cics_statements'].append({
                'command': node.cics_command,
                'options': node.cics_options,
                'line': node.location.line
            })
        elif isinstance(node, ExecIMSStatement):
            middleware_info['ims_statements'].append({
                'command': node.ims_command,
                'options': node.ims_options,
                'line': node.location.line
            })
        elif hasattr(node, 'statement_type') and node.statement_type == 'CALL':
            # Check if it's an IMS interface call
            if hasattr(node, 'operands') and len(node.operands) > 0:
                call_target = node.operands[0].strip("'\"")
                if call_target in ['CBLTDLI', 'AIBTDLI', 'CEETDLI']:
                    middleware_info['ims_interface_calls'].append({
                        'interface': call_target,
                        'parameters': node.operands[1:],
                        'line': node.location.line
                    })

        if hasattr(node, 'children'):
            for child in node.children:
                find_middleware(child)

    find_middleware(result.ast)
    return middleware_info

# Example output:
# {
#   'cics_statements': [
#     {'command': 'RECEIVE', 'options': {'INTO': 'WS-COMMAREA', 'LENGTH': 'WS-COMMAREA-LEN', 'NOHANDLE': True}, 'line': 3},
#     {'command': 'SEND', 'options': {'FROM': 'WS-RESPONSE-DATA', 'LENGTH': 'WS-RESPONSE-LEN'}, 'line': 3}
#   ],
#   'ims_statements': [
#     {'command': 'GU', 'options': {'SEGMENT': 'EMPLOYEE', 'SSA': "EMP-ID = '12345'", 'INTO': 'IO-AREA'}, 'line': 3},
#     {'command': 'ISRT', 'options': {'SEGMENT': 'EMPLOYEE', 'INTO': 'IO-AREA'}, 'line': 3}
#   ],
#   'ims_interface_calls': [
#     {'interface': 'CBLTDLI', 'parameters': ['DLI-FUNCTION', 'IO-PCB-MASK', 'IO-AREA'], 'line': 3},
#     {'interface': 'AIBTDLI', 'parameters': ['AIB-MASK', 'DLI-FUNCTION', 'IO-PCB-MASK', 'IO-AREA'], 'line': 3}
#   ]
# }
```

## Program-Level Detection

You can also check if a program uses CICS or IMS at the program level:

```python
from cobolparser import parse_cobol

def check_middleware_usage(cobol_source):
    result = parse_cobol(cobol_source)
    program = result.ast

    return {
        'uses_cics': program.has_cics(),
        'uses_ims_interface': program.uses_ims_interface(),
        'cics_statement_count': len(program.get_cics_statements()),
        'ims_interface_call_count': len(program.get_ims_interface_calls())
    }

# Example output:
# {'uses_cics': True, 'uses_ims_interface': True, 'cics_statement_count': 2, 'ims_interface_call_count': 1}