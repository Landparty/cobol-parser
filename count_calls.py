"""Quick script to count CALL statements in test files"""
from cobolparser.parser import CobolParser
from cobolparser.models.statements import CallStatement
from pathlib import Path

def count_calls(node):
    """Recursively count CALL statements"""
    count = 0
    if node is None:
        return 0
    
    if isinstance(node, CallStatement):
        count += 1
    
    if hasattr(node, 'children') and node.children:
        for child in node.children:
            count += count_calls(child)
    
    if hasattr(node, 'divisions'):
        for division in node.divisions:
            count += count_calls(division)
    
    return count

parser = CobolParser()
samples = Path('tests/samples')

files = [
    'call_multiline_comprehensive.cbl',
    'call_with_comments.cbl',
    'call_exception_handlers_complete.cbl',
    'call_in_control_structures.cbl',
]

print("CALL Statement Counts:")
print("=" * 50)
total = 0
for filename in files:
    result = parser.parse_file(str(samples / filename))
    if result.success:
        calls = count_calls(result.ast)
        print(f"{filename:45} {calls:3}")
        total += calls
    else:
        print(f"{filename:45} FAILED")

print("=" * 50)
print(f"{'Total':45} {total:3}")
