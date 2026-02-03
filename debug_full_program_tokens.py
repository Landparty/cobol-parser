"""Check tokenization of full program to see PERFORM token sequence."""
from cobolparser.lexer import CobolLexer

source = """IDENTIFICATION DIVISION.
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

# Find PERFORM and show surrounding tokens
perform_idx = None
for i, token in enumerate(tokens):
    if token.value and token.value.upper() == 'PERFORM':
        perform_idx = i
        break

if perform_idx:
    print(f"PERFORM found at index {perform_idx}")
    print("\nTokens around PERFORM (indices -2 to +15):")
    for i in range(max(0, perform_idx - 2), min(len(tokens), perform_idx + 15)):
        marker = " <- PERFORM" if i == perform_idx else ""
        print(f"{i:3}: {tokens[i].type.name:20} = {repr(tokens[i].value):15}{marker}")
