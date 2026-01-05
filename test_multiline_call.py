#!/usr/bin/env python
"""Debug script to trace CALL parsing"""

from cobolparser.lexer import CobolLexer
from cobolparser.parser import CobolParser

code = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-PROG.
       
       PROCEDURE DIVISION.
       MAIN-SECTION.
           CALL 'CALCPAY' USING WS-SALARY 
                                WS-HOURS
                                WS-GROSS-PAY
           
           CALL WS-CALC-TAX-PGM USING WS-GROSS-PAY
                                      WS-TAX-AMOUNT
           
           DISPLAY 'Done'.
           STOP RUN.
"""

# Tokenize
lexer = CobolLexer(code)
tokens = lexer.tokenize()

print("Tokens around CALL statements:")
for i, tok in enumerate(tokens):
    if i >= 20 and i <= 60:
        print(f"{i:3d}: {str(tok.type):30s} = '{tok.value}'")

# Parse
parser = CobolParser()
result = parser.parse(code)

from cobolparser.models.statements import CallStatement
all_stmts = result.ast.get_all_statements()
calls = [s for s in all_stmts if isinstance(s, CallStatement)]

print(f"\n\nCALL statements parsed: {len(calls)}")
for call in calls:
    print(f"  Program: {call.called_program}")
    if call.using_parameters:
        print(f"    Parameters ({len(call.using_parameters)}):")
        for p in call.using_parameters:
            print(f"      - {p.name} ({p.passing_mode})")
