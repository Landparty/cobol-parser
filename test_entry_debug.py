"""Debug test to see what the preprocessor does."""

from cobolparser.parser import CobolParser

# Test COBOL code with ENTRY statement
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

# Check preprocessed code
from cobolparser.preprocess import normalize_fixed_format

normalized = normalize_fixed_format(test_code)
print("Normalized code:")
print(repr(normalized[:200]))
print()

result = parser.parse(test_code)

if result and result.ast:
    print("[OK] Parsing succeeded")
else:
    print("[FAIL] Parsing failed")
    if result and result.errors:
        print(f"Errors ({len(result.errors)}):")
        for error in result.errors:
            print(f"  - {error}")
