#!/usr/bin/env python3
"""Accurate CALL statement parsing analysis - counts only actual statements"""

from cobolparser import CobolParser
from cobolparser.models.statements import CallStatement
import os
import glob
import re

def count_actual_calls(code):
    """Count actual CALL statements (not in comments/identifiers)"""
    # Look for CALL statements at procedure level (not in comments or data names)
    # Pattern: whitespace + CALL + identifier/literal (statement level)
    pattern = r'^\s{11,}CALL\s+(?:\'[^\']+\'|[A-Z][A-Z0-9\-]*)'
    matches = re.findall(pattern, code, re.IGNORECASE | re.MULTILINE)
    return len(matches)

def analyze_samples():
    parser = CobolParser()
    call_samples = sorted(glob.glob('tests/samples/call_*.cbl'))
    
    print("=" * 80)
    print("ACCURATE CALL STATEMENT PARSING ANALYSIS")
    print("=" * 80)
    
    total_actual = 0
    total_parsed = 0
    
    results = []
    
    for sample_file in call_samples:
        try:
            with open(sample_file, 'r', encoding='utf-8') as f:
                code = f.read()
            
            # Count actual CALL statements (statements, not keywords in comments/data)
            actual_count = count_actual_calls(code)
            total_actual += actual_count
            
            # Parse and count CallStatements
            result = parser.parse(code)
            all_stmts = result.ast.get_all_statements()
            calls = [s for s in all_stmts if isinstance(s, CallStatement)]
            parsed_count = len(calls)
            total_parsed += parsed_count
            
            # Calculate coverage
            missed = actual_count - parsed_count
            
            filename = os.path.basename(sample_file)
            results.append({
                'file': filename,
                'actual': actual_count,
                'parsed': parsed_count,
                'missed': missed,
                'coverage': f"{(parsed_count/actual_count*100):.1f}%" if actual_count > 0 else "0%"
            })
            
        except Exception as e:
            print(f"ERROR parsing {os.path.basename(sample_file)}: {e}")
    
    # Print results
    print(f"\n{'File':<40} {'Actual':<10} {'Parsed':<10} {'Missed':<10} {'Coverage':<10}")
    print("-" * 80)
    
    for r in results:
        print(f"{r['file']:<40} {r['actual']:<10} {r['parsed']:<10} {r['missed']:<10} {r['coverage']:<10}")
    
    print("-" * 80)
    print(f"{'TOTAL':<40} {total_actual:<10} {total_parsed:<10} {total_actual-total_parsed:<10} {(total_parsed/total_actual*100):.1f}%")
    
    print("\n" + "=" * 80)
    print("FILES WITH GAPS:")
    print("=" * 80)
    
    for r in results:
        if r['missed'] > 0:
            print(f"\n{r['file']}: {r['missed']} statements not parsed ({r['coverage']})")

if __name__ == '__main__':
    analyze_samples()
