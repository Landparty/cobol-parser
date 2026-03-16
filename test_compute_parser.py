from cobolparser.lexer import CobolLexer, TokenType
from cobolparser.core.token_stream import TokenStream
from cobolparser.parsers.statements import ComputeStatementParser

code = 'COMPUTE A = B + 1.'

lexer = CobolLexer(code, "<test>", free_form=True)
tokens = lexer.tokenize()

print("Tokens:")
for i, token in enumerate(tokens):
    print(f"  {i}: {token.type.name} = {repr(token.value)}")

stream = TokenStream(tokens)
parser = ComputeStatementParser()

print(f"\nParser matches: {parser.matches(stream)}")
print(f"Current token: {stream.peek().type.name} = {repr(stream.peek().value)}")

stmt = parser.parse(stream)
print(f"\nParsed statement:")
print(f"  Type: {type(stmt).__name__}")
print(f"  Targets: {stmt.targets}")
print(f"  Expression: {stmt.expression}")
