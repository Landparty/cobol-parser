from cobolparser.parser import CobolParser
from cobolparser.lexer import Token, TokenType, SourceLocation
from cobolparser.models.program import CobolDivision

parser = CobolParser()
proc_division = CobolDivision('PROCEDURE', SourceLocation(1, 1))
parser.current_division = proc_division

tokens = [
    Token(TokenType.CALL, 'CALL', SourceLocation(1, 1)),
    Token(TokenType.STRING_LITERAL, 'SUBPROGRAM', SourceLocation(1, 6)),
    Token(TokenType.PERIOD, '.', SourceLocation(1, 18)),
    Token(TokenType.EOF, '', SourceLocation(2, 1))
]

# Monkey patch to debug
original_add = CobolParser._add_statement
def debug_add(self, stmt):
    stmt_type = stmt.statement_type if hasattr(stmt, 'statement_type') else type(stmt).__name__
    print(f'_add_statement called with {stmt_type}')
    print(f'  current_section: {self.current_section is not None}')
    print(f'  current_paragraph: {self.current_paragraph is not None}')
    result = original_add(self, stmt)
    if self.current_paragraph:
        print(f'  after add_statement, paragraph children: {len(self.current_paragraph.children)}')
    return result

CobolParser._add_statement = debug_add

result = parser.parse_sentence(tokens, SourceLocation(1, 1))
if parser.current_paragraph:
    print(f'\nFinal: paragraph children = {len(parser.current_paragraph.children)}')
    print(f'Statements: {parser.current_paragraph.statements}')
print(f'Result: {result}')
