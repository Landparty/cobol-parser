#!/usr/bin/env python
"""Check parsed CALL statements in edge cases file"""

from cobolparser import CobolParser
from cobolparser.models.statements import CallStatement

parser = CobolParser()
with open('tests/samples/call_edge_cases_advanced.cbl', 'r') as f:
    code = f.read()

result = parser.parse(code)
all_stmts = result.ast.get_all_statements()
calls = [s for s in all_stmts if isinstance(s, CallStatement)]

print(f"Parsed {len(calls)} CALL statements:")
for i, call in enumerate(calls, 1):
    print(f"{i:2d}. {call.called_program}")

expected = [
    "SIMPLE-CALC",
    "WS-CHILD-PROG",  # line 86
    "BATCH-PROCESSOR",
    "WS-CHILD-PROG",  # line 117
    "WS-FALLBACK-SVC",
    "WS-PARENT-PROG",
    "WS-CHILD-PROG",  # line 139
    "WS-GRANDCHILD-PROG",
    "GET-STATUS",
    "CALCULATE-VALUE",
    "GET-MESSAGE",
]

print(f"\nExpected: {len(expected)} (excluding line 72 dynamic with BY VALUE - might not be a distinct count)")
