#!/usr/bin/env python
"""Debug PERFORM THRU parsing."""

from cobolparser.parser import CobolParser
from cobolparser.plugins.core import ErrorRecoveryMode
from cobolparser.models.program import CobolDivision
from cobolparser.parsers.divisions.factory import DivisionParserFactory

# Patch CobolParser to see what's happening
original_parse_method = CobolParser.parse

def new_parse(self, source, filename="<string>"):
    # Call original to see if we can intercept the division parsing
    print("[DEBUG] Starting parse...")
    result = original_parse_method(self, source, filename)
    print(f"[DEBUG] Parse complete. AST divisions: {len(getattr(result.ast, 'divisions', []))}")
    if result.ast and hasattr(result.ast, 'divisions'):
        for div in result.ast.divisions:
            print(f"[DEBUG]   - {div.division_name}")
    return result

CobolParser.parse = new_parse

# Also patch the factory to see what it returns
factory = DivisionParserFactory()
original_find = factory.find_parser

def new_find(stream):
    parser = original_find(stream)
    print(f"[DEBUG FACTORY] find_parser returned: {parser}")
    return parser

factory.find_parser = new_find

source = """
    IDENTIFICATION DIVISION.
    PROGRAM-ID. TEST-THRU.
    PROCEDURE DIVISION.
    MAIN-PARA.
        STOP RUN.
"""

parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
result = parser.parse(source)

print("\n[FINAL RESULT]")
print("Parse success:", result.success)
print("Errors:", result.errors)
if result.ast:
    print("Program divisions:", len(result.ast.divisions))
    for div in result.ast.divisions:
        print(f"  - {div.division_name}")




