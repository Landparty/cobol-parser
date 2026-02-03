"""Debug script to check division names."""
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

print(f"\nDivisions in AST: {result.ast.divisions}")
print(f"Number of divisions: {len(result.ast.divisions)}")

# Check the _divisions dict directly
print(f"\nDirect _divisions dict:")
for key, value in result.ast._divisions.items():
    print(f"  Key: {repr(key)}, Value: {value}")
    if hasattr(value, 'division_name'):
        print(f"    division_name attr: {value.division_name}")

# Now try to get divisions by different names
print(f"\nTrying lookups:")
print(f"get_division('PROCEDURE'): {result.ast.get_division('PROCEDURE')}")
print(f"get_division('IDENTIFICATION'): {result.ast.get_division('IDENTIFICATION')}")
print(f"get_division('DATA'): {result.ast.get_division('DATA')}")

# Check if the division has a division_type or type attribute
proc = result.ast.divisions[2]  # Should be procedure division (last one based on debug_division_types.py)
print(f"\nProcedure division object: {proc}")
print(f"Type: {type(proc)}")
print(f"Attributes: {[a for a in dir(proc) if not a.startswith('_')]}")
