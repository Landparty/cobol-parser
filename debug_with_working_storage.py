"""Test with the exact source from debug_division_types.py."""
from cobolparser import CobolParser
from cobolparser.plugins.core import ErrorRecoveryMode

# Exact source from debug_division_types.py
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

parser = CobolParser()
result = parser.parse(source)

print("=== Parse Result ===")
print(f"Success: {result.success}")
print(f"Divisions: {len(result.ast.divisions)}")
print(f"_divisions keys: {list(result.ast._divisions.keys())}")

# Get each division
proc_div = result.ast.get_division("PROCEDURE")
print(f"\nProcedure Division: {proc_div}")
if proc_div:
    print(f"Has _sections? {hasattr(proc_div, '_sections')}")
    if hasattr(proc_div, '_sections'):
        print(f"Sections: {proc_div._sections}")
    print(f"Has paragraphs? {hasattr(proc_div, 'paragraphs')}")
    if hasattr(proc_div, 'paragraphs'):
        print(f"Paragraphs: {proc_div.paragraphs}")
