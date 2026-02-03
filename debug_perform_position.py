"""Debug what position the perform parser receives tokens at."""
from cobolparser import CobolParser
from cobolparser.plugins.core import ErrorRecoveryMode
from cobolparser.lexer import CobolLexer
from cobolparser.core.token_stream import TokenStream
from cobolparser.parsers.perform_parser import PerformStatementParser
from cobolparser.core.interfaces import ParseContext

# Full program source to ensure proper tokenization
full_source = """IDENTIFICATION DIVISION.
PROGRAM-ID. TEST-TIME.
PROCEDURE DIVISION.
MAIN-PARA.
    PERFORM PARA-A THRU PARA-B 5 TIMES.
PARA-A.
    DISPLAY 'A'.
PARA-B.
    DISPLAY 'B'.
"""

lexer = CobolLexer(full_source)
tokens = lexer.tokenize()

# Find the PERFORM token
perform_idx = None
for i, token in enumerate(tokens):
    if token.value and token.value.upper() == 'PERFORM':
        perform_idx = i
        break

if perform_idx is not None:
    print(f"Found PERFORM at index {perform_idx}")
    print("\nTokens around PERFORM:")
    for i in range(max(0, perform_idx - 1), min(len(tokens), perform_idx + 10)):
        token = tokens[i]
        marker = " <- PERFORM" if i == perform_idx else ""
        print(f"{i}: {token.type.name:20} = {repr(token.value)}{marker}")
    
    # The perform parser would start after getting PERFORM
    # So it needs to advance past PERFORM first
    stream = TokenStream(tokens)
    
    # Simulate parser positioning: advance to PERFORM
    for _ in range(perform_idx):
        stream.advance()
    
    # Now at PERFORM token
    print(f"\nStream positioned at: {stream.peek().type.name} = {stream.peek().value}")
    
    # Parser sees PERFORM and advances
    stream.advance()
    stream.skip_whitespace_and_comments()
    
    # Now what does the parser see?
    print(f"After skipping PERFORM: {stream.peek().type.name} = {stream.peek().value}")
