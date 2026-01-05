#!/usr/bin/env python
"""Simple test to see if CALL statements are being added"""

from cobolparser.lexer import CobolLexer
from cobolparser.parser import CobolParser
from cobolparser.models.statements import CallStatement

code = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-PROG.
       
       PROCEDURE DIVISION.
       MAIN-SECTION.
           CALL 'SUBPROG1' USING VAR1 VAR2.
           DISPLAY 'Done'.
           STOP RUN.
"""

# Test parser
parser = CobolParser()
result = parser.parse(code)
print(f"Parsed result type: {type(result)}")
print(f"Result: {result}")

if hasattr(result, 'ast'):
    ast = result.ast
    print(f"\nAST: {ast}")
    
    # Test get_all_statements()
    all_stmts = ast.get_all_statements()
    print(f"\nTotal statements found: {len(all_stmts)}")
    for stmt in all_stmts:
        print(f"  - {type(stmt).__name__}: {stmt}")
    
    # Find CALL statements
    calls = [s for s in all_stmts if isinstance(s, CallStatement)]
    print(f"\nCALL statements found: {len(calls)}")
    for call in calls:
        print(f"  - {call.called_program} with {len(call.using_parameters or [])} params")
