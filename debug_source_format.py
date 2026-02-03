#!/usr/bin/env python3
"""Debug - check raw source formatting."""

source = """
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
PROCEDURE DIVISION.
    PERFORM 1 TIMES
        CALL "SUBPROGRAM"
    END-PERFORM.
    STOP RUN.
"""

print("=== Source with markers ===")
lines = source.split('\n')
for i, line in enumerate(lines):
    # Mark columns
    print(f"L{i:2d} [{len(line):2d}] |{line}|")
    if len(line) > 0:
        # Show character positions
        print(f"      ", end="")
        for j, ch in enumerate(line[:min(len(line), 50)]):
            if ch == ' ':
                print("·", end="")
            else:
                print(ch, end="")
        print()
