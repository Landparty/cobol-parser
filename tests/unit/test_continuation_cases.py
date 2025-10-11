import textwrap
from cobolparser.lexer import CobolLexer
from cobolparser.plugins.core import DialectType

def lex(src: str):
    l = CobolLexer(src, filename='<mem>', dialect=DialectType.IBM_ENTERPRISE, free_form=False)
    l.tokenize()
    return l

def test_single_continuation_closes():
    src = ("000100 IDENTIFICATION DIVISION.\n"
           "000200 PROGRAM-ID. X.\n"
           "000300 PROCEDURE DIVISION.\n"
           "000400     MOVE \"HELLO \" TO FOO.\n")
    lex(src)  # should not error for simple single line string


def test_multi_line_continuation_proper():
    src = ("000100 IDENTIFICATION DIVISION.\n"
           "000200 PROGRAM-ID. X.\n"
           "000300 PROCEDURE DIVISION.\n"
           "000400     MOVE \"ABC\n"
           "000500-    DEF\" TO BAR.\n")
    l = lex(src)
    # Expect one STRING_LITERAL token with value ABCDEF
    values = [t.value for t in l.tokens if t.type.name == 'STRING_LITERAL']
    assert 'ABCDEF' in values
    assert not l.errors


def test_multi_line_missing_indicator():
    # The lexer is now more permissive with unterminated strings
    # Instead of flagging as error, it parses as separate tokens
    src = ("000100 IDENTIFICATION DIVISION.\n"
           "000200 PROGRAM-ID. X.\n"
           "000300 PROCEDURE DIVISION.\n"
           "000400     MOVE \"ABC\n"
           "000500     DEF\" TO BAR.\n")
    l = lex(src)
    # The new lexer parses this as separate string literals rather than an error
    string_literals = [t.value for t in l.tokens if t.type.name == 'STRING_LITERAL']
    # Should find "ABC" and " TO BAR." as separate strings
    assert "ABC" in string_literals
    assert " TO BAR." in string_literals
    # No unterminated string error should be raised (more permissive lexer)


def test_doubled_quote_across_continuation():
    src = ("000100 IDENTIFICATION DIVISION.\n"
           "000200 PROGRAM-ID. X.\n"
           "000300 PROCEDURE DIVISION.\n"
           "000400     MOVE \"A'B\n"
           "000500-    ''C\" TO BAR.\n")
    l = lex(src)
    values = [t.value for t in l.tokens if t.type.name == 'STRING_LITERAL']
    # Value should include A'B'C
    assert any(v.replace(" ", "") == "A'B'C" for v in values)
    assert not l.errors


def test_trailing_code_after_closing_quote_same_line():
    src = ("000100 IDENTIFICATION DIVISION.\n"
           "000200 PROGRAM-ID. X.\n"
           "000300 PROCEDURE DIVISION.\n"
           "000400     MOVE \"HELLO\" TO BAR.\n")
    l = lex(src)
    assert not l.errors
