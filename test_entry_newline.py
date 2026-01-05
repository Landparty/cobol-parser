"""Test with newline after opening triple quote."""

from cobolparser.parser import CobolParser

# Match the exact format from the unit tests
test_code = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TESTPROG.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-VAR PIC X(10).
        PROCEDURE DIVISION.
            ENTRY 'DLITCBL' USING WS-VAR.
            DISPLAY 'Hello'.
            STOP RUN.
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
