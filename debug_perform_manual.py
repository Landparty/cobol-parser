"""Debug PERFORM THRU TIMES parsing at the statement level."""
from cobolparser.parser import CobolParser
from cobolparser.plugins.core import ErrorRecoveryMode
from cobolparser.lexer import CobolLexer
from cobolparser.core.token_stream import TokenStream
from cobolparser.parsers.perform_parser import PerformStatementParser

# Just the perform statement tokens
source_line = "PERFORM PARA-A THRU PARA-B 5 TIMES."

lexer = CobolLexer(source_line)
tokens = lexer.tokenize()

print("Tokens:")
for i, token in enumerate(tokens):
    print(f"{i}: {token.type.name:20} = {repr(token.value)}")

# Create token stream and skip PERFORM
stream = TokenStream(tokens)

# Peek at first token to verify it's PERFORM
token0 = stream.peek()
print(f"\nFirst token: {token0.type.name} = {token0.value}")

# The parser should start after PERFORM has been verified
# Let's manually advance to after PERFORM
stream.advance()  # Skip PERFORM

print(f"\nAfter skipping PERFORM, at: {stream.peek().type.name} = {stream.peek().value}")

# Now manually trace through the perform parser logic
stream.skip_whitespace_and_comments()

# Check for paragraph name
token = stream.peek()
print(f"\nAt paragraph name: {token.type.name} = {token.value}")

if token and token.type.name == "IDENTIFIER":
    paragraph = token.value
    print(f"Got paragraph: {paragraph}")
    stream.advance()
    stream.skip_whitespace_and_comments()
    
    # Check for THRU
    token = stream.peek()
    print(f"At next token: {token.type.name} = {repr(token.value)}")
    
    if token and token.value and token.value.upper() == "THRU":
        print("Got THRU")
        stream.advance()
        stream.skip_whitespace_and_comments()
        
        token = stream.peek()
        print(f"After THRU, at: {token.type.name} = {token.value}")
        
        if token and token.type.name == "IDENTIFIER":
            thru_paragraph = token.value
            print(f"Got THRU paragraph: {thru_paragraph}")
            stream.advance()
            stream.skip_whitespace_and_comments()
            
            # Now check for TIMES
            token = stream.peek()
            print(f"After THRU paragraph, at: {token.type.name} = {repr(token.value)}")
            
            if token and token.type.name in ("NUMERIC_LITERAL", "LEVEL_NUMBER"):
                print(f"Got numeric: {token.value}")
                times_count = int(token.value)
                stream.advance()
                stream.skip_whitespace_and_comments()
                
                token = stream.peek()
                print(f"After numeric, at: {token.type.name} = {repr(token.value)}")
                
                if token and token.value and token.value.upper() in ("TIMES", "TIME"):
                    print("Got TIMES!")
                else:
                    print("Did NOT get TIMES")
            else:
                print(f"Did not get numeric, got {token.type.name} instead")
