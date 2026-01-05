#!/usr/bin/env python
"""Debug tokens in IF CALL statement"""

from cobolparser.lexer import CobolLexer

code = """
           IF WS-AMOUNT > 50.00
               CALL WS-CHILD-PROG USING WS-AMOUNT
                                        BY REFERENCE WS-RESULT
                   RETURNING WS-RECOVERY-CODE
           END-IF
"""

lexer = CobolLexer(code)
tokens = lexer.tokenize()

print("Tokens:")
for i, tok in enumerate(tokens):
    if i < 50:
        print(f"{i:3d}: {str(tok.type):30s} = '{tok.value}'")
