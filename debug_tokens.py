from cobolparser.lexer import CobolLexer
from cobolparser.core.token_stream import TokenStream

code = '''PROCEDURE DIVISION.
COMPUTE A = B + 1.'''

lexer = CobolLexer(code, "<test>", free_form=True)
tokens = lexer.tokenize()

print("Tokens created:")
for i, token in enumerate(tokens):
    print(f"{i}: {token.type.name} = {repr(token.value)}")

# Now create a TokenStream and see what happens
stream = TokenStream(tokens)
print("\nTokenStream iteration:")
pos = 0
while pos < len(tokens):
    token = stream.peek()
    if token:
        print(f"pos {stream._pos}: {token.type.name} = {repr(token.value)}")
    stream.advance()
    pos += 1
