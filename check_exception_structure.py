#!/usr/bin/env python
"""Check exception handler structure"""

from cobolparser import CobolParser
from cobolparser.models.statements import CallStatement

# Use a simple test code instead
code = '''
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-EXCEPTION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PROG PIC X(20).
       01  WS-VAR PIC 9(5).
       PROCEDURE DIVISION.
           CALL WS-PROG USING WS-VAR
               ON EXCEPTION
                   DISPLAY 'Error'
               NOT ON EXCEPTION
                   DISPLAY 'Success'
           END-CALL.
           STOP RUN.
'''

parser = CobolParser()
result = parser.parse(code)

print(f"Parse successful: {result.success}")

if result.ast:
    all_stmts = result.ast.get_all_statements()
    print(f"\nLooking for CALL statements with handlers...\n")
    
    for i, stmt in enumerate(all_stmts):
        if isinstance(stmt, CallStatement):
            has_handlers = stmt.on_exception or stmt.not_on_exception or stmt.on_overflow
            if has_handlers:
                print(f"[{i}] CallStatement: {stmt.called_program}")
                if stmt.on_exception:
                    print(f"    ON EXCEPTION ({len(stmt.on_exception)} statements):")
                    for ex_stmt in stmt.on_exception:
                        print(f"      - {type(ex_stmt).__name__}", end="")
                        if hasattr(ex_stmt, 'value_items'):
                            print(f": {ex_stmt.value_items}", end="")
                        print()
                if stmt.not_on_exception:
                    print(f"    NOT ON EXCEPTION ({len(stmt.not_on_exception)} statements):")
                    for nox_stmt in stmt.not_on_exception:
                        print(f"      - {type(nox_stmt).__name__}", end="")
                        if hasattr(nox_stmt, 'value_items'):
                            print(f": {nox_stmt.value_items}", end="")
                        print()
                if stmt.on_overflow:
                    print(f"    ON OVERFLOW ({len(stmt.on_overflow)} statements):")
                    for of_stmt in stmt.on_overflow:
                        print(f"      - {type(of_stmt).__name__}", end="")
                        if hasattr(of_stmt, 'called_program'):
                            print(f": {of_stmt.called_program}", end="")
                        print()
                print()
