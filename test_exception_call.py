#!/usr/bin/env python
"""Test CALL in exception handler"""

from cobolparser import CobolParser
from cobolparser.models.statements import CallStatement

code = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-PROG.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMOUNT               PIC 9(5).
       01  WS-RESULT               PIC 9(5).
       01  WS-CHILD-PROG           PIC X(20).
       01  WS-FALLBACK-SVC         PIC X(20).
       
       PROCEDURE DIVISION.
       MAIN-SECTION.
           MOVE 5000.00 TO WS-AMOUNT
           MOVE 'RISKY-OP' TO WS-CHILD-PROG
           MOVE 'FALLBACK' TO WS-FALLBACK-SVC
           
           CALL WS-CHILD-PROG USING WS-AMOUNT
                                    BY REFERENCE WS-RESULT
               ON EXCEPTION
                   DISPLAY 'Exception occurred'
                   CALL WS-FALLBACK-SVC USING BY REFERENCE WS-AMOUNT
                                                WS-RESULT
                   DISPLAY 'Called fallback handler'
               NOT ON EXCEPTION
                   DISPLAY 'Success'.
           
           STOP RUN.
"""

parser = CobolParser()
result = parser.parse(code)
all_stmts = result.ast.get_all_statements()

# Find CALL statements
calls = [s for s in all_stmts if isinstance(s, CallStatement)]
print(f"Total CALL statements parsed: {len(calls)}")

# Check the first CALL (should be WS-CHILD-PROG with exception handler)
first_call = calls[-1]  # Last in all_stmts should be first chronologically
print(f"\nFirst CALL: {first_call.called_program}")
print(f"  Has on_exception: {first_call.on_exception is not None}")
if first_call.on_exception:
    print(f"  on_exception type: {type(first_call.on_exception)}")
    print(f"  on_exception length: {len(first_call.on_exception) if first_call.on_exception else 0}")
    if first_call.on_exception:
        for j, stmt in enumerate(first_call.on_exception):
            print(f"    [{j}] {type(stmt).__name__}: {stmt}")
    
# Check second CALL
if len(calls) > 1:
    second_call = calls[0]
    print(f"\nSecond CALL: {second_call.called_program}")
