from cobolparser.parser import CobolParser

source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           MOVE 1 TO X.
           DISPLAY "HELLO".
"""

parser = CobolParser()
result = parser.parse(source)

print(f"Success: {result.success}")
print(f"Errors: {result.errors}")

if result.success:
    statements = result.ast.get_all_statements()
    print(f"Found {len(statements)} statements")
    for stmt in statements:
        print(f"  - {stmt.statement_type}: division={stmt.division_name}")
else:
    for error in result.errors:
        print(f"ERROR: {error.message}")
