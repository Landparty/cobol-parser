from cobolparser.parser import CobolParser
from cobolparser.plugins.core import ErrorRecoveryMode

source = """IDENTIFICATION DIVISION.
PROGRAM-ID. TEST-THRU.
PROCEDURE DIVISION.
MAIN-PARA.
    PERFORM PARA-START THRU PARA-END.
    STOP RUN.
PARA-START.
    DISPLAY 'Start'.
PARA-MIDDLE.
    DISPLAY 'Middle'.
PARA-END.
    DISPLAY 'End'.
"""

parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL, free_form=True)
result = parser.parse(source)

print(f'Parse result success: {result.success}')
print(f'Parse errors: {result.errors}')
print(f'AST exists: {result.ast is not None}')

if result.ast:
    proc_div = result.ast.get_division('PROCEDURE')
    print(f'PROCEDURE division exists: {proc_div is not None}')
    
    if proc_div:
        sections = proc_div.sections
        paragraphs = proc_div.paragraphs
        print(f'Number of sections: {len(sections)}')
        print(f'Number of paragraphs: {len(paragraphs)}')
        
        if sections:
            print(f'Section names: {[s.section_name for s in sections]}')
            for section in sections:
                print(f'  Section {section.section_name} has {len(section.children)} children')
                for child in section.children:
                    node_type = getattr(child, 'node_type', 'unknown')
                    name = getattr(child, 'paragraph_name', getattr(child, 'statement_type', '?'))
                    print(f'    - {type(child).__name__}: {node_type} ({name})')
        
        if paragraphs:
            print(f'Paragraph names: {[p.paragraph_name for p in paragraphs]}')
