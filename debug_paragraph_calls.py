from cobolparser.parser import CobolParser

# Patch to debug
original_method = CobolParser.parse_paragraph_or_statement

call_count = [0]
def debug_wrapper(self):
    call_count[0] += 1
    print(f'parse_paragraph_or_statement call #{call_count[0]}')
    if self.current_token:
        print(f'  current token: {self.current_token.value}')
    return original_method(self)

CobolParser.parse_paragraph_or_statement = debug_wrapper

source = """IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
PROCEDURE DIVISION.
MAIN-PARAGRAPH.
    DISPLAY 'Main'.
SUB-PARA.
    DISPLAY 'Sub'.
"""

parser = CobolParser(free_form=True)
result = parser.parse(source)

print(f'\nFinal sections: {[s.section_name for s in result.ast.get_division("PROCEDURE").sections]}')
