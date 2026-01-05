"""Test ENTRY parsing with actual COBOL file content."""

from cobolparser.parser import CobolParser

# Use actual COBOL format from the file
test_code = """000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. TESTPROG.
000300 DATA DIVISION.
000400 WORKING-STORAGE SECTION.
000500 01  WS-VAR PIC X(10).
000600 PROCEDURE DIVISION.
000700     ENTRY 'DLITCBL' USING WS-VAR.
000800     DISPLAY 'Hello'.
000900     STOP RUN.
"""

# Parse the code
parser = CobolParser()
result = parser.parse(test_code)

# Check if parsing succeeded
if result and result.ast:
    program = result.ast
    print("[OK] Parsing succeeded")
    print(f"Program name: {program.program_name}")
    
    # Check for ENTRY in the AST
    proc_div = program.get_division("PROCEDURE")
    if proc_div:
        print(f"[OK] Found PROCEDURE division")
        print(f"  Sections: {len(proc_div.sections)}")
        
        # Look for ENTRY statement
        entry_found = False
        for section in proc_div.sections:
            print(f"  Section: {section.section_name}")
            for child in section.children:
                child_type = getattr(child, 'statement_type', getattr(child, 'node_type', 'N/A'))
                print(f"    Child: {child.node_type} - {child_type}")
                if hasattr(child, 'statement_type') and 'ENTRY' in str(child.statement_type).upper():
                    entry_found = True
                    print("    [OK] ENTRY statement found!")
        
        if not entry_found:
            print("  [FAIL] ENTRY statement NOT found in AST")
    else:
        print("[FAIL] No PROCEDURE division found")
else:
    print("[FAIL] Parsing failed")
    
# Print errors if any
if result and result.errors:
    print(f"\nErrors ({len(result.errors)}):")
    for error in result.errors:
        print(f"  - {error}")
