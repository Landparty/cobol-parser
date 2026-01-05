"""Comprehensive test for ENTRY statement parsing."""

from cobolparser.parser import CobolParser

# Test COBOL code with ENTRY statement including USING clause
test_code = """IDENTIFICATION DIVISION.
PROGRAM-ID. TESTPROG.
DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-VAR1 PIC X(10).
01  WS-VAR2 PIC X(10).
01  WS-VAR3 PIC X(10).
PROCEDURE DIVISION.
    ENTRY 'DLITCBL' USING WS-VAR1 WS-VAR2 WS-VAR3.
    DISPLAY 'Hello'.
    STOP RUN.
"""

# Parse the code with free_form=True
parser = CobolParser(free_form=True)
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
            print(f"\n  Section: {section.section_name}")
            for child in section.children:
                child_type = getattr(child, 'statement_type', getattr(child, 'node_type', 'N/A'))
                print(f"    Child: {child.node_type} - {child_type}")
                
                if hasattr(child, 'statement_type') and 'ENTRY' in str(child.statement_type).upper():
                    entry_found = True
                    print("    [OK] ENTRY statement found!")
                    
                    # Check entry details
                    if hasattr(child, 'entry_name'):
                        print(f"      Entry name: {child.entry_name}")
                    
                    if hasattr(child, 'using_parameters'):
                        print(f"      USING parameters: {child.using_parameters}")
                        print(f"      Number of parameters: {len(child.using_parameters)}")
                        
                        # Verify the parameters
                        expected_params = ['WS-VAR1', 'WS-VAR2', 'WS-VAR3']
                        if child.using_parameters == expected_params:
                            print("      [OK] Parameters match expected values!")
                        else:
                            print(f"      [FAIL] Parameters don't match. Expected: {expected_params}, Got: {child.using_parameters}")
                    
                    # Test to_dict() method
                    entry_dict = child.to_dict()
                    print(f"\n      Dictionary representation:")
                    print(f"        statement_type: {entry_dict.get('statement_type')}")
                    print(f"        entry_name: {entry_dict.get('entry_name')}")
                    print(f"        using_parameters: {entry_dict.get('using_parameters')}")
        
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
else:
    print("\n[OK] No parsing errors!")
