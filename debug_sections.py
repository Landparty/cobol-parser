from cobolparser.parser import CobolParser

source = """IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-VAR PIC X(10).
PROCEDURE DIVISION.
MAIN-PARAGRAPH.
    DISPLAY 'Main'.
SUB-PARA.
    DISPLAY 'Sub'.
"""

parser = CobolParser(free_form=True)
result = parser.parse(source)

print(f'Parse success: {result.success}')
print(f'Parse errors: {result.errors}')

if result.ast:
    proc_div = result.ast.get_division('PROCEDURE')
    if proc_div:
        print(f'\nPROCEDURE Division:')
        print(f'  Sections: {[s.section_name for s in proc_div.sections]}')
        print(f'  Paragraphs: {[p.paragraph_name for p in proc_div.paragraphs]}')
        
        for section in proc_div.sections:
            print(f'\n  Section: {section.section_name}')
            print(f'    Children: {len(section.children)}')
            print(f'    Paragraphs in section: {[p.paragraph_name for p in section.paragraphs]}')
            for child in section.children:
                if hasattr(child, 'paragraph_name'):
                    print(f'      - Paragraph: {child.paragraph_name}')
                elif hasattr(child, 'statement_type'):
                    print(f'      - Statement: {child.statement_type}')
