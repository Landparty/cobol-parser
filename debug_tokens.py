"""Debug script to check tokenization and parsing."""

from cobolparser.lexer import CobolLexer
from cobolparser.parser import CobolParser
from cobolparser.plugins.core import ErrorRecoveryMode

source = """IDENTIFICATION DIVISION.
PROGRAM-ID. TEST-THRU.
PROCEDURE DIVISION.
MAIN-PARA.
    PERFORM PARA-START THRU PARA-END.
"""

print("=== TOKENIZATION ===")
lexer = CobolLexer()
tokens = lexer.tokenize(source)
for i, token in enumerate(tokens):
    print(f"{i}: {token.type.name:20} | {repr(token.value):30} | Line {token.location.line}")

print("\n=== PARSING ===")
parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
result = parser.parse(source)

print(f"Success: {result.success}")
if result.errors:
    for err in result.errors:
        print(f"Error: {err}")
