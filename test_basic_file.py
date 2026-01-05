#!/usr/bin/env python
"""Test parsing the basic CALL file"""

from cobolparser import CobolParser
from cobolparser.models.statements import CallStatement

parser = CobolParser()
with open('tests/samples/call_statements_basic.cbl', 'r') as f:
    code = f.read()

result = parser.parse(code)
all_stmts = result.ast.get_all_statements()
calls = [s for s in all_stmts if isinstance(s, CallStatement)]

print(f"Total CALL statements parsed: {len(calls)}")
for call in calls:
    prog = call.called_program
    params = len(call.using_parameters or [])
    print(f"  - {prog}: {params} parameters")
    if call.using_parameters:
        for p in call.using_parameters:
            print(f"      * {p.name} ({p.passing_mode})")
