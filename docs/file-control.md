# File Control Parsing Examples

This document shows examples of how FILE-CONTROL SELECT statements and file definitions are parsed into AST nodes.

## Basic SELECT Statement

### COBOL Source
```cobol
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT PRINT-FILE ASSIGN TO
               XXXXX055.
```

### Parsed AST Output
```json
{
  "node_type": "FileControlEntry",
  "file_name": "PRINT-FILE",
  "assign_target": "XXXXX055",
  "organization": null,
  "access_mode": null,
  "file_status": null,
  "location": {
    "file": "example.cob",
    "line": 4,
    "column": 12
  },
  "metadata": {
    "has_organization": false,
    "has_access_mode": false,
    "has_file_status": false
  }
}
```

### Key Properties
- `file_name`: The logical file name used in the program
- `assign_target`: The physical file/dataset name assigned to
- `organization`: File organization (SEQUENTIAL, INDEXED, RELATIVE)
- `access_mode`: Access method (SEQUENTIAL, RANDOM, DYNAMIC)
- `file_status`: File status field for error handling

## SELECT with ORGANIZATION

### COBOL Source
```cobol
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT EMPLOYEE-FILE ASSIGN TO "EMPFILE.DAT"
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC
               RECORD KEY IS EMP-ID
               FILE STATUS IS WS-FILE-STATUS.
```

### Parsed AST Output
```json
{
  "node_type": "FileControlEntry",
  "file_name": "EMPLOYEE-FILE",
  "assign_target": "EMPFILE.DAT",
  "organization": "INDEXED",
  "access_mode": "DYNAMIC",
  "record_key": "EMP-ID",
  "file_status": "WS-FILE-STATUS",
  "location": {
    "file": "example.cob",
    "line": 4,
    "column": 12
  },
  "metadata": {
    "has_organization": true,
    "has_access_mode": true,
    "has_record_key": true,
    "has_file_status": true,
    "is_indexed": true
  }
}
```

## Multiple SELECT Statements

### COBOL Source
```cobol
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT INPUT-FILE ASSIGN TO INPUT01
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL.

           SELECT OUTPUT-FILE ASSIGN TO OUTPUT01
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL
               FILE STATUS IS WS-OUT-STATUS.

           SELECT INDEXED-FILE ASSIGN TO IDXFILE
               ORGANIZATION IS INDEXED
               ACCESS MODE IS RANDOM
               RECORD KEY IS REC-KEY
               ALTERNATE RECORD KEY IS ALT-KEY.
```

### Parsed AST Output
```json
[
  {
    "node_type": "FileControlEntry",
    "file_name": "INPUT-FILE",
    "assign_target": "INPUT01",
    "organization": "SEQUENTIAL",
    "access_mode": "SEQUENTIAL",
    "location": {
      "file": "example.cob",
      "line": 4,
      "column": 12
    },
    "metadata": {
      "has_organization": true,
      "has_access_mode": true,
      "file_type": "INPUT"
    }
  },
  {
    "node_type": "FileControlEntry",
    "file_name": "OUTPUT-FILE",
    "assign_target": "OUTPUT01",
    "organization": "SEQUENTIAL",
    "access_mode": "SEQUENTIAL",
    "file_status": "WS-OUT-STATUS",
    "location": {
      "file": "example.cob",
      "line": 8,
      "column": 12
    },
    "metadata": {
      "has_organization": true,
      "has_access_mode": true,
      "has_file_status": true,
      "file_type": "OUTPUT"
    }
  },
  {
    "node_type": "FileControlEntry",
    "file_name": "INDEXED-FILE",
    "assign_target": "IDXFILE",
    "organization": "INDEXED",
    "access_mode": "RANDOM",
    "record_key": "REC-KEY",
    "alternate_keys": ["ALT-KEY"],
    "location": {
      "file": "example.cob",
      "line": 12,
      "column": 12
    },
    "metadata": {
      "has_organization": true,
      "has_access_mode": true,
      "has_record_key": true,
      "has_alternate_keys": true,
      "alternate_key_count": 1,
      "is_indexed": true
    }
  }
]
```

## File Description (FD) Parsing

### COBOL Source
```cobol
       DATA DIVISION.
       FILE SECTION.
       FD  PRINT-FILE
           LABEL RECORDS ARE STANDARD
           RECORD CONTAINS 120 CHARACTERS
           DATA RECORD IS PRINT-REC.
```

### Parsed AST Output
```json
{
  "node_type": "FileDescription",
  "file_name": "PRINT-FILE",
  "label_records": "STANDARD",
  "record_contains": {
    "size": 120,
    "unit": "CHARACTERS"
  },
  "data_records": ["PRINT-REC"],
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 8
  },
  "metadata": {
    "has_label_records": true,
    "has_record_contains": true,
    "data_record_count": 1
  }
}
```

## Complex File Description

### COBOL Source
```cobol
       DATA DIVISION.
       FILE SECTION.
       FD  EMPLOYEE-FILE
           LABEL RECORDS ARE OMITTED
           RECORD IS VARYING IN SIZE
               FROM 50 TO 200 CHARACTERS
               DEPENDING ON WS-REC-SIZE
           DATA RECORD IS EMP-REC
           BLOCK CONTAINS 10 RECORDS.
```

### Parsed AST Output
```json
{
  "node_type": "FileDescription",
  "file_name": "EMPLOYEE-FILE",
  "label_records": "OMITTED",
  "record_varying": {
    "from": 50,
    "to": 200,
    "depending_on": "WS-REC-SIZE"
  },
  "data_records": ["EMP-REC"],
  "block_contains": {
    "count": 10,
    "unit": "RECORDS"
  },
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 8
  },
  "metadata": {
    "has_label_records": true,
    "has_record_varying": true,
    "has_block_contains": true,
    "is_variable_length": true
  }
}
```

## Usage in File Analysis

```python
from cobolparser import parse_cobol

def analyze_file_control(cobol_source):
    result = parse_cobol(cobol_source)

    file_analysis = {
        'file_control_entries': [],
        'file_descriptions': [],
        'indexed_files': [],
        'sequential_files': []
    }

    def analyze_node(node):
        if hasattr(node, 'node_type'):
            if node.node_type == 'FileControlEntry':
                entry = {
                    'file_name': node.file_name,
                    'assign_target': node.assign_target,
                    'organization': node.organization,
                    'access_mode': node.access_mode,
                    'record_key': getattr(node, 'record_key', None),
                    'file_status': getattr(node, 'file_status', None),
                    'line': node.location.line
                }
                file_analysis['file_control_entries'].append(entry)

                # Categorize by organization
                if node.organization == 'INDEXED':
                    file_analysis['indexed_files'].append(entry)
                elif node.organization == 'SEQUENTIAL':
                    file_analysis['sequential_files'].append(entry)

            elif node.node_type == 'FileDescription':
                fd = {
                    'file_name': node.file_name,
                    'label_records': getattr(node, 'label_records', None),
                    'record_contains': getattr(node, 'record_contains', None),
                    'data_records': getattr(node, 'data_records', []),
                    'line': node.location.line
                }
                file_analysis['file_descriptions'].append(fd)

        if hasattr(node, 'children'):
            for child in node.children:
                analyze_node(child)

    analyze_node(result.ast)
    return file_analysis

# Example output:
# {
#   'file_control_entries': [
#     {
#       'file_name': 'PRINT-FILE',
#       'assign_target': 'XXXXX055',
#       'organization': None,
#       'access_mode': None,
#       'record_key': None,
#       'file_status': None,
#       'line': 4
#     },
#     {
#       'file_name': 'EMPLOYEE-FILE',
#       'assign_target': 'EMPFILE.DAT',
#       'organization': 'INDEXED',
#       'access_mode': 'DYNAMIC',
#       'record_key': 'EMP-ID',
#       'file_status': 'WS-FILE-STATUS',
#       'line': 4
#     }
#   ],
#   'file_descriptions': [
#     {
#       'file_name': 'PRINT-FILE',
#       'label_records': 'STANDARD',
#       'record_contains': {'size': 120, 'unit': 'CHARACTERS'},
#       'data_records': ['PRINT-REC'],
#       'line': 3
#     }
#   ],
#   'indexed_files': [
#     {
#       'file_name': 'EMPLOYEE-FILE',
#       'assign_target': 'EMPFILE.DAT',
#       'organization': 'INDEXED',
#       'access_mode': 'DYNAMIC',
#       'record_key': 'EMP-ID',
#       'file_status': 'WS-FILE-STATUS',
#       'line': 4
#     }
#   ],
#   'sequential_files': []
# }
```

## File Organization Summary

```python
def summarize_file_organization(cobol_source):
    """Summarize file organization and access patterns."""
    analysis = analyze_file_control(cobol_source)

    summary = {
        'total_files': len(analysis['file_control_entries']),
        'indexed_files': len(analysis['indexed_files']),
        'sequential_files': len(analysis['sequential_files']),
        'files_with_status': sum(1 for f in analysis['file_control_entries'] if f['file_status']),
        'files_with_keys': sum(1 for f in analysis['file_control_entries'] if f['record_key']),
        'access_modes': {}
    }

    for entry in analysis['file_control_entries']:
        mode = entry['access_mode'] or 'DEFAULT'
        summary['access_modes'][mode] = summary['access_modes'].get(mode, 0) + 1

    return summary

# Example output:
# {
#   'total_files': 3,
#   'indexed_files': 1,
#   'sequential_files': 2,
#   'files_with_status': 1,
#   'files_with_keys': 1,
#   'access_modes': {'SEQUENTIAL': 2, 'DYNAMIC': 1}
# }
```