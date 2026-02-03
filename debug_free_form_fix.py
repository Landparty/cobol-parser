"""Test if passing free_form=True fixes the parsing."""
from cobolparser import CobolParser
from cobolparser.plugins.core import ErrorRecoveryMode

# Indented free-form source (NO fixed-format indentation)
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

print("=== Test 1: free_form=False (default) ===")
parser1 = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL, free_form=False)
result1 = parser1.parse(source)
print(f"Success: {result1.success}")
print(f"Divisions: {len(result1.ast.divisions)}")
if result1.errors:
    print(f"Errors: {result1.errors[:2]}")  # First 2 errors

print("\n=== Test 2: free_form=True ===")
parser2 = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL, free_form=True)
result2 = parser2.parse(source)
print(f"Success: {result2.success}")
print(f"Divisions: {len(result2.ast.divisions)}")
if result2.errors:
    print(f"Errors: {result2.errors[:2]}")  # First 2 errors

# If divisions are found, check if we can get PROCEDURE division
if len(result2.ast.divisions) > 0:
    proc_div = result2.ast.get_division("PROCEDURE")
    print(f"Procedure Division: {proc_div}")
