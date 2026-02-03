"""Corrected manual simulation of PERFORM THRU TIMES parsing."""
from cobolparser.lexer import CobolLexer, TokenType
from cobolparser.core.token_stream import TokenStream
from cobolparser.models.statements import PerformStatement
from cobolparser.models.ast_base import SourceLocation

# Test the actual perform parser
source_line = "PERFORM PARA-A THRU PARA-B 5 TIMES."

lexer = CobolLexer(source_line)
tokens = lexer.tokenize()

print("Tokenization of 'PERFORM PARA-A THRU PARA-B 5 TIMES.':")
print("Tokens returned by lexer:")
for i, t in enumerate(tokens):
    print(f"  {i}: {t.type.name:20} = {repr(t.value)}")

# The parser should skip PERFORM and position at PARA-A
# But our lexer doesn't include PERFORM, so we're at PARA-A already
stream = TokenStream(tokens)

print("\n=== Simulating perform parser logic (corrected) ===")

stmt = PerformStatement(SourceLocation(1, 1, 1))

# Simple PERFORM paragraph-name (the parser skips PERFORM first, but since our tokens don't have it, we're already at PARA-A)
token = stream.peek()
print(f"1. At first token: {token.type.name:20} = {repr(token.value)}")

if token and token.type == TokenType.IDENTIFIER:
    paragraph = token.value
    stmt.set_target_paragraph(paragraph)
    print(f"2. Set target_paragraph: {paragraph}")
    stream.advance()
    stream.skip_whitespace_and_comments()

    # Check for THRU clause
    token = stream.peek()
    print(f"3. After advancing, at: {token.type.name:20} = {repr(token.value)}")
    
    if token and token.value and token.value.upper() == "THRU":
        print(f"4. Found THRU keyword")
        stream.advance()  # Skip THRU
        stream.skip_whitespace_and_comments()
        
        token = stream.peek()
        print(f"5. After THRU advance, at: {token.type.name:20} = {repr(token.value)}")
        
        if token and token.type == TokenType.IDENTIFIER:
            stmt.set_thru_paragraph(token.value)
            print(f"6. Set thru_paragraph: {token.value}")
            stream.advance()  # THIS WAS MISSING IN MY EARLIER TEST!
            stream.skip_whitespace_and_comments()
            print(f"7. After thru_paragraph advance, at: {token.type.name:20} = {repr(token.value)}")

    # Check for TIMES clause - THIS IS WHERE IT SHOULD BE A NUMBER
    print(f"\n=== Checking for TIMES clause ===")
    token = stream.peek()
    print(f"8. At next token: {token.type.name:20} = {repr(token.value)}")
    print(f"   TokenType check: NUMERIC_LITERAL={TokenType.NUMERIC_LITERAL}, LEVEL_NUMBER={TokenType.LEVEL_NUMBER}")
    print(f"   Actual token type enum value: {token.type}")
    print(f"   Is numeric? {token.type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER)}")
    
    if token and token.type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER):
        print(f"9. Token is numeric!")
        try:
            times_count = int(token.value)
            print(f"10. Parsed times_count: {times_count}")
            stream.advance()
            stream.skip_whitespace_and_comments()
            
            token = stream.peek()
            print(f"11. After numeric advance, at: {token.type.name:20} = {repr(token.value)}")
            
            if token and token.value and token.value.upper() in ("TIMES", "TIME"):
                print(f"12. Found TIMES keyword!")
                stream.advance()
                stmt.set_times_clause(times_count)
                print(f"13. Set times_clause: {times_count}")
            else:
                print(f"12. Did NOT find TIMES keyword (token.value={repr(token.value if token else None)})")
        except ValueError as e:
            print(f"ERROR parsing times_count: {e}")
    else:
        print(f"9. Token is NOT numeric (it's {token.type.name})")

print(f"\n=== Final Statement State ===")
print(f"perform_type: {stmt.perform_type}")
print(f"times_count: {stmt.times_count}")
print(f"target_paragraph: {stmt.target_paragraph}")
print(f"thru_paragraph: {stmt.thru_paragraph}")
