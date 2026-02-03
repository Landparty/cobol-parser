"""Debug token generation for PERFORM THRU TIMES."""
from cobolparser.lexer import CobolLexer

source = """
    IDENTIFICATION DIVISION.
    PROGRAM-ID. TEST-THRU-TIMES.
    PROCEDURE DIVISION.
    MAIN-PARA.
        PERFORM PARA-A THRU PARA-B 5 TIMES.
        STOP RUN.
    PARA-A.
        DISPLAY 'A'.
    PARA-B.
        DISPLAY 'B'.
"""

lexer = CobolLexer(source)
tokens = lexer.tokenize()

# Find the line with PERFORM THRU and print tokens around it
print("Tokens for PERFORM statement:")
in_perform = False
for i, token in enumerate(tokens):
    if token.value and token.value.upper() == 'PERFORM':
        in_perform = True
        start_idx = max(0, i - 1)
    if in_perform:
        print(f"{i}: {token.type.name:20} = {repr(token.value)}")
        if token.type.name == 'PERIOD':
            break
