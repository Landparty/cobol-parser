#!/usr/bin/env python
"""Deep analysis of missing CALL patterns"""

import re
from cobolparser import CobolParser
from cobolparser.models.statements import CallStatement

def analyze_file(filename):
    """Detailed analysis of parsing gaps in a specific file"""
    with open(filename, 'r') as f:
        code = f.read()
    
    # Find all CALL statements in code with context
    call_pattern = r'(?:^|\s)CALL\s+(\S+)(.{0,200})'
    calls_in_code = []
    for match in re.finditer(call_pattern, code, re.IGNORECASE | re.MULTILINE):
        prog = match.group(1)
        context = match.group(2).strip()[:60]
        calls_in_code.append((prog, context))
    
    # Parse and find what was actually captured
    parser = CobolParser()
    result = parser.parse(code)
    all_stmts = result.ast.get_all_statements()
    parsed_calls = [s for s in all_stmts if isinstance(s, CallStatement)]
    parsed_progs = {c.called_program for c in parsed_calls}
    
    print(f"\n{'='*80}")
    print(f"FILE: {filename}")
    print(f"{'='*80}")
    print(f"\nFound {len(calls_in_code)} CALL statements in code")
    print(f"Parsed {len(parsed_calls)} CALL statements\n")
    
    # Show which calls were missed
    missed = []
    for prog, context in calls_in_code:
        if prog not in parsed_progs and f'"{prog}"' not in parsed_progs:
            missed.append((prog, context))
    
    if missed:
        print(f"MISSED CALLS ({len(missed)}):")
        for prog, context in missed[:10]:  # Show first 10
            print(f"  - {prog}: {context}")
    
    return len(calls_in_code), len(parsed_calls)

# Analyze poorly performing files
files = [
    'tests/samples/call_statements_basic.cbl',
    'tests/samples/call_edge_cases_advanced.cbl',
    'tests/samples/call_banking_system.cbl',
]

total_keywords = 0
total_parsed = 0

for f in files:
    try:
        k, p = analyze_file(f)
        total_keywords += k
        total_parsed += p
    except Exception as e:
        print(f"Error analyzing {f}: {e}")

print(f"\n{'='*80}")
print(f"TOTALS: {total_parsed}/{total_keywords} parsed ({100*total_parsed/total_keywords:.1f}%)")
