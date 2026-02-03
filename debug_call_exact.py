#!/usr/bin/env python3
"""Debug CALL parsing - using exact test source WITH test indentation."""

from cobolparser import parse_cobol

# Use EXACT format from test_perform_with_call_inside - with indentation
source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            PERFORM 1 TIMES
                CALL "SUBPROGRAM"
            END-PERFORM.
            STOP RUN.
        """

print("=== Parsing PERFORM with CALL (with indent) ===")
result = parse_cobol(source)
print(f"Parse success: {result.success}")

if result.ast:
    # Find all statements
    perform_stmts = result.ast.find_statements("PERFORM")
    call_stmts = result.ast.find_statements("CALL")
    
    print(f"\nPERFORM statements: {len(perform_stmts)}")
    print(f"CALL statements: {len(call_stmts)}")
    
    if perform_stmts:
        perf = perform_stmts[0]
        print(f"\nFirst PERFORM:")
        print(f"  times_count: {getattr(perf, 'times_count', None)}")
        print(f"  inline_statements: {len(getattr(perf, 'inline_statements', []))}")
        
        inline = getattr(perf, 'inline_statements', [])
        for i, stmt in enumerate(inline):
            print(f"    {i}: {type(stmt).__name__}")
