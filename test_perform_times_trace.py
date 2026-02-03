"""Detailed tracing of PERFORM THRU TIMES parsing."""
from cobolparser import CobolParser
from cobolparser.plugins.core import ErrorRecoveryMode

# Test case from the failing test
source = """
    IDENTIFICATION DIVISION.
    PROGRAM-ID. TEST-THRU-TIMES.
    PROCEDURE DIVISION.
    MAIN-PARA.
        PERFORM PARA-A THRU PARA-B 5 TIMES.
        STOP RUN.
    PARA-A.
        DISPLAY 'A'.
    PARA-B.
        DISPLAY 'B'.
"""

# Parse with explicit error collection
parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
result = parser.parse(source)

print(f"Parse success: {result.success}")
print(f"Parse errors: {result.errors}")

proc_div = result.ast.get_division("PROCEDURE")
main_para = next((s for s in proc_div.sections if s.section_name == "MAIN-PARA"), None)

perform_stmts = [c for c in main_para.children if hasattr(c, 'target_paragraph')]
perform_stmt = perform_stmts[0]

print(f"\nPerform Statement Analysis:")
print(f"  target_paragraph: {perform_stmt.target_paragraph}")
print(f"  thru_paragraph: {perform_stmt.thru_paragraph}")
print(f"  perform_type: {perform_stmt.perform_type}")
print(f"  times_count: {perform_stmt.times_count}")

# Check what the test expects
test_expects = {
    'target_paragraph': 'PARA-A',
    'thru_paragraph': 'PARA-B',
    'perform_type': 'TIMES',
    'times_count': 5
}

print(f"\nTest Expectations vs Actual:")
for key, expected_value in test_expects.items():
    actual_value = getattr(perform_stmt, key)
    status = "✓" if actual_value == expected_value else "✗"
    print(f"  {status} {key}: expected={expected_value}, actual={actual_value}")
