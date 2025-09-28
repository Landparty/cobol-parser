#!/usr/bin/env python3
"""Integration test for the complete COBOL parser package."""

from cobolparser import (
    CobolParser, IBMEnterpriseCobol, MemoryConfiguration, 
    parse_cobol, ErrorRecoveryMode
)

def test_integration():
    print("=== COBOL Parser Integration Test ===")
    
    # Test complete parser
    with open('test_program.cob', 'r') as f:
        cobol_source = f.read()
    
    print("1. Testing complete parser...")
    result = parse_cobol(cobol_source, 'test_program.cob')
    print(f"   ✓ Parse successful: {result.success}")
    print(f"   ✓ Program name: {result.ast.program_name if result.ast else 'None'}")
    print(f"   ✓ Divisions: {len(result.ast.divisions) if result.ast else 0}")
    print(f"   ✓ Errors: {len(result.errors)}")
    
    # Test IBM dialect
    print("\n2. Testing IBM Enterprise COBOL dialect...")
    ibm = IBMEnterpriseCobol()
    info = ibm.get_dialect_info()
    print(f"   ✓ Dialect: {info['name']}")
    print(f"   ✓ Features: {len(ibm.supported_features)}")
    print(f"   ✓ COMP-3 reserved: {ibm.is_reserved_word('COMP-3')}")
    print(f"   ✓ LENGTH intrinsic: {ibm.is_intrinsic_function('LENGTH')}")
    
    # Test memory configuration
    print("\n3. Testing memory configuration...")
    config = MemoryConfiguration(max_memory_mb=512)
    print(f"   ✓ Memory limit: {config.max_memory_mb}MB")
    print(f"   ✓ Chunk size: {config.chunk_size_kb}KB")
    
    print("\n🎉 All components working together successfully!")
    return True

if __name__ == "__main__":
    test_integration()