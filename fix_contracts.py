import re

with open('tests/contracts/test_if_statement_contract.py', 'r') as f:
    content = f.read()

# Replace all SourceLocation calls with wrong signature
# Pattern: SourceLocation('test.cob', line, column, length)
# Should be: SourceLocation(line, column)
content = re.sub(r'SourceLocation\("test\.cob",\s*(\d+),\s*(\d+),\s*\d+\)', r'SourceLocation(\1, \2)', content)

with open('tests/contracts/test_if_statement_contract.py', 'w') as f:
    f.write(content)

print('Fixed SourceLocation calls')
