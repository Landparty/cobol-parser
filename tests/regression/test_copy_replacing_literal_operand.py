"""COPY ... REPLACING with a literal operand replaces the literal.

``COPY B REPLACING 'ABC-NAME' BY 'ZZ'`` must turn ``VALUE 'ABC-NAME'`` into
``VALUE 'ZZ'`` (checked against ``cobc -E``). The REPLACING operand reader
stripped a literal's quotes, so the clause searched for the *word*
``ABC-NAME``: it never matched the literal, and it rewrote an identifier
``ABC-NAME`` to a bare ``ZZ`` instead.
"""

from cobolparser import expand_copybooks
from cobolparser.preprocess.copy_statement_parser import extract_copy_statements

_COPYBOOK = """\
       01 ABC-REC.
          05 ABC-NAME    PIC X(10) VALUE 'ABC-NAME'.
          05 F2          PIC X(10) VALUE "IT'S".
          05 F3          PIC X(4)  VALUE 'O''K'.
"""


def _expand(tmp_path, replacing: str) -> list[str]:
    (tmp_path / "B.cpy").write_text(_COPYBOOK)
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. T.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        f"       COPY B REPLACING {replacing}.\n"
        "       PROCEDURE DIVISION.\n"
        "           STOP RUN.\n"
    )
    result = expand_copybooks(source, copybook_paths=[str(tmp_path)])
    return [" ".join(line.split()) for line in result.expanded_source.splitlines()]


def test_literal_operand_keeps_its_quotes():
    [stmt] = extract_copy_statements("       COPY B REPLACING 'O''K' BY 'FINE'.\n")
    clause = stmt.replacing_clauses[0]
    assert (clause.find_text, clause.replace_text) == ("'O''K'", "'FINE'")


def test_member_name_literal_is_still_unquoted():
    [stmt] = extract_copy_statements("       COPY 'B'.\n")
    assert stmt.member_name == "B"


def test_literal_replaces_the_literal_not_the_identifier(tmp_path):
    lines = _expand(tmp_path, "'ABC-NAME' BY 'ZZ'")
    assert "05 ABC-NAME PIC X(10) VALUE 'ZZ'." in lines


def test_double_quoted_and_escaped_literals(tmp_path):
    lines = _expand(tmp_path, "\"IT'S\" BY 'NO' 'O''K' BY 'FINE'")
    assert "05 F2 PIC X(10) VALUE 'NO'." in lines
    assert "05 F3 PIC X(4) VALUE 'FINE'." in lines


def test_identifier_by_literal_still_replaces_the_identifier(tmp_path):
    lines = _expand(tmp_path, "ABC-NAME BY 'LIT'")
    assert "05 'LIT' PIC X(10) VALUE 'ABC-NAME'." in lines
