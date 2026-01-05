#!/usr/bin/env python
"""Final validation of CALL enhancements"""

from cobolparser import CobolParser
from cobolparser.models.statements import CallStatement

code = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-VARS.
           05  WS-AMOUNT      PIC 9(5).
           05  WS-RESULT      PIC 9(5).
       PROCEDURE DIVISION.
       MAIN.
           CALL 'PROG1' USING WS-AMOUNT
                             BY REFERENCE WS-RESULT.
           IF WS-AMOUNT > 100
               CALL 'PROG2' USING WS-AMOUNT
           END-IF.
           STOP RUN.
"""

parser = CobolParser()
result = parser.parse(code)
calls = [s for s in result.ast.get_all_statements() 
         if isinstance(s, CallStatement)]

print(f"Parsed {len(calls)} CALL statements:")
for call in calls:
    params = f", {len(call.using_parameters)} params" if call.using_parameters else ""
    print(f"  ✓ {call.called_program}{params}")
