from cobolparser.parser import CobolParser

source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           STOP RUN.
"""

parser = CobolParser()
result = parser.parse(source)

print(f"Success: {result.success}")
if result.success:
    all_stmts = result.ast.get_all_statements()
    print(f"Found {len(all_stmts)} statements")
    for stmt in all_stmts:
        print(f"  - {stmt.statement_type}")
else:
    for error in result.errors:
        print(f"ERROR: {error.message}")
