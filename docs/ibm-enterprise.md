# IBM Enterprise COBOL Features

This document shows examples of IBM Enterprise COBOL dialect features and how they are parsed. The IBM Enterprise dialect is the default, so no special flags are needed.

## CLI Examples

```bash
# Parse with IBM Enterprise dialect (default)
cobol-parser parse program.cbl

# Explicitly specify the dialect
cobol-parser parse program.cbl --dialect ibm-enterprise

# Find all EXEC CICS statements
cobol-parser parse program.cbl --find-type ExecCICSStatement

# Find all EXEC SQL statements
cobol-parser parse program.cbl --find-type ExecSQLStatement

# Analyze dynamic CALL targets (useful for CICS LINK/XCTL programs)
cobol-parser analyze program.cbl

# View the DATA division to see COMP-3 and POINTER data items
cobol-parser parse program.cbl data
```

## EXEC CICS Statements

### Basic CICS Command

#### COBOL Source
```cobol
       PROCEDURE DIVISION.
       SEND-MAP.
           EXEC CICS SEND MAP('MAP01') MAPSET('MAPSET01')
                     FROM(WS-MAP-DATA) ERASE END-EXEC.
```

#### Parsed AST Output
```json
{
  "node_type": "ExecCICSStatement",
  "command": "SEND",
  "options": {
    "MAP": "MAP01",
    "MAPSET": "MAPSET01",
    "FROM": "WS-MAP-DATA",
    "ERASE": true
  },
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {
    "dialect": "IBM_ENTERPRISE",
    "cics_command": "SEND",
    "option_count": 4
  }
}
```

### CICS with Condition Handling

#### COBOL Source
```cobol
       PROCEDURE DIVISION.
       RECEIVE-DATA.
           EXEC CICS RECEIVE MAP('INPUTMAP') MAPSET('MYMAPS')
                     INTO(WS-INPUT-DATA)
                     RESP(WS-RESPONSE-CODE)
           END-EXEC.

           IF WS-RESPONSE-CODE NOT = DFHRESP(NORMAL)
               EXEC CICS SEND TEXT FROM('INVALID INPUT') ERASE
               END-EXEC
           END-IF.
```

#### Parsed AST Output
```json
{
  "node_type": "ExecCICSStatement",
  "command": "RECEIVE",
  "options": {
    "MAP": "INPUTMAP",
    "MAPSET": "MYMAPS",
    "INTO": "WS-INPUT-DATA",
    "RESP": "WS-RESPONSE-CODE"
  },
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {
    "dialect": "IBM_ENTERPRISE",
    "cics_command": "RECEIVE",
    "option_count": 4,
    "has_resp": true
  }
}
```

## Advanced COMP-3 Features

### COMP-3 with Different Sizes

#### COBOL Source
```cobol
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMOUNTS.
           05  WS-SMALL-AMT     PIC 9(3) COMP-3.
           05  WS-MEDIUM-AMT    PIC 9(7)V99 COMP-3.
           05  WS-LARGE-AMT     PIC 9(15)V99 COMP-3.
```

#### Parsed AST Output
```json
{
  "node_type": "DataItem",
  "level": 1,
  "name": "WS-AMOUNTS",
  "children": [
    {
      "node_type": "DataItem",
      "level": 5,
      "name": "WS-SMALL-AMT",
      "picture_clause": {
        "pattern": "9(3)",
        "type": "NUMERIC",
        "length": 3,
        "usage": "COMP-3"
      },
      "usage": "COMP-3",
      "metadata": {
        "storage_size": 2,
        "comp3_digits": 3,
        "comp3_bytes": 2
      }
    },
    {
      "node_type": "DataItem",
      "level": 5,
      "name": "WS-MEDIUM-AMT",
      "picture_clause": {
        "pattern": "9(7)V99",
        "type": "NUMERIC",
        "length": 9,
        "usage": "COMP-3"
      },
      "usage": "COMP-3",
      "metadata": {
        "storage_size": 5,
        "comp3_digits": 9,
        "comp3_bytes": 5
      }
    },
    {
      "node_type": "DataItem",
      "level": 5,
      "name": "WS-LARGE-AMT",
      "picture_clause": {
        "pattern": "9(15)V99",
        "type": "NUMERIC",
        "length": 17,
        "usage": "COMP-3"
      },
      "usage": "COMP-3",
      "metadata": {
        "storage_size": 9,
        "comp3_digits": 17,
        "comp3_bytes": 9
      }
    }
  ],
  "metadata": {
    "storage_size": 16,
    "is_group_item": true,
    "has_children": true,
    "child_count": 3
  }
}
```

## IBM Intrinsic Functions

### LENGTH Function

#### COBOL Source
```cobol
       PROCEDURE DIVISION.
       CALCULATE-LENGTH.
           COMPUTE WS-LEN = LENGTH(WS-INPUT-FIELD).
           DISPLAY "Field length: " WS-LEN.
```

#### Parsed AST Output
```json
{
  "node_type": "ComputeStatement",
  "expression": {
    "node_type": "FunctionCall",
    "function_name": "LENGTH",
    "arguments": ["WS-INPUT-FIELD"],
    "is_intrinsic": true,
    "dialect": "IBM_ENTERPRISE"
  },
  "targets": ["WS-LEN"],
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  }
}
```

### NUMVAL Function

#### COBOL Source
```cobol
       PROCEDURE DIVISION.
       CONVERT-TO-NUMBER.
           COMPUTE WS-NUMBER = NUMVAL(WS-CHAR-FIELD).
```

#### Parsed AST Output
```json
{
  "node_type": "ComputeStatement",
  "expression": {
    "node_type": "FunctionCall",
    "function_name": "NUMVAL",
    "arguments": ["WS-CHAR-FIELD"],
    "is_intrinsic": true,
    "dialect": "IBM_ENTERPRISE"
  },
  "targets": ["WS-NUMBER"],
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  }
}
```

## EXEC SQL with IBM Extensions

### Dynamic SQL

#### COBOL Source
```cobol
       PROCEDURE DIVISION.
       DYNAMIC-QUERY.
           EXEC SQL PREPARE STMT1 FROM :WS-SQL-TEXT END-EXEC.

           EXEC SQL EXECUTE STMT1 USING :WS-PARAM1, :WS-PARAM2
                             INTO :WS-RESULT1, :WS-RESULT2 END-EXEC.
```

#### Parsed AST Output
```json
[
  {
    "node_type": "ExecSQLStatement",
    "sql_type": "PREPARE",
    "sql_text": "PREPARE STMT1 FROM :WS-SQL-TEXT",
    "host_variables": ["WS-SQL-TEXT"],
    "sql_operation": "PREPARE",
    "table_references": [],
    "location": {
      "file": "example.cob",
      "line": 3,
      "column": 12
    },
    "metadata": {
      "dialect": "IBM_ENTERPRISE",
      "is_dynamic_sql": true
    }
  },
  {
    "node_type": "ExecSQLStatement",
    "sql_type": "EXECUTE",
    "sql_text": "EXECUTE STMT1 USING :WS-PARAM1, :WS-PARAM2 INTO :WS-RESULT1, :WS-RESULT2",
    "host_variables": ["WS-PARAM1", "WS-PARAM2", "WS-RESULT1", "WS-RESULT2"],
    "sql_operation": "EXECUTE",
    "table_references": [],
    "location": {
      "file": "example.cob",
      "line": 5,
      "column": 12
    },
    "metadata": {
      "dialect": "IBM_ENTERPRISE",
      "is_dynamic_sql": true,
      "using_count": 2,
      "into_count": 2
    }
  }
]
```

## IBM Data Types

### POINTER Data Type

#### COBOL Source
```cobol
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-POINTER-1     USAGE IS POINTER.
       01  WS-POINTER-2     POINTER.
```

#### Parsed AST Output
```json
[
  {
    "node_type": "DataItem",
    "level": 1,
    "name": "WS-POINTER-1",
    "usage": "POINTER",
    "picture_clause": null,
    "metadata": {
      "storage_size": 4,
      "is_pointer": true
    }
  },
  {
    "node_type": "DataItem",
    "level": 1,
    "name": "WS-POINTER-2",
    "usage": "POINTER",
    "picture_clause": null,
    "metadata": {
      "storage_size": 4,
      "is_pointer": true
    }
  }
]
```

### COMP-5 (Native Binary)

#### COBOL Source
```cobol
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-BINARY-INT    PIC 9(9) COMP-5.
       01  WS-BINARY-SHORT  PIC 9(4) COMP-5.
```

#### Parsed AST Output
```json
[
  {
    "node_type": "DataItem",
    "level": 1,
    "name": "WS-BINARY-INT",
    "picture_clause": {
      "pattern": "9(9)",
      "type": "NUMERIC",
      "length": 9,
      "usage": "COMP-5"
    },
    "usage": "COMP-5",
    "metadata": {
      "storage_size": 4,
      "comp5_bytes": 4,
      "is_native_binary": true
    }
  },
  {
    "node_type": "DataItem",
    "level": 1,
    "name": "WS-BINARY-SHORT",
    "picture_clause": {
      "pattern": "9(4)",
      "type": "NUMERIC",
      "length": 4,
      "usage": "COMP-5"
    },
    "usage": "COMP-5",
    "metadata": {
      "storage_size": 2,
      "comp5_bytes": 2,
      "is_native_binary": true
    }
  }
]
```

## Usage in IBM Environment Analysis

```python
from cobolparser import parse_cobol, CobolDataItem
from cobolparser.dialects.ibm_enterprise import ExecCICSStatement
from cobolparser.models.sql_statements import ExecSQLStatement

def analyze_ibm_features(cobol_source):
    result = parse_cobol(cobol_source)

    ibm_features = {
        'cics_commands': [],
        'comp3_fields': [],
        'pointer_fields': [],
        'sql_operations': [],
        'intrinsic_functions': []
    }

    def analyze_node(node):
        if isinstance(node, ExecCICSStatement):
            ibm_features['cics_commands'].append({
                'command': node.command,
                'options': list(node.options.keys()),
                'line': node.location.line
            })
        elif isinstance(node, ExecSQLStatement):
            ibm_features['sql_operations'].append({
                'operation': node.sql_operation,
                'host_vars': len(node.host_variables),
                'line': node.location.line
            })
        elif isinstance(node, CobolDataItem):
            if node.usage == 'COMP-3':
                ibm_features['comp3_fields'].append({
                    'name': node.name,
                    'picture': node.picture_clause.pattern if node.picture_clause else None,
                    'storage': node.calculate_storage_size(),
                    'line': node.location.line
                })
            elif node.usage == 'POINTER':
                ibm_features['pointer_fields'].append({
                    'name': node.name,
                    'line': node.location.line
                })

        # Check for intrinsic functions in expressions
        if hasattr(node, 'expression') and hasattr(node.expression, 'function_name'):
            if getattr(node.expression, 'is_intrinsic', False):
                ibm_features['intrinsic_functions'].append({
                    'function': node.expression.function_name,
                    'line': node.location.line
                })

        if hasattr(node, 'children'):
            for child in node.children:
                analyze_node(child)

    analyze_node(result.ast)
    return ibm_features

# Example output:
# {
#   'cics_commands': [
#     {'command': 'SEND', 'options': ['MAP', 'MAPSET', 'FROM', 'ERASE'], 'line': 3},
#     {'command': 'RECEIVE', 'options': ['MAP', 'MAPSET', 'INTO', 'RESP'], 'line': 3}
#   ],
#   'comp3_fields': [
#     {'name': 'WS-SMALL-AMT', 'picture': '9(3)', 'storage': 2, 'line': 4},
#     {'name': 'WS-MEDIUM-AMT', 'picture': '9(7)V99', 'storage': 5, 'line': 5}
#   ],
#   'pointer_fields': [
#     {'name': 'WS-POINTER-1', 'line': 3},
#     {'name': 'WS-POINTER-2', 'line': 4}
#   ],
#   'sql_operations': [
#     {'operation': 'SELECT', 'host_vars': 3, 'line': 3},
#     {'operation': 'INSERT', 'host_vars': 2, 'line': 5}
#   ],
#   'intrinsic_functions': [
#     {'function': 'LENGTH', 'line': 3},
#     {'function': 'NUMVAL', 'line': 5}
#   ]
# }
```

## Key IBM Enterprise COBOL Features Supported

- ✅ **EXEC CICS** - Complete CICS command parsing with options
- ✅ **EXEC SQL** - Embedded SQL with host variables and dynamic SQL
- ✅ **COMP-3** - Packed decimal with accurate storage calculations
- ✅ **COMP-5** - Native binary data types
- ✅ **POINTER** - Pointer data type support
- ✅ **Intrinsic Functions** - LENGTH, NUMVAL, and other IBM functions
- ✅ **Dynamic SQL** - PREPARE and EXECUTE statements
- ✅ **CICS Conditions** - Response code handling (DFHRESP values)