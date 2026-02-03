"""Fixed manual simulation with proper peek after each advance."""
from cobolparser.lexer import CobolLexer, TokenType
from cobolparser.core.token_stream import TokenStream
from cobolparser.models.statements import PerformStatement
from cobolparser.models.ast_base import SourceLocation

source_line = "PERFORM PARA-A THRU PARA-B 5 TIMES."
lexer = CobolLexer(source_line)
tokens = lexer.tokenize()

stream = TokenStream(tokens)
stmt = PerformStatement(SourceLocation(1, 1, 1))

# Simple PERFORM paragraph-name
token = stream.peek()
print(f"1. At first token: {token.type.name:20} = {repr(token.value)}")

if token and token.type == TokenType.IDENTIFIER:
    paragraph = token.value
    stmt.set_target_paragraph(paragraph)
    print(f"2. Set target_paragraph: {paragraph}")
    
    # Advance and re-peek (THIS IS KEY!)
    stream.advance()
    stream.skip_whitespace_and_comments()
    token = stream.peek()  # RE-PEEK AFTER ADVANCE
    print(f"3. After advancing past '{paragraph}', now at: {token.type.name:20} = {repr(token.value)}")
    
    if token and token.value and token.value.upper() == "THRU":
        print(f"4. Found THRU keyword")
        
        # Advance past THRU and re-peek
        stream.advance()
        stream.skip_whitespace_and_comments()
        token = stream.peek()  # RE-PEEK
        print(f"5. After advancing past THRU, now at: {token.type.name:20} = {repr(token.value)}")
        
        if token and token.type == TokenType.IDENTIFIER:
            stmt.set_thru_paragraph(token.value)
            print(f"6. Set thru_paragraph: {token.value}")
            
            # Advance and re-peek
            stream.advance()
            stream.skip_whitespace_and_comments()
            token = stream.peek()  # RE-PEEK
            print(f"7. After advancing past '{token.value}', now at: {stream.peek().type.name:20} = {repr(stream.peek().value)}")

    # Check for TIMES clause
    print(f"\n=== Checking for TIMES clause ===")
    token = stream.peek()
    print(f"8. At next token: {token.type.name:20} = {repr(token.value)}")
    print(f"   Is in (NUMERIC_LITERAL, LEVEL_NUMBER)? {token.type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER)}")
    
    if token and token.type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER):
        print(f"9. Token is numeric!")
        try:
            times_count = int(token.value)
            print(f"10. Parsed times_count: {times_count}")
            
            stream.advance()
            stream.skip_whitespace_and_comments()
            token = stream.peek()
            print(f"11. After advancing past numeric, now at: {token.type.name:20} = {repr(token.value)}")
            
            if token and token.value and token.value.upper() in ("TIMES", "TIME"):
                print(f"12. Found TIMES keyword!")
                stream.advance()
                stmt.set_times_clause(times_count)
                print(f"13. Set times_clause: {times_count}, perform_type={stmt.perform_type}")
            else:
                print(f"12. No TIMES keyword found")
        except ValueError as e:
            print(f"ERROR: {e}")
    else:
        print(f"9. Token is NOT numeric")

print(f"\n=== Final State ===")
print(f"perform_type: {stmt.perform_type}")
print(f"times_count: {stmt.times_count}")
