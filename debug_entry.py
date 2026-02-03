#!/usr/bin/env python
"""Debug script to explore ENTRY statement parsing."""

from cobolparser.parser import CobolParser
from cobolparser.models.statements import EntryStatement

def debug_parse():
    """Debug ENTRY statement parsing."""
    parser = CobolParser(free_form=True)
    source = """IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
PROCEDURE DIVISION.
    ENTRY 'MAINENTRY'.
    STOP RUN.
"""
    
    result = parser.parse(source)
    print(f"Parse successful: {result.ast is not None}")
    
    if result.ast:
        proc_div = result.ast.get_division("PROCEDURE")
        print(f"Procedure Division found: {proc_div is not None}")
        
        if proc_div:
            print(f"Number of sections: {len(proc_div.sections)}")
            print(f"Number of paragraphs: {len(proc_div.paragraphs)}")
            
            # Iterate through paragraphs
            for i, para in enumerate(proc_div.paragraphs):
                print(f"\nParagraph {i}: {para.paragraph_name}")
                print(f"  Number of statements: {len(para.statements)}")
                for j, stmt in enumerate(para.statements):
                    print(f"  Statement {j}: {type(stmt).__name__}")
                    if isinstance(stmt, EntryStatement):
                        print(f"    Entry name: {stmt.entry_name}")
                        print(f"    Using parameters: {stmt.using_parameters}")

if __name__ == "__main__":
    debug_parse()
