import re, sys
with open("cookbook.md", "r", encoding="utf-8") as f:
    content = f.read()
original = content

# Fix 1: Recipe 2 bug
pattern = r"(    file_section = data_div\.get_section_by_name\(\"FILE\"\)\n)    if not file_section:\n\s*\n    if not file_section:\n        return"
replacement = r"\1    if not file_section:\n        return"
content = re.sub(pattern, replacement, content)
print("Fix 1 (Recipe 2):", "applied" if content != original else "no match")

# Fix 2: Insert Recipe 5 solution
recipe5_solution = "\n**Solution**: Use the `DeadCodeAnalyzer` class.\n\n```python\nfrom cobolparser import parse_cobol\nfrom cobolparser.analysis import DeadCodeAnalyzer\n\ndef find_dead_code(source: str):\n    result = parse_cobol(source)\n    if not result.success or not result.ast:\n        print(\"Parse failed\")\n        return []\n    analyzer = DeadCodeAnalyzer()\n    report = analyzer.analyze(result.ast)\n    issues = []\n    for item in report.dead_items:\n        issues.append(f\"Dead {item.procedure_type} 
\
item.name
\' at line {item.location.line}\")\n    print(f\"Total: {report.total_procedures}, Referenced: {report.referenced_procedures}, Dead: {report.dead_count}\")\n    return issues\n```\n"
marker = "## Recipe 6: CRUD Matrix for Mainframe Modernization"
if marker in content:
    content = content.replace(marker, recipe5_solution + marker)
    print("Fix 2 (Recipe 5): inserted")
else:
    print("Fix 2: marker not found")

with open("cookbook.md", "w", encoding="utf-8") as f:
    f.write(content)
print("Done")
