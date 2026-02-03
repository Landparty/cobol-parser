"""Test with indented free-form COBOL (NO fixed-format indentation)."""
from cobolparser import CobolParser
from cobolparser.plugins.core import ErrorRecoveryMode

# Indented free-form source (no 7-space offset)
source1 = """IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
PROCEDURE DIVISION.
MAIN-PARA.
    DISPLAY 'HELLO'.
    STOP RUN.
"""

print("=== Test 1: Free-form with DATA DIVISION ===")
parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
result = parser.parse(source1)
print(f"Success: {result.success}")
print(f"Divisions: {len(result.ast.divisions)}")
print(f"Keys: {list(result.ast._divisions.keys())}")

# Now try without DATA DIVISION
source2 = """IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
PROCEDURE DIVISION.
MAIN-PARA.
    DISPLAY 'HELLO'.
    STOP RUN.
"""

print("\n=== Test 2: Free-form without DATA DIVISION ===")
result2 = parser.parse(source2)
print(f"Success: {result2.success}")
print(f"Divisions: {len(result2.ast.divisions)}")
print(f"Keys: {list(result2.ast._divisions.keys())}")
