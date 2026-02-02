#!/usr/bin/env python
"""Verify that key tests pass with our architectural fixes."""

import subprocess
import sys

test_suites = [
    "tests/unit/test_arithmetic_migration.py",
    "tests/unit/test_entry_statement.py",
    "tests/unit/test_implicit_section.py",
    "tests/unit/test_move_advanced.py",
    "tests/unit/test_evaluate_variants.py",
    "tests/integration/test_if_complete.py",
    "tests/integration/test_perform_statement_coverage.py",
    "tests/regression/test_perform_backward_compat.py",
]

print(f"Running {len(test_suites)} test suites that we've fixed...\n")

total_passed = 0
total_failed = 0

for suite in test_suites:
    result = subprocess.run(
        ["python", "-m", "pytest", suite, "-q", "--tb=no", "--no-cov"],
        capture_output=True,
        text=True
    )
    
    # Parse output to get counts
    lines = result.stdout.strip().split('\n')
    summary_line = lines[-1] if lines else ""
    
    # Extract counts from summary like "14 passed" or "3 passed, 1 failed"
    import re
    match = re.search(r'(\d+) passed', summary_line)
    passed = int(match.group(1)) if match else 0
    total_passed += passed
    
    match = re.search(r'(\d+) failed', summary_line)
    failed = int(match.group(1)) if match else 0
    total_failed += failed
    
    status = "✓" if failed == 0 else "✗"
    print(f"{status} {suite}: {summary_line.strip()}")

print(f"\n{'='*60}")
print(f"TOTAL: {total_passed} passed, {total_failed} failed")

if total_failed == 0:
    print("✓ All architectural fixes verified successfully!")
    sys.exit(0)
else:
    print(f"✗ {total_failed} tests still failing")
    sys.exit(1)
