"""Debug preprocessor with newline."""

from cobolparser.preprocess import normalize_fixed_format

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

print("Input code:")
print(repr(test_code[:100]))
print()

normalized = normalize_fixed_format(test_code)
print("Normalized code:")
print(repr(normalized[:200]))
print()
print("Full normalized:")
print(normalized)
