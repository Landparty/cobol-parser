#!/usr/bin/env python3
"""
Debug script to identify which specific CALL statements are missing
"""

from cobolparser import CobolParser
from cobolparser.models.statements import CallStatement
import re

def extract_call_lines(code):
    """Extract CALL statements from raw code with line numbers"""
    lines = code.split('\n')
    calls = []
    
    for i, line in enumerate(lines, 1):
        # Look for CALL keyword
        if re.search(r'\bCALL\b', line, re.IGNORECASE):
            # Extract the content after CALL
            match = re.search(r'CALL\s+(.+?)(?:ON\s+EXCEPTION|NOT\s+ON\s+EXCEPTION|$)', line, re.IGNORECASE)
            if match:
                call_text = match.group(1).strip()
                calls.append({
                    'line': i,
                    'text': line.strip(),
                    'call_part': call_text[:60] + '...' if len(call_text) > 60 else call_text
                })
    
    return calls

def analyze_file(filename):
    print(f"\n{'='*80}")
    print(f"ANALYZING: {filename}")
    print(f"{'='*80}")
    
    parser = CobolParser()
    
    with open(filename, 'r', encoding='utf-8') as f:
        code = f.read()
    
    # Get all CALL statements from raw code
    raw_calls = extract_call_lines(code)
    print(f"\nFound {len(raw_calls)} CALL keywords in source code:")
    
    # Parse and get CallStatements
    result = parser.parse(code)
    all_stmts = result.ast.get_all_statements()
    parsed_calls = [s for s in all_stmts if isinstance(s, CallStatement)]
    
    print(f"Parser found {len(parsed_calls)} CallStatement objects")
    
    # Print raw CALL statements
    print(f"\nRaw CALL statements (from keyword search):")
    print("-" * 80)
    for call in raw_calls[:15]:  # Show first 15
        print(f"  Line {call['line']:3d}: {call['call_part']}")
    
    if len(raw_calls) > 15:
        print(f"  ... and {len(raw_calls)-15} more")
    
    # Print parsed CALL statements
    print(f"\nParsed CALL statements (from parser):")
    print("-" * 80)
    for i, call in enumerate(parsed_calls[:15], 1):  # Show first 15
        prog = call.called_program if hasattr(call, 'called_program') else 'UNKNOWN'
        print(f"  [{i}] Program: {prog}")
        if hasattr(call, 'using_parameters') and call.using_parameters:
            print(f"       Parameters: {len(call.using_parameters)} items")
        if hasattr(call, 'on_exception') and call.on_exception:
            print(f"       Has exception handler")
    
    if len(parsed_calls) > 15:
        print(f"  ... and {len(parsed_calls)-15} more")
    
    # Identify patterns in missed CALL statements
    print(f"\nPATTERN ANALYSIS - Likely reasons for {len(raw_calls)-len(parsed_calls)} missed CALL statements:")
    print("-" * 80)
    
    patterns = {
        'ON EXCEPTION': 0,
        'NOT ON EXCEPTION': 0,
        'RETURNING': 0,
        'BY REFERENCE': 0,
        'BY VALUE': 0,
        'IF condition before': 0,
        'Inside PERFORM': 0,
        'Multiple lines': 0
    }
    
    for call in raw_calls:
        text = call['text'].upper()
        if 'ON EXCEPTION' in text:
            patterns['ON EXCEPTION'] += 1
        if 'NOT ON EXCEPTION' in text:
            patterns['NOT ON EXCEPTION'] += 1
        if 'RETURNING' in text:
            patterns['RETURNING'] += 1
        if 'BY REFERENCE' in text:
            patterns['BY REFERENCE'] += 1
        if 'BY VALUE' in text:
            patterns['BY VALUE'] += 1
        if 'IF' in code.split('\n')[call['line']-2]:
            patterns['IF condition before'] += 1
    
    for pattern, count in patterns.items():
        if count > 0:
            print(f"  {pattern:<25} : {count:>3} occurrences")

if __name__ == '__main__':
    files = [
        'tests/samples/call_statements_basic.cbl',
        'tests/samples/call_statements_advanced.cbl',
        'tests/samples/call_banking_system.cbl',
    ]
    
    for f in files:
        try:
            analyze_file(f)
        except Exception as e:
            print(f"ERROR: {e}")
