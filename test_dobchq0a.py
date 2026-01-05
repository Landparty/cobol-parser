"""Quick test script to verify PROCESS directive handling with dobchq0a.cbl"""

from cobolparser import CobolParser
from cobolparser.preprocess import strip_compiler_directives

# Test 1: Strip directives from the file
print("=" * 70)
print("Test 1: Stripping PROCESS directives from dobchq0a.cbl")
print("=" * 70)

with open('c:/Users/sam94/workspace/legacylens-backend/examples/dobchq0a.cbl', 'r', encoding='utf-8') as f:
    source = f.read()

# Show first few lines before stripping
print("\nFirst 10 lines BEFORE stripping:")
for i, line in enumerate(source.splitlines()[:10], 1):
    print(f"{i:3}: {line[:80]}")

# Strip directives
cleaned = strip_compiler_directives(source)

# Show first few lines after stripping
print("\nFirst 10 lines AFTER stripping:")
for i, line in enumerate(cleaned.splitlines()[:10], 1):
    print(f"{i:3}: {line[:80]}")

# Verify PROCESS lines are gone
has_process = "PROCESS" in cleaned.splitlines()[0] or "PROCESS" in cleaned.splitlines()[1]
print(f"\nPROCESS directives removed: {not has_process}")

# Test 2: Parse the file
print("\n" + "=" * 70)
print("Test 2: Parsing dobchq0a.cbl with CobolParser")
print("=" * 70)

parser = CobolParser()
result = parser.parse_file('c:/Users/sam94/workspace/legacylens-backend/examples/dobchq0a.cbl')

print(f"\nParsing successful: {result.success}")
if result.ast:
    print(f"Program ID: {result.ast.program_id}")
    print(f"Number of divisions: {len(result.ast.divisions)}")
print(f"Number of errors: {len(result.errors)}")
if result.errors:
    print("\nFirst few errors:")
    for error in result.errors[:3]:
        print(f"  - Line {error.line}: {error.message}")

print("\n" + "=" * 70)
print("Tests completed!")
print("=" * 70)
