import sys
sys.path.insert(0, r'c:\Users\sam94\workspace\cobol-parser')

from cobolparser import CobolParser
from cobolparser.lexer import TokenType

cobol_code = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 COUNTER PIC 9(2).
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM VARYING COUNTER FROM 1 BY 1
               UNTIL COUNTER > 10
               CALL "INNER-PROG" USING COUNTER
           END-PERFORM.
           STOP RUN.
"""

# First, check what tokens are generated
from cobolparser.lexer import CobolLexer
lexer = CobolLexer(cobol_code)
tokens = list(lexer.tokenize())

print("Tokens around PROCEDURE DIVISION:")
for i, token in enumerate(tokens):
    if token.value and 'PROCEDURE' in str(token.value).upper():
        # Print tokens around this one
        start = max(0, i - 3)
        end = min(len(tokens), i + 4)
        for j in range(start, end):
            marker = " <---" if j == i else ""
            print(f"  Token {j}: {tokens[j].type.name:30} | {tokens[j].value!r:20} {marker}")
        print()

# Now parse and see what happens
print("\n" + "="*60)
print("Parsing...")
parser = CobolParser()
result = parser.parse(cobol_code)

print(f"Parse success: {result.success}")
print(f"Program: {result.ast.program_name if result.ast else 'None'}")
if result.ast:
    print(f"Divisions: {[d.division_name for d in result.ast.divisions]}")
    for div in result.ast.divisions:
        print(f"  Division: {div.division_name}")
        if div.division_name == 'DATA':
            print(f"    Sections: {[s.section_name for s in div.sections]}")
        if div.division_name == 'PROCEDURE':
            print(f"    Sections: {[s.section_name for s in div.sections]}")
