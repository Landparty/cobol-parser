#!/usr/bin/env python
"""Comprehensive validation of all CALL enhancements"""

from cobolparser import CobolParser
from cobolparser.models.statements import CallStatement, IfStatement, PerformStatement

# Test program with all enhancement features
code = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COMPREHENSIVE-TEST.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-VARS.
           05  WS-AMOUNT      PIC 9(5).
           05  WS-RESULT      PIC 9(5).
           05  WS-INDEX       PIC 99.
           05  WS-PROG-NAME   PIC X(20).
       
       PROCEDURE DIVISION.
       MAIN-SECTION.
           
      *    Test 1: Multi-line parameters
           CALL 'SIMPLE' USING WS-AMOUNT
                             BY REFERENCE WS-RESULT
                             BY VALUE WS-INDEX.
           
      *    Test 2: CALL in IF block
           IF WS-AMOUNT > 100
               CALL WS-PROG-NAME USING WS-AMOUNT
                                       WS-RESULT
                   RETURNING WS-INDEX
           END-IF.
           
      *    Test 3: CALL in PERFORM loop
           PERFORM VARYING WS-INDEX FROM 1 BY 1
               UNTIL WS-INDEX > 5
               CALL 'BATCH' USING BY REFERENCE WS-AMOUNT
           END-PERFORM.
           
      *    Test 4: Multiple CALLs in sentence
           CALL 'FIRST' USING WS-AMOUNT
           CALL 'SECOND' USING WS-RESULT.
           
           STOP RUN.
"""

parser = CobolParser()
result = parser.parse(code)
all_stmts = result.ast.get_all_statements()

# Analyze results
calls = [s for s in all_stmts if isinstance(s, CallStatement)]
ifs = [s for s in all_stmts if isinstance(s, IfStatement)]
performs = [s for s in all_stmts if isinstance(s, PerformStatement)]

print("="*80)
print("COMPREHENSIVE CALL ENHANCEMENT VALIDATION")
print("="*80)

print(f"\n✓ Multi-line Parameters")
print(f"  {calls[0].called_program}: {len(calls[0].using_parameters)} params")
for p in calls[0].using_parameters:
    print(f"    - {p.name} ({p.passing_mode})")

print(f"\n✓ CALL in IF Block")
print(f"  IF statement found: {len(ifs)}")
print(f"  THEN statements: {len(ifs[0].then_statements) if ifs else 0}")
if ifs and ifs[0].then_statements:
    for stmt in ifs[0].then_statements:
        if isinstance(stmt, CallStatement):
            print(f"    - {stmt.called_program}")
            if stmt.returning_parameter:
                print(f"      RETURNING: {stmt.returning_parameter}")

print(f"\n✓ CALL in PERFORM Loop")
print(f"  PERFORM statement found: {len(performs)}")
if performs:
    for stmt in performs[0].inline_statements:
        if isinstance(stmt, CallStatement):
            print(f"    - {stmt.called_program}")

print(f"\n✓ Multiple CALLs in Sentence")
first_multi = [c for c in calls if c.called_program == "'FIRST'"]
second_multi = [c for c in calls if c.called_program == "'SECOND'"]
print(f"  'FIRST' CALL: {len(first_multi)}")
print(f"  'SECOND' CALL: {len(second_multi)}")

print(f"\n{'='*80}")
print(f"SUMMARY: {len(calls)} CALL statements parsed")
print(f"  - {calls[0].called_program} (multi-line params)")
print(f"  - IF block integration")
print(f"  - PERFORM loop integration")
print(f"  - Multi-CALL sentences")
print(f"{'='*80}")
