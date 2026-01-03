import sys
sys.path.insert(0, r'c:\Users\sam94\workspace\cobol-parser')

from cobolparser import CobolParser

cobol_code = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 COUNTER PIC 9(2).
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM VARYING COUNTER FROM 1 BY 1
               UNTIL COUNTER > 10
               CALL "INNER-PROG" USING COUNTER
           END-PERFORM.
           STOP RUN.
"""

# Enable parser debug mode
parser = CobolParser()

# Parse with error recovery to collect messages
from cobolparser.plugins.core import ErrorRecoveryMode
parser._error_recovery = ErrorRecoveryMode.COLLECT_ALL

result = parser.parse(cobol_code)

print(f"Parse success: {result.success}")
print(f"Errors: {len(result.errors)}")
print(f"Warnings: {len(result.warnings)}")

# Check procedure division
proc_div = None
for div in result.ast.divisions:
    if div.division_name == 'PROCEDURE':
        proc_div = div
        break

if proc_div:
    print(f"\nPROCEDURE division sections: {[s.section_name for s in proc_div.sections]}")
    
    for section in proc_div.sections:
        print(f"\nSection '{section.section_name}':")
        print(f"  Children: {len(section.children)}")
        for i, child in enumerate(section.children):
            child_type = child.node_type if hasattr(child, 'node_type') else type(child).__name__
            print(f"    {i+1}. {child_type}")
            if hasattr(child, 'inline_statements'):
                inline = child.inline_statements
                print(f"       inline_statements: {inline}")
                if inline:
                    for j, stmt in enumerate(inline):
                        stmt_type = stmt.node_type if hasattr(stmt, 'node_type') else type(stmt).__name__
                        print(f"         {j+1}. {stmt_type}")
