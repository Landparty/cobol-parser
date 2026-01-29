"""Test script to verify documentation examples work."""
from cobolparser import parse_cobol
from cobolparser.plugins.core import ErrorRecoveryMode

# Test basic parsing from README example
cobol_code = """       IDENTIFICATION DIVISION.
         PROGRAM-ID. EMPLOYEE-PROCESSOR.
         AUTHOR. COBOL Parser Team.
         
         ENVIRONMENT DIVISION.
         INPUT-OUTPUT SECTION.
         FILE-CONTROL.
             SELECT EMPLOYEE-FILE ASSIGN TO "EMP.DAT"
                 ORGANIZATION IS SEQUENTIAL.
         
         DATA DIVISION.
         FILE SECTION.
         FD EMPLOYEE-FILE.
         01 EMPLOYEE-RECORD.
             05 EMP-ID         PIC X(10).
             05 EMP-NAME       PIC X(30).
             05 EMP-SALARY     PIC 9(7)V99 COMP-3.
         
         WORKING-STORAGE SECTION.
         01 WS-COUNTER       PIC 9(4) VALUE 0.
         01 WS-TOTAL-SALARY  PIC 9(10)V99 COMP-3 VALUE 0.
         
         PROCEDURE DIVISION.
         MAIN-PARA.
             OPEN INPUT EMPLOYEE-FILE.
             READ EMPLOYEE-FILE
                 AT END DISPLAY "No records found"
                 NOT AT END PERFORM PROCESS-RECORDS.
             CLOSE EMPLOYEE-FILE.
             DISPLAY "Total salary: " WS-TOTAL-SALARY.
             STOP RUN.
             
         PROCESS-RECORDS.
             PERFORM UNTIL WS-COUNTER > 100
                 ADD 1 TO WS-COUNTER
                 ADD EMP-SALARY TO WS-TOTAL-SALARY
                 READ EMPLOYEE-FILE
                     AT END EXIT PERFORM
                     NOT AT END CONTINUE.
"""

result = parse_cobol(cobol_code, filename="employee_processor.cob")
print(f"Result: {result}")
print(f"Success: {result.success}")
if result.success:
    print(f"Program name: {result.ast.program_name}")
    print(f"Author: {result.ast.author}")
    print(f"Divisions: {list(result.ast.divisions.keys())}")
    print(f"Parse time: {result.statistics.total_time_ms}ms")
else:
    print("Errors:")
    for error in result.errors:
        print(f"  Line {error.line}: {error.message}")
