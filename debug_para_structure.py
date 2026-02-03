"""Debug script to understand paragraph structure."""
from cobolparser import CobolParser
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
    PARA-MIDDLE.
        DISPLAY 'Middle'.
    PARA-END.
        DISPLAY 'End'.
"""

parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
result = parser.parse(source)

print("=== Parse Result ===")
print(f"Success: {result.success}")
if result.errors:
    print(f"Errors: {result.errors}")

proc_div = result.ast.get_division("PROCEDURE")
print(f"\nProcedure Division: {proc_div}")
print(f"Procedure Division Type: {type(proc_div)}")
print(f"Has sections attr? {hasattr(proc_div, 'sections')}")
if hasattr(proc_div, 'sections'):
    print(f"Sections: {proc_div.sections}")
    print(f"Number of sections: {len(proc_div.sections)}")
    for sec in proc_div.sections:
        print(f"  - Section: {sec}")
        if hasattr(sec, 'section_name'):
            print(f"    Name: {sec.section_name}")

print(f"\nHas paragraphs attr? {hasattr(proc_div, 'paragraphs')}")
if hasattr(proc_div, 'paragraphs'):
    print(f"Paragraphs: {proc_div.paragraphs}")

print(f"\nProcedure division attributes: {dir(proc_div)}")
