#!/usr/bin/env python3
"""Analyze coverage data for Phase 3 planning."""

import json
import os

coverage_file = 'coverage.json'
if not os.path.exists(coverage_file):
    print(f"Coverage file {coverage_file} not found")
    exit(1)

with open(coverage_file) as f:
    data = json.load(f)

print(f"Overall Coverage: {data['totals']['percent_covered']:.1f}%")
print(f"Total Statements: {data['totals']['num_statements']}")
print(f"Covered Lines: {data['totals']['covered_lines']}")
print(f"Missing Lines: {data['totals']['missing_lines']}")
print(f"Statement Coverage: {data['totals']['percent_statements_covered']:.1f}%")

# Get module coverage
modules = {}
for path, info in data['files'].items():
    if 'cobolparser' not in path or '__pycache__' in path:
        continue
    
    module = path.replace('cobolparser/', '').replace('.py', '')
    totals = info['totals']
    if totals['num_statements'] > 0:
        percent = 100 * totals['covered'] / totals['num_statements']
        modules[module] = {
            'coverage': percent,
            'covered': totals['covered'],
            'missing': totals['missing'],
            'statements': totals['num_statements']
        }

# Sort by lowest coverage
sorted_modules = sorted(modules.items(), key=lambda x: x[1]['coverage'])

print("\n" + "="*80)
print("LOWEST COVERAGE MODULES (candidates for Phase 3 test creation)")
print("="*80)

for module, stats in sorted_modules[:20]:
    print(f"{module:50} {stats['coverage']:5.1f}% ({stats['covered']:3d}/{stats['statements']:3d})")

print("\n" + "="*80)
print("HIGHEST COVERAGE MODULES (well-tested already)")
print("="*80)

for module, stats in sorted_modules[-10:]:
    print(f"{module:50} {stats['coverage']:5.1f}% ({stats['covered']:3d}/{stats['statements']:3d})")
