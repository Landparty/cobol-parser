#!/usr/bin/env python
"""Validate CALL parsing after exception handler fixes"""

from cobolparser import CobolParser
from cobolparser.models.statements import CallStatement
import os

def validate_test_files():
    """Validate all generated CALL test files parse correctly."""
    test_files = [
        'tests/samples/call_banking_system.cbl',
        'tests/samples/call_hr_system.cbl', 
        'tests/samples/call_edge_cases_advanced.cbl',
        'tests/samples/call_finance_system.cbl',
        'tests/samples/call_utilities.cbl',
        'tests/samples/call_vendor_management.cbl',
        'tests/samples/call_inventory_system.cbl',
        'tests/samples/call_real_world_enterprise.cbl',
        'tests/samples/call_complex_workflows.cbl',
        'tests/samples/call_distributed_systems.cbl'
    ]
    
    parser = CobolParser()
    
    print("=" * 70)
    print("VALIDATING CALL PARSING WITH EXCEPTION HANDLER FIXES")
    print("=" * 70)
    
    total_files = 0
    successful_files = 0
    total_calls = 0
    total_with_handlers = 0
    
    for filepath in test_files:
        if not os.path.exists(filepath):
            print(f"SKIP: {filepath} (not found)")
            continue
        
        total_files += 1
        filename = os.path.basename(filepath)
        
        with open(filepath, 'r') as f:
            code = f.read()
        
        result = parser.parse(code)
        
        if not result.success:
            print(f"FAIL: {filename}")
            print(f"  Errors: {result.errors}")
            continue
        
        successful_files += 1
        
        # Count CALL statements
        all_stmts = result.ast.get_all_statements()
        call_stmts = [s for s in all_stmts if isinstance(s, CallStatement)]
        total_calls += len(call_stmts)
        
        # Count CALL statements with exception handlers
        calls_with_handlers = sum(1 for s in call_stmts if s.on_exception or s.not_on_exception or s.on_overflow)
        total_with_handlers += calls_with_handlers
        
        print(f"PASS: {filename}")
        print(f"      CALL statements: {len(call_stmts)}, with handlers: {calls_with_handlers}")
    
    print("\n" + "=" * 70)
    print(f"Files: {successful_files}/{total_files} successful")
    print(f"Total CALL statements: {total_calls}")
    print(f"CALL statements with handlers: {total_with_handlers}")
    
    if successful_files == total_files:
        print("[OK] All files validated successfully!")
    else:
        print(f"[WARN] {total_files - successful_files} files failed")
    
    print("=" * 70)


if __name__ == "__main__":
    validate_test_files()
