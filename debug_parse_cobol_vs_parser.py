"""Test parse_cobol vs CobolParser.parse() behavior."""
from cobolparser import CobolParser
from cobolparser.parser import parse_cobol

# Simple source with procedures
source = """
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
PROCEDURE DIVISION.
MAIN-PARA.
    DISPLAY 'MAIN'.
SUB-PARA.
    DISPLAY 'SUB'.
"""

print("=== Using parse_cobol() ===")
result1 = parse_cobol(source)
print(f"Success: {result1.success}")
proc_div1 = result1.ast.get_division("PROCEDURE")
print(f"Procedure Division: {proc_div1}")
print(f"Sections: {len(proc_div1.sections)}")
print(f"Paragraphs: {len(proc_div1.paragraphs)}")
if proc_div1.sections:
    print(f"First section name: {proc_div1.sections[0].section_name}")

print("\n=== Using CobolParser.parse() ===")
parser = CobolParser()
result2 = parser.parse(source)
print(f"Success: {result2.success}")
proc_div2 = result2.ast.get_division("PROCEDURE")
print(f"Procedure Division: {proc_div2}")
print(f"Sections: {len(proc_div2.sections)}")
print(f"Paragraphs: {len(proc_div2.paragraphs)}")
if proc_div2.sections:
    print(f"First section name: {proc_div2.sections[0].section_name}")
