#!/usr/bin/env python3
"""Debug script to trace CALL parsing in PERFORM."""

from cobolparser import parse_cobol

source = """
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
PROCEDURE DIVISION.
    PERFORM 1 TIMES
        CALL "SUBPROGRAM"
    END-PERFORM.
    STOP RUN.
"""

result = parse_cobol(source)
print("Parse success:", result.success)

if result.ast:
    print("\n=== Top-level statements ===")
    procedures = result.ast.find_statements("PROCEDURE DIVISION")
    if procedures:
        proc = procedures[0]
        print(f"Found {len(procedures)} PROCEDURE DIVISION")
        if hasattr(proc, 'statements'):
            print(f"  Direct statements: {len(proc.statements)}")
            for i, stmt in enumerate(proc.statements):
                print(f"    {i}: {type(stmt).__name__}")
    
    print("\n=== PERFORM statements ===")
    performs = result.ast.find_statements("PERFORM")
    print(f"Total PERFORM statements found: {len(performs)}")
    for i, perf in enumerate(performs):
        print(f"\nPERFORM {i}:")
        print(f"  Type: {type(perf).__name__}")
        if hasattr(perf, '__dict__'):
            attrs = perf.__dict__
            print(f"  Attributes: {list(attrs.keys())}")
            if 'inline_statements' in attrs:
                inline = attrs['inline_statements']
                print(f"  Inline statements: {len(inline)}")
                for j, stmt in enumerate(inline):
                    print(f"    {j}: {type(stmt).__name__}")
                    if hasattr(stmt, '__dict__'):
                        print(f"       attrs: {list(stmt.__dict__.keys())}")
    
    print("\n=== CALL statements ===")
    calls = result.ast.find_statements("CALL")
    print(f"Total CALL statements found: {len(calls)}")
    for i, call in enumerate(calls):
        print(f"  {i}: {type(call).__name__}")
    
    print("\n=== All statements (tree traversal) ===")
    def print_tree(node, indent=0):
        """Recursively print statement tree."""
        prefix = "  " * indent
        if hasattr(node, '__class__'):
            print(f"{prefix}{type(node).__name__}")
        
        # Try different possible attributes
        children_lists = [
            ('statements', 'statements'),
            ('inline_statements', 'inline_statements'),
            ('when_clauses', 'when_clauses'),
            ('body', 'body'),
            ('paragraphs', 'paragraphs'),
            ('sections', 'sections'),
        ]
        
        for attr_name, _ in children_lists:
            if hasattr(node, attr_name):
                items = getattr(node, attr_name)
                if items and isinstance(items, list):
                    for item in items:
                        if hasattr(item, '__class__') and hasattr(item.__class__, '__name__'):
                            print_tree(item, indent + 1)
    
    print_tree(result.ast)
