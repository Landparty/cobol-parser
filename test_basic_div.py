#!/usr/bin/env python
"""Test basic division parsing."""

from cobolparser import CobolParser

source = '''
IDENTIFICATION DIVISION.
PROGRAM-ID. SIMPLE.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 X PIC 9.
PROCEDURE DIVISION.
    DISPLAY 'HELLO'.
    STOP RUN.
'''

parser = CobolParser()
result = parser.parse(source)
print('Success:', result.success)
print('Errors:', result.errors)
if result.ast:
    print('Program name:', result.ast.program_name)
    print('Divisions:', len(result.ast.divisions))
    for div in result.ast.divisions:
        print(f'  Division: {div.division_name}')
        if hasattr(div, 'sections'):
            for sec in div.sections:
                print(f'    Section: {sec.section_name if hasattr(sec, "section_name") else sec}')
