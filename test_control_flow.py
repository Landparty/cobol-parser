"""Test parsing the control_flow.cbl sample file."""

from cobolparser.parser import CobolParser
from cobolparser.plugins.core import ErrorRecoveryMode

# Parse the actual control_flow.cbl file
parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
result = parser.parse_file("tests/samples/control_flow.cbl")

print(f"Parse success: {result.success}")
print(f"Errors: {len(result.errors)}")

if result.ast:
    proc_div = result.ast.get_division("PROCEDURE")
    if proc_div:
        # Find PERFORM-TESTS section
        perform_tests = next((s for s in proc_div.sections if s.section_name == "PERFORM-TESTS"), None)
        if perform_tests:
            print(f"\nFound PERFORM-TESTS section with {len(perform_tests.children)} statements")
            
            # Find PERFORM THRU statements
            for child in perform_tests.children:
                if hasattr(child, 'target_paragraph') and child.thru_paragraph:
                    print(f"  ✅ PERFORM {child.target_paragraph} THRU {child.thru_paragraph}")
