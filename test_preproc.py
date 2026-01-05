"""Debug preprocessor."""

from cobolparser.preprocess import normalize_fixed_format

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

normalized = normalize_fixed_format(test_code)
print("Normalized code:")
print(normalized)
print()
print("First 100 chars:")
print(repr(normalized[:100]))
