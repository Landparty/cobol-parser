"""Regression: IDENTIFICATION DIVISION comment-entries are kept verbatim.

A comment-entry (``AUTHOR.``, ``INSTALLATION.``, ``DATE-WRITTEN.``,
``DATE-COMPILED.``, ``SECURITY.``, ``REMARKS.``) is free documentation text:
IBM Enterprise COBOL accepts any character in it, up to the next entry that
starts in Area A. It used to be tokenized like program text, so

* ``AUTHOR. JOHN O'BRIEN.`` read the apostrophe as an unterminated
  alphanumeric literal -- a spurious "Unterminated string literal" lexer
  warning on a valid program -- and stored ``"JOHN O BRIEN. \\n"``;
* ``DATE-WRITTEN. 01/02/99.`` came back as ``"01 / 02 / 99"``.

The lexer now emits each comment-entry line as one COMMENT_ENTRY token, and
the IDENTIFICATION DIVISION parser stores the text as written.
"""

from cobolparser import parse_cobol
from cobolparser.lexer import CobolLexer, TokenType
from cobolparser.plugins.core import ErrorRecoveryMode


def _identification(result):
    for division in result.ast.divisions:
        if division.to_dict().get("division_name") == "IDENTIFICATION":
            return division.metadata
    raise AssertionError("no IDENTIFICATION DIVISION")


_SOURCE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CEVERB.
       AUTHOR. JOHN O'BRIEN.
       INSTALLATION. ACME "WEST" DATA CENTER; BLDG #4 @ 50% CAPACITY.
       DATE-WRITTEN. 01/02/99.
       DATE-COMPILED.
       SECURITY. DON'T SHARE -- J. SMITH, R. JONES
           AND THE AUDIT TEAM.
       REMARKS. IT'S A TEST.
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-X PIC X VALUE 'A'.
       PROCEDURE DIVISION.
           DISPLAY WS-X.
           STOP RUN.
"""


def test_comment_entries_parse_without_diagnostics() -> None:
    result = parse_cobol(_SOURCE, error_recovery=ErrorRecoveryMode.FAIL_FAST)
    assert result.errors == []
    assert result.warnings == []


def test_comment_entry_text_is_verbatim() -> None:
    meta = _identification(parse_cobol(_SOURCE))
    assert meta["program_id"] == "CEVERB"
    assert meta["author"] == "JOHN O'BRIEN"
    assert meta["installation"] == 'ACME "WEST" DATA CENTER; BLDG #4 @ 50% CAPACITY'
    assert meta["date_written"] == "01/02/99"
    assert meta["date_compiled"] == ""
    # Interior periods are text; Area B continuation lines join with a space.
    assert meta["security"] == ("DON'T SHARE -- J. SMITH, R. JONES AND THE AUDIT TEAM")
    assert meta["remarks"] == "IT'S A TEST"


def test_rest_of_program_unaffected() -> None:
    result = parse_cobol(_SOURCE)
    names = [d.to_dict().get("division_name") for d in result.ast.divisions]
    assert names == ["IDENTIFICATION", "ENVIRONMENT", "DATA", "PROCEDURE"]
    statements = result.ast.get_all_statements()
    assert [type(s).__name__ for s in statements] == [
        "DisplayStatement",
        "StopStatement",
    ]


def test_free_form_comment_entry() -> None:
    source = (
        "IDENTIFICATION DIVISION.\n"
        "PROGRAM-ID. FREECE.\n"
        "AUTHOR. MARY O'HARA.\n"
        "DATE-WRITTEN. 2024/03/31.\n"
        "PROCEDURE DIVISION.\n"
        "    STOP RUN.\n"
    )
    result = parse_cobol(source, free_form=True)
    assert result.errors == [] and result.warnings == []
    meta = _identification(result)
    assert meta["author"] == "MARY O'HARA"
    assert meta["date_written"] == "2024/03/31"


def test_lexer_emits_comment_entry_tokens() -> None:
    text = (
        "IDENTIFICATION DIVISION.\n"
        "PROGRAM-ID. X.\n"
        "AUTHOR. JOHN O'BRIEN.\n"
        "    SECOND LINE'S TEXT\n"
        "PROCEDURE DIVISION.\n"
        "    DISPLAY 'O''K'.\n"
    )
    lexer = CobolLexer(text, free_form=True)
    tokens = lexer.tokenize()
    assert lexer.get_warnings() == []
    assert not lexer.get_errors()
    entries = [t.value for t in tokens if t.type == TokenType.COMMENT_ENTRY]
    assert entries == ["JOHN O'BRIEN.", "SECOND LINE'S TEXT"]
    # Outside the IDENTIFICATION DIVISION literals lex as before.
    literals = [t.value for t in tokens if t.type == TokenType.STRING_LITERAL]
    assert literals == ["O'K"]


def test_comment_entry_keyword_outside_identification_is_program_text() -> None:
    text = "PROCEDURE DIVISION.\nREMARKS. DISPLAY 'X'.\n"
    tokens = CobolLexer(text, free_form=True).tokenize()
    assert not [t for t in tokens if t.type == TokenType.COMMENT_ENTRY]
