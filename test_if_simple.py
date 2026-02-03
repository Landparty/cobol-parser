#!/usr/bin/env python3
"""Test IF statement parsing in procedure division."""

import sys
sys.path.insert(0, '.')

from cobolparser import CobolParser

code = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           IF 1 = 1
              DISPLAY 'ONE'
           END-IF.
           STOP RUN.
"""

parser = CobolParser()
result = parser.parse(code)

if result.ast:
    print("Program ID:", result.ast.program_name)
    proc = result.ast.get_division("PROCEDURE")
    if proc:
        print(f"\nPROCEDURE Division:")
        print(f"  paragraphs: {len(proc.paragraphs)}")
        for i, para in enumerate(proc.paragraphs):
            print(f"    Para[{i}]: name='{para.paragraph_name}', statements={len(para.statements)}")
            for j, stmt in enumerate(para.statements):
                print(f"      Stmt[{j}]: {type(stmt).__name__}")
else:
    print("Parsing failed!")
    for error in result.errors:
        print(f"  Error: {error}")
