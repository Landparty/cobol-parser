"""'!' / '|' / '¬' are valid only inside EXEC ... END-EXEC blocks.

The corpus series added BANG/PIPE/NOT_SIGN token types so embedded EXEC SQL
text (``!=``, ``||``, ``¬=``) round-trips instead of failing the whole parse
with a hard "Invalid character" LexerError. The first version accepted the
tokens *everywhere*, which silently turned garbage COBOL (``MOVE BOGUS !!!
TO WS-A``) into a successful parse with zero diagnostics -- the junk folded
into the statement's operand text. ``CobolLexer._flag_stray_sql_chars`` (a
linear post-pass shared by the Cython fast path) restores the old error for
any of these characters outside an EXEC block.
"""

from cobolparser import parse_cobol

PROLOGUE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. STRAYSQL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC X(4).
       01  WS-CNT PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
"""


class TestStrayCharsOutsideExec:
    def test_bang_outside_exec_is_a_lexer_error(self):
        result = parse_cobol(
            PROLOGUE + "           MOVE BOGUS !!! TO WS-A\n           STOP RUN.\n"
        )
        assert not result.success
        assert any("Invalid character: !" in str(e) for e in result.errors)

    def test_pipe_outside_exec_is_a_lexer_error(self):
        result = parse_cobol(
            PROLOGUE + "           MOVE BOGUS || TO WS-A\n           STOP RUN.\n"
        )
        assert not result.success
        assert any("Invalid character: |" in str(e) for e in result.errors)

    def test_not_sign_outside_exec_is_a_lexer_error(self):
        result = parse_cobol(
            PROLOGUE + "           MOVE BOGUS ¬= TO WS-A\n           STOP RUN.\n"
        )
        assert not result.success
        assert any("Invalid character: ¬" in str(e) for e in result.errors)


class TestSqlCharsInsideExec:
    def test_not_equal_and_concat_inside_exec_sql_still_parse(self):
        result = parse_cobol(
            PROLOGUE
            + "           EXEC SQL\n"
            + "               SELECT COUNT(*) INTO :WS-CNT FROM T\n"
            + "               WHERE A != 1 AND B || C <> 'X' AND D ¬= 2\n"
            + "           END-EXEC\n"
            + "           STOP RUN.\n"
        )
        assert result.success, result.errors
        assert not result.errors
