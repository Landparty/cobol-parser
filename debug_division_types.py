"""Debug script to check what types division parsers are returning."""
import sys
from cobolparser import CobolParser
from cobolparser.models.program import CobolDivision
from cobolparser.parsers.divisions.factory import DivisionParserFactory

# Simple COBOL source
source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-VAR PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY 'HELLO'.
           STOP RUN.
"""

# Parse and trace
parser = CobolParser()
result = parser.parse(source)

print("=== Parse Result ===")
print(f"Success: {result.success}")
print(f"AST type: {type(result.ast)}")
print(f"AST divisions type: {type(result.ast.divisions)}")
print(f"AST divisions: {result.ast.divisions}")
print(f"Number of divisions: {len(result.ast.divisions)}")

# Check if we can access divisions via get_division
id_div = result.ast.get_division("IDENTIFICATION")
data_div = result.ast.get_division("DATA")
proc_div = result.ast.get_division("PROCEDURE")

print(f"\nID Division: {id_div}")
print(f"Data Division: {data_div}")
print(f"Procedure Division: {proc_div}")

# Now let's trace through the division parser factory directly
print("\n=== Direct Factory Test ===")
from cobolparser.lexer import CobolLexer

lexer = CobolLexer()
tokens = lexer.tokenize(source)

# Try to trace the first division
factory = DivisionParserFactory()

# Our parser should be using factory to create division parsers
# Let's check what the factory returns
print(f"Factory type: {type(factory)}")

# Let's look at what a division parser returns
from cobolparser.lexer import TokenStream
stream = TokenStream(tokens)

# Get first token to understand what we're parsing
first_tokens = list(stream.tokens)[:5]
print(f"First tokens: {[(t.type, t.value) for t in first_tokens]}")

# Reset stream
stream = TokenStream(list(stream.tokens))

# Try parsing a division directly
parser_from_factory = factory.find_parser(stream)
if parser_from_factory:
    print(f"\nFactory returned parser: {type(parser_from_factory)}")
    print(f"Parser class name: {parser_from_factory.__class__.__name__}")
    
    # Try parsing
    division_result = parser_from_factory.parse(stream)
    print(f"Parse result type: {type(division_result)}")
    print(f"Is CobolDivision? {isinstance(division_result, CobolDivision)}")
    print(f"Division result value: {division_result}")
