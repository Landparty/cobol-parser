from cobolparser.lexer import CobolLexer

src = """IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
PROCEDURE DIVISION.
    ADD A TO B
        ON SIZE ERROR
            DISPLAY "Error"
            MOVE X TO Y.
"""

lexer = CobolLexer(src, "<test>")
tokens = lexer.tokenize()

print(f"Total tokens: {len(tokens)}")
print("\nTokens:")
for i, token in enumerate(tokens):
    print(f"{i:2}: {token.type.name:20} = {repr(token.value):20} | location={token.location}")
