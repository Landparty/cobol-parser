"""Debug script to test PERFORM THRU parsing."""

from cobolparser.parser import CobolParser
from cobolparser.plugins.core import ErrorRecoveryMode

source = """
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST-THRU.
PROCEDURE DIVISION.
MAIN-PARA.
    PERFORM PARA-START THRU PARA-END.
    STOP RUN.
PARA-START.
    DISPLAY 'Start'.
PARA-END.
    DISPLAY 'End'.
"""

parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
result = parser.parse(source)

print(f"Parse success: {result.success}")
print(f"Errors: {result.errors}")

if result.ast:
    proc_div = result.ast.get_division("PROCEDURE")
    if proc_div:
        print(f"\nSections: {len(proc_div.sections)}")
        for section in proc_div.sections:
            print(f"\n  Section: {section.section_name}")
            print(f"  Children: {len(section.children)}")
            for child in section.children:
                print(f"    - {child.statement_type}")
                if hasattr(child, 'target_paragraph'):
                    print(f"      target_paragraph: {child.target_paragraph}")
                    print(f"      thru_paragraph: {child.thru_paragraph}")
                    print(f"      perform_type: {child.perform_type}")
