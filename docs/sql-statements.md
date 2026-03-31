# SQL Statement Parsing Examples

This document shows examples of how EXEC SQL statements are parsed into AST nodes.

## SELECT Statement

### COBOL Source
```cobol
       PROCEDURE DIVISION.
       FETCH-EMPLOYEE.
           EXEC SQL
               SELECT EMP_ID, EMP_NAME, SALARY
               INTO :WS-EMP-ID, :WS-EMP-NAME, :WS-SALARY
               FROM EMPLOYEE
               WHERE EMP_ID = :SEARCH-ID
           END-EXEC.
```

### Parsed AST Output
```json
{
  "node_type": "ExecSQLStatement",
  "sql_type": "SELECT",
  "sql_text": "SELECT EMP_ID, EMP_NAME, SALARY INTO :WS-EMP-ID, :WS-EMP-NAME, :WS-SALARY FROM EMPLOYEE WHERE EMP_ID = :SEARCH-ID",
  "host_variables": [
    "WS-EMP-ID",
    "WS-EMP-NAME",
    "WS-SALARY",
    "SEARCH-ID"
  ],
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {
    "dialect": "IBM_ENTERPRISE",
    "has_host_variables": true,
    "host_variable_count": 4
  }
}
```

### Key Properties
- `sql_type`: Type of SQL operation (SELECT, INSERT, UPDATE, DELETE, etc.)
- `sql_text`: Complete SQL statement text
- `host_variables`: Array of COBOL variable names used as host variables (prefixed with :)

## INSERT Statement

### COBOL Source
```cobol
       PROCEDURE DIVISION.
       ADD-EMPLOYEE.
           EXEC SQL
               INSERT INTO EMPLOYEE (EMP_ID, EMP_NAME, SALARY)
               VALUES (:WS-EMP-ID, :WS-EMP-NAME, :WS-SALARY)
           END-EXEC.
```

### Parsed AST Output
```json
{
  "node_type": "ExecSQLStatement",
  "sql_type": "INSERT",
  "sql_text": "INSERT INTO EMPLOYEE (EMP_ID, EMP_NAME, SALARY) VALUES (:WS-EMP-ID, :WS-EMP-NAME, :WS-SALARY)",
  "host_variables": [
    "WS-EMP-ID",
    "WS-EMP-NAME",
    "WS-SALARY"
  ],
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {
    "dialect": "IBM_ENTERPRISE",
    "has_host_variables": true,
    "host_variable_count": 3
  }
}
```

## UPDATE Statement

### COBOL Source
```cobol
       PROCEDURE DIVISION.
       UPDATE-SALARY.
           EXEC SQL
               UPDATE EMPLOYEE
               SET SALARY = :NEW-SALARY,
                   LAST_UPDATED = CURRENT TIMESTAMP
               WHERE EMP_ID = :WS-EMP-ID
           END-EXEC.
```

### Parsed AST Output
```json
{
  "node_type": "ExecSQLStatement",
  "sql_type": "UPDATE",
  "sql_text": "UPDATE EMPLOYEE SET SALARY = :NEW-SALARY, LAST_UPDATED = CURRENT TIMESTAMP WHERE EMP_ID = :WS-EMP-ID",
  "host_variables": [
    "NEW-SALARY",
    "WS-EMP-ID"
  ],
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {
    "dialect": "IBM_ENTERPRISE",
    "has_host_variables": true,
    "host_variable_count": 2
  }
}
```

## DELETE Statement

### COBOL Source
```cobol
       PROCEDURE DIVISION.
       REMOVE-EMPLOYEE.
           EXEC SQL
               DELETE FROM EMPLOYEE
               WHERE EMP_ID = :WS-EMP-ID
                 AND STATUS = 'TERMINATED'
           END-EXEC.
```

### Parsed AST Output
```json
{
  "node_type": "ExecSQLStatement",
  "sql_type": "DELETE",
  "sql_text": "DELETE FROM EMPLOYEE WHERE EMP_ID = :WS-EMP-ID AND STATUS = 'TERMINATED'",
  "host_variables": [
    "WS-EMP-ID"
  ],
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {
    "dialect": "IBM_ENTERPRISE",
    "has_host_variables": true,
    "host_variable_count": 1
  }
}
```

## SQL with No Host Variables

### COBOL Source
```cobol
       PROCEDURE DIVISION.
       COMMIT-TRANSACTION.
           EXEC SQL COMMIT END-EXEC.
```

### Parsed AST Output
```json
{
  "node_type": "ExecSQLStatement",
  "sql_type": "COMMIT",
  "sql_text": "COMMIT",
  "host_variables": [],
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {
    "dialect": "IBM_ENTERPRISE",
    "has_host_variables": false,
    "host_variable_count": 0
  }
}
```

## Complex SQL with Subqueries

### COBOL Source
```cobol
       PROCEDURE DIVISION.
       COMPLEX-QUERY.
           EXEC SQL
               SELECT E.EMP_ID, E.EMP_NAME,
                      (SELECT COUNT(*) FROM PROJECTS P
                       WHERE P.EMP_ID = E.EMP_ID) AS PROJECT_COUNT
               INTO :WS-EMP-ID, :WS-EMP-NAME, :WS-PROJECT-COUNT
               FROM EMPLOYEE E
               WHERE E.DEPT_ID = :WS-DEPT-ID
                 AND E.SALARY > (SELECT AVG(SALARY) FROM EMPLOYEE)
           END-EXEC.
```

### Parsed AST Output
```json
{
  "node_type": "ExecSQLStatement",
  "sql_type": "SELECT",
  "sql_text": "SELECT E.EMP_ID, E.EMP_NAME, (SELECT COUNT(*) FROM PROJECTS P WHERE P.EMP_ID = E.EMP_ID) AS PROJECT_COUNT INTO :WS-EMP-ID, :WS-EMP-NAME, :WS-PROJECT-COUNT FROM EMPLOYEE E WHERE E.DEPT_ID = :WS-DEPT-ID AND E.SALARY > (SELECT AVG(SALARY) FROM EMPLOYEE)",
  "host_variables": [
    "WS-EMP-ID",
    "WS-EMP-NAME",
    "WS-PROJECT-COUNT",
    "WS-DEPT-ID"
  ],
  "location": {
    "file": "example.cob",
    "line": 3,
    "column": 12
  },
  "metadata": {
    "dialect": "IBM_ENTERPRISE",
    "has_host_variables": true,
    "host_variable_count": 4,
    "has_subqueries": true
  }
}
```

## Usage in Code Analysis

```python
from cobolparser import parse_cobol
from cobolparser.dialects.ibm_enterprise import ExecSQLStatement

def analyze_sql_statements(cobol_source):
    result = parse_cobol(cobol_source)

    sql_info = []
    def find_sql(node):
        if isinstance(node, ExecSQLStatement):
            sql_info.append({
                'type': node.sql_type,
                'host_variables': node.host_variables,
                'line': node.location.line,
                'has_host_vars': len(node.host_variables) > 0
            })

        if hasattr(node, 'children'):
            for child in node.children:
                find_sql(child)

    find_sql(result.ast)
    return sql_info

# Example output:
# [
#   {'type': 'SELECT', 'host_variables': ['WS-EMP-ID', 'WS-EMP-NAME', 'WS-SALARY', 'SEARCH-ID'], 'line': 3, 'has_host_vars': True},
#   {'type': 'INSERT', 'host_variables': ['WS-EMP-ID', 'WS-EMP-NAME', 'WS-SALARY'], 'line': 3, 'has_host_vars': True},
#   {'type': 'UPDATE', 'host_variables': ['NEW-SALARY', 'WS-EMP-ID'], 'line': 3, 'has_host_vars': True},
#   {'type': 'DELETE', 'host_variables': ['WS-EMP-ID'], 'line': 3, 'has_host_vars': True},
#   {'type': 'COMMIT', 'host_variables': [], 'line': 3, 'has_host_vars': False}
# ]
```