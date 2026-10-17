"""CANCEL records whether each program name is a literal (#479, part 1).

``CancelStatement`` kept only the name strings, so ``CANCEL 'X'`` (cancel
program X) and ``CANCEL X`` (cancel whatever program data item X names)
were one node and ``diff`` reported no change between them.
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.analysis.ast_diff import ProgramDiffer


def _program(statement: str) -> str:
    lines = (
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. T.",
        "DATA DIVISION.",
        "WORKING-STORAGE SECTION.",
        "01 X PIC X(8) VALUE 'Y'.",
        "PROCEDURE DIVISION.",
        "MAIN-PARA.",
        f"    {statement}",
        "    STOP RUN.",
    )
    return "".join(f"       {line}\n" for line in lines)


def _cancel(source: str):
    result = parse_cobol(source)
    assert result.success, result.errors
    (stmt,) = [
        s for s in result.ast.get_all_statements() if s.statement_type == "CANCEL"
    ]
    return stmt


def test_literal_flag_per_name() -> None:
    stmt = _cancel(_program("CANCEL 'X' X 'Z'"))
    assert stmt.program_names == ["X", "X", "Z"]
    assert stmt.program_names_literal == [True, False, True]
    assert stmt.to_dict()["program_names_literal"] == [True, False, True]
    # An all-data-name CANCEL serializes as before.
    assert "program_names_literal" not in _cancel(_program("CANCEL X")).to_dict()


def test_diff_sees_literal_to_data_name() -> None:
    old, new = parse_cobol(_program("CANCEL 'X'")), parse_cobol(_program("CANCEL X"))
    report = ProgramDiffer().diff(old.ast, new.ast)
    assert report.has_changes
    assert "CANCEL 'X' -> CANCEL X" in report.to_text()
    same = ProgramDiffer().diff(old.ast, parse_cobol(_program("CANCEL 'X'")).ast)
    assert not same.has_changes
