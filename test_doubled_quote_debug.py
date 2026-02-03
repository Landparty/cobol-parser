from cobolparser.lexer import CobolLexer
from cobolparser.plugins.core import DialectType

src = ("000100 IDENTIFICATION DIVISION.\n"
       "000200 PROGRAM-ID. X.\n"
       "000300 PROCEDURE DIVISION.\n"
       "000400     MOVE \"A'B\n"
       "000500-    ''C\" TO BAR.\n")

l = CobolLexer(src, filename='<mem>', dialect=DialectType.IBM_ENTERPRISE, free_form=False)
l.tokenize()
values = [t.value for t in l.tokens if t.type.name == 'STRING_LITERAL']
print('String literal values:', values)
print('Errors:', l.errors)

# Check if we have the expected string
# In COBOL, single quote is escaped with single quote: '' = '
# So "A'B" + "''C" should become STRING_LITERAL with value A'B'C
expected = "A'B'C"
found = any(v.replace(" ", "") == expected for v in values)
print(f'Found expected value {repr(expected)}:', found)
print(f'Values as repr: {[repr(v) for v in values]}')
