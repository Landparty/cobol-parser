#!/usr/bin/env python3
"""
Analyze CALL statements in real-world examples to identify parsing gaps
"""

from cobolparser import CobolParser
from cobolparser.models.statements import CallStatement
import os
import glob
import re

def count_call_keywords(code):
    """Count CALL keywords in raw code"""
    # Count standalone CALL keywords
    pattern = r'\bCALL\b'
    matches = re.findall(pattern, code, re.IGNORECASE)
    return len(matches)

def analyze_samples():
    parser = CobolParser()
    call_samples = sorted(glob.glob('tests/samples/call_*.cbl'))
    
    print("=" * 80)
    print("CALL STATEMENT PARSING ANALYSIS")
    print("=" * 80)
    
    total_keywords = 0
    total_parsed = 0
    
    results = []
    
    for sample_file in call_samples:
        try:
            with open(sample_file, 'r', encoding='utf-8') as f:
                code = f.read()
            
            # Count keywords in raw code
            keyword_count = count_call_keywords(code)
            total_keywords += keyword_count
            
            # Parse and count CallStatements
            result = parser.parse(code)
            all_stmts = result.ast.get_all_statements()
            calls = [s for s in all_stmts if isinstance(s, CallStatement)]
            parsed_count = len(calls)
            total_parsed += parsed_count
            
            # Calculate difference
            missed = keyword_count - parsed_count
            
            filename = os.path.basename(sample_file)
            results.append({
                'file': filename,
                'keywords': keyword_count,
                'parsed': parsed_count,
                'missed': missed,
                'coverage': f"{(parsed_count/keyword_count*100):.1f}%" if keyword_count > 0 else "0%"
            })
            
        except Exception as e:
            print(f"ERROR parsing {os.path.basename(sample_file)}: {e}")
    
    # Print results
    print(f"\n{'File':<40} {'Keywords':<10} {'Parsed':<10} {'Missed':<10} {'Coverage':<10}")
    print("-" * 80)
    
    for r in results:
        print(f"{r['file']:<40} {r['keywords']:<10} {r['parsed']:<10} {r['missed']:<10} {r['coverage']:<10}")
    
    print("-" * 80)
    print(f"{'TOTAL':<40} {total_keywords:<10} {total_parsed:<10} {total_keywords-total_parsed:<10} {(total_parsed/total_keywords*100):.1f}%")
    
    print("\n" + "=" * 80)
    print("FILES WITH MISSING CALL STATEMENTS:")
    print("=" * 80)
    
    for r in results:
        if r['missed'] > 0:
            print(f"\n{r['file']}: {r['missed']} CALL statements not parsed")
            print(f"  Parsed: {r['parsed']}/{r['keywords']} ({r['coverage']})")

if __name__ == '__main__':
    analyze_samples()
