#!/usr/bin/env python3
"""Test EVALUATE with conditions."""

import sys
sys.path.insert(0, '.')

from cobolparser.lexer import CobolLexer
from cobolparser.core.token_stream import TokenStream
from cobolparser.parsers.statements.evaluate_parser import EvaluateStatementParser

code = """       EVALUATE TRUE
           WHEN WS-GRADE = 9 AND WS-COUNTER > 5
               DISPLAY 'HIGH'
       END-EVALUATE.
"""

# Lex the code
lexer = CobolLexer(code)
tokens = lexer.tokenize()

print("Tokens:")
for i, token in enumerate(tokens):
    print(f"  {i:2}: {token.type.name:20} = '{token.value}'")

# Create token stream
stream = TokenStream(tokens)

# Parse
parser = EvaluateStatementParser()
stmt = parser.parse(stream)

print(f"\nParsed statement: {type(stmt).__name__}")
print(f"  subjects: {stmt.subjects}")
print(f"  when_clauses: {len(stmt.when_clauses)}")
for i, clause in enumerate(stmt.when_clauses):
    print(f"    clause[{i}]: {clause.selectors}")
    for j, sel in enumerate(clause.selectors):
        print(f"      selector[{j}]: {sel}")
