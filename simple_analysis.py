#!/usr/bin/env python
"""Analyze call_statements_basic.cbl in detail"""

import re
from cobolparser import CobolParser
from cobolparser.models.statements import CallStatement

filename = 'tests/samples/call_statements_basic.cbl'
with open(filename, 'r') as f:
    lines = f.readlines()

# Find CALL keywords with line numbers
for i, line in enumerate(lines, 1):
    if 'CALL' in line.upper() and not line.strip().startswith('*'):
        print(f"Line {i}: {line.rstrip()}")

# Now parse
parser = CobolParser()
with open(filename, 'r') as f:
    code = f.read()

result = parser.parse(code)
all_stmts = result.ast.get_all_statements()
calls = [s for s in all_stmts if isinstance(s, CallStatement)]

print(f"\n\nParsed {len(calls)} CALL statements:")
for call in calls:
    print(f"  - {call.called_program}")
