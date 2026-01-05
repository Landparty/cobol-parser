#!/usr/bin/env python
"""Test CALL in PERFORM loop"""

from cobolparser import CobolParser
from cobolparser.models.statements import CallStatement, PerformStatement

code = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-PROG.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CURRENT-LEVEL        PIC 99.
       01  WS-AMOUNT               PIC 9(5).
       01  WS-RESULT               PIC 9(5).
       
       PROCEDURE DIVISION.
       MAIN-SECTION.
           MOVE 0 TO WS-CURRENT-LEVEL
           
           PERFORM VARYING WS-CURRENT-LEVEL FROM 1 BY 1
               UNTIL WS-CURRENT-LEVEL > 5
               
               MOVE WS-CURRENT-LEVEL TO WS-AMOUNT
               
               CALL 'BATCH-PROCESSOR' USING BY REFERENCE WS-AMOUNT
                                              WS-RESULT
           END-PERFORM
           
           STOP RUN.
"""

parser = CobolParser()
result = parser.parse(code)
all_stmts = result.ast.get_all_statements()

# Find PERFORM statements
perform_stmts = [s for s in all_stmts if isinstance(s, PerformStatement)]
print(f"PERFORM statements: {len(perform_stmts)}")
for perf in perform_stmts:
    print(f"  Inline statements: {len(perf.inline_statements) if hasattr(perf, 'inline_statements') else 0}")

# Find CALL statements
calls = [s for s in all_stmts if isinstance(s, CallStatement)]
print(f"\nTotal CALL statements parsed: {len(calls)}")
for call in calls:
    print(f"  - {call.called_program}: {len(call.using_parameters or [])} params")
