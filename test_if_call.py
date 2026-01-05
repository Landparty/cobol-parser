#!/usr/bin/env python
"""Test CALL in IF block"""

from cobolparser import CobolParser
from cobolparser.models.statements import CallStatement, IfStatement

code = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-PROG.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMOUNT               PIC 9(5).
       01  WS-RESULT               PIC 9(5).
       01  WS-CHILD-PROG           PIC X(20).
       01  WS-RECOVERY-CODE        PIC 999.
       
       PROCEDURE DIVISION.
       MAIN-SECTION.
           MOVE 100.00 TO WS-AMOUNT
           MOVE 'PROCESSOR' TO WS-CHILD-PROG
           
           IF WS-AMOUNT > 50.00
               CALL WS-CHILD-PROG USING WS-AMOUNT
                                        BY REFERENCE WS-RESULT
                   RETURNING WS-RECOVERY-CODE
           ELSE
               DISPLAY 'Amount below threshold'
           END-IF
           
           STOP RUN.
"""

parser = CobolParser()
result = parser.parse(code)

# First, get all statements
all_stmts = result.ast.get_all_statements()
print(f"Total statements from get_all_statements: {len(all_stmts)}")

# Find IF statements
if_stmts = [s for s in all_stmts if isinstance(s, IfStatement)]
print(f"IF statements: {len(if_stmts)}")
for if_stmt in if_stmts:
    print(f"  IF condition: {if_stmt.condition}")
    print(f"    THEN statements: {len(if_stmt.then_statements)}")
    for stmt in if_stmt.then_statements:
        print(f"      - {type(stmt).__name__}")
    print(f"    ELSE statements: {len(if_stmt.else_statements) if if_stmt.else_statements else 0}")
    for stmt in if_stmt.else_statements or []:
        print(f"      - {type(stmt).__name__}")

# Find CALL statements
calls = [s for s in all_stmts if isinstance(s, CallStatement)]
print(f"\nTotal CALL statements parsed: {len(calls)}")
for call in calls:
    print(f"  - {call.called_program}: {len(call.using_parameters or [])} params")
    if call.using_parameters:
        for p in call.using_parameters:
            print(f"      * {p.name} ({p.passing_mode})")
    if hasattr(call, 'returning_parameter') and call.returning_parameter:
        print(f"    RETURNING: {call.returning_parameter}")
