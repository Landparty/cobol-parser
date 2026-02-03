"""Add debugging to perform parser to trace TIMES clause parsing."""
import sys
from cobolparser.lexer import CobolLexer, TokenType
from cobolparser.core.token_stream import TokenStream
from cobolparser.models.statements import PerformStatement
from cobolparser.models.ast_base import SourceLocation

# Manually simulate the parsing logic with debug output
source_line = "PERFORM PARA-A THRU PARA-B 5 TIMES."

lexer = CobolLexer(source_line)
tokens = lexer.tokenize()

print("All tokens:")
for i, t in enumerate(tokens):
    print(f"  {i}: {t.type.name:20} = {repr(t.value)}")

# Create stream and position after PERFORM
stream = TokenStream(tokens)
stream.advance()  # Skip PERFORM
stream.skip_whitespace_and_comments()

# Now manually run through the perform parser logic
stmt = PerformStatement(SourceLocation(1, 1, 1))

print("\n=== Simulating perform parser logic ===")

token = stream.peek()
print(f"At paragraph name: {token.type.name} = {repr(token.value)}")

if token and token.type == TokenType.IDENTIFIER:
    paragraph = token.value
    stmt.set_target_paragraph(paragraph)
    print(f"Set target_paragraph: {paragraph}")
    stream.advance()
    stream.skip_whitespace_and_comments()

    # Check for THRU clause
    token = stream.peek()
    print(f"\nChecking THRU at: {token.type.name} = {repr(token.value)}")
    
    if token and token.value and token.value.upper() == "THRU":
        print("Found THRU keyword")
        stream.advance()  # Skip THRU
        stream.skip_whitespace_and_comments()
        
        token = stream.peek()
        print(f"After THRU, at: {token.type.name} = {repr(token.value)}")
        
        if token and token.type == TokenType.IDENTIFIER:
            stmt.set_thru_paragraph(token.value)
            print(f"Set thru_paragraph: {token.value}")
            stream.advance()
            stream.skip_whitespace_and_comments()
        else:
            print(f"ERROR: Expected IDENTIFIER after THRU, got {token.type.name}")

    # Check for TIMES clause after paragraph name
    print(f"\n=== Checking for TIMES clause ===")
    token = stream.peek()
    print(f"At next token: {token.type.name} = {repr(token.value)}")
    print(f"  Is NUMERIC_LITERAL? {token.type == TokenType.NUMERIC_LITERAL}")
    print(f"  Is LEVEL_NUMBER? {token.type == TokenType.LEVEL_NUMBER}")
    print(f"  Is in (NUMERIC_LITERAL, LEVEL_NUMBER)? {token.type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER)}")
    
    if token and token.type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER):
        print(f"Token is numeric type!")
        try:
            times_count = int(token.value)
            print(f"Parsed times_count: {times_count}")
            stream.advance()
            stream.skip_whitespace_and_comments()
            
            token = stream.peek()
            print(f"After numeric, at: {token.type.name} = {repr(token.value)}")
            print(f"  Is TIMES? {token.value.upper() in ('TIMES', 'TIME') if token and token.value else False}")
            
            if token and token.value and token.value.upper() in ("TIMES", "TIME"):
                print("Found TIMES keyword!")
                stream.advance()
                stmt.set_times_clause(times_count)
                print(f"Set times_clause: {times_count}")
            else:
                print(f"Did not find TIMES keyword at this position")
        except ValueError as e:
            print(f"ValueError parsing times_count: {e}")
    else:
        print(f"Token is NOT numeric type (type is {token.type.name})")

print(f"\n=== Final Statement State ===")
print(f"perform_type: {stmt.perform_type}")
print(f"times_count: {stmt.times_count}")
