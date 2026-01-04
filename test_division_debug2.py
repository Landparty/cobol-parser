from cobolparser.parser import CobolParser

source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           MOVE 1 TO X.
           DISPLAY "HELLO".
           STOP RUN.
"""

parser = CobolParser()
result = parser.parse(source)

if result.success:
    proc_stmts = result.ast.get_statements_in_division("PROCEDURE")
    print(f"Found {len(proc_stmts)} statements in PROCEDURE division")
    for stmt in proc_stmts:
        print(f"  - {stmt.statement_type}")
else:
    print("Parse failed")
