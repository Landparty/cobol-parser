import sys
sys.path.insert(0, r'c:\Users\sam94\workspace\cobol-parser')

from cobolparser.lexer import CobolLexer

cobol_code = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 COUNTER PIC 9(2).
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM VARYING COUNTER FROM 1 BY 1
               UNTIL COUNTER > 10
               CALL "INNER-PROG" USING COUNTER
           END-PERFORM.
           STOP RUN.
"""

lexer = CobolLexer(cobol_code)
tokens = list(lexer.tokenize())

# Find PERFORM token
perform_idx = None
for i, token in enumerate(tokens):
    if token.value and 'PERFORM' in str(token.value).upper():
        perform_idx = i
        break

if perform_idx:
    print(f"Tokens starting from PERFORM:")
    for i in range(perform_idx, min(perform_idx + 30, len(tokens))):
        token = tokens[i]
        print(f"  {i}: {token.type.name:25} | {token.value!r:20}")
