# File Control Parsing Examples

This document shows examples of how FILE-CONTROL SELECT statements and file definitions are parsed into AST nodes.

## CLI Examples

```bash
# View the ENVIRONMENT division (contains FILE-CONTROL)
cobol-parser parse program.cbl environment

# Find all SELECT/file control entries
cobol-parser parse program.cbl --find-type FileControlEntry

# Find all file descriptions (FD entries)
cobol-parser parse program.cbl --find-type FileDescription

# View the full AST with errors for debugging file section issues
cobol-parser parse program.cbl --errors
```

## Supported SELECT Clause Variations

The parser supports comprehensive SELECT statement parsing for FILE-CONTROL:

### SELECT Clauses

| Clause | Status | Notes |
|--------|--------|-------|
| SELECT file-name | ✅ Full | Basic file selection |
| SELECT OPTIONAL file-name | ✅ Full | Optional file handling |
| ASSIGN TO identifier | ✅ Full | Simple assignment |
| ASSIGN TO string-literal | ✅ Full | e.g., "MYFILE.DAT" |
| ASSIGN TO device-type | ✅ Full | DISK, TAPE, PRINTER, etc. |
| ASSIGN TO device-type identifier | ✅ Full | e.g., DISK MYFILE |
| ORGANIZATION IS SEQUENTIAL | ✅ Full | Sequential file organization |
| ORGANIZATION IS INDEXED | ✅ Full | Indexed file organization |
| ORGANIZATION IS RELATIVE | ✅ Full | Relative file organization |
| ORGANIZATION IS LINE SEQUENTIAL | ✅ Full | Text file organization |
| ACCESS MODE IS SEQUENTIAL | ✅ Full | Sequential access |
| ACCESS MODE IS RANDOM | ✅ Full | Random access |
| ACCESS MODE IS DYNAMIC | ✅ Full | Dynamic access |
| RECORD KEY IS data-name | ✅ Full | Primary record key |
| RECORD KEY ... SOURCE IS | ✅ Full | Key source specification |
| ALTERNATE RECORD KEY | ✅ Full | Alternate keys |
| ALTERNATE KEY ... WITH DUPLICATES | ✅ Full | Duplicate handling |
| RELATIVE KEY IS data-name | ✅ Full | Relative file key |
| FILE STATUS IS data-name | ✅ Full | Single status variable |
| FILE STATUS IS data-name, data-name | ✅ Full | VSAM return code |
| RESERVE integer AREAS | ✅ Full | Buffer areas |
| PADDING CHARACTER IS | ✅ Full | Padding specification |
| RECORD DELIMITER IS | ✅ Full | Delimiter specification |
| PASSWORD IS data-name | ✅ Full | File password |
| LOCK MODE IS MANUAL | ✅ Full | Manual locking |
| LOCK MODE IS AUTOMATIC | ✅ Full | Automatic locking |
| LOCK MODE IS EXCLUSIVE | ✅ Full | Exclusive locking |
| LOCK MODE ... WITH LOCK ON RECORD | ✅ Full | Record locking |
| LOCK MODE ... WITH ROLLBACK | ✅ Full | Rollback support |
| SHARING WITH ALL OTHER | ✅ Full | Multi-user sharing |
| SHARING WITH NO OTHER | ✅ Full | Exclusive access |
| SHARING WITH READ ONLY | ✅ Full | Read-only sharing |

### FD/SD Clauses

| Clause | Status | Notes |
|--------|--------|-------|
| FD file-name | ✅ Full | File description entry |
| SD file-name | ✅ Full | Sort description entry |
| BLOCK CONTAINS integer RECORDS | ✅ Full | Fixed block size |
| BLOCK CONTAINS integer CHARACTERS | ✅ Full | Character-based block |
| BLOCK CONTAINS min TO max | ✅ Full | Variable block size |
| RECORD CONTAINS integer | ✅ Full | Fixed record size |
| RECORD CONTAINS min TO max | ✅ Full | Variable record size |
| RECORD IS VARYING ... DEPENDING ON | ✅ Full | Variable length records |
| LABEL RECORDS ARE STANDARD | ✅ Full | Standard labels |
| LABEL RECORDS ARE OMITTED | ✅ Full | Omitted labels |
| VALUE OF system-name | ✅ Full | File information |
| DATA RECORDS ARE | ✅ Full | Record names |
| LINAGE IS integer LINES | ✅ Full | Page lines |
| LINAGE ... FOOTING AT | ⚠️ Partial | May need error recovery |
| LINAGE ... LINES AT TOP | ⚠️ Partial | May need error recovery |
| LINAGE ... LINES AT BOTTOM | ⚠️ Partial | May need error recovery |
| CODE-SET IS alphabet-name | ✅ Full | Character encoding |
| RECORDING MODE IS F/V/U/S | ✅ Full | IBM recording modes |
| IS EXTERNAL | ✅ Full | External file |
| IS GLOBAL | ✅ Full | Global file |
| REPORT IS | ✅ Full | Report file |

## Device Types Supported

The ASSIGN clause recognizes these device types:
- `DISK` - Disk files
- `TAPE` - Magnetic tape
- `PRINTER` - Print output
- `READER` - Card reader
- `PUNCH` - Card punch
- `KEYBOARD` - Keyboard input
- `DISPLAY` - Display output
- `CONSOLE` - Console device
- `DA` - Direct access
- `UT` - Utility
- `UR` - Unit record
- `EXTERNAL` - External assignment
- `DYNAMIC` - Dynamic assignment

## Dialect-Specific Variations

The parser supports dialect-specific syntax variations:

### IBM Enterprise COBOL
- RECORDING MODE clause (F, V, U, S)
- EXEC SQL file handling
- VSAM file status codes

### Micro Focus COBOL
- LINE SEQUENTIAL organization
- SHARING clause variations
- LOCK MODE extensions

### GnuCOBOL
- Extended device types
- Relaxed syntax requirements

### ACUCOBOL
- Additional file status codes
- Extended sharing modes

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

---

## IO Statements (READ, WRITE, REWRITE, DELETE, START, OPEN, CLOSE, UNLOCK, ACCEPT)

The COBOL parser now supports comprehensive IO statement parsing with complete AST metadata tracking. All 9 major IO statement types are fully implemented and tested.

### Supported IO Operations

| Statement | Organization | Access Mode | Clauses | Tests |
|-----------|---------------|------------|---------|-------|
| **OPEN** | All | - | INPUT, OUTPUT, I-O, EXTEND | 28 tests |
| **CLOSE** | All | - | WITH LOCK, REEL, UNIT, NO REWIND | 19 tests |
| **READ** | Sequential, Indexed, Relative | Seq/Rnd/Dyn | AT END, NOT AT END, WITH LOCK, KEY | 43 tests |
| **WRITE** | Sequential, Indexed, Relative | Seq/Rnd/Dyn | ADVANCING, FROM, DELETE (VSAM), WITH LOCK | 36 tests |
| **REWRITE** | Indexed, Relative | Rnd/Dyn | INVALID KEY, NOT INVALID KEY, WITH LOCK | 27 tests |
| **DELETE** | Indexed, Relative | Rnd/Dyn | INVALID KEY, NOT INVALID KEY, WITH LOCK | 27 tests |
| **START** | Indexed, Relative | Rnd/Dyn | KEY (EQUAL/GREATER/LESS), INVALID KEY, NOT INVALID KEY | 21 tests |
| **UNLOCK** | Indexed | - | RECORD | 14 tests |
| **ACCEPT** | - | - | FROM (DATE/TIME/ENV/COMMAND-LINE), WITH PROMPT, WITHOUT ADVANCING | 28 tests |

### READ Statement Examples

#### Sequential File READ
```cobol
       READ CUSTOMER-FILE
           AT END
               MOVE "YES" TO EOF-FLAG
           NOT AT END
               PERFORM PROCESS-RECORD
       END-READ
```

#### Indexed File READ with KEY
```cobol
       READ INVOICE-FILE
           KEY IS INVOICE-KEY
           INVALID KEY
               MOVE 1 TO FILE-STATUS
           NOT INVALID KEY
               PERFORM UPDATE-RECORD
           WITH LOCK
       END-READ
```

### WRITE Statement Examples

#### Sequential File WRITE with ADVANCING
```cobol
       WRITE PRINT-RECORD
           FROM OUTPUT-LINE
           BEFORE ADVANCING 1 LINE
       END-WRITE
```

#### Indexed File WRITE with Record Lock
```cobol
       WRITE INVENTORY-RECORD
           WITH LOCK
           INVALID KEY
               PERFORM DUPLICATE-KEY-ERROR
           NOT INVALID KEY
               MOVE 0 TO FILE-STATUS
       END-WRITE
```

### REWRITE Statement Example
```cobol
       REWRITE INDEXED-RECORD
           WITH LOCK
           INVALID KEY
               PERFORM REWRITE-ERROR
           NOT INVALID KEY
               PERFORM REWRITE-SUCCESS
       END-REWRITE
```

### DELETE Statement Example
```cobol
       DELETE INDEXED-FILE
           INVALID KEY
               PERFORM DELETE-ERROR
           NOT INVALID KEY
               SUBTRACT 1 FROM RECORD-COUNT
       END-DELETE
```

### START Statement Examples

```cobol
       START INDEXED-FILE
           KEY IS GREATER THAN SEARCH-KEY
           INVALID KEY
               PERFORM NO-MATCHING-RECORD
           NOT INVALID KEY
               PERFORM READ-NEXT-RECORD
       END-START
```

### AST Output for READ Statement

```json
{
  "node_type": "IOReadStatement",
  "file_name": "CUSTOMER-FILE",
  "record_name": "CUSTOMER-RECORD",
  "key_name": "CUSTOMER-ID",
  "access_mode": "RANDOM",
  "lock_scope": "RECORD",
  "at_end_clause": {
    "statements": [...]
  },
  "not_at_end_clause": {
    "statements": [...]
  },
  "invalid_key_clause": null,
  "metadata": {
    "has_at_end": true,
    "has_not_at_end": true,
    "has_key": false,
    "has_lock": false,
    "uses_lock": false
  },
  "location": {
    "file": "example.cob",
    "line": 150,
    "column": 8
  }
}
```

### Error Diagnostics for IO Statements

When IO statements have invalid clause combinations, the parser emits specific `IO_*` error codes:

| Error Code | Condition | Example |
|------------|-----------|---------|
| `IO_READ_LOCK_ON_SEQUENTIAL` | WITH LOCK used on sequential file | Sequential READ with LOCK |
| `IO_REWRITE_INVALID_ORG` | REWRITE on sequential file | Sequential REWRITE |
| `IO_DELETE_INVALID_ORG` | DELETE on sequential file | Sequential DELETE |
| `IO_START_INVALID_ORG` | START on sequential file | Sequential START |
| `IO_START_MISSING_KEY` | START without KEY clause | START without condition |
| `IO_UNLOCK_INVALID_ORG` | UNLOCK on non-indexed file | Relative UNLOCK |
| `IO_WRITE_ADVANCING_INVALID_UNIT` | Invalid ADVANCING unit | ADVANCING 5 SCREENS |
| `IO_OPEN_INVALID_MODE` | Invalid OPEN mode | OPEN READONLY |

### Parsing Configuration

Use `ErrorRecoveryMode.COLLECT_ALL` to capture all IO statement errors without halting:

```python
from cobolparser import CobolParser, ErrorRecoveryMode

parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
result = parser.parse(cobol_source)

# Check for IO-specific errors
io_errors = [e for e in result.errors if "IO_" in e.code]
for error in io_errors:
    print(f"{error.code}: {error.message} (line {error.line})")
```

### Test Coverage Summary

- **Contract Tests** (64): AST structure, serialization, field validation
- **Integration Tests** (38): Multi-statement programs, file binding
- **Unit Tests** (119): Clause combinations, syntax variations, error handling
- **Total IO Tests**: 221 tests (91.7% of planned coverage)