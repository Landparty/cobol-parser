#!/usr/bin/env python
"""Debug script to analyze CALL statement parsing"""

from cobolparser import CobolParser

def analyze_file(filename):
    """Analyze a COBOL file for CALL statements"""
    parser = CobolParser()
    
    with open(filename, 'r') as f:
        content = f.read()
    
    result = parser.parse(content)
    
    # Navigate to the procedure division
    if hasattr(result, 'ast') and result.ast:
        program = result.ast
        if hasattr(program, 'divisions') and program.divisions:
            for div in program.divisions:
                if hasattr(div, 'division_type') and div.division_type == 'PROCEDURE':
                    print(f"Found PROCEDURE DIVISION with {len(div.sections)} sections")
                    for section in div.sections:
                        print(f"  Section: {section.name}")
                        for child in section.children:
                            if hasattr(child, 'node_type') and 'Call' in child.node_type:
                                print(f"    - CallStatement: {child.called_program}")
                                if hasattr(child, 'using_parameters') and child.using_parameters:
                                    print(f"      Parameters: {len(child.using_parameters)}")

if __name__ == '__main__':
    print("Testing: call_statements_basic.cbl")
    analyze_file('tests/samples/call_statements_basic.cbl')
