#!/usr/bin/env python3
"""Debug tokens - exact test case."""

from cobolparser.lexer import CobolLexer

# Use EXACT format from test with indentation
source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            PERFORM 1 TIMES
                CALL "SUBPROGRAM"
            END-PERFORM.
            STOP RUN.
        """

lexer = CobolLexer(source)
tokens = lexer.tokenize()

print(f"Total tokens: {len(tokens)}\n")
print("Tokens:")
for i, token in enumerate(tokens):
    print(f"{i:3d}: {str(token.type.name):20s} = {repr(token.value):20s}")
