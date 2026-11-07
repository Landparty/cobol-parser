"""'!' / '|' / '¬' are valid only inside EXEC ... END-EXEC blocks.

The corpus series added BANG/PIPE/NOT_SIGN token types so embedded EXEC SQL
text (``!=``, ``||``, ``¬=``) round-trips instead of failing the whole parse
with a hard "Invalid character" LexerError. The first version accepted the
tokens *everywhere*, which silently turned garbage COBOL (``MOVE BOGUS !!!
TO WS-A``) into a successful parse with zero diagnostics -- the junk folded
into the statement's operand text. A later version restored the hard error,
which failed whole files over a box-drawing '|' in a misplaced comment.
``CobolLexer._drop_stray_chars`` (a linear post-pass) now drops these characters outside an EXEC block and names each
one in a warning: the file parses, and the junk is not silent.
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
    def test_bang_outside_exec_is_dropped_with_a_warning(self):
        result = parse_cobol(
            PROLOGUE + "           MOVE BOGUS !!! TO WS-A\n           STOP RUN.\n"
        )
        assert not any("Invalid character" in str(e) for e in result.errors)
        assert any(
            "Ignored invalid character '!'" in w and "line 9" in w
            for w in result.warnings
        ), result.warnings

    def test_pipe_outside_exec_is_dropped_with_a_warning(self):
        result = parse_cobol(
            PROLOGUE + "           MOVE BOGUS || TO WS-A\n           STOP RUN.\n"
        )
        assert not any("Invalid character" in str(e) for e in result.errors)
        assert any(
            "Ignored invalid character '|'" in w and "line 9" in w
            for w in result.warnings
        ), result.warnings

    def test_not_sign_outside_exec_is_dropped_with_a_warning(self):
        result = parse_cobol(
            PROLOGUE + "           MOVE BOGUS ¬= TO WS-A\n           STOP RUN.\n"
        )
        assert not any("Invalid character" in str(e) for e in result.errors)
        assert any(
            "Ignored invalid character '¬'" in w and "line 9" in w
            for w in result.warnings
        ), result.warnings


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
