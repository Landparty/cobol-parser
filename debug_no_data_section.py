"""Test without WORKING-STORAGE SECTION."""
from cobolparser import CobolParser
from cobolparser.plugins.core import ErrorRecoveryMode

# Source without WORKING-STORAGE SECTION but still has DATA DIVISION
source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       DATA DIVISION.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY 'HELLO'.
           STOP RUN.
"""

parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
result = parser.parse(source)

print("=== Parse Result ===")
print(f"Success: {result.success}")
print(f"Errors: {result.errors}")
print(f"Divisions: {len(result.ast.divisions)}")
print(f"_divisions keys: {list(result.ast._divisions.keys())}")

proc_div = result.ast.get_division("PROCEDURE")
print(f"Procedure Division: {proc_div}")
