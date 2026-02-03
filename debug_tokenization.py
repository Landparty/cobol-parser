#!/usr/bin/env python
"""Debug script to trace DATA DIVISION parsing."""

from cobolparser.lexer import CobolLexer
from cobolparser.preprocess import normalize_fixed_format
from cobolparser.core.token_stream import TokenStream

with open('examples/cobol/IX103A.CBL', 'r') as f:
    lines = f.readlines()

normalized = normalize_fixed_format(lines)
lexer = CobolLexer(normalized, free_form=True)
tokens = lexer.tokenize()

# Create token stream
stream = TokenStream(tokens)

# Skip to DATA DIVISION
while not stream.is_empty():
    token = stream.peek(0)
    if token and token.type.name == 'DATA_DIVISION':
        print(f'Found DATA_DIVISION at position')
        # Show next 5 tokens
        for i in range(5):
            t = stream.peek(i)
            if t:
                print(f'  Token {i}: type={t.type.name:20s} value={t.value!r}')
        break
    stream.consume()

# Now consume as the parser would
division_token = stream.consume()
print(f'\nConsumed: type={division_token.type.name:20s} value={division_token.value!r}')

# Check for optional DIVISION keyword
if not stream.is_empty():
    next_token = stream.peek(0)
    if next_token:
        print(f'Next token: type={next_token.type.name:20s} value={next_token.value!r}')
        if next_token and next_token.value.upper() == "DIVISION":
            print('Consuming DIVISION keyword')
            stream.consume()

# Skip whitespace and comments
stream.skip_whitespace_and_comments()

# Check what's next
if not stream.is_empty():
    token = stream.peek(0)
    if token:
        print(f'After skip_whitespace: type={token.type.name:20s} value={token.value!r}')
    else:
        print('Stream is empty')
else:
    print('Stream is empty')
