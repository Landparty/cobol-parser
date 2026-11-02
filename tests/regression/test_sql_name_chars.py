"""'#' / '@' (and '$') are letters of a DB2 name inside EXEC SQL.

DB2 ordinary identifiers may hold '#', '@' and '$' (``ACCT#``, ``@ADDR``,
``T#TAB``). The lexer had no token for '#' or '@', so a mainframe program
selecting such a column failed the whole parse with "Invalid character: #"
(a sweep blocker for mocky-mock), and ``X$Y`` round-tripped as ``X $ Y``.
``CobolLexer._merge_exec_name_chars`` glues the characters back into the
name they abut inside an EXEC block; outside one they stay invalid unless
SPECIAL-NAMES declared them a currency symbol.
"""

from cobolparser import parse_cobol

PROLOGUE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLNAMES.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
"""


def _sql_text(source: str) -> str:
    result = parse_cobol(source)
    assert result.success, result.errors
    (statement,) = result.ast.find_all_by_type("ExecSQLStatement")
    return " ".join(statement.sql_text.split())


def test_hash_and_at_in_db2_names_parse_and_round_trip():
    text = _sql_text(
        PROLOGUE
        + "           EXEC SQL SELECT ACCT#, @ADDR, C#1, X$Y INTO :WS-A\n"
        + "                    FROM T#TAB WHERE K# = 1 AND B = 'X # Y'\n"
        + "           END-EXEC\n"
        + "           STOP RUN.\n"
    )
    assert text == (
        "SELECT ACCT#, @ADDR, C#1, X$Y INTO:WS-A FROM T#TAB WHERE K# = 1 "
        "AND B = 'X # Y'"
    )


def test_a_name_char_set_apart_by_blanks_is_left_alone():
    text = _sql_text(
        PROLOGUE
        + "           EXEC SQL SELECT A # B INTO :WS-A FROM T END-EXEC\n"
        + "           STOP RUN.\n"
    )
    assert "A # B" in text


def test_hash_outside_exec_is_glued_into_the_name_with_a_warning():
    result = parse_cobol(
        PROLOGUE + "           MOVE SPACES TO WS-A#\n           STOP RUN.\n"
    )
    assert not any("Invalid character" in str(e) for e in result.errors)
    assert any("Non-standard character '#'" in w for w in result.warnings)
    move = result.ast.find_all_by_type("MoveStatement")[0]
    assert "WS-A#" in str(move.to_dict())


def test_a_declared_hash_currency_symbol_is_still_a_picture_symbol():
    source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. HASHCUR.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SPECIAL-NAMES.
           CURRENCY SIGN IS 'EUR' WITH PICTURE SYMBOL '#'.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMT PIC ###9.99.
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""
    result = parse_cobol(source)
    assert result.success, result.errors
