"""Simple test of PERFORM THRU parsing."""

from cobolparser.parser import CobolParser
from cobolparser.plugins.core import ErrorRecoveryMode

# Use the exact format from the test samples
source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTTHRU.
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
print(f"Errors: {[str(e) for e in result.errors]}")

if result.ast:
    proc_div = result.ast.get_division("PROCEDURE")
    if proc_div:
        print(f"\nFound {len(proc_div.sections)} sections")
        for section in proc_div.sections:
            print(f"\nSection: {section.section_name}")
            for child in section.children:
                if hasattr(child, 'target_paragraph'):
                    print(f"  PERFORM: target={child.target_paragraph}, thru={child.thru_paragraph}")
