# Complete Program Parsing Example

This document shows the complete AST output for a comprehensive COBOL program that demonstrates various language features.

## Sample COBOL Program

```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EMPLOYEE-REPORT.
       AUTHOR. JOHN DOE.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-EMPLOYEE.
           05  WS-EMP-ID      PIC 9(6) COMP-3.
           05  WS-EMP-NAME    PIC X(30).
           05  WS-EMP-SALARY  PIC 9(7)V99 COMP-3.
       
       01  WS-REPORT-LINE     PIC X(80).
       01  WS-COUNTER         PIC 9(5) VALUE 0.
       
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           PERFORM INITIALIZE-REPORT.
           
           EXEC SQL
               DECLARE EMP_CURSOR CURSOR FOR
               SELECT EMP_ID, EMP_NAME, SALARY
               FROM EMPLOYEE
               WHERE DEPT_ID = :WS-DEPT-ID
               ORDER BY EMP_NAME
           END-EXEC.
           
           EXEC SQL OPEN EMP_CURSOR END-EXEC.
           
           PERFORM PROCESS-EMPLOYEES
               UNTIL SQLCODE NOT = 0.
           
           EXEC SQL CLOSE EMP_CURSOR END-EXEC.
           
           PERFORM PRINT-REPORT-SUMMARY.
           STOP RUN.
           
       INITIALIZE-REPORT.
           MOVE "EMPLOYEE SALARY REPORT" TO WS-REPORT-LINE.
           DISPLAY WS-REPORT-LINE.
           MOVE 0 TO WS-COUNTER.
           
       PROCESS-EMPLOYEES.
           EXEC SQL
               FETCH EMP_CURSOR
               INTO :WS-EMP-ID, :WS-EMP-NAME, :WS-EMP-SALARY
           END-EXEC.
           
           IF SQLCODE = 0
               ADD 1 TO WS-COUNTER
               CALL "FORMAT-EMPLOYEE-LINE" USING WS-EMPLOYEE
               DISPLAY WS-REPORT-LINE
           END-IF.
           
       PRINT-REPORT-SUMMARY.
           MOVE WS-COUNTER TO WS-REPORT-LINE.
           DISPLAY "TOTAL EMPLOYEES: " WS-REPORT-LINE.
```

## Complete AST Output

```json
{
  "node_type": "CobolProgram",
  "program_name": "EMPLOYEE-REPORT",
  "author": "JOHN DOE",
  "divisions": {
    "DATA": {
      "node_type": "CobolDivision",
      "division_name": "DATA",
      "sections": {
        "WORKING-STORAGE": {
          "node_type": "CobolSection",
          "section_name": "WORKING-STORAGE",
          "children": [
            {
              "node_type": "DataItem",
              "level": 1,
              "name": "WS-EMPLOYEE",
              "picture_clause": null,
              "usage": "DISPLAY",
              "value_clause": null,
              "occurs_clause": null,
              "children": [
                {
                  "node_type": "DataItem",
                  "level": 5,
                  "name": "WS-EMP-ID",
                  "picture_clause": {
                    "pattern": "9(6)",
                    "type": "NUMERIC",
                    "length": 6,
                    "usage": "COMP-3"
                  },
                  "usage": "COMP-3",
                  "value_clause": null,
                  "occurs_clause": null,
                  "children": [],
                  "location": {
                    "file": "employee-report.cob",
                    "line": 7,
                    "column": 12
                  },
                  "metadata": {
                    "storage_size": 4,
                    "is_group_item": false,
                    "has_children": false
                  }
                },
                {
                  "node_type": "DataItem",
                  "level": 5,
                  "name": "WS-EMP-NAME",
                  "picture_clause": {
                    "pattern": "X(30)",
                    "type": "ALPHANUMERIC",
                    "length": 30,
                    "usage": "DISPLAY"
                  },
                  "usage": "DISPLAY",
                  "value_clause": null,
                  "occurs_clause": null,
                  "children": [],
                  "location": {
                    "file": "employee-report.cob",
                    "line": 8,
                    "column": 12
                  },
                  "metadata": {
                    "storage_size": 30,
                    "is_group_item": false,
                    "has_children": false
                  }
                },
                {
                  "node_type": "DataItem",
                  "level": 5,
                  "name": "WS-EMP-SALARY",
                  "picture_clause": {
                    "pattern": "9(7)V99",
                    "type": "NUMERIC",
                    "length": 9,
                    "usage": "COMP-3"
                  },
                  "usage": "COMP-3",
                  "value_clause": null,
                  "occurs_clause": null,
                  "children": [],
                  "location": {
                    "file": "employee-report.cob",
                    "line": 9,
                    "column": 12
                  },
                  "metadata": {
                    "storage_size": 5,
                    "is_group_item": false,
                    "has_children": false
                  }
                }
              ],
              "location": {
                "file": "employee-report.cob",
                "line": 6,
                "column": 12
              },
              "metadata": {
                "storage_size": 39,
                "is_group_item": true,
                "has_children": true,
                "child_count": 3
              }
            },
            {
              "node_type": "DataItem",
              "level": 1,
              "name": "WS-REPORT-LINE",
              "picture_clause": {
                "pattern": "X(80)",
                "type": "ALPHANUMERIC",
                "length": 80,
                "usage": "DISPLAY"
              },
              "usage": "DISPLAY",
              "value_clause": null,
              "occurs_clause": null,
              "children": [],
              "location": {
                "file": "employee-report.cob",
                "line": 11,
                "column": 12
              },
              "metadata": {
                "storage_size": 80,
                "is_group_item": false,
                "has_children": false
              }
            },
            {
              "node_type": "DataItem",
              "level": 1,
              "name": "WS-COUNTER",
              "picture_clause": {
                "pattern": "9(5)",
                "type": "NUMERIC",
                "length": 5,
                "usage": "DISPLAY"
              },
              "usage": "DISPLAY",
              "value_clause": {
                "value": 0,
                "is_literal": true
              },
              "occurs_clause": null,
              "children": [],
              "location": {
                "file": "employee-report.cob",
                "line": 12,
                "column": 12
              },
              "metadata": {
                "storage_size": 5,
                "is_group_item": false,
                "has_children": false,
                "has_initial_value": true
              }
            }
          ],
          "location": {
            "file": "employee-report.cob",
            "line": 5,
            "column": 8
          },
          "metadata": {
            "item_count": 3,
            "total_storage": 124
          }
        }
      },
      "location": {
        "file": "employee-report.cob",
        "line": 4,
        "column": 8
      },
      "metadata": {
        "section_count": 1
      }
    },
    "PROCEDURE": {
      "node_type": "CobolDivision",
      "division_name": "PROCEDURE",
      "sections": {
        "MAIN-PROCESS": {
          "node_type": "CobolSection",
          "section_name": "MAIN-PROCESS",
          "children": [
            {
              "node_type": "PerformStatement",
              "perform_type": "SIMPLE",
              "target_paragraph": "INITIALIZE-REPORT",
              "times_count": null,
              "until_condition": null,
              "varying_clause": null,
              "inline_statements": null,
              "location": {
                "file": "employee-report.cob",
                "line": 16,
                "column": 12
              },
              "metadata": {}
            },
            {
              "node_type": "ExecSQLStatement",
              "sql_type": "DECLARE",
              "sql_text": "DECLARE EMP_CURSOR CURSOR FOR SELECT EMP_ID, EMP_NAME, SALARY FROM EMPLOYEE WHERE DEPT_ID = :WS-DEPT-ID ORDER BY EMP_NAME",
              "host_variables": ["WS-DEPT-ID"],
              "location": {
                "file": "employee-report.cob",
                "line": 18,
                "column": 12
              },
              "metadata": {
                "dialect": "IBM_ENTERPRISE",
                "has_host_variables": true,
                "host_variable_count": 1
              }
            },
            {
              "node_type": "ExecSQLStatement",
              "sql_type": "OPEN",
              "sql_text": "OPEN EMP_CURSOR",
              "host_variables": [],
              "location": {
                "file": "employee-report.cob",
                "line": 24,
                "column": 12
              },
              "metadata": {
                "dialect": "IBM_ENTERPRISE",
                "has_host_variables": false,
                "host_variable_count": 0
              }
            },
            {
              "node_type": "PerformStatement",
              "perform_type": "UNTIL",
              "target_paragraph": "PROCESS-EMPLOYEES",
              "times_count": null,
              "until_condition": {
                "left_operand": "SQLCODE",
                "operator": "NOT =",
                "right_operand": 0
              },
              "varying_clause": null,
              "inline_statements": null,
              "location": {
                "file": "employee-report.cob",
                "line": 26,
                "column": 12
              },
              "metadata": {}
            },
            {
              "node_type": "ExecSQLStatement",
              "sql_type": "CLOSE",
              "sql_text": "CLOSE EMP_CURSOR",
              "host_variables": [],
              "location": {
                "file": "employee-report.cob",
                "line": 30,
                "column": 12
              },
              "metadata": {
                "dialect": "IBM_ENTERPRISE",
                "has_host_variables": false,
                "host_variable_count": 0
              }
            },
            {
              "node_type": "PerformStatement",
              "perform_type": "SIMPLE",
              "target_paragraph": "PRINT-REPORT-SUMMARY",
              "times_count": null,
              "until_condition": null,
              "varying_clause": null,
              "inline_statements": null,
              "location": {
                "file": "employee-report.cob",
                "line": 32,
                "column": 12
              },
              "metadata": {}
            }
          ],
          "location": {
            "file": "employee-report.cob",
            "line": 15,
            "column": 8
          },
          "metadata": {
            "statement_count": 6
          }
        },
        "INITIALIZE-REPORT": {
          "node_type": "CobolSection",
          "section_name": "INITIALIZE-REPORT",
          "children": [
            {
              "node_type": "MoveStatement",
              "source": "EMPLOYEE SALARY REPORT",
              "targets": ["WS-REPORT-LINE"],
              "location": {
                "file": "employee-report.cob",
                "line": 37,
                "column": 12
              }
            },
            {
              "node_type": "DisplayStatement",
              "display_items": ["WS-REPORT-LINE"],
              "location": {
                "file": "employee-report.cob",
                "line": 38,
                "column": 12
              }
            },
            {
              "node_type": "MoveStatement",
              "source": 0,
              "targets": ["WS-COUNTER"],
              "location": {
                "file": "employee-report.cob",
                "line": 39,
                "column": 12
              }
            }
          ],
          "location": {
            "file": "employee-report.cob",
            "line": 36,
            "column": 8
          },
          "metadata": {
            "statement_count": 3
          }
        },
        "PROCESS-EMPLOYEES": {
          "node_type": "CobolSection",
          "section_name": "PROCESS-EMPLOYEES",
          "children": [
            {
              "node_type": "ExecSQLStatement",
              "sql_type": "FETCH",
              "sql_text": "FETCH EMP_CURSOR INTO :WS-EMP-ID, :WS-EMP-NAME, :WS-EMP-SALARY",
              "host_variables": ["WS-EMP-ID", "WS-EMP-NAME", "WS-EMP-SALARY"],
              "location": {
                "file": "employee-report.cob",
                "line": 43,
                "column": 12
              },
              "metadata": {
                "dialect": "IBM_ENTERPRISE",
                "has_host_variables": true,
                "host_variable_count": 3
              }
            },
            {
              "node_type": "IfStatement",
              "condition": {
                "left_operand": "SQLCODE",
                "operator": "=",
                "right_operand": 0
              },
              "then_statements": [
                {
                  "node_type": "AddStatement",
                  "value": 1,
                  "target": "WS-COUNTER",
                  "location": {
                    "file": "employee-report.cob",
                    "line": 49,
                    "column": 16
                  }
                },
                {
                  "node_type": "CallStatement",
                  "called_program": "FORMAT-EMPLOYEE-LINE",
                  "using_parameters": ["WS-EMPLOYEE"],
                  "giving_parameter": null,
                  "on_exception": null,
                  "not_on_exception": null,
                  "location": {
                    "file": "employee-report.cob",
                    "line": 50,
                    "column": 16
                  }
                },
                {
                  "node_type": "DisplayStatement",
                  "display_items": ["WS-REPORT-LINE"],
                  "location": {
                    "file": "employee-report.cob",
                    "line": 51,
                    "column": 16
                  }
                }
              ],
              "else_statements": [],
              "location": {
                "file": "employee-report.cob",
                "line": 48,
                "column": 12
              }
            }
          ],
          "location": {
            "file": "employee-report.cob",
            "line": 42,
            "column": 8
          },
          "metadata": {
            "statement_count": 2
          }
        },
        "PRINT-REPORT-SUMMARY": {
          "node_type": "CobolSection",
          "section_name": "PRINT-REPORT-SUMMARY",
          "children": [
            {
              "node_type": "MoveStatement",
              "source": "WS-COUNTER",
              "targets": ["WS-REPORT-LINE"],
              "location": {
                "file": "employee-report.cob",
                "line": 55,
                "column": 12
              }
            },
            {
              "node_type": "DisplayStatement",
              "display_items": ["TOTAL EMPLOYEES: ", "WS-REPORT-LINE"],
              "location": {
                "file": "employee-report.cob",
                "line": 56,
                "column": 12
              }
            }
          ],
          "location": {
            "file": "employee-report.cob",
            "line": 54,
            "column": 8
          },
          "metadata": {
            "statement_count": 2
          }
        }
      },
      "location": {
        "file": "employee-report.cob",
        "line": 14,
        "column": 8
      },
      "metadata": {
        "section_count": 4
      }
    }
  },
  "location": {
    "file": "employee-report.cob",
    "line": 1,
    "column": 1
  },
  "metadata": {
    "division_count": 2,
    "total_sections": 5,
    "total_data_items": 5,
    "total_statements": 17,
    "has_sql": true,
    "sql_statement_count": 4,
    "has_calls": true,
    "call_statement_count": 1
  }
}
```

## Program Analysis Summary

This example demonstrates:

- **Data Division**: Group items, COMP-3 packed decimal, initial values
- **Procedure Division**: Multiple paragraphs with different statement types
- **SQL Integration**: DECLARE CURSOR, OPEN, FETCH, CLOSE operations
- **Control Flow**: PERFORM statements, IF conditions
- **Subprogram Calls**: CALL statement with parameter passing

### Key Metrics from AST
- **Divisions**: 2 (DATA, PROCEDURE)
- **Sections**: 5 total (1 in DATA, 4 in PROCEDURE)
- **Data Items**: 5 (3 elementary, 2 group items)
- **Statements**: 17 total
- **SQL Statements**: 4 (DECLARE, OPEN, FETCH, CLOSE)
- **CALL Statements**: 1
- **PERFORM Statements**: 3 (2 SIMPLE, 1 UNTIL)

### Storage Analysis
- **WS-EMPLOYEE**: 39 bytes (COMP-3 fields save space)
- **WS-REPORT-LINE**: 80 bytes
- **WS-COUNTER**: 5 bytes
- **Total Working Storage**: 124 bytes

This comprehensive example shows how the parser creates a complete, traversable AST that can be used for code analysis, refactoring, documentation generation, and migration projects.