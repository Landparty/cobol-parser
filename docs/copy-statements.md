# COPY Statement Parsing Examples

This document shows examples of how COPY statements (copybook references) are parsed into AST nodes.

## CLI Examples

```bash
# Expand COPY statements and see the result
cobol-parser expand program.cbl --copybook-path ./copybooks

# Expand with multiple search directories
cobol-parser expand program.cbl --copybook-path ./copybooks --copybook-path /shared/includes

# Limit nesting depth for deeply nested copybooks
cobol-parser expand program.cbl --copybook-path ./copybooks --max-depth 10

# Parse a program with inline copybook expansion
cobol-parser parse program.cbl --copybook-path ./copybooks

# Find COPY statement nodes in the AST (before expansion)
cobol-parser parse program.cbl --find-type CopyStatement
```

## Basic COPY Statement

### COBOL Source
```cobol
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           COPY EMPLOYEE-RECORD.
```

### Parsed AST Output
```json
{
  "node_type": "CopyStatement",
  "copybook_name": "EMPLOYEE-RECORD",
  "library_name": null,
  "suppressions": [],
  "replacements": [],
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {
    "has_replacements": false,
    "has_suppressions": false,
    "has_library": false
  }
}
```

### Key Properties
- `copybook_name`: Name of the copybook file being included
- `library_name`: Optional library/dataset where the copybook is located
- `suppressions`: Lines to suppress from the copybook
- `replacements`: Text replacement rules to apply

## COPY with Library Reference

### COBOL Source
```cobol
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           COPY EMPLOYEE-RECORD IN LIBRARY1.
```

### Parsed AST Output
```json
{
  "node_type": "CopyStatement",
  "copybook_name": "EMPLOYEE-RECORD",
  "library_name": "LIBRARY1",
  "suppressions": [],
  "replacements": [],
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {
    "has_replacements": false,
    "has_suppressions": false,
    "has_library": true
  }
}
```

## COPY with Text Replacements

### COBOL Source
```cobol
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           COPY STANDARD-FIELDS REPLACING
               ==:PREFIX:== BY ==EMP==
               ==:COUNTER:== BY ==EMP-COUNT==.
```

### Parsed AST Output
```json
{
  "node_type": "CopyStatement",
  "copybook_name": "STANDARD-FIELDS",
  "library_name": null,
  "suppressions": [],
  "replacements": [
    {
      "old_text": ":PREFIX:",
      "new_text": "EMP"
    },
    {
      "old_text": ":COUNTER:",
      "new_text": "EMP-COUNT"
    }
  ],
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {
    "has_replacements": true,
    "has_suppressions": false,
    "has_library": false,
    "replacement_count": 2
  }
}
```

## COPY with Suppressions

### COBOL Source
```cobol
       DATA DIVISION.
       FILE SECTION.
           COPY FILE-DEFINITIONS SUPPRESS.
```

### Parsed AST Output
```json
{
  "node_type": "CopyStatement",
  "copybook_name": "FILE-DEFINITIONS",
  "library_name": null,
  "suppressions": ["ALL"],
  "replacements": [],
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {
    "has_replacements": false,
    "has_suppressions": true,
    "has_library": false,
    "suppression_type": "ALL"
  }
}
```

## COPY with Specific Line Suppressions

### COBOL Source
```cobol
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           COPY EMPLOYEE-RECORD SUPPRESS 1 THRU 5, 10.
```

### Parsed AST Output
```json
{
  "node_type": "CopyStatement",
  "copybook_name": "EMPLOYEE-RECORD",
  "library_name": null,
  "suppressions": [
    {"type": "RANGE", "start": 1, "end": 5},
    {"type": "LINE", "line": 10}
  ],
  "replacements": [],
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {
    "has_replacements": false,
    "has_suppressions": true,
    "has_library": false,
    "suppressed_lines": [1, 2, 3, 4, 5, 10]
  }
}
```

## Complex COPY with Library and Replacements

### COBOL Source
```cobol
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           COPY CUSTOMER-RECORD IN CUSTLIB
               REPLACING ==:SYS:== BY ==PROD==
                        ==:VER:== BY ==V2==.
```

### Parsed AST Output
```json
{
  "node_type": "CopyStatement",
  "copybook_name": "CUSTOMER-RECORD",
  "library_name": "CUSTLIB",
  "suppressions": [],
  "replacements": [
    {
      "old_text": ":SYS:",
      "new_text": "PROD"
    },
    {
      "old_text": ":VER:",
      "new_text": "V2"
    }
  ],
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {
    "has_replacements": true,
    "has_suppressions": false,
    "has_library": true,
    "replacement_count": 2
  }
}
```

## COPY in Procedure Division

### COBOL Source
```cobol
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           COPY STANDARD-PROCEDURES.
           STOP RUN.
```

### Parsed AST Output
```json
{
  "node_type": "CopyStatement",
  "copybook_name": "STANDARD-PROCEDURES",
  "library_name": null,
  "suppressions": [],
  "replacements": [],
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {
    "has_replacements": false,
    "has_suppressions": false,
    "has_library": false,
    "context": "PROCEDURE_DIVISION"
  }
}
```

## Usage in Code Analysis

```python
from cobolparser import parse_cobol
from cobolparser.models.statements import CopyStatement

def analyze_copy_statements(cobol_source):
    result = parse_cobol(cobol_source)

    copy_info = []
    def find_copies(node):
        if isinstance(node, CopyStatement):
            info = {
                'copybook': node.copybook_name,
                'library': node.library_name,
                'replacements': len(node.replacements),
                'suppressions': len(node.suppressions) > 0,
                'line': node.location.line
            }
            copy_info.append(info)

        if hasattr(node, 'children'):
            for child in node.children:
                find_copies(child)

    find_copies(result.ast)
    return copy_info

# Example output:
# [
#   {'copybook': 'EMPLOYEE-RECORD', 'library': None, 'replacements': 0, 'suppressions': False, 'line': 3},
#   {'copybook': 'STANDARD-FIELDS', 'library': None, 'replacements': 2, 'suppressions': False, 'line': 3},
#   {'copybook': 'FILE-DEFINITIONS', 'library': None, 'replacements': 0, 'suppressions': True, 'line': 3},
#   {'copybook': 'CUSTOMER-RECORD', 'library': 'CUSTLIB', 'replacements': 2, 'suppressions': False, 'line': 3}
# ]
```

## Copybook Dependencies Analysis

```python
def extract_copybook_dependencies(cobol_source):
    """Extract all copybook dependencies from COBOL source."""
    result = parse_cobol(cobol_source)

    dependencies = []
    def find_dependencies(node):
        if isinstance(node, CopyStatement):
            dep = {
                'name': node.copybook_name,
                'library': node.library_name,
                'qualified_name': f"{node.library_name}/{node.copybook_name}" if node.library_name else node.copybook_name,
                'has_modifications': len(node.replacements) > 0 or len(node.suppressions) > 0
            }
            dependencies.append(dep)

        if hasattr(node, 'children'):
            for child in node.children:
                find_dependencies(child)

    find_dependencies(result.ast)
    return dependencies

# Example output:
# [
#   {'name': 'EMPLOYEE-RECORD', 'library': None, 'qualified_name': 'EMPLOYEE-RECORD', 'has_modifications': False},
#   {'name': 'STANDARD-FIELDS', 'library': None, 'qualified_name': 'STANDARD-FIELDS', 'has_modifications': True},
#   {'name': 'CUSTOMER-RECORD', 'library': 'CUSTLIB', 'qualified_name': 'CUSTLIB/CUSTOMER-RECORD', 'has_modifications': True}
# ]
```