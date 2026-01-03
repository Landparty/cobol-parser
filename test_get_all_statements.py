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

parser = CobolParser()
result = parser.parse(cobol_code)

print(f"Parse success: {result.success}")
print(f"Program: {result.ast.program_name}")
print(f"Divisions: {[d.division_name for d in result.ast.divisions]}")

# Find PROCEDURE division
proc_div = None
for div in result.ast.divisions:
    if div.division_name == 'PROCEDURE':
        proc_div = div
        break

if proc_div:
    print(f"\nPROCEDURE division found")
    print(f"Sections: {[s.section_name for s in proc_div.sections]}")
    
    # Get all statements using the method
    all_stmts = list(result.ast.get_all_statements())
    print(f"\nget_all_statements() returned {len(all_stmts)} statements:")
    for i, stmt in enumerate(all_stmts):
        stmt_type = stmt.node_type if hasattr(stmt, 'node_type') else type(stmt).__name__
        print(f"  {i+1}. {stmt_type}")
        if hasattr(stmt, 'inline_statements'):
            inline_list = stmt.inline_statements
            print(f"     - inline_statements: {inline_list}")
            print(f"     - inline_statements is None: {inline_list is None}")
            print(f"     - inline_statements type: {type(inline_list)}")
            if inline_list:
                for j, inline_stmt in enumerate(inline_list):
                    inline_type = inline_stmt.node_type if hasattr(inline_stmt, 'node_type') else type(inline_stmt).__name__
                    print(f"       {j+1}. {inline_type}")
        if hasattr(stmt, 'called_program'):
            print(f"     - CALL to: {stmt.called_program}")
else:
    print("\nNo PROCEDURE division found")
