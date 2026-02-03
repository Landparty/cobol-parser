"""Debug detailed parsing of PERFORM statement."""
from cobolparser import CobolParser
from cobolparser.lexer import CobolLexer
from cobolparser.plugins.core import ErrorRecoveryMode
from cobolparser.core.token_stream import TokenStream

source_line = "PERFORM PARA-A THRU PARA-B 5 TIMES."

# First tokenize just the statement line
lexer = CobolLexer(source_line)
tokens = lexer.tokenize()

print("Tokens:")
for i, token in enumerate(tokens):
    print(f"{i}: {token.type.name:20} = {repr(token.value)}")

# Now tokenize the full program
full_source= """
    IDENTIFICATION DIVISION.
    PROGRAM-ID. TEST-THRU-TIMES.
    PROCEDURE DIVISION.
    MAIN-PARA.
        PERFORM PARA-A THRU PARA-B 5 TIMES.
        STOP RUN.
    PARA-A.
        DISPLAY 'A'.
    PARA-B.
        DISPLAY 'B'.
"""

parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
result = parser.parse(full_source)

proc_div = result.ast.get_division("PROCEDURE")
if proc_div:
    main_para = next((s for s in proc_div.sections if s.section_name == "MAIN-PARA"), None)
    if main_para:
        for child in main_para.children:
            print(f"\nChild: {child}")
            if hasattr(child, 'to_dict'):
                d = child.to_dict()
                if 'statement_type' in d:
                    print(f"  Statement type: {d['statement_type']}")
                    print(f"  Full dict: {d}")
