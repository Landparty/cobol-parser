"""Debug test to see what error is happening."""

from cobolparser.parser import CobolParser

source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-NUM  PIC 9(5).
        """

parser = CobolParser()
result = parser.parse(source)

print(f"Success: {result.success}")
print(f"AST: {result.ast}")
print(f"Errors ({len(result.errors)}):")
for error in result.errors:
    print(f"  - {error}")
