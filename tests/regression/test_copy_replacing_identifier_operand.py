"""Regression (#253): COPY ... REPLACING keeps a qualified / subscripted operand.

IBM lets a REPLACING operand be an *identifier* -- qualification, subscripts
and reference modification included. ``CopyStatementLexer`` used to read
``OF`` after an operand as the COPY statement's library name (dropping
``OF WS-GRP`` and looking the member up under ``WS-GRP/``), and to stop a word
before a ``(`` that follows a blank (the leftover ``(2)`` failed the ``BY``
check and was discarded). Neither produced a warning, so the AST got the
wrong MOVE target. NIST SM202A / SM206A use this form.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser import parse_cobol, parse_cobol_with_expansion
from cobolparser.preprocess.copy_statement_parser import CopyStatementLexer

NIST_DIR = Path(__file__).parent.parent.parent / "examples" / "cobol"

_PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. T1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-GRP.
          05 WS-FLD PIC 9.
       01 WS-TBL PIC 9 OCCURS 3.
       PROCEDURE DIVISION.
       MAIN-PARA.
           {body}
           STOP RUN.
"""

_OPERANDS = [
    "WS-FLD OF WS-GRP",
    "WS-FLD IN WS-GRP",
    "WS-TBL (2)",
    "WS-TBL(2)",
    "WS-TBL (2) (1:1)",
]


def _move_targets(result) -> list[str]:
    assert result.ast is not None
    [move] = result.ast.find_all_by_type("MoveStatement")
    return move.targets


@pytest.mark.parametrize("operand", _OPERANDS)
def test_replacing_operand_reaches_the_ast(operand: str, tmp_path: Path) -> None:
    (tmp_path / "QR.cpy").write_text("           MOVE 1 TO FALSE-DATA-1\n")
    copied = parse_cobol_with_expansion(
        _PROGRAM.format(body=f"COPY QR REPLACING FALSE-DATA-1 BY {operand}."),
        "x.cbl",
        [str(tmp_path)],
    )
    written = parse_cobol(_PROGRAM.format(body=f"MOVE 1 TO {operand}"))
    assert _move_targets(copied) == _move_targets(written)
    assert copied.warnings == []


@pytest.mark.parametrize("operand", _OPERANDS)
def test_lexer_reads_the_whole_operand(operand: str) -> None:
    [stmt] = CopyStatementLexer(
        f"       COPY QR REPLACING FALSE-DATA-1 BY {operand}.\n"
    ).tokenize_copy_statements()
    assert stmt.library_qualifier is None
    assert [(c.find_text, c.replace_text) for c in stmt.replacing_clauses] == [
        ("FALSE-DATA-1", operand)
    ]


def test_qualified_search_operand_and_several_pairs() -> None:
    [stmt] = CopyStatementLexer(
        "       COPY QR OF LIB REPLACING A OF B BY C\n"
        "                                IN D\n"
        "                                Z (2, 1, 1) BY ==Y==.\n"
    ).tokenize_copy_statements()
    assert stmt.library_qualifier == "LIB"
    assert [(c.find_text, c.replace_text) for c in stmt.replacing_clauses] == [
        ("A OF B", "C\n                                IN D"),
        ("Z (2, 1, 1)", "Y"),
    ]


@pytest.mark.parametrize("program", ["SM202A.CBL", "SM206A.CBL"])
def test_nist_copy_replacing_identifier_programs_expand(program: str) -> None:
    source = (NIST_DIR / program).read_text(errors="replace")
    result = parse_cobol_with_expansion(source, program, [str(NIST_DIR)])
    assert not [w for w in result.warnings if "NOT expanded" in w]
